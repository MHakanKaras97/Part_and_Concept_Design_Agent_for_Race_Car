"""Image attachments: validation, persistence with the run, delivery to reasoners, IMAGE provenance gates."""
import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.attachments import MAX_IMAGE_BYTES, check_image, decode_upload, sniff_image
from agent.reasoning import ClaudeCodeBackend, FileExchangeBackend, ReasoningBackendError, make_task
from agent.service import AgentService
from agent.workflow import Engine, create_run, load_run, record_answer
from tests.helpers import REQUEST, FakeFusion, ScriptedBackend, analysis_response, plan_response
from vehicle.models import Requirement
from vehicle.store import ProjectStore

ROOT = Path(__file__).resolve().parent.parent
# 1x1 PNG
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
ACCEPT = {"decision": "ACCEPT", "rationale": "ok"}


def _image_req(rid="R07", evidence="2x M5, 40", text="Two M5 holes 40 mm apart, as drawn", att="IMG-01"):
    return {"id": rid, "key": "drawing_holes", "text": text, "source": "IMAGE", "attachment_id": att,
            "image_evidence": evidence}


# ---------------------------------------------------------------- validation
def test_sniff_and_check():
    assert sniff_image(PNG) == ("image/png", "png")
    assert sniff_image(JPG) == ("image/jpeg", "jpg")
    assert sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("image/webp", "webp")
    assert sniff_image(b"%PDF-1.7") is None
    with pytest.raises(ValueError):
        check_image(b"%PDF-1.7 not an image", "x.pdf")
    with pytest.raises(ValueError):
        check_image(b"", "empty.png")
    with pytest.raises(ValueError):
        check_image(PNG + b"\x00" * MAX_IMAGE_BYTES, "huge.png")


def test_decode_upload():
    data, name = decode_upload({"filename": "C:\\tmp\\..\\sketch.png", "data_base64": base64.b64encode(PNG).decode()})
    assert data == PNG and name == "sketch.png"                   # path components stripped
    with pytest.raises(ValueError):
        decode_upload({"filename": "x.png", "data_base64": "not base64!!"})


# ---------------------------------------------------------------- persistence with the run
def test_image_is_stored_with_the_run_and_hashed(tmp_path):
    store = ProjectStore("bench", root=tmp_path)
    run = create_run(store, REQUEST, images=[(PNG, "sketch.png")], entered_via="test")
    att = run["attachments"][0]
    assert att["id"] == "IMG-01" and att["file"] == "attachments/IMG-01.png" and att["media_type"] == "image/png"
    stored = (run.dir / att["file"]).read_bytes()
    assert stored == PNG and att["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert load_run(store, run.id)["attachments"] == run["attachments"]


def test_invalid_image_creates_no_run(tmp_path):
    store = ProjectStore("bench", root=tmp_path)
    with pytest.raises(ValueError):
        create_run(store, REQUEST, images=[(b"not an image", "x.png")])
    assert not store.runs_dir.exists() or not list(store.runs_dir.iterdir())


# ---------------------------------------------------------------- delivery to reasoners
def test_file_exchange_request_lists_the_image(tmp_path):
    store = ProjectStore("bench", root=tmp_path)
    run = Engine(store, fusion=FakeFusion()).advance(create_run(store, REQUEST, images=[(PNG, "sketch.png")]))
    md = (run.dir / "reasoning" / "01_analysis.request.md").read_text(encoding="utf-8")
    assert "IMG-01" in md and "../attachments/IMG-01.png" in md and "IMAGE evidence" in md
    task = json.loads((run.dir / "reasoning" / "01_analysis.request.json").read_text(encoding="utf-8"))
    assert task["attachments"][0]["id"] == "IMG-01" and task["context"]["attachments"][0]["id"] == "IMG-01"


def test_claude_code_receives_image_block_and_detects_tampering(tmp_path):
    store = ProjectStore("bench", root=tmp_path)
    run = create_run(store, REQUEST, images=[(PNG, "sketch.png")])
    task = make_task(run.id, 1, "analysis", {"x": 1}, attachments=run["attachments"])
    msg = json.loads(ClaudeCodeBackend(run.dir).stream_input(task))
    blocks = msg["message"]["content"]
    assert blocks[0]["type"] == "text" and "IMG-01" in blocks[0]["text"]
    assert blocks[1] == {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                      "data": base64.b64encode(PNG).decode()}}
    (run.dir / "attachments" / "IMG-01.png").write_bytes(JPG)          # file changed after it was recorded
    with pytest.raises(ReasoningBackendError):
        ClaudeCodeBackend(run.dir).stream_input(task)


