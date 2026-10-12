"""Overlap depth, measurement version 2: per interference piece, rays along the contact direction through both parts.

The pure helpers (fusion.assembly.DEPTH_HELPERS) are the exact source the Fusion assembly script runs; here they are
driven by an analytic ray caster over solids given as inside(point) predicates."""
import itertools

import pytest

from fusion.assembly import DEPTH_HELPERS, MEASURE_VERSION, assembly_script, overlap_axes
from tests.helpers import decode_part_cfg
from validation.part_checks import mate_results, planned_contact_axis
from vehicle.models import Severity, Status
from vehicle.parts import PartSpec

H: dict = {}
exec(DEPTH_HELPERS, H)
pair_depth, piece_depth = H["pair_depth"], H["piece_depth"]


def caster(inside_a, inside_b, start=-5000.0, end=5000.0, step=0.5):
    """cast(point, axis) for the helpers: boundary crossings of both solids along +axis, refined by bisection."""
    def crossings(inside, p, axis):
        hits, q = [], list(p)

        def at(t):
            q[axis] = t
            return inside(q)
        t, prev = start, at(start)
        while t < end:
            t2 = t + step
            cur = at(t2)
            if cur != prev:
                a, b = t, t2
                for _ in range(40):
                    m = (a + b) / 2
                    a, b = (m, b) if at(m) == prev else (a, m)
                hits.append((a + b) / 2)
            t, prev = t2, cur
        return hits

    def cast(p, axis):
        return crossings(inside_a, p, axis), crossings(inside_b, p, axis)
    return cast


# ---------------------------------------------------------------- tapered wall: a thin strip, not its Y extent
def w(x):                                              # monocoque half-width, tapering 250 -> 430 mm
    return 250.0 + 0.08 * (-x - 700.0)


def mon(p):
    return -3700 <= p[0] <= 550 and 30 <= p[2] <= 730 and abs(p[1]) <= w(min(max(p[0], -3700), 550))


def sidepod(p, t=15.0):                                # inner wall t mm inside the tub, along the whole length
    return -2950 <= p[0] <= -700 and 55 <= p[2] <= 400 and w(p[0]) - t <= p[1] <= w(p[0]) + 250


def test_tapered_wall_strip_reports_its_thickness_not_its_y_extent():
    piece = [[-2950.0, w(-700) - 15, 55.0], [-700.0, w(-2950), 400.0]]           # the strip's bbox
    assert piece[1][1] - piece[0][1] == pytest.approx(195.0)                    # what version 1 reported
    depth, rows, note = pair_depth([piece], None, caster(sidepod, mon, step=2.0), 5)
    assert depth == pytest.approx(15.0, abs=0.01) and rows[0]["axis"] == "Y" and note == ""


# ---------------------------------------------------------------- mirrored beam ends: same depth left and right
def beam(sign, y_end=170.0, half=15.0):
    """A 30 mm wide, 60 mm tall beam at 70 deg in XY ending 30 mm inside the tub wall (|y| = 200), its end face
    slanted - like SUF-L's links (their pieces are thinnest in Y, as measured live)."""
    import math
    d = (math.cos(math.radians(70)), math.sin(math.radians(70)))
    e = (-100.0, y_end)                                                        # inboard end (left side)

    def inside(p):
        x, y, z = p[0], sign * p[1], p[2]
        s = (x - e[0]) * d[0] + (y - e[1]) * d[1]
        n = -(x - e[0]) * d[1] + (y - e[1]) * d[0]
        return 0.0 <= s <= 400.0 and abs(n) <= half and 170.0 <= z <= 230.0
    return inside


def tub(p):
    return -400 <= p[0] <= 200 and 0 <= p[2] <= 400 and abs(p[1]) <= 200.0


def piece_box(inside_a, inside_b, lo, hi, n=60):
    pts = [p for p in itertools.product(*[[lo[i] + (hi[i] - lo[i]) * k / n for k in range(n + 1)] for i in range(3)])
           if inside_a(p) and inside_b(p)]
    return [[min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]]


def test_mirrored_left_and_right_pieces_give_the_same_depth():
    box_l = piece_box(beam(1), tub, (-130, 150, 165), (-70, 205, 235))
    box_r = [[box_l[0][0], -box_l[1][1], box_l[0][2]], [box_l[1][0], -box_l[0][1], box_l[1][2]]]
    dl = pair_depth([box_l], None, caster(beam(1), tub, start=-1000, end=1000, step=0.25), 9)[0]
    dr = pair_depth([box_r], None, caster(beam(-1), tub, start=-1000, end=1000, step=0.25), 9)[0]
    assert abs(dl - dr) <= 1.0
    # the deepest corner of the slanted end face: 30 mm centre-line depth + 15 * cos(70 deg) = 35.1 mm
    assert box_l[1][1] - box_l[0][1] == min(box_l[1][i] - box_l[0][i] for i in range(3))
    assert 33.5 <= dl <= 35.2                     # a 9 x 9 grid can miss the sharp corner by ~1 mm (never over)


