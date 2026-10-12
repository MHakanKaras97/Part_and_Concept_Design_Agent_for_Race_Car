"""Render framing calibration (fusion/render_calibration.py + .json) and the start-path failure handling: the measured
factor is derived from the stored measurements, applied to the render camera only, looked up per camera type and
aspect ratio (never reused for another aspect ratio), and a start call that returns nothing is counted and reported."""
import math

import pytest

from agent.design_run import load_design_run
from fusion import render as render_mod
from fusion import render_calibration as cal
from fusion.assembly import VIEWS
from fusion.client import FusionOutputLost
from fusion.render_frame import FRAME_HELPERS
from tests.helpers import decode_part_cfg
from tests.test_render import setup  # noqa: F401  (fixture)
from tests.test_render_frame import ASPECT, POINTS

CAL_VP = [1920, 841]

H = {}
exec(FRAME_HELPERS, H)


def test_the_factor_is_derived_from_the_stored_measurements():
    (e,) = [x for x in cal.load() if x["id"] == "perspective-3:2-2705.1.30"]
    rows = e["derived_from"]
    assert [r["render"] for r in rows] == ["RD04", "RD05", "RD06"] and e["camera"] == "perspective"
    sx = sum(r["planned_fill"][0] / r["measured_fill"][0] for r in rows) / 3
    sy = sum(r["planned_fill"][1] / r["measured_fill"][1] for r in rows) / 3
    assert cal.derive(e) == (round(sx, 4), round(sy, 4)) == (2.3277, 2.2549)
    with pytest.raises(ValueError):
        cal.derive(dict(e, derived_from=[]))


@pytest.mark.parametrize("size", [(1280, 853), (1920, 1280), (2400, 1600)])
def test_every_preset_is_3_to_2_and_uses_the_perspective_entry(size):
    got = cal.field_scale("perspective", *size, viewport=CAL_VP)
    assert got["id"] == "perspective-3:2-2705.1.30" and got["scale"] == [2.3277, 2.2549]
    assert got["viewport_match"] and got["viewport"] == CAL_VP


@pytest.mark.parametrize("vp", [[1600, 900], [1920, 1080], None])
def test_another_viewport_is_flagged_not_silently_reused(vp):
    got = cal.field_scale("perspective", 1280, 853, viewport=vp)
    assert got["viewport_match"] is False and got["viewport_now"] == vp


def test_rescale_by_the_screenshot_factor():
    c = cal.field_scale("perspective", 1280, 853, viewport=CAL_VP)
    assert cal.rescale(c, c["screenshot_scale"]) == c["scale"]                     # unchanged screenshot -> same
    assert cal.rescale(c, [2 * v for v in c["screenshot_scale"]]) == [round(2 * v, 4) for v in c["scale"]]


@pytest.mark.parametrize("camera,size", [("perspective", (1920, 1080)), ("perspective", (1280, 1280)),
                                         ("perspective", (1600, 1200)), ("orthographic", (1920, 1280))])
def test_no_factor_for_another_aspect_ratio_or_camera(camera, size):
    assert cal.field_scale(camera, *size) is None


def test_planning_with_the_measured_field_reaches_the_planned_fill():
    """If the render's real field is k times the camera's (per axis), planning with tangents x k puts the car at the
    planned fill in the real field; planning without the correction gives fill / k (what RD04-RD06 showed)."""
    d, up = VIEWS["iso"]
    th, tv = H["half_tangents"](2 * math.atan(18 / 50.0), "horizontal", ASPECT)
    k = (2.3277, 2.2549)
    t, dist = H["frame_perspective"](POINTS, d, up, th * k[0], tv * k[1], 0.8)
    fw, fh, ox, oy = H["fill_of"](POINTS, t, d, up, dist, th * k[0], tv * k[1])     # in the real (wider) field
    assert max(fw, fh) == pytest.approx(0.8, abs=0.002) and abs(ox) < 0.002 and abs(oy) < 0.002
    t0, d0 = H["frame_perspective"](POINTS, d, up, th, tv, 0.8)                       # uncorrected plan
    fw0, fh0, _, _ = H["fill_of"](POINTS, t0, d, up, d0, th * k[0], tv * k[1])        # seen in the real field
    pw, ph, _, _ = H["fill_of"](POINTS, t0, d, up, d0, th, tv)                         # as planned
    assert (fw0, fh0) == (pytest.approx(pw / k[0]), pytest.approx(ph / k[1]))
    assert 0.8 / 2.3277 - 1e-3 <= max(fw0, fh0) <= 0.8 / 2.2549 + 1e-3              # 34-35 %, as measured
    assert dist < d0                                                                  # corrected: the eye moves in