def test_review_task_does_not_carry_images(tmp_path):
    store = ProjectStore("bench", root=tmp_path)
    backend = ScriptedBackend({"analysis": [analysis_response()], "plan": [plan_response()]})
    run = Engine(store, backend_factory=lambda r: backend, fusion=FakeFusion()).advance(
        create_run(store, REQUEST, images=[(PNG, "s.png")]))
    kinds = {t.kind: len(t.attachments) for t in backend.tasks}
    assert kinds == {"analysis": 1, "plan": 1, "review": 0}


# ---------------------------------------------------------------- IMAGE provenance
def test_image_requirement_model():
    with pytest.raises(ValidationError):
        Requirement(id="R07", key="k", text="t", source="IMAGE", attachment_id="IMG-01")       # no evidence
    r = Requirement.model_validate(_image_req())
    assert r.interpreted_by == "AI" and r.quote is None


def _errors(tmp_path, analysis, images=((PNG, "s.png"),)):
    store = ProjectStore("bench", root=tmp_path)
    run = Engine(store, backend_factory=lambda r: ScriptedBackend({"analysis": [analysis]}), fusion=FakeFusion()) \
        .advance(create_run(store, REQUEST, images=list(images)))
    return (run["feedback"] or {}).get("errors", []), run


def test_image_requirement_accepted_and_kept_distinct(tmp_path):
    a = analysis_response()
    a["requirements"].append(_image_req())
    errors, run = _errors(tmp_path, a)
    assert errors == [] and run["stage"] == "PLAN"
    r7 = next(r for r in run["analysis"]["requirements"] if r["id"] == "R07")
    assert r7["source"] == "IMAGE" and r7["attachment_id"] == "IMG-01" and r7["answer_id"] is None


def test_image_requirement_must_reference_an_attachment_of_the_run(tmp_path):
    a = analysis_response()
    a["requirements"].append(_image_req(att="IMG-02"))
    assert any("IMG-02 is not an image of this run" in e for e in _errors(tmp_path, a)[0])
    a2 = analysis_response()
    a2["requirements"].append(_image_req())
    assert any("not an image of this run" in e for e in _errors(tmp_path / "b", a2, images=())[0])


def test_image_numbers_must_be_in_the_stated_evidence(tmp_path):
    a = analysis_response()
    a["requirements"].append(_image_req(text="Two M5 holes 45 mm apart"))
    assert any("not in the stated image_evidence" in e for e in _errors(tmp_path, a)[0])


def test_question_may_repeat_image_values_only_when_naming_the_image(tmp_path):
    def with_q(q):
        a = analysis_response(ask_load=True)
        a["requirements"].append(_image_req())
        a["missing_information"][0]["question"] = q
        return a
    errs, _ = _errors(tmp_path / "a", with_q("The drawing shows holes 40 mm apart - is that correct?"))
    assert any("introduces numeric values" in e for e in errs)
    errs, run = _errors(tmp_path / "b", with_q("IMG-01 shows holes 40 mm apart - is that correct?"))
    assert errs == [] and run["status"] == "AWAITING_USER"


def test_image_values_never_pass_as_user_values_in_the_plan(tmp_path):
    a = analysis_response()
    a["requirements"].append(_image_req())
    store = ProjectStore("bench", root=tmp_path)
    eng = Engine(store, backend_factory=lambda r: ScriptedBackend({"analysis": [a]}), fusion=FakeFusion())
    run = eng.advance(create_run(store, REQUEST, images=[(PNG, "s.png")]))
    from agent.reasoning import PlanResponse
    p = plan_response()
    p["parameters"]["upright_hole_pitch_y"].update(source="USER", trace=["R07"])          # image value labelled USER
    assert any("must trace to the user's request or answers" in e for e in eng.gate_plan(run, PlanResponse.model_validate(p)))
    p = plan_response()
    p["parameters"]["upright_hole_pitch_y"].update(source="IMAGE_EVIDENCE", trace=["A01"])  # no IMAGE requirement
    assert any("must trace to an IMAGE requirement" in e for e in eng.gate_plan(run, PlanResponse.model_validate(p)))
    p = plan_response()
    p["parameters"]["upright_hole_pitch_y"].update(source="IMAGE_EVIDENCE", trace=["R07"])
    assert eng.gate_plan(run, PlanResponse.model_validate(p)) == []