def test_grouped_and_ungrouped_pieces_give_the_same_depth():
    """Fusion grouped SUF-L's five pieces into 4 result bodies and SUF-R's into 1. Version 2 flattens every body
    into its pieces first, so the grouping cannot change the depth (version 1 took a grouped body's bbox)."""
    def slab(x0, t):
        return lambda p: x0 <= p[0] <= x0 + 80 and 0 <= p[2] <= 80 and 200 - t <= p[1] <= 400

    def wall(p):
        return abs(p[1]) <= 200 and -1000 <= p[0] <= 1000 and -100 <= p[2] <= 100
    slabs = [slab(0, 20), slab(100, 35), slab(300, 10)]
    pieces = [[[x0, 200 - t, 0], [x0 + 80, 200, 80]] for x0, t in ((0, 20), (100, 35), (300, 10))]
    cast = caster(lambda p: any(s(p) for s in slabs), wall, start=-1000, end=1000, step=0.5)
    ungrouped = pair_depth(pieces, None, cast, 5)[0]
    grouped_bodies = [[pieces[0], pieces[1]], [pieces[2]]]                         # how Fusion may return them
    grouped = pair_depth([p for body in grouped_bodies for p in body], None, cast, 5)[0]
    assert ungrouped == pytest.approx(grouped) == pytest.approx(35.0, abs=0.01)
    union = [[min(p[0][i] for p in pieces[:2]) for i in range(3)], [max(p[1][i] for p in pieces[:2]) for i in range(3)]]
    assert min(union[1][i] - union[0][i] for i in range(3)) == 35.0             # v1: the grouped body's bbox
    assert min(pieces[0][1][i] - pieces[0][0][i] for i in range(3)) == 20.0     # v1: piece 0 alone


def test_rays_that_find_nothing_leave_the_depth_undetermined():
    assert pair_depth([[[0, 0, 0], [10, 10, 10]]], 1, lambda p, axis: None, 3)[0] is None
    d, rows, note = pair_depth([[[0, 0, 0], [10, 10, 10]]], 1, lambda p, axis: ([1.0], [2.0, 3.0]), 3)
    assert d is None and rows[0]["rays"] == 0 and "no ray" in note                # odd hits: grazing ray dropped


# ---------------------------------------------------------------- mate_results with version 2 measurements
def _m(**p):
    base = {"a": "SDP-L", "b": "MON-001", "min_distance_mm": 0.0, "overlap_mm3": 9.4e6, "overlap_depth_mm": 164.5}
    return {"measure_version": MEASURE_VERSION, "pairs": [dict(base, **p)]}


MATE = [{"a": "SDP-L", "b": "MON-001", "expect": "overlap", "value_mm": 25.0}]


def test_ray_depth_replaces_the_bbox_depth_and_both_are_reported():
    r = mate_results(MATE, _m(depth_method="ray", overlap_depth_ray_mm=20.4,
                              depth_pieces=[{"axis": "Y", "depth_mm": 20.4, "rays": 81}]))[0]
    assert r.status == Status.VERIFIED and r.measured["overlap_depth_mm"] == 20.4
    assert r.measured["overlap_depth_bbox_mm"] == 164.5 and r.measured["depth_method"] == "ray"
    assert r.measured["measure_version"] == 2
    r = mate_results(MATE, _m(depth_method="ray", overlap_depth_ray_mm=44.0))[0]
    assert r.status == Status.NON_COMPLIANT and "44.00" in r.message


@pytest.mark.parametrize("bbox_depth", [164.5, 3.0])
def test_fallback_is_advisory_never_a_silent_pass(bbox_depth):
    r = mate_results(MATE, _m(depth_method="bbox_fallback", overlap_depth_mm=bbox_depth,
                              depth_note="piece 1: no ray found a stretch inside both parts"))[0]
    assert r.status == Status.NOT_VERIFIED and r.severity == Severity.ADVISORY
    assert "not determined by rays" in r.message and "no ray found" in r.message and "check manually" in r.message


def test_version_1_measurements_are_evaluated_as_before():
    old = {"pairs": [{"a": "SDP-L", "b": "MON-001", "min_distance_mm": 0.0, "overlap_mm3": 9.4e6,
                      "overlap_depth_mm": 164.5}]}
    r = mate_results(MATE, old)[0]
    assert r.status == Status.NON_COMPLIANT and r.measured == {"state": "overlap", "gap_mm": 0.0,
                                                               "overlap_mm3": 9400000.0, "overlap_depth_mm": 164.5}


# ---------------------------------------------------------------- script config and contact axis
def spec(pid, lo, hi):
    return PartSpec(id=pid, name=pid, role="", dims={"a": 1.0}, position_mm=lo, envelope_min=lo, envelope_max=hi)


def test_contact_axis_from_planned_envelopes_else_none():
    a, b = spec("SUR-L", (0, 430, 0), (100, 500, 100)), spec("MON-001", (-50, -450, -50), (150, 450, 150))
    m = {"a": "SUR-L", "b": "MON-001", "expect": "overlap", "value_mm": 20.0}
    assert planned_contact_axis(m, a, b) == 1                                    # Y: envelopes meet 20 mm deep
    deep = spec("SDP-L", (0, 270, 0), (100, 700, 100))                            # 180 mm into the tub envelope
    assert planned_contact_axis(m, deep, b) is None
    assert overlap_axes([m, dict(m, expect="touching")], {"SUR-L": a, "MON-001": b}) == {("SUR-L", "MON-001"): 1}


def test_script_carries_the_overlap_pairs_the_version_and_the_helpers():
    s = assembly_script("t", "mf1", ["MON-001", "SDP-L"], [], [("SDP-L", "MON-001")],
                        overlaps={("SDP-L", "MON-001"): None})
    compile(s, "assembly", "exec")
    cfg = decode_part_cfg(s)
    assert cfg["overlaps"] == {"MON-001|SDP-L": None} and cfg["measure_version"] == 2 and cfg["joints"] == []
    assert "def pair_depth(" in s and "findBRepUsingRay" in s and "body.lumps.item(k)" in s