def test_angle_narrowing_keeps_the_true_lens_distance_and_reaches_the_fill():
    """The eye stays where a true 50 mm view puts it; the camera angle is narrowed by k so that, in the render's
    measured (wider) field, the car fills 80 %. The resulting angle is that of a ~113 mm lens (nominal)."""
    d, up = VIEWS["iso"]
    angle = 2 * math.atan(18 / 50.0)
    th, tv = H["half_tangents"](angle, "horizontal", ASPECT)
    t, dist = H["frame_perspective"](POINTS, d, up, th, tv, 0.8)                     # true 50 mm framing
    p = H["fill_of"](POINTS, t, d, up, dist, th, tv)[:2]
    scale = (2.3277, 2.2549)
    k = H["narrow_factor"](p, scale, 0.8)
    a2 = H["narrowed_angle"](angle, k)
    th2, tv2 = H["half_tangents"](a2, "horizontal", ASPECT)
    real = H["fill_of"](POINTS, t, d, up, dist, th2 * scale[0], tv2 * scale[1])     # what the render shows
    assert max(real[:2]) == pytest.approx(0.8, abs=1e-6) and abs(real[2]) < 0.002 and abs(real[3]) < 0.002
    assert math.tan(a2 / 2) == pytest.approx(math.tan(angle / 2) / k)
    assert H["focal_of"](angle, "horizontal") == pytest.approx(50.0)
    assert H["focal_of"](a2, "horizontal") == pytest.approx(50.0 * k)
    assert 2.2 < k < 2.4 and 105 < H["focal_of"](a2, "horizontal") < 120             # outside 35-85: reported
    assert H["narrow_factor"](p, (1.0, 1.0), 0.8) == pytest.approx(1.0, abs=0.003)   # uncalibrated: no narrowing


def test_the_start_script_keeps_the_true_lens_distance_and_narrows_the_angle():
    from agent.render_run import parse_options
    s = render_mod.start_script("mf1:x", "iso", [[[0, 0, 0], [100, 50, 30]]], "C:/a.png", "t",
                                parse_options().cfg(), 100, (2.3277, 2.2549))
    i = s.index("def _camera")
    body = s[i:s.index("def _scene_set")]
    assert "frame_perspective(pts, d, up, th0, tv0, fill)" in body                   # distance from the true field
    assert "cam.perspectiveAngle = angle_set" in body and "narrow_factor(" in body
    assert "th0 * sx" not in body                                                    # no distance correction


def test_the_render_start_carries_the_calibrated_factor(setup):  # noqa: F811
    store, fake, reasoner, orch, run, clock = setup
    rd = orch.render(load_design_run(store, run.id), options={"preset": "draft"})
    assert fake.render_starts[-1]["field_scale"] == [2.3277, 2.2549]
    assert rd["items"][0]["calibration"]["id"] == "perspective-3:2-2705.1.30"
    assert rd["items"][0]["calibration"]["viewport_match"] and not fake.aims
    note = rd["items"][0]["note"] or ""
    assert "uncalibrated" not in note and "viewport changed" not in note
    assert "nominal 112.74 mm focal length (outside 35-85" in note and "perspective is that of a 50.0 mm lens" in note