def test_completed_run_links_component_to_source_image(tmp_path):
    a = analysis_response()
    a["requirements"].append(_image_req())
    store = ProjectStore("bench", root=tmp_path)
    backend = ScriptedBackend({"analysis": [a], "plan": [plan_response()], "review": [ACCEPT]})
    run = Engine(store, backend_factory=lambda r: backend, fusion=FakeFusion()).advance(
        create_run(store, REQUEST, images=[(PNG, "sketch.png")]))
    assert run["status"] == "COMPLETED"
    comp = store.get_component("BRK-001")
    assert comp.source_attachments == [{"id": "IMG-01", "run_id": run.id, "file": "attachments/IMG-01.png",
                                        "original_name": "sketch.png", "media_type": "image/png",
                                        "sha256": hashlib.sha256(PNG).hexdigest()}]
    assert any(r.source == "IMAGE" for r in comp.requirements)
    report = (run.dir / "report.md").read_text(encoding="utf-8")
    assert "Source image IMG-01" in report and 'image IMG-01: "2x M5, 40" (AI reading)' in report


# ---------------------------------------------------------------- service / HTTP
def test_service_upload_and_serve(tmp_path):
    svc = AgentService(project="bench", root=tmp_path, fusion=FakeFusion(),
                       backend_factory=lambda r: ScriptedBackend({}), background=False)
    run_id = svc.start_run(REQUEST, [{"filename": "sketch.png", "data_base64": base64.b64encode(PNG).decode()}])
    v = svc.run_view(run_id)
    assert v["attachments"][0]["url"] == f"/api/runs/{run_id}/attachments/IMG-01"
    assert v["messages"][0]["attachments"][0]["id"] == "IMG-01"
    path, mt = svc.attachment(run_id, "IMG-01")
    assert path.read_bytes() == PNG and mt == "image/png"
    with pytest.raises(KeyError):
        svc.attachment(run_id, "IMG-02")
    with pytest.raises(ValueError):
        svc.start_run(REQUEST, [{"filename": "a.txt", "data_base64": base64.b64encode(b"hello").decode()}])
    with pytest.raises(ValueError):
        svc.start_run(REQUEST, [{"filename": f"{i}.png", "data_base64": base64.b64encode(PNG).decode()} for i in range(5)])


def test_http_image_upload(tmp_path):
    import threading
    import urllib.error
    import urllib.request
    from ui.server import make_server
    svc = AgentService(project="bench", root=tmp_path, fusion=FakeFusion(),
                       backend_factory=lambda r: ScriptedBackend({}), background=False)
    srv = make_server(svc, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        body = json.dumps({"request": REQUEST, "attachments": [{"filename": "s.png",
                                                               "data_base64": base64.b64encode(PNG).decode()}]}).encode()
        req = urllib.request.Request(base + "/api/runs", data=body, headers={"Content-Type": "application/json"})
        run_id = json.loads(urllib.request.urlopen(req, timeout=10).read())["run_id"]
        with urllib.request.urlopen(f"{base}/api/runs/{run_id}/attachments/IMG-01", timeout=10) as r:
            assert r.read() == PNG and r.headers["Content-Type"] == "image/png"
        bad = json.dumps({"request": REQUEST, "attachments": [{"filename": "x.png", "data_base64": "aGVsbG8="}]}).encode()
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(base + "/api/runs", data=bad,
                                                          headers={"Content-Type": "application/json"}), timeout=10)
        assert e.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{base}/api/runs/{run_id}/attachments/IMG-09", timeout=10)
        assert e.value.code == 404
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------- CLI
def test_cli_rejects_non_image_attachment(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("not an image")
    before = sorted(p.name for p in (ROOT / "data/prototype_bench/runs").iterdir())
    p = subprocess.run([sys.executable, "-B", "-m", "agent", "new", "x", "--image", str(bad)], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=120)
    assert p.returncode == 2 and "not a PNG, JPEG, GIF or WebP" in p.stderr
    assert sorted(p.name for p in (ROOT / "data/prototype_bench/runs").iterdir()) == before
