"""Regression: the fast UI's run selector showed RUNNING for a run whose status is DONE.

Root cause: ui/static/fast.js built the <select> options once (page load / after starting a run) and refresh() never
updated them, so an option loaded while the run was RUNNING kept that text after the run finished. Fix: one
server-side label (design_service.run_label) for the run list and the run view; after every poll the page reloads the
list when the selected option differs from the fresh view."""
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from agent.design_run import create_design_run, load_design_run
from agent.design_service import DesignService, run_label
from agent.fast_reasoning import ScriptedReasoner
from agent.service import AgentService
from tests.helpers import MINI_BOX_BODY, FakeFusion, FakePartFusion, ScriptedBackend, mini_f1_plan
import ui.server as server

EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()),
            shutil.which("msedge") or shutil.which("chromium") or shutil.which("google-chrome"))


def _svc(tmp_path):
    rs = ScriptedReasoner({"plan": [mini_f1_plan()], "part": [{"body": MINI_BOX_BODY}] * 4})
    return DesignService(project="mini_f1", root=tmp_path, fusion=FakePartFusion(), reasoner_factory=lambda r: rs,
                         background=False)


def test_list_and_view_share_one_label_and_a_finished_run_reads_done(tmp_path):
    svc = _svc(tmp_path)
    run = create_design_run(svc.store, "Mini F1")                       # created: RUNNING, not yet advanced
    assert svc.list_runs()[0]["label"] == f"{run.id} · RUNNING" == svc.run_view(run.id)["run_label"]
    svc.resume(run.id)                                                  # runs to the end
    assert load_design_run(svc.store, run.id)["status"] == "DONE"
    assert svc.list_runs()[0]["label"] == f"{run.id} · DONE" == svc.run_view(run.id)["run_label"]
    assert run_label({"run_id": "x", "status": "DONE"}) == "x · DONE"


def test_page_reloads_a_stale_option_from_the_server():
    js = (server.STATIC / "fast.js").read_text(encoding="utf-8")
    refresh = js[js.index("async function refresh()"):js.index("window.addEventListener")]
    assert "syncRunOption(S.view)" in refresh
    assert "text: r.label" in js and "${r.run_id} · ${r.status}" not in js                 # no status text composed client-side


@pytest.mark.skipif(not EDGE, reason="no headless Edge/Chromium available")
def test_browser_selector_shows_done_after_the_run_finishes(tmp_path):
    """Real page in headless Edge: loaded while RUNNING, the run finishes, the selector must then read DONE."""
    svc = _svc(tmp_path)
    run = create_design_run(svc.store, "Mini F1")
    harness = (server.STATIC / "index.html").read_text(encoding="utf-8").replace(
        '<script src="/static/fast.js"></script>', '''<script src="/static/fast.js"></script>
<pre id="out">pending</pre>
<script>
const opt = () => document.querySelector('#run-select option[value="%s"]');
const st = (o) => o ? o.textContent.split(" ").pop() : "missing";
setTimeout(() => {
  const before = st(opt());
  fetch("/finish").then(() => setTimeout(() => {
    document.getElementById("out").textContent = before + " then " + st(opt());
  }, 5000));
}, 1500);
</script>''' % run.id)
    strict = AgentService(project="bench", root=tmp_path, fusion=FakeFusion(),
                          backend_factory=lambda r: ScriptedBackend({}), background=False)

    class H(server.make_handler(strict, svc)):
        def _get(self, path):
            if path == "/harness":
                return self._send(200, harness.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/finish":
                svc.resume(run.id)
                return self._json(200, {"ok": True})
            return super()._get(path)
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        out = subprocess.run([EDGE, "--headless=new", "--disable-gpu", f"--user-data-dir={tmp_path / 'edge'}",
                              "--virtual-time-budget=20000", "--dump-dom",
                              f"http://127.0.0.1:{srv.server_address[1]}/harness?run={run.id}"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90).stdout
    finally:
        srv.shutdown()
        srv.server_close()
    got = out.split('<pre id="out">', 1)[1].split("</pre>", 1)[0] if '<pre id="out">' in out else out[:300]
    assert got == "RUNNING then DONE", got                             # the stale-option bug gave RUNNING then RUNNING
