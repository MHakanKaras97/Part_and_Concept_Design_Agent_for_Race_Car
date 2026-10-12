"""Service facade, HTTP API, reasoning backends and CLI smoke tests (no real Fusion / Claude needed)."""
import hashlib
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent.reasoning import (ClaudeCodeBackend, FallbackBackend, FileExchangeBackend, ReasoningBackendError,
                             make_task)
from agent.service import AgentService, build_run_view
from agent.workflow import Engine, create_run, load_run
from fusion.client import FusionUnavailable
from tests.helpers import (LOAD_QUESTION, REQUEST, FakeFusion, ScriptedBackend, analysis_response, plan_response)
from ui.server import make_server
from vehicle.store import ProjectStore

ROOT = Path(__file__).resolve().parent.parent
ACCEPT = {"decision": "ACCEPT", "rationale": "all blocking checks pass"}
ANSWER = "The box weighs 2 kg and sees up to 5 g of vibration."


def _service(tmp_path, responses, fusion=None):
    backend = ScriptedBackend(responses)
    return AgentService(project="bench", root=tmp_path, fusion=fusion or FakeFusion(),
                        backend_factory=lambda run: backend, background=False), backend


def _full_responses():
    return {"analysis": [analysis_response(ask_load=True), analysis_response(load_answer="weighs 2 kg and sees up to 5 g")],
            "plan": [plan_response()], "review": [ACCEPT]}


# ---------------------------------------------------------------- service / view model
def test_service_runs_the_existing_workflow_and_exposes_the_question(tmp_path):
    svc, _ = _service(tmp_path, _full_responses())
    run_id = svc.start_run(REQUEST)
    v = svc.run_view(run_id)
    assert v["status"] == "AWAITING_USER"
    assert v["open_questions"] == [{"id": "M01", "question": LOAD_QUESTION, "criticality": "CRITICAL", "follows_up": None}]
    pipe = {s["key"]: s["state"] for s in v["pipeline"]}
    assert pipe["REQUIREMENTS"] == "done" and pipe["QUESTIONS"] == "waiting" and pipe["CAD"] == "todo"
    last = v["messages"][-1]
    assert last["layer"] == "QUESTION" and last["pending"] is True and last["text"] == LOAD_QUESTION


def test_service_answer_is_verbatim_and_layers_are_distinct(tmp_path):
    svc, _ = _service(tmp_path, _full_responses())
    run_id = svc.start_run(REQUEST)
    svc.answer(run_id, "M01", ANSWER)
    v = svc.run_view(run_id)
    assert v["status"] == "COMPLETED"
    layers = [m["layer"] for m in v["messages"]]
    for layer in ("USER_REQUEST", "QUESTION", "USER_ANSWER", "AI_INTERPRETATION", "ASSUMPTION",
                  "ENGINEERING_DECISION", "VALIDATION", "REVIEW", "RESULT"):
        assert layer in layers, layer
    ans = next(m for m in v["messages"] if m["layer"] == "USER_ANSWER")
    assert ans["text"] == ANSWER and ans["role"] == "user"
    interp = next(m for m in v["messages"] if m["layer"] == "AI_INTERPRETATION")
    r07 = next(i for i in interp["items"] if i["id"] == "R07")
    assert r07["source"] == "USER_ANSWER" and r07["quote"] in ANSWER
    labels = v["validation"]["labels"]
    assert "HOLE_GEOMETRY_VERIFIED" in labels and "MATING_INTERFACE_NOT_VERIFIED" in labels
    assert v["validation"]["fia"] == "FIA_NOT_APPLICABLE"
    assert v["component"]["id"] == "BRK-001" and v["component"]["revision"] == 1
    assert all(i["mating"] == "NOT_VERIFIED" for i in v["component"]["interfaces"])
    assert all(s["state"] == "done" for s in v["pipeline"] if s["key"] != "QUESTIONS")
    run = load_run(svc.store, run_id)
    assert run["user_answers"]["M01"]["entered_via"] == "ui: web interface"


def test_service_rejects_bad_input(tmp_path):
    svc, _ = _service(tmp_path, {"analysis": [analysis_response(ask_load=True)]})
    with pytest.raises(ValueError):
        svc.start_run("   ")
    run_id = svc.start_run(REQUEST)
    with pytest.raises(ValueError):
        svc.answer(run_id, "M09", "x")
    with pytest.raises(KeyError):
        svc.run_view("../../etc")
    with pytest.raises(KeyError):
        svc.run_view("20990101-000000-nope")


def test_fusion_status_reports_offline(tmp_path):
    svc, _ = _service(tmp_path, {}, fusion=FakeFusion(unavailable=True))
    assert svc.system_status()["fusion"]["connected"] is False


