"""ONE live test of derived left/right parts (python -m pytest -m fusion tests/integration/test_mirror_live.py -s).

In a throwaway document tagged "livetest-mirror:<uuid>" (no Claude call, no registry write):
- TST-L: a deliberately ASYMMETRIC box with an offset lug at a rotated pose; TST-R = mirror of it (mirror feature
  about the component XZ plane + removal of the source body, mirrored pose);
- WHL-FL: a wheel-like disc (axle = local Y through the origin) with a hub boss on the inboard -Y side; WHL-FR =
  yaw180 (same script, pose Y negated, turned 180 deg about local Z).
Checks: PART-DERIVED (volume, solids/lumps, local + world bbox), placement read-back, the lug / hub boss on the
expected side (world bbox against the analytically placed geometry), and the planned keep-clear mates measured.
Refuses to run above wrapper depth 60. About 7 script calls. The document is closed without saving at the end.
"""
import json
import math
import uuid

import pytest

from fusion.assembly import mate_pairs, measure_assembly
from fusion.client import RESULT_MARKER, FusionError, FusionMCPClient
from fusion.part_runner import build_part, derive_part, to_record
from validation.part_checks import geometry_of, mate_results
from vehicle.mirror import derive_spec
from vehicle.parts import PartSpec
from vehicle.transforms import bbox_to_vcs

pytestmark = pytest.mark.fusion
NS = "mlt"
MAX_DEPTH = 60

LUG_BOX = '''def build(part):
    sk = part.sketch(part.plane("z", 10.0), "SK_box")
    part.polygon(sk, [(0, 0, 10), (100, 0, 10), (100, 40, 10), (0, 40, 10)])
    part.extrude(part.profile(sk), 20.0, "EX_box", symmetric=True)
    sk2 = part.sketch(part.plane("z", 22.5), "SK_lug")
    part.polygon(sk2, [(80, 30, 22.5), (100, 30, 22.5), (100, 60, 22.5), (80, 60, 22.5)])
    part.extrude(part.profile(sk2), 25.0, "EX_lug", op="join", symmetric=True)
'''
BOX = ((0.0, 0.0, 0.0), (100.0, 40.0, 20.0))          # part frame, mm
LUG = ((80.0, 30.0, 10.0), (100.0, 60.0, 35.0))
LUG_BOX_VOLUME = 100 * 40 * 20 + 20 * 30 * 25 - 20 * 10 * 10

WHEEL = '''def build(part):
    sk = part.sketch(part.plane("y"), "SK_tyre")
    sk.sketchCurves.sketchCircles.addByCenterRadius(sk.modelToSketchSpace(pt(0, 0, 0)), mm(100.0))
    part.extrude(part.profile(sk), 80.0, "EX_tyre", symmetric=True)
    sk2 = part.sketch(part.plane("y", -45.0), "SK_hub")
    sk2.sketchCurves.sketchCircles.addByCenterRadius(sk2.modelToSketchSpace(pt(0, -45.0, 0)), mm(30.0))
    part.extrude(part.profile(sk2), 30.0, "EX_hub", op="join", symmetric=True)
'''
WHEEL_LOCAL = ((-100.0, -60.0, -100.0), (100.0, 40.0, 100.0))   # hub boss y -60..-30 (inboard for the left wheel)
WHEEL_VOLUME = math.pi * (100 ** 2 * 80 + 30 ** 2 * 30 - 30 ** 2 * 10)


def _spec(pid, pos, rot, local_boxes, dims):
    """Envelope = Fusion's world bbox convention: the AABB of the part's LOCAL bbox transformed by the pose (verified
    live: a rotated occurrence reports that box, not the tight box of its geometry) + 1 mm."""
    local_boxes = [_union(local_boxes)]
    pose = PartSpec(id=pid, name=pid, role="", dims={"a": 1.0}, position_mm=pos, rotation_deg=rot,
                    envelope_min=(0, 0, 0), envelope_max=(1, 1, 1)).pose
    los, his = zip(*(bbox_to_vcs(pose, lo, hi) for lo, hi in local_boxes))
    lo = tuple(min(v[i] for v in los) - 1.0 for i in range(3))
    hi = tuple(max(v[i] for v in his) + 1.0 for i in range(3))
    return PartSpec(id=pid, name=pid, role="live mirror test", dims=dims, position_mm=pos, rotation_deg=rot,
                    envelope_min=lo, envelope_max=hi)


