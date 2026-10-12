"""Live fast-mode smoke tests against a running Fusion (python -m pytest -m fusion tests/integration/test_fast_live.py).

All parts are built in ONE throwaway design document that the prelude creates and tags (agent_design/run =
"livetest-fast:<uuid>"); every script activates that document first, so no user document is written. The document
is closed without saving at the end (test cleanup only - the product never closes documents).
Set FAST_LIVE_OUT=<dir> to keep the screenshots.
"""
import json
import os
import uuid
from pathlib import Path

import pytest

from fusion.assembly import measure_assembly, screenshot_views
from fusion.client import FusionError, FusionMCPClient
from fusion.part_runner import build_part
from validation.part_checks import mate_results
from vehicle.models import Status
from vehicle.parts import PartSpec

pytestmark = pytest.mark.fusion
NS = "lt"

BOX = '''def build(part):
    L, W, H = part.p["length"], part.p["width"], part.p["height"]
    sk = part.sketch(part.plane("z"), "SK_base")
    part.polygon(sk, [(0, -W / 2, 0), (L, -W / 2, 0), (L, W / 2, 0), (0, W / 2, 0)])
    part.extrude(part.profile(sk), "height", "EX_base")
    top = part.sketch(part.plane("z", H), "SK_pocket")
    part.polygon(top, [(L * 0.3, -W / 4, H), (L * 0.7, -W / 4, H), (L * 0.7, W / 4, H), (L * 0.3, W / 4, H)])
    part.extrude(part.profile(top), -H / 2, "CUT_pocket", op="cut")
'''

WING = '''def build(part):
    c, t, s, e = part.p["chord"], part.p["thickness"], part.p["span"], part.p["endplate"]
    sk = part.sketch(part.plane("y"), "SK_main")
    part.polygon(sk, [(0, 0, 0), (c * 0.3, 0, t), (c, 0, t * 0.4), (c, 0, 0)])
    part.extrude(part.profile(sk), "span", "EX_main", symmetric=True)
    for side, y in (("L", s / 2), ("R", -s / 2)):
        ep = part.sketch(part.plane("y", y), "SK_endplate_" + side)
        part.polygon(ep, [(0, y, 0), (c, y, 0), (c, y, t * 2), (0, y, t * 2)])
        part.extrude(part.profile(ep), e if y > 0 else -e, "EX_endplate_" + side, op="join")
'''

NOSE = '''def build(part):
    L, W, H = part.p["length"], part.p["width"], part.p["height"]
    secs = []
    for i, (x, k) in enumerate(((0, 1.0), (L * 0.5, 0.7), (L, 0.3))):
        w, h = W * k / 2, H * k
        secs.append(part.section("x", x, [(x, -w, 0), (x, w, 0), (x, w * 0.6, h), (x, -w * 0.6, h)], "SK_sec%d" % i))
    part.loft(secs, "LF_nose")
'''

_CLOSE = '''
import adsk.core, adsk.fusion, json
def run(_context: str):
    app = adsk.core.Application.get()
    closed = 0
    for i in range(app.documents.count - 1, -1, -1):
        doc = app.documents.item(i)
        d = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
        a = d.attributes.itemByName("agent_design", "run") if d else None
        if a is not None and a.value == "%s":
            doc.close(False)
            closed += 1
    print("@@RESULT@@" + json.dumps({"closed": closed}))
'''


def _spec(pid, name, dims, pos, lo, hi, rot=(0.0, 0.0, 0.0)):
    return PartSpec(id=pid, name=name, role="live test", dims=dims, position_mm=pos, rotation_deg=rot,
                    envelope_min=lo, envelope_max=hi)


@pytest.fixture(scope="module")
def session():
    c = FusionMCPClient()
    try:
        c.connect()
    except FusionError as e:
        pytest.skip(f"Fusion not available: {e}")
    tag = f"livetest-fast:{uuid.uuid4().hex[:8]}"
    yield c, tag
    c.run_script(_CLOSE % tag)