class _CountingFusion(FakeFusion):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.connects, self.scripts = 0, 0

    def connect(self):
        self.connects += 1
        return super().connect()

    def ping(self):                                            # the real ping() is one script call
        self.scripts += 1
        if self.unavailable:
            raise FusionUnavailable("test: fusion down")
        return {"fusion_version": "test-1", "active_document": "Untitled", "has_design": True}

    def run_script(self, script, read_only=False):
        self.scripts += 1
        return super().run_script(script, read_only)


def test_fusion_status_polls_without_running_scripts(tmp_path):
    """Every Fusion script call leaks one stdout wrapper layer in the MCP add-in, so the UI status poll must use
    the handshake only: one script ping per (re)connection, none per poll."""
    fusion = _CountingFusion()
    svc, _ = _service(tmp_path, {}, fusion=fusion)
    for _ in range(100):
        st = svc.fusion_status(max_age_s=0)
    assert st == {"connected": True, "version": "test-1", "document": "Untitled", "checked_at": st["checked_at"]}
    assert fusion.connects == 100 and fusion.scripts == 1
    fusion.unavailable = True                                  # Fusion goes away ...
    assert svc.fusion_status(max_age_s=0)["connected"] is False
    fusion.unavailable = False                                 # ... and comes back: version/document re-read once
    for _ in range(10):
        assert svc.fusion_status(max_age_s=0)["connected"] is True
    assert fusion.scripts == 2


def test_fusion_status_is_cached(tmp_path):
    fusion = _CountingFusion()
    svc, _ = _service(tmp_path, {}, fusion=fusion)
    for _ in range(5):
        svc.system_status()
    assert fusion.connects == 1 and fusion.scripts == 1


def test_legacy_runs_render_read_only():
    """The committed MVP 1.0 and 1.1 runs must render, and rendering must not modify any file."""
    store = ProjectStore("prototype_bench")
    files = sorted((ROOT / "data").rglob("*"))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
    for run_id in ("20261005-203018-design-a-machined-alumin", "20261005-205141-design-a-machined-alumin"):
        v = build_run_view(load_run(store, run_id).data, store)
        assert v["status"] == "COMPLETED" and v["component"]["revision"] == 1
        assert any(m["layer"] == "USER_ANSWER" for m in v["messages"])
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
    assert before == after


