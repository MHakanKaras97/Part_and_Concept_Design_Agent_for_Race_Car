"""Render pipeline (fusion/render.py, agent/render_run.py): preflight by tag, start + one state check per minute,
refusal / failure / timeout -> recorded MCP screenshot fallback, depth refusal, run.json entries, CLI and the HTTP
route - with the fake Fusion and a fake clock (no Fusion, no waiting)."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from agent import __main__ as cli
from agent import render_run
from agent.design_run import load_design_run
from agent.render_run import bbox_boxes, parse_options
from fusion.assembly import VIEWS
from fusion.client import FusionOutputLost
from fusion.render import MAX_LINE, png_size, poll_script, preflight_script, start_script
from tests.helpers import decode_part_cfg
from tests.test_mirror import run18


class Clock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(render_run, "temp_render_dir", lambda: tmp_path / "fusion_tmp")
    store, fake, reasoner, orch, run = run18(tmp_path)
    clock = Clock()
    orch.render_sleep, orch.render_clock = clock.sleep, clock
    return store, fake, reasoner, orch, run, clock


def registry(store):
    return {p.name: p.read_bytes() for p in store.components_dir.glob("*.json")}


def test_render_iso_records_the_image_in_run_json(setup):
    store, fake, reasoner, orch, run, clock = setup
    fake.render_polls = 2
    reg, claude0, n0, s0 = registry(store), reasoner.calls, len(fake.scripts), len(fake.screens)
    rd = orch.render(load_design_run(store, run.id))
    assert rd["id"] == "RD01" and rd["status"] == "done" and rd["error"] is None
    assert rd["script_calls"] == 1 + 1 + 2 == len(fake.scripts) - n0                # preflight + start + 2 polls
    assert clock.sleeps == [60, 60]                                                  # one state check per minute
    (it,) = rd["items"]
    assert it["render_full"] == "renders/RD01/iso.png" and it["full_size"] == [1920, 1280]
    assert it["render_cropped"] == "renders/RD01/iso_cropped.png" and it["crop"]["resized"] == "none"
    assert png_size(run.dir / it["render_full"]) == (1920, 1280)
    full = {k: it.pop(k) for k in ("render_full", "render_cropped", "crop", "native_size", "full_size")}
    assert it == {"view": "iso", "state": "finished", "progress": 1.0, "method": "render",
                  "path": "renders/RD01/iso_cropped.png", "size_bytes": it["size_bytes"],
                  "width": full["crop"]["output_size"][0], "height": full["crop"]["output_size"][1],
                  "quality": 50, "seconds": 120.0, "note": it["note"], "error": None,
                  "settings": {"aspect_custom": True, "width": 1920, "height": 1280, "quality": 50},
                  "scene": None, "frame": it["frame"],
                  "environment_read_back": "unreadable with a solid background",
                  "calibration": it["calibration"]}
    assert it["calibration"]["id"] == "perspective-3:2-2705.1.30"
    assert it["note"].startswith("the narrowed camera angle corresponds to a nominal 112.74 mm")
    assert "NOT upscaled" in it["note"]
    assert it["size_bytes"] > 0 and png_size(run.dir / it["path"]) == tuple(full["crop"]["output_size"])
    cfg = fake.render_starts[0]
    assert cfg["doc_tag"] == run["doc_tag"] and cfg["quality"] == 50 and (cfg["width"], cfg["height"]) == (1920, 1280)
    assert (tuple(cfg["dir"]), tuple(cfg["up"])) == VIEWS["iso"]                    # screenshot view direction
    assert len(cfg["boxes_mm"]) == 18 == len(bbox_boxes(run))                          # framed from the part bboxes
    assert cfg["boxes_mm"][0] == [[round(v, 1) for v in c] for c in bbox_boxes(run)[0]]
    script = fake.scripts[n0 + 1]
    assert max(len(ln) for ln in script.splitlines()) < MAX_LINE                     # see fusion/render.start_script
    assert cfg["environment"] is None and cfg["max_depth"] == 100
    assert (cfg["camera"], cfg["focal_mm"], cfg["background"], cfg["background_rgb"]) == \
        ("perspective", 50.0, "#3A3F47", [0x3A, 0x3F, 0x47])
    assert cfg["ground_reflections"] is True and cfg["ground_roughness"] == 0.15 and cfg["fill"] == 0.8
    assert rd["preset"] == "standard" and rd["seconds"] == 120.0 and rd["options"]["camera"] == "perspective"
    assert rd["preflight"]["active_is_run_document"] and rd["preflight"]["environments"] == fake.environments
    saved = load_design_run(store, run.id)
    assert saved["renders"][-1]["items"][0]["method"] == "render"
    assert registry(store) == reg and reasoner.calls == claude0                    # no registry write, no Claude
    assert len(fake.screens) == s0                                                   # no screenshot taken
    assert "RD01: iso rendered (1920x1280, 120.0 s)" in saved["events"][-1]["msg"]


def test_refused_render_falls_back_to_the_marked_screenshot(setup):
    store, fake, reasoner, orch, run, clock = setup
    fake.render_mode = "refuse"
    shots0 = len(fake.screens)
    rd = orch.render(load_design_run(store, run.id))
    (it,) = rd["items"]
    assert it["method"] == "screenshot_fallback" and it["state"] == "fallback"
    assert it["error"] == "render refused: RuntimeError: rendering is not available"
    assert "NOT a render: MCP screenshot 2400x1600 (fallback)" in it["note"]
    assert fake.screens[shots0:] == ["current"] and fake.screen_sizes[-1] == (2400, 1600)
    assert (run.dir / it["path"]).read_bytes().startswith(b"\x89PNG test")
    assert rd["script_calls"] == 3 and rd["status"] == "done"                        # preflight + start + camera
    assert "SCREENSHOT FALLBACK" in load_design_run(store, run.id)["events"][-1]["msg"]


def test_timeout_checks_once_a_minute_then_falls_back(setup):
    store, fake, reasoner, orch, run, clock = setup
    fake.render_mode = "never"
    rd = orch.render(load_design_run(store, run.id))
    (it,) = rd["items"]
    assert clock.sleeps == [60] * 15 and rd["script_calls"] == 1 + 1 + 15 + 1
    assert it["method"] == "screenshot_fallback" and it["seconds"] == 900.0
    assert it["error"] == "render timed out after 900 s (last state processing, progress 50%)"
    assert "may still be running in Fusion" in it["note"]


def test_failed_render_falls_back(setup):
    store, fake, reasoner, orch, run, clock = setup
    fake.render_mode = "fail"
    rd = orch.render(load_design_run(store, run.id))
    assert rd["items"][0]["method"] == "screenshot_fallback"
    assert rd["items"][0]["error"] == "Fusion reported the render as failed"


def test_lost_render_future_completes_from_the_output_file(setup):
    store, fake, reasoner, orch, run, clock = setup
    fake.render_mode = "lose_future"
    rd = orch.render(load_design_run(store, run.id))
    (it,) = rd["items"]
    assert it["method"] == "render" and it["full_size"] == [1920, 1280]
    assert "completion taken from the output file" in it["note"] and "_lost_future" not in it


def test_settings_read_back_mismatch_is_noted(setup):
    store, fake, reasoner, orch, run, clock = setup
    fake.render_readback = {"height": 1080, "aspect_custom": False}
    rd = orch.render(load_design_run(store, run.id))
    assert rd["items"][0]["method"] == "render"
    assert "Fusion read back 1920x1080 (custom aspect False), requested 1920x1280" in rd["items"][0]["note"]


def test_deep_wrapper_refuses_before_any_render_or_screenshot(setup):
    store, fake, reasoner, orch, run, clock = setup
    fake.depth = 150
    n0, s0 = len(fake.scripts), len(fake.screens)
    rd = orch.render(load_design_run(store, run.id))
    assert rd["status"] == "refused" and "restart Fusion" in rd["error"] and "151 (> 100)" in rd["error"]
    assert len(fake.scripts) - n0 == 1 and len(fake.screens) == s0 and not fake.render_starts
    assert rd["items"][0]["state"] == "refused" and rd["items"][0]["method"] is None


def test_closed_document_and_unknown_environment_are_refused(setup):
    store, fake, reasoner, orch, run, clock = setup
    rd = orch.render(load_design_run(store, run.id), options={"environment": "Photo Booth"})
    assert rd["status"] == "refused" and "'Photo Booth' is not in the Fusion library" in rd["error"]
    rd = orch.render(load_design_run(store, run.id), options={"environment": "Plaza"})
    assert rd["status"] == "done" and fake.render_starts[-1]["environment"] == "Plaza"
    fake.close_document(run["doc_tag"])
    rd = orch.render(load_design_run(store, run.id))
    assert rd["id"] == "RD03" and rd["status"] == "refused" and "is not open in Fusion" in rd["error"]


def test_three_views_and_the_final_preset(setup):
    store, fake, reasoner, orch, run, clock = setup
    rd = orch.render(load_design_run(store, run.id), views=["top", "iso", "front"], options={"preset": "final"})
    assert [i["view"] for i in rd["items"]] == ["iso", "front", "top"]
    assert all(i["method"] == "render" and i["quality"] == 75 and i["full_size"] == [2400, 1600]
               for i in rd["items"])
    assert [tuple(c["dir"]) for c in fake.render_starts] == [VIEWS[v][0] for v in ("iso", "front", "top")]
    assert [c["view"] for c in fake.render_starts] == ["iso", "front", "top"]
    assert len({c["token"] for c in fake.render_starts}) == 3


@pytest.mark.parametrize("kw,needle", [({"options": {"quality": 60}}, "quality"), ({"views": ["side"]}, "views"),
                                       ({"views": ["iso", "iso"]}, "views"),
                                       ({"options": {"preset": "ultra"}}, "preset"),
                                       ({"options": {"camera": "fisheye"}}, "camera"),
                                       ({"options": {"focal_mm": 20}}, "focal_mm"),
                                       ({"options": {"focal_mm": 90}}, "focal_mm"),
                                       ({"options": {"background": "#3A3F4"}}, "background"),
                                       ({"options": {"brightness_lux": -1}}, "brightness"),
                                       ({"options": {"light_angle_deg": 200}}, "light_angle"),
                                       ({"options": {"ground_roughness": 1.5}}, "roughness"),
                                       ({"options": {"ground_reflections": "yes"}}, "ground_reflections"),
                                       ({"options": {"environment": "Custom..."}}, "placeholder")])
def test_bad_requests_are_rejected_without_fusion_calls(setup, kw, needle):
    store, fake, reasoner, orch, run, clock = setup
    n0 = len(fake.scripts)
    with pytest.raises(ValueError, match=needle):
        orch.render(load_design_run(store, run.id), **kw)
    assert len(fake.scripts) == n0


def test_output_lost_stops_the_render_and_says_so(setup, monkeypatch):
    store, fake, reasoner, orch, run, clock = setup
    real = fake.run_script

    def lossy(script, read_only=False, expect_result=True):
        if decode_part_cfg(script).get("render_poll"):
            raise FusionOutputLost("test: output lost")
        return real(script, read_only, expect_result)
    monkeypatch.setattr(fake, "run_script", lossy)
    rd = orch.render(load_design_run(store, run.id), views=["iso", "top"])
    assert rd["status"] == "failed" and "Fusion" in rd["error"] and "did not run" in rd["error"]
    assert rd["items"][0]["state"] == "failed" and "output lost" in rd["items"][0]["error"]
    assert rd["items"][1]["state"] == "skipped"


def test_scripts_compile_and_carry_the_tag():
    pts = [[[0, 0, 0], [100, 50, 30]]]
    for s in (preflight_script("mf1:x"), poll_script("mf1:x", "t"),
              start_script("mf1:x", "iso", pts, "C:/tmp/a.png", "t", parse_options().cfg(), 100)):
        compile(s, "render", "exec")
        assert decode_part_cfg(s)["doc_tag"] == "mf1:x"
    s = start_script("mf1:x", "iso", pts, "C:/tmp/a.png", "t", parse_options({"preset": "draft"}).cfg(), 100)
    cfg = decode_part_cfg(s)
    assert (cfg["quality"], cfg["width"], cfg["height"]) == (25, 1280, 853)
    # aspect ratio first, then the resolution (otherwise Fusion keeps the old aspect ratio)
    assert s.index("CustomRenderAspectRatio") < s.index("resolutionWidth = ") < s.index("resolutionHeight = ")
    # the environment (light) is set before the solid background colour (which switches the background type)
    assert s.index("sc.backgroundEnvironment = env") < s.index("sc.backgroundSolidColor = ")
    assert "preferences" not in s and "itemByName(CFG[\"environment\"])" in s
    assert "startLocalRender(CFG[\"path\"], cam)" in s
    assert '"viewport": [vp.width, vp.height]' in s                 # recorded with every render (calibration)
    for bad in ("documents.itemByName", "doc.name =="):
        assert bad not in s
    with pytest.raises(ValueError):
        start_script("mf1:x", "iso", pts, "a.png", "t", dict(parse_options().cfg(), preset="ultra"), 100)


def test_cli_render(setup, monkeypatch, capsys):
    store, fake, reasoner, orch, run, clock = setup
    monkeypatch.setattr("vehicle.store.DATA_ROOT", store.root.parent)
    monkeypatch.setattr("agent.design_run.Orchestrator.fusion", lambda self: fake)
    monkeypatch.setattr("agent.design_run.time.sleep", lambda s: None)
    assert cli.main(["render", run.id]) == 0
    out = capsys.readouterr().out
    assert "render RD01: done" in out and "full    renders/RD01/iso.png  [1920, 1280]" in out
    assert "renders/RD01/iso_cropped.png" in out
    assert "environment library: Sharp Highlights, Plaza" in out
    fake.render_mode = "refuse"
    assert cli.main(["render", run.id, "--views", "iso,front"]) == 1
    assert "SCREENSHOT FALLBACK" in capsys.readouterr().out


def test_http_render_route(tmp_path, monkeypatch):
    from agent.design_service import DesignService
    from agent.fast_reasoning import ScriptedReasoner
    from agent.service import AgentService
    from tests.helpers import MINI_BOX_BODY, FakeFusion, FakePartFusion, ScriptedBackend
    from tests.test_kit_scaling import BRIEF18
    from tests.test_mirror import derived_plan, gate
    from ui.server import make_server
    monkeypatch.setattr(render_run, "temp_render_dir", lambda: tmp_path / "fusion_tmp")
    plan = derived_plan()
    specs = {s.id: s for s in gate(plan)[0]}
    fake = FakePartFusion(envelopes={k: (list(s.envelope_min), list(s.envelope_max)) for k, s in specs.items()})
    rs = ScriptedReasoner({"plan": [plan], "part": [{"body": MINI_BOX_BODY}] * 12})
    svc = DesignService(project="mini_f1", root=tmp_path, fusion=fake, reasoner_factory=lambda r: rs, background=False)
    clock = Clock()
    svc.orch.render_sleep, svc.orch.render_clock = clock.sleep, clock
    run_id = svc.start(BRIEF18)
    strict = AgentService(project="bench", root=tmp_path, fusion=FakeFusion(),
                          backend_factory=lambda r: ScriptedBackend({}), background=False)
    srv = make_server(strict, port=0, design=svc)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        view = json.loads(urllib.request.urlopen(f"{base}/api/design/{run_id}", timeout=10).read())
        assert view["renders"] == [] and view["render_environments"] == []
        assert post(f"{base}/api/design/{run_id}/render", {}) == (202, {"ok": True})
        view = json.loads(urllib.request.urlopen(f"{base}/api/design/{run_id}", timeout=10).read())
        (rd,) = view["renders"]
        assert rd["id"] == "RD01" and rd["status"] == "done" and rd["quality"] == 50
        (it,) = rd["items"]
        assert it["method"] == "render" and it["url"] == f"/api/design/{run_id}/renders/RD01/iso.png"
        assert view["render_environments"] == ["Sharp Highlights", "Plaza"]
        png = urllib.request.urlopen(base + it["url_full"], timeout=10).read()
        assert png_size_bytes(png) == (1920, 1280) and it["url_full"].endswith("/RD01/iso_full.png")
        cropped = urllib.request.urlopen(base + it["url"], timeout=10).read()
        assert png_size_bytes(cropped) == (it["width"], it["height"]) and it["full_size"] == [1920, 1280]
        code, body = post(f"{base}/api/design/{run_id}/render", {"quality": 60})
        assert code == 400 and "quality" in body["error"]
        code, body = post(f"{base}/api/design/{run_id}/render", {"focal_mm": 120})
        assert code == 400 and "focal_mm" in body["error"]
        code, body = post(f"{base}/api/design/{run_id}/render", {"environment": "Photo Booth"})
        assert code == 400 and "not in the Fusion library list" in body["error"]
        assert post(f"{base}/api/design/{run_id}/render", {"views": ["front"], "preset": "draft",
                                                           "environment": "Plaza", "camera": "orthographic",
                                                           "background": "#202020", "ground_reflections": False,
                                                           "light_angle_deg": -45}) == (202, {"ok": True})
        view = json.loads(urllib.request.urlopen(f"{base}/api/design/{run_id}", timeout=10).read())
        rd = view["renders"][-1]
        assert rd["preset"] == "draft" and rd["options"]["camera"] == "orthographic"
        assert rd["options"]["background"] == "#202020" and rd["options"]["ground_reflections"] is False
        assert fake.render_starts[-1]["light_angle_deg"] == -45 and fake.render_starts[-1]["environment"] == "Plaza"
        assert (fake.render_starts[-1]["width"], fake.render_starts[-1]["height"]) == (1280, 853)
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{base}/api/design/{run_id}/renders/RD09/iso.png", timeout=10)
        page = urllib.request.urlopen(f"{base}/", timeout=10).read().decode()
        assert 'id="btn-render"' in page and 'id="render-progress"' in page and 'id="render-camera"' in page
        assert 'id="render-preset"' in page and 'value="#3a3f47"' in page
    finally:
        srv.shutdown()
        srv.server_close()


def png_size_bytes(b: bytes):
    import struct
    return struct.unpack(">II", b[16:24])


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
