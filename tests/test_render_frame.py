"""Render camera framing (fusion/render_frame.py FRAME_HELPERS, the code that runs inside Fusion): the car fills the
requested fraction of the frame with an even margin, for every screenshot view direction, perspective and ortho."""
import math

import pytest

from agent.design_service import known_environments
from fusion.assembly import VIEWS
from fusion.render_frame import FRAME_HELPERS

H = {}
exec(FRAME_HELPERS, H)

# a Mini-F1-like cloud of part bbox corners (cm): body, front wing (wide, low, ahead), rear wing (high, behind)
BOXES = [((-50, -45, 0), (350, 45, 60)), ((-120, -90, 5), (-60, 90, 25)), ((300, -50, 70), (360, 50, 110)),
         ((0, -95, 0), (70, -60, 66)), ((0, 60, 0), (70, 95, 66)), ((260, -95, 0), (330, -60, 66))]
POINTS = [[x, y, z] for lo, hi in BOXES for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
ASPECT = 1920 / 1280


@pytest.mark.parametrize("view", list(VIEWS))
def test_ortho_fills_80_percent_with_an_even_margin(view):
    d, up = VIEWS[view]
    t, w, h = H["frame_ortho"](POINTS, d, up, ASPECT, 0.8)
    assert w / h == pytest.approx(ASPECT)
    xs, ys = zip(*H["project"](POINTS, t, d, up))
    fx, fy = (max(xs) - min(xs)) / w, (max(ys) - min(ys)) / h
    assert max(fx, fy) == pytest.approx(0.8) and min(fx, fy) <= 0.8 + 1e-9
    assert (max(xs) + min(xs)) / 2 == pytest.approx(0, abs=1e-6)            # centred: even margin
    assert (max(ys) + min(ys)) / 2 == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("view", list(VIEWS))
@pytest.mark.parametrize("focal", [35, 50, 85])
def test_perspective_fills_80_percent_with_an_even_margin(view, focal):
    d, up = VIEWS[view]
    angle = 2 * math.atan(12.0 / focal)                                     # vertical film axis
    th, tv = H["half_tangents"](angle, "vertical", ASPECT)
    t, dist = H["frame_perspective"](POINTS, d, up, th, tv, 0.8)
    fw, fh, ox, oy = H["fill_of"](POINTS, t, d, up, dist, th, tv)
    assert max(fw, fh) == pytest.approx(0.8, abs=0.002) and min(fw, fh) <= 0.802
    assert abs(ox) < 0.002 and abs(oy) < 0.002
    n = math.sqrt(sum(c * c for c in d))
    near = max(sum((p[i] - t[i]) * d[i] / n for i in range(3)) for p in POINTS)
    assert dist > near                                                      # the eye is in front of the car


def test_fov_axis_identifies_the_film_axis_and_the_tangents_agree():
    for axis, half in (("horizontal", 18.0), ("vertical", 12.0), ("diagonal", math.hypot(18, 12))):
        angle = 2 * math.atan(half / 50.0)
        assert H["fov_axis"](angle, 50.0) == (axis, pytest.approx(0, abs=1e-12))
        th, tv = H["half_tangents"](angle, axis, 1.5)
        assert (th, tv) == (pytest.approx(18 / 50), pytest.approx(12 / 50))   # 36 x 24 frame, 3:2


def test_a_longer_focal_length_moves_the_eye_back():
    d, up = VIEWS["iso"]
    dists = []
    for f in (35, 50, 85):
        th, tv = H["half_tangents"](2 * math.atan(12.0 / f), "vertical", ASPECT)
        dists.append(H["frame_perspective"](POINTS, d, up, th, tv, 0.8)[1])
    assert dists[0] < dists[1] < dists[2]


def test_the_custom_placeholder_is_never_offered_as_an_environment():
    d = {"renders": [{"preflight": {"environments": ["Soft Light", "Custom...", "Photobooth"]}}]}
    assert known_environments(d) == ["Soft Light", "Photobooth"]