def test_an_eye_moved_by_fusion_is_reported_not_claimed_as_the_lens_distance(setup, monkeypatch):  # noqa: F811
    """RD08 (live): Fusion moved the eye from 905.97 to 2042.9 cm (x2.2549) when the narrowed angle was assigned."""
    store, fake, reasoner, orch, run, clock = setup
    real = fake._render

    def moved(cfg, read_only):
        r = real(cfg, read_only)
        if cfg.get("render_start") and r.get("frame"):
            r["frame"]["distance_read_back_cm"] = 2042.9
        return r
    monkeypatch.setattr(fake, "_render", moved)
    rd = orch.render(load_design_run(store, run.id), options={"preset": "draft"})
    note = rd["items"][0]["note"]
    assert "Fusion moved the eye: distance set 905.97 cm, read back 2042.9 cm (x2.2549)" in note
    assert "perspective is NOT that of a 50.0 mm lens" in note and "perspective is that of a" not in note


def test_the_start_script_reads_the_eye_distance_back():
    from agent.render_run import parse_options
    s = render_mod.start_script("mf1:x", "iso", [[[0, 0, 0], [100, 50, 30]]], "C:/a.png", "t",
                                parse_options().cfg(), 100, (2.3277, 2.2549))
    assert 'frame["distance_read_back_cm"]' in s


def test_a_changed_viewport_is_noted_and_re_scaled_from_a_screenshot(setup):  # noqa: F811
    import io
    from PIL import Image, ImageDraw
    store, fake, reasoner, orch, run, clock = setup
    fake.viewport = [1600, 900]
    im = Image.new("RGB", (1280, 853), (58, 63, 71))
    ImageDraw.Draw(im).rectangle([384, 256, 896, 597], fill=(230, 230, 230))         # 40 % x 40 % "car"
    buf = io.BytesIO()
    im.save(buf, "PNG")
    fake.screenshot_png = buf.getvalue()
    rd = orch.render(load_design_run(store, run.id), options={"preset": "draft"})
    (it,) = rd["items"]
    c = it["calibration"]
    assert len(fake.aims) == 1 and fake.aims[0]["field_scale"] == [1.0, 1.0] and fake.screen_sizes[-1] == (1280, 853)
    m = c["recalibrated"]["screenshot_fill"]
    now = [round(0.7807 / m[0], 4), round(0.8 / m[1], 4)]
    assert c["recalibrated"]["screenshot_scale"] == now and c["scale"] == cal.rescale(
        cal.field_scale("perspective", 1280, 853, viewport=CAL_VP), now)
    assert fake.render_starts[-1]["field_scale"] == c["scale"]
    assert "calibration may not apply: viewport changed (calibrated at [1920, 841], now [1600, 900])" in it["note"]
    assert "UNVERIFIED" in it["note"]


def test_a_changed_viewport_without_a_usable_screenshot_renders_uncorrected_and_says_so(setup):  # noqa: F811
    store, fake, reasoner, orch, run, clock = setup
    fake.viewport = [1600, 900]                                                       # fake screenshot: not a PNG
    rd = orch.render(load_design_run(store, run.id), options={"preset": "draft"})
    (it,) = rd["items"]
    assert it["calibration"] is None and fake.render_starts[-1]["field_scale"] == [1.0, 1.0]
    assert "calibration may not apply: viewport changed" in it["note"] and "framing UNCORRECTED" in it["note"]


def test_a_camera_moved_between_renders_is_reported(setup):  # noqa: F811
    store, fake, reasoner, orch, run, clock = setup
    rd1 = orch.render(load_design_run(store, run.id), options={"preset": "draft"})
    assert rd1["camera_moved"] is None                                                # first render: nothing to compare
    rd2 = orch.render(load_design_run(store, run.id), options={"preset": "draft"})
    assert rd2["camera_moved"] is None                                                # left where RD01 set it
    fake.viewport_camera = {"eye_cm": [500.0, 1.0, 2.0], "target_cm": [0.0, 0.0, 0.0]}  # someone orbited
    rd3 = orch.render(load_design_run(store, run.id), options={"preset": "draft"})
    assert rd3["camera_moved"] == {"since": "RD02", "eye_moved_cm": 480.0, "target_moved_cm": 0.0}
    assert "moved since RD02" in load_design_run(store, run.id)["events"][-2]["msg"]


