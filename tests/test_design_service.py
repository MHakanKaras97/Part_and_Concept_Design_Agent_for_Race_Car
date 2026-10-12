"""Fast mode P4: design service, view model and HTTP API (fake Fusion, scripted Claude)."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from agent.design_run import create_design_run
from agent.design_service import DesignService, build_design_view
from agent.fast_reasoning import ScriptedReasoner
from agent.service import AgentService
from tests.helpers import MINI_BOX_BODY, FakeFusion, FakePartFusion, ScriptedBackend, mini_f1_plan
from ui.server import make_server

BRIEF = "Mini F1 with a two-element front wing."


def _envs():
    return {p["id"]: (p["envelope_min"], p["envelope_max"]) for p in mini_f1_plan()["parts"]}


def _service(tmp_path, responses):
    reasoner = ScriptedReasoner(responses)
    fake = FakePartFusion(envelopes=_envs())
    return DesignService(project="mini_f1", root=tmp_path, fusion=fake, reasoner_factory=lambda run: reasoner,
                         background=False), fake, reasoner


def _full():
    return {"plan": [mini_f1_plan()], "part": [{"body": MINI_BOX_BODY}] * 4}


# ---------------------------------------------------------------- view model
def test_view_of_a_finished_run(tmp_path):
    svc, fake, reasoner = _service(tmp_path, _full())
    rid = svc.start(BRIEF)
    v = svc.run_view(rid)
    assert v["status"] == "DONE" and v["terminal"] and not v["busy"] and v["question"] is None
    assert [s["state"] for s in v["strip"]] == ["done"] * 5
    parts_step = v["strip"][1]
    assert [c["id"] for c in parts_step["chips"]] == ["MON-001", "FWG-001", "FLR-001", "RWG-001"]
    assert set(v["screenshots"]) == {"iso", "front", "top"}
    assert v["screenshots"]["iso"] == f"/api/design/{rid}/screenshots/iso.png"
    assert len(v["parts"]) == 4 and all(p["rebuildable"] and p["version"] == 1 for p in v["parts"])
    assert all(any(f["article"] == "C2.3.1" and f["status"] == "VERIFIED" for f in p["fia"]) for p in v["parts"])
    assert len(v["log"]) <= 15 and v["counters"]["claude_calls"] == 5 and v["has_summary"]
    assert all(a["flag"] == "ASSUMPTION" for a in v["assumptions"])


def test_strip_states_for_question_blocked_and_failed():
    base = {"run_id": "20261010-120000-x", "brief": "b", "created": "t", "events": [{"t": "", "msg": f"m{i}"} for i in range(30)],
            "kit": [{"id": "MON-001"}], "parts": {}, "plan": None, "assembly": None, "screenshots": {},
            "counters": {"script_calls": 0, "claude_calls": 1, "depth_first": None, "depth_last": None}}
    v = build_design_view(dict(base, status="AWAITING_USER", phase="PLAN", question={"text": "Wheelbase?"}))
    assert v["strip"][0]["state"] == "waiting" and v["question"] == {"text": "Wheelbase?"}
    assert v["log"] == [f"m{i}" for i in range(15, 30)]
    v = build_design_view(dict(base, status="BLOCKED_FUSION", phase="PARTS", banner="Restart Fusion ...",
                               parts={"MON-001": {"state": "building", "attempts": []}}))
    assert v["strip"][0]["state"] == "done" and v["strip"][1]["state"] == "blocked" and v["banner"]
    assert v["strip"][1]["chips"] == [{"id": "MON-001", "state": "building"}] and v["screenshots"] == {}
    v = build_design_view(dict(base, status="FAILED", phase="PLAN", error="plan rejected twice"))
    assert v["strip"][0]["state"] == "failed" and v["error"] == "plan rejected twice"


def test_one_run_at_a_time(tmp_path):
    svc, fake, reasoner = _service(tmp_path, _full())
    gate = threading.Event()
    svc._worker = threading.Thread(target=gate.wait, daemon=True)
    svc._worker.start()
    svc._worker_run = "20261010-120000-other"
    with pytest.raises(ValueError):
        svc.start(BRIEF)
    gate.set()


def test_rebuild_and_files(tmp_path):
    svc, fake, reasoner = _service(tmp_path, _full())
    rid = svc.start(BRIEF)
    n = len(fake.scripts)
    svc.rebuild(rid, "FWG-001")
    assert len(fake.scripts) == n + 5 and reasoner.calls == 5
    assert svc.screenshot_path(rid, "iso").read_bytes().startswith(b"\x89PNG")
    assert "Claude calls: 5" in svc.summary_text(rid)
    with pytest.raises(KeyError):
        svc.rebuild(rid, "XYZ-001")
    with pytest.raises(KeyError):
        svc.screenshot_path(rid, "../../run")


def test_question_answer_flow(tmp_path):
    svc, fake, reasoner = _service(tmp_path, {"plan": [mini_f1_plan(question="Which wheelbase?"), mini_f1_plan()],
                                              "part": [{"body": MINI_BOX_BODY}] * 4})
    rid = svc.start(BRIEF)
    assert svc.run_view(rid)["question"] == {"text": "Which wheelbase?"}
    with pytest.raises(ValueError):
        svc.answer(rid, "   ")
    svc.answer(rid, "3000 mm")
    v = svc.run_view(rid)
    assert v["status"] == "DONE" and v["answer"]["answer"] == "3000 mm"


# ---------------------------------------------------------------- HTTP API
@pytest.fixture
def server(tmp_path):
    svc, fake, reasoner = _service(tmp_path, _full())
    strict = AgentService(project="bench", root=tmp_path, fusion=FakeFusion(),
                          backend_factory=lambda run: ScriptedBackend({}), background=False)
    srv = make_server(strict, port=0, design=svc)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _call(url, data=None):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read()
            ct = r.headers.get("Content-Type", "")
            return r.status, (json.loads(body) if "json" in ct else body if "image" in ct else body.decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_fast_mode_end_to_end(server):
    code, page = _call(server + "/")
    assert code == 200 and "/static/fast.js" in page and "brief" in page and "Advanced" in page
    assert _call(server + "/static/fast.js")[0] == 200
    code, r = _call(server + "/api/design", {"brief": BRIEF})
    assert code == 201
    rid = r["run_id"]
    code, v = _call(server + f"/api/design/{rid}")
    assert code == 200 and v["status"] == "DONE" and len(v["parts"]) == 4
    code, png = _call(server + v["screenshots"]["iso"])
    assert code == 200 and png.startswith(b"\x89PNG")
    code, md = _call(server + f"/api/design/{rid}/summary")
    assert code == 200 and "no FIA compliance" in md
    assert _call(server + "/api/design")[1][0]["run_id"] == rid
    assert _call(server + f"/api/design/{rid}/rebuild", {"part_id": "MON-001"})[0] == 202
    assert _call(server + f"/api/design/{rid}/answer", {"text": "x"})[0] == 400       # no open question
    assert _call(server + f"/api/design/{rid}/continue", {})[0] == 202
    assert _call(server + "/api/design/20991010-000000-nope")[0] == 404
    assert _call(server + f"/api/design/{rid}/screenshots/side.png")[0] == 404
    assert _call(server + "/api/design", {"brief": "  "})[0] == 400


def test_http_strict_mode_still_served(server):
    code, page = _call(server + "/advanced")
    assert code == 200 and "advanced.js" in page
    assert _call(server + "/api/runs")[0] == 200


def test_http_rebuild_assembly_returns_a_new_run(server):
    code, r = _call(server + "/api/design", {"brief": BRIEF})
    code, r2 = _call(server + f"/api/design/{r['run_id']}/rebuild-assembly", {})
    assert code == 201 and r2["run_id"] != r["run_id"]
    v = _call(server + f"/api/design/{r2['run_id']}")[1]
    assert v["mode"] == "assembly_rebuild" and v["source_run"] == r["run_id"] and v["status"] == "DONE"
    assert v["counters"]["claude_calls"] == 0


def test_http_read_only_browses_recorded_runs_and_refuses_every_post(tmp_path):
    svc, fake, reasoner = _service(tmp_path, _full())
    rid = svc.start(BRIEF)                                     # a recorded run, made before the read-only server
    calls = reasoner.calls
    strict = AgentService(project="bench", root=tmp_path, fusion=FakeFusion(),
                          backend_factory=lambda run: ScriptedBackend({}), background=False)
    srv = make_server(strict, port=0, design=svc, read_only=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
        assert _call(base + "/api/status")[1]["read_only"] is True
        assert "ro-only" in _call(base + "/")[1]
        assert _call(base + "/api/design")[1][0]["run_id"] == rid
        code, v = _call(base + f"/api/design/{rid}")
        assert code == 200 and v["status"] == "DONE"
        assert _call(base + v["screenshots"]["iso"])[1].startswith(b"\x89PNG")
        assert _call(base + f"/api/design/{rid}/summary")[0] == 200
        for path, body in (("/api/design", {"brief": BRIEF}), (f"/api/design/{rid}/rebuild", {"part_id": "MON-001"}),
                           (f"/api/design/{rid}/rebuild-assembly", {}), (f"/api/design/{rid}/recolor", {}),
                           (f"/api/design/{rid}/render", {}), (f"/api/design/{rid}/continue", {}),
                           (f"/api/design/{rid}/revise", {"target": "FWG-001", "instruction": "x"}),
                           (f"/api/design/{rid}/revert", {"part_id": "FWG-001", "version": 1}),
                           ("/api/runs", {"request": "x"})):
            code, err = _call(base + path, body)
            assert code == 403 and "read-only" in err["error"], path
        assert reasoner.calls == calls
        assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------- revise / revert API (agent/revise.py)
@pytest.fixture
def revise_server(tmp_path):
    from agent.revise import Reviser  # noqa: F401  (import check)
    reasoner = ScriptedReasoner(_full())
    rev = ScriptedReasoner({"revise": [{"spec_delta": {"dims": {"width": 1700.0}, "envelope_min": [600.0, -850.0, 60.0],
                                                       "envelope_max": [1000.0, 850.0, 300.0]},
                                        "body": MINI_BOX_BODY + "    # narrower\n", "change_summary": "span 1700 mm",
                                        "assumptions": [], "neighbour_adjustments": []}]})
    fake = FakePartFusion(from_params=True, geometric_mates=True)
    svc = DesignService(project="mini_f1", root=tmp_path, fusion=fake, reasoner_factory=lambda run: reasoner,
                        background=False, revise_reasoner_factory=lambda d: rev)
    strict = AgentService(project="bench", root=tmp_path, fusion=FakeFusion(),
                          backend_factory=lambda run: ScriptedBackend({}), background=False)
    srv = make_server(strict, port=0, design=svc)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_http_revise_then_revert(revise_server):
    s = revise_server
    rid = _call(s + "/api/design", {"brief": BRIEF})[1]["run_id"]
    v = _call(s + f"/api/design/{rid}")[1]
    fwg = next(p for p in v["parts"] if p["id"] == "FWG-001")
    assert v["revisable"] and fwg["revisable"] and fwg["active_version"] == 1 and fwg["revert_versions"] == []
    assert v["revisions"] == []
    code, r = _call(s + f"/api/design/{rid}/revise", {"target": "FWG-001", "instruction": "Make the span 1700 mm."})
    assert code == 202 and r == {"ok": True}
    v = _call(s + f"/api/design/{rid}")[1]
    rv = v["revisions"][0]
    assert rv["state"] == "DONE" and rv["steps"][0]["new_version"] == 2 and rv["steps"][0]["change_summary"] == "span 1700 mm"
    assert rv["counters"]["claude_calls"] == 1 and rv["counters"]["script_calls"] <= 10
    assert rv["mates"][0]["status"] == "VERIFIED" and rv["steps"][0]["bbox_delta"]["min"] == [0.0, 50.0, 0.0]
    assert [p["view"] for p in rv["pairs"]] == ["iso", "front", "top"]
    code, png = _call(s + rv["pairs"][0]["after"])
    assert code == 200 and png.startswith(b"\x89PNG")
    assert _call(s + rv["pairs"][0]["before"])[0] == 200
    fwg = next(p for p in v["parts"] if p["id"] == "FWG-001")
    assert fwg["version"] == 2 and fwg["active_version"] == 2 and fwg["revert_versions"] == [1]
    assert _call(s + f"/api/design/{rid}/revert", {"part_id": "FWG-001", "version": 1})[0] == 202
    v = _call(s + f"/api/design/{rid}")[1]
    assert v["revisions"][1]["kind"] == "revert" and v["revisions"][1]["state"] == "DONE"
    assert next(p for p in v["parts"] if p["id"] == "FWG-001")["active_version"] == 3
    # input errors: synchronous, nothing started
    assert _call(s + f"/api/design/{rid}/revise", {"target": "FWG-001", "instruction": "  "})[0] == 400
    assert _call(s + f"/api/design/{rid}/revise", {"target": "XYZ-001", "instruction": "x"})[0] == 404
    assert _call(s + f"/api/design/{rid}/revert", {"part_id": "FWG-001", "version": "one"})[0] == 400
    assert _call(s + f"/api/design/{rid}/revisions/R01/after_side.png")[0] == 404
    assert _call(s + f"/api/design/{rid}/revisions/R09/after_iso.png")[0] == 404
    assert len(v["revisions"]) == 2