# ---------------------------------------------------------------- HTTP API
@pytest.fixture
def server(tmp_path):
    svc, _ = _service(tmp_path, _full_responses())
    srv = make_server(svc, port=0)
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
            return r.status, (json.loads(body) if "json" in r.headers.get("Content-Type", "") else body.decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_end_to_end(server):
    code, page = _call(server + "/")
    assert code == 200 and "AI ENGINEERING AGENT" in page and "Made by Muhammed Hakan Karas" in page
    code, adv = _call(server + "/advanced")                     # the strict UI moved to the Advanced page
    assert code == 200 and "/static/advanced.js" in adv and "Made by Muhammed Hakan Karas" in adv
    assert _call(server + "/static/advanced.js")[0] == 200
    code, st = _call(server + "/api/status")
    assert code == 200 and st["fusion"]["connected"] is True and st["reasoner"]["mode"] == "custom"
    code, r = _call(server + "/api/runs", {"request": REQUEST})
    assert code == 201
    run_id = r["run_id"]
    code, v = _call(f"{server}/api/runs/{run_id}")
    assert v["status"] == "AWAITING_USER" and v["open_questions"][0]["id"] == "M01"
    code, _ = _call(f"{server}/api/runs/{run_id}/answer", {"question_id": "M01", "text": ANSWER})
    assert code == 202
    code, v = _call(f"{server}/api/runs/{run_id}")
    assert v["status"] == "COMPLETED" and v["component"]["id"] == "BRK-001"
    code, report = _call(f"{server}/api/runs/{run_id}/report")
    assert code == 200 and ANSWER in report
    code, runs = _call(server + "/api/runs")
    assert [x["run_id"] for x in runs] == [run_id]


def test_http_errors(server):
    assert _call(server + "/api/runs", {"request": ""})[0] == 400
    assert _call(server + "/api/runs/20990101-000000-nope")[0] == 404
    assert _call(server + "/static/../agent/workflow.py")[0] == 404
    assert _call(server + "/static/..%2Fagent%2Fworkflow.py")[0] == 404
    assert _call(server + "/api/nothing")[0] == 404


def test_server_refuses_non_local_bind(tmp_path):
    svc, _ = _service(tmp_path, {})
    with pytest.raises(ValueError):
        make_server(svc, port=0, host="0.0.0.0")


# ---------------------------------------------------------------- reasoning backends
def _task(kind="review"):
    return make_task("20261005-000000-x", 1, kind, {"note": "test"})


def _runner(code=0, envelope=None, raw=None):
    def run(cmd, prompt, cwd, timeout):
        run.cmd, run.prompt = cmd, prompt
        events = [{"type": "system", "subtype": "init"}, dict(envelope or {}, type="result")]
        return code, raw if raw is not None else "\n".join(json.dumps(e) for e in events), "err"
    return run


def test_claude_code_backend_success_writes_audit_trail(tmp_path):
    env = {"subtype": "success", "is_error": False, "structured_output": ACCEPT, "num_turns": 2,
           "modelUsage": {"claude-opus-5-5": {}}, "total_cost_usd": 0.1, "session_id": "s"}
    runner = _runner(envelope=env)
    b = ClaudeCodeBackend(tmp_path, runner=runner)
    assert b.request(_task()) == ACCEPT
    assert runner.cmd[:2] == ["claude", "-p"] and "--json-schema" in runner.cmd and runner.cmd[runner.cmd.index("--tools") + 1] == ""
    msg = json.loads(runner.prompt)
    assert msg["type"] == "user" and "## Context" in msg["message"]["content"][0]["text"]
    d = tmp_path / "reasoning"
    assert json.loads((d / "01_review.response.json").read_text()) == ACCEPT
    meta = json.loads((d / "01_review.meta.json").read_text())
    assert meta["answered_by"] == "claude_code" and meta["models"] == ["claude-opus-5-5"]
    assert meta["reported_cost_usd"] == 0.1 and "session_id" not in meta
    assert (d / "01_review.request.md").exists()
    assert "claude-opus-5-5" in b.last_source


@pytest.mark.parametrize("runner", [
    _runner(code=1),
    _runner(raw="not json"),
    _runner(envelope={"subtype": "error_max_turns", "is_error": True}),
    _runner(envelope={"subtype": "success", "is_error": False, "structured_output": None}),
])
def test_claude_code_backend_failures_raise(tmp_path, runner):
    with pytest.raises(ReasoningBackendError):
        ClaudeCodeBackend(tmp_path, runner=runner).request(_task())


def test_fallback_to_file_exchange_when_claude_fails(tmp_path):
    fb = FallbackBackend(ClaudeCodeBackend(tmp_path, runner=_runner(code=1)), FileExchangeBackend(tmp_path))
    assert fb.request(_task()) is None
    assert "unavailable" in fb.last_error
    assert (tmp_path / "reasoning" / "01_review.request.md").exists()


def test_existing_response_file_is_used_without_calling_claude(tmp_path):
    (tmp_path / "reasoning").mkdir()
    (tmp_path / "reasoning" / "01_review.response.json").write_text(json.dumps(ACCEPT))
    def boom(*a):
        raise AssertionError("claude must not be called")
    assert ClaudeCodeBackend(tmp_path, runner=boom).request(_task()) == ACCEPT


def test_engine_logs_which_reasoner_answered_and_caps_rejections(tmp_path):
    bad = analysis_response()
    bad["requirements"][0]["quote"] = "words the user never wrote"
    store = ProjectStore("bench", root=tmp_path)
    backend = ScriptedBackend({"analysis": [bad] * 10})
    backend.last_source = "scripted"
    run = Engine(store, backend_factory=lambda r: backend, fusion=FakeFusion()).advance(create_run(store, REQUEST))
    assert run["status"] == "STOPPED" and "rejected 4 times" in run["stop_reason"]
    assert any("answered via scripted" in e["message"] for e in run["events"])


# ---------------------------------------------------------------- CLI still works
@pytest.mark.parametrize("args", [["--help"], ["rules"], ["components"],
                                  ["status", "20261005-205141-design-a-machined-alumin"]])
def test_cli_smoke(args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}          # the child writes UTF-8 whatever the console codepage
    p = subprocess.run([sys.executable, "-B", "-m", "agent", *args], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=120)
    assert p.returncode == 0, p.stderr
    if args == ["components"]:
        assert "BRK-001 rev 1" in p.stdout and "BRK-002 rev 1" in p.stdout


def test_ui_falls_back_to_file_exchange_without_claude_code(tmp_path):
    svc = AgentService(project="bench", root=tmp_path, fusion=FakeFusion(), background=False,
                       claude_executable="definitely-not-an-installed-claude")
    assert svc.reasoner["mode"] == "file_exchange" and "unavailable" in svc.reasoner["detail"]
    v = svc.run_view(svc.start_run(REQUEST))
    assert v["status"] == "AWAITING_REASONING"
    assert (svc.store.runs_dir / v["run_id"] / "reasoning" / "01_analysis.request.md").exists()


def test_forced_claude_mode_falls_back_per_task_when_cli_fails(tmp_path):
    svc = AgentService(project="bench", root=tmp_path, fusion=FakeFusion(), background=False,
                       reasoner="claude_code", claude_executable="definitely-not-an-installed-claude")
    svc.reasoner = {"mode": "claude_code", "available": True, "detail": "forced for test"}
    svc.engine.backend_factory = svc._make_factory("claude_code")
    run_id = svc.start_run(REQUEST)
    run = load_run(svc.store, run_id)
    assert run["status"] == "AWAITING_REASONING"
    assert any("Reasoning backend fallback: claude_code unavailable" in e["message"] for e in run["events"])