def test_another_aspect_ratio_does_not_reuse_the_3_to_2_factor(setup, monkeypatch):  # noqa: F811
    store, fake, reasoner, orch, run, clock = setup
    monkeypatch.setitem(render_mod.PRESETS, "draft", (25, 1280, 720))                 # a 16:9 frame
    rd = orch.render(load_design_run(store, run.id), options={"preset": "draft"})
    assert fake.render_starts[-1]["field_scale"] == [1.0, 1.0] and rd["items"][0]["calibration"] is None
    assert "framing uncalibrated for perspective at 1280x720" in rd["items"][0]["note"]


def test_orthographic_is_uncalibrated_and_says_so(setup):  # noqa: F811
    store, fake, reasoner, orch, run, clock = setup
    rd = orch.render(load_design_run(store, run.id), options={"camera": "orthographic"})
    assert fake.render_starts[-1]["field_scale"] == [1.0, 1.0]
    assert "framing uncalibrated for orthographic" in rd["items"][0]["note"]


def test_screenshots_are_not_calibrated():
    from fusion.assembly import camera_script
    cfg = decode_part_cfg(camera_script("mf1:x", "iso"))
    assert "field_scale" not in cfg and "boxes_mm" not in cfg


# ---------------------------------------------------------------- start path: empty result, long lines
def test_a_start_call_that_returns_nothing_is_counted_and_not_blamed_on_the_channel(setup, monkeypatch):  # noqa: F811
    store, fake, reasoner, orch, run, clock = setup
    real = fake.run_script

    def lossy(script, read_only=False, expect_result=True):
        if decode_part_cfg(script).get("render_start"):
            fake.scripts.append(script)
            raise FusionOutputLost("Fusion reported success but returned no @@RESULT@@ line (0 chars of output)")
        return real(script, read_only, expect_result)
    monkeypatch.setattr(fake, "run_script", lossy)
    rd = orch.render(load_design_run(store, run.id))
    assert rd["status"] == "failed" and rd["items"][0]["state"] == "failed" and rd["items"][0]["method"] is None
    assert rd["script_calls"] == 2                                       # preflight + the lost start call
    assert "probably did not run" in rd["error"] and "check the script" in rd["error"]
    assert not list((run.dir / "renders").glob("*/iso.png")) if (run.dir / "renders").exists() else True


def test_the_real_client_raises_on_an_empty_success():
    """The render start goes through FusionMCPClient.run_script with expect_result=True (the default): an empty
    success is FusionOutputLost, never data=None."""
    from fusion.client import FusionMCPClient

    def transport(url, payload, headers, timeout):
        if payload["method"] == "initialize":
            return 200, {"mcp-session-id": "s"}, '{"jsonrpc": "2.0", "id": 1, "result": {}}'
        if payload["method"].startswith("notifications/"):
            return 202, {}, ""
        body = '{"jsonrpc": "2.0", "id": %d, "result": {"content": [{"type": "text", "text": ' \
               '"{\\"success\\": true, \\"message\\": \\"\\"}"}]}}' % payload["id"]
        return 200, {"content-type": "application/json"}, body
    client = FusionMCPClient(transport=transport)
    s = render_mod.start_script("mf1:x", "iso", [[[0, 0, 0], [1, 1, 1]]], "C:/a.png", "t",
                                __import__("agent.render_run", fromlist=["x"]).parse_options().cfg(), 100)
    with pytest.raises(FusionOutputLost):
        client.run_script(s)


def test_an_over_long_start_script_is_never_sent(setup, monkeypatch):  # noqa: F811
    store, fake, reasoner, orch, run, clock = setup
    monkeypatch.setattr(render_mod, "MAX_LINE", 500)
    n0 = len(fake.scripts)
    rd = orch.render(load_design_run(store, run.id))
    (it,) = rd["items"]
    assert not fake.render_starts and it["method"] == "screenshot_fallback"
    assert it["error"].startswith("render not started: render start script line of") and "not sent" in it["error"]
    assert len(fake.scripts) - n0 == 2                                   # preflight + the fallback camera only