def test_fast_parts_assembly_and_screenshots(session):
    client, tag = session
    box = _spec("TST-001", "box", {"length": 100.0, "width": 50.0, "height": 30.0},
                (500.0, 0.0, 100.0), (500.0, -25.0, 100.0), (600.0, 25.0, 130.0))
    wing = _spec("TST-002", "wing", {"chord": 80.0, "thickness": 20.0, "span": 200.0, "endplate": 3.0},
                 (510.0, 0.0, 130.0), (510.0, -103.0, 130.0), (590.0, 103.0, 170.0))
    # rotated 90 deg about Z: local +X (nose tip) points to VCS +Y
    nose = _spec("TST-003", "nose", {"length": 120.0, "width": 60.0, "height": 40.0},
                 (300.0, 0.0, 100.0), (270.0, 0.0, 100.0), (330.0, 120.0, 140.0), rot=(0.0, 0.0, 90.0))
    builds = {}
    for s, body in ((box, BOX), (wing, WING), (nose, NOSE)):
        b = build_part(client, s, body, NS, tag, create_doc=True)
        failed = {c.check_id: c.message for c in b.checks if c.status != Status.VERIFIED}
        assert b.ok and not failed, (s.id, b.error, failed, b.data.get("measure", {}).get("bbox_world"))
        assert b.data["warnings"] == [], b.data["warnings"]                     # appearance applied
        builds[s.id] = b
    vols = {pid: sum(x["volume_mm3"] for x in b.data["measure"]["bodies"]) for pid, b in builds.items()}
    assert abs(vols["TST-001"] - (100 * 50 * 30 - 40 * 25 * 15)) < 1e-3       # negative-distance cut worked
    assert len(builds["TST-002"].data["measure"]["bodies"]) == 1                # endplates joined
    # idempotent rebuild: same part again replaces the previous build
    again = build_part(client, box, BOX, NS, tag, create_doc=False)
    assert again.passed and again.data["created_document"] is False
    meas = measure_assembly(client, tag, NS, ["TST-001", "TST-002", "TST-003"], [("TST-001", "TST-002")])
    assert meas["ok"] and not meas["missing"], meas
    res = {r.check_id: r for r in mate_results([{"a": "TST-001", "b": "TST-002", "expect": "touching"},
                                               {"a": "TST-001", "b": "TST-003", "expect": "gap", "value_mm": 200}],
                                              meas)}
    assert res["MATE-TST-001-TST-002"].status == Status.VERIFIED, res["MATE-TST-001-TST-002"]
    gap = res["MATE-TST-001-TST-003"].measured["gap_mm"]
    assert abs(gap - 170.0) < 1e-3, gap                                        # box x=500 vs nose x<=330
    assert meas["joints"] == [["TST-001", "TST-002"]], meas
    images, calls, errors = screenshot_views(client, tag, (450.0, 0.0, 120.0))
    assert not errors and set(images) == {"iso", "front", "top"}, errors
    out = os.environ.get("FAST_LIVE_OUT")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        for k, png in images.items():
            (Path(out) / f"{k}.png").write_bytes(png)
    print(json.dumps({"depth_first": builds["TST-001"].depth, "depth_assembly": meas["depth"],
                      "camera_calls": calls, "fusion_version": builds["TST-001"].data["fusion_version"]}))


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_claude_written_body_builds(session):
    """A body Claude wrote against docs/fusion_script_contract.md (stored verbatim, no paid call) builds first try."""
    client, tag = session
    body = (FIXTURES / "claude_part_TST-010.body.txt").read_text(encoding="utf-8")
    spec = PartSpec(id="TST-010", name="Test floor", role="floor plate under the car with rear diffuser ramp",
                    dims={"length": 1200, "width": 800, "thickness": 20, "diffuser_length": 300, "diffuser_height": 120},
                    position_mm=(-1500.0, 0.0, 0.0), envelope_min=(-1500.0, -400.0, 0.0),
                    envelope_max=(-300.0, 400.0, 120.0), fia_refs_used=["C2.3.1"])
    b = build_part(client, spec, body, NS, tag, create_doc=True)
    failed = {c.check_id: c.message for c in b.checks if c.status != Status.VERIFIED}
    assert b.ok and not failed, (b.error, failed, b.data.get("measure", {}).get("bbox_world"))
    print(json.dumps({"TST-010_bbox": b.data["measure"]["bbox_world"], "depth": b.depth}))