def _union(boxes):
    return (tuple(min(b[0][i] for b in boxes) for i in range(3)), tuple(max(b[1][i] for b in boxes) for i in range(3)))


def _expected_world(spec: PartSpec, local_boxes):
    """Fusion's world bbox of the placed part: the local bbox (union of the boxes) transformed, then axis-aligned."""
    return [list(v) for v in bbox_to_vcs(spec.pose, *_union(local_boxes))]


def _mirror_boxes(boxes):
    return [((lo[0], -hi[1], lo[2]), (hi[0], -lo[1], hi[2])) for lo, hi in boxes]


def _dev(a, b):
    return max(abs(x - y) for p, q in zip(a, b) for x, y in zip(p, q))


_STATE = ("import adsk.core, adsk.fusion, json, sys\n"
          "def run(_context: str):\n"
          "    d, s = 0, sys.stdout\n"
          "    while hasattr(s, '_original') and d < 100000:\n"
          "        d += 1; s = s._original\n"
          "    app = adsk.core.Application.get()\n"
          "    closed = 0\n"
          "    for i in range(app.documents.count - 1, -1, -1):\n"
          "        doc = app.documents.item(i)\n"
          "        dz = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))\n"
          "        a = dz.attributes.itemByName('agent_design', 'run') if dz else None\n"
          "        if CLOSE and a is not None and a.value == TAG:\n"
          "            doc.close(False); closed += 1\n"
          "    docs = [app.documents.item(i).name for i in range(app.documents.count)]\n"
          f"    print('{RESULT_MARKER}' + json.dumps({{'depth': d, 'documents': docs, 'closed': closed}}))\n")


def _state(client, tag, close):
    return client.run_script(f"TAG = {json.dumps(tag)}\nCLOSE = {close}\n" + _STATE).data or {}


def test_live_mirror_and_yaw180_in_a_throwaway_document():
    client = FusionMCPClient()
    try:
        client.connect()
    except FusionError as e:
        pytest.skip(f"Fusion not available: {e}")
    tag = f"livetest-mirror:{uuid.uuid4().hex[:8]}"
    start = _state(client, tag, False)
    if start["depth"] > MAX_DEPTH:
        pytest.skip(f"wrapper depth {start['depth']} > {MAX_DEPTH}: restart Fusion first")
    report = {"depth_start": start["depth"], "script_calls": 1}
    end = {}
    try:
        tst_l = _spec("TST-L", (200.0, 300.0, 50.0), (10.0, 20.0, 30.0), [BOX, LUG],
                      {"length": 100.0, "width": 40.0, "height": 20.0})
        whl_l = _spec("WHL-FL", (0.0, 500.0, 330.0), (0.0, 0.0, 0.0), [WHEEL_LOCAL],
                      {"radius": 100.0, "width": 80.0})
        builds = {}
        for src, body, mode, new_id in ((tst_l, LUG_BOX, "mirror", "TST-R"), (whl_l, WHEEL, "yaw180", "WHL-FR")):
            b = build_part(client, src, body, NS, tag, create_doc=True)
            report["script_calls"] += 1
            report[src.id] = {"passed": b.passed, "error": b.error, "depth": b.depth,
                              "geometry": geometry_of(b.data)}
            assert b.passed, (src.id, b.error, [(c.check_id, c.message) for c in b.checks if c.blocking_failure])
            d_spec = derive_spec(src, new_id, mode)
            d = derive_part(client, to_record(b, NS, None, []), geometry_of(b.data), d_spec, NS, tag,
                            create_doc=False)
            report["script_calls"] += 1
            builds[src.id], builds[new_id] = b, d
            checks = {c.check_id: c for c in d.checks}
            report[new_id] = {"passed": d.passed, "error": d.error, "stage": d.stage, "mirror": d.data.get("mirror"),
                              "pose": [list(d_spec.position_mm), list(d_spec.rotation_deg)], "depth": d.depth,
                              "geometry": geometry_of(d.data),
                              "failed": [(c.check_id, c.message) for c in d.checks if c.blocking_failure],
                              "PART-DERIVED": checks["PART-DERIVED"].measured if "PART-DERIVED" in checks else None,
                              "placement": checks["PART-PLACEMENT"].measured if "PART-PLACEMENT" in checks else None}
            assert d.passed, (new_id, report[new_id])
        g = {k: geometry_of(b.data) for k, b in builds.items()}
        # volume: equal to the source within 1e-6 relative, and the analytic value; one connected solid each
        assert abs(g["TST-L"]["volume_mm3"] - LUG_BOX_VOLUME) <= 1e-6 * LUG_BOX_VOLUME
        assert abs(g["WHL-FL"]["volume_mm3"] - WHEEL_VOLUME) <= 1e-6 * WHEEL_VOLUME
        for s, d in (("TST-L", "TST-R"), ("WHL-FL", "WHL-FR")):
            assert abs(g[d]["volume_mm3"] - g[s]["volume_mm3"]) <= 1e-6 * g[s]["volume_mm3"]
            assert (g[d]["solids"], g[d]["lumps"]) == (1, 1) == (g[s]["solids"], g[s]["lumps"])
        # local bbox: mirror flips Y (the lug moves to local -Y); yaw180 keeps the source's
        assert _dev(g["TST-L"]["bbox_local"], [[0, 0, 0], [100, 60, 35]]) <= 0.01
        assert _dev(g["TST-R"]["bbox_local"], [[0, -60, 0], [100, 0, 35]]) <= 0.01
        assert _dev(g["WHL-FR"]["bbox_local"], g["WHL-FL"]["bbox_local"]) <= 0.01
        # world: the derived part is the analytically mirrored geometry at the mirrored pose -> lug on the right side
        report["world_dev_mm"] = {
            "TST-L": _dev(g["TST-L"]["bbox_world"], _expected_world(tst_l, [BOX, LUG])),
            "TST-R": _dev(g["TST-R"]["bbox_world"], _expected_world(builds["TST-R"].spec, _mirror_boxes([BOX, LUG]))),
            "WHL-FL": _dev(g["WHL-FL"]["bbox_world"], [[-100, 440, 230], [100, 540, 430]]),
            "WHL-FR": _dev(g["WHL-FR"]["bbox_world"], [[-100, -540, 230], [100, -440, 430]])}
        assert all(v <= 0.01 for v in report["world_dev_mm"].values()), report["world_dev_mm"]
        # planned mates involving derived parts are measured as usual
        mates = [{"a": "TST-L", "b": "TST-R", "expect": "clear", "value_mm": 100.0},
                 {"a": "WHL-FL", "b": "WHL-FR", "expect": "clear", "value_mm": 800.0}]
        meas = measure_assembly(client, tag, NS, list(builds), *mate_pairs(mates))
        report["script_calls"] += 1
        res = mate_results(mates, meas)
        report["mates"] = [(r.check_id, r.status.value, r.measured) for r in res]
        assert meas.get("ok") and all(r.status.value == "VERIFIED" for r in res), (report["mates"], meas)
        wheel = next(p for p in meas["pairs"] if {p["a"], p["b"]} == {"WHL-FL", "WHL-FR"})
        assert abs(wheel["min_distance_mm"] - 880.0) <= 0.01
    finally:
        end = _state(client, tag, True)
        report["script_calls"] += 1
        report.update(depth_end=end.get("depth"), closed=end.get("closed"))
        print("\nLIVE MIRROR REPORT " + json.dumps(report, default=str))
    assert end.get("closed") == 1
