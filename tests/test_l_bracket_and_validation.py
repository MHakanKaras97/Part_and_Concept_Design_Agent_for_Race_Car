import json
import math
from pathlib import Path

import pytest

from fusion.generators import l_bracket as g
from fusion.inspect import GeometryReport
from manufacturing.dfm import load_materials
from tests.helpers import FakeFusion, assert_close, good_inputs
from validation.checks import ExpectedGeometry, geometry_checks, plate_bending_check
from vehicle.models import Pose, Severity, Status, ValidationResult

DATA = Path(__file__).resolve().parents[1] / "data"


# ---------------- generator: feasibility / quantities ----------------
def test_good_inputs_are_feasible():
    assert g.feasibility_errors(good_inputs()) == []


@pytest.mark.parametrize("over,fragment", [
    ({"base_hole_x0": 10}, "cuts into the bend"),
    ({"upright_hole_z0": 12}, "cuts into the bend"),
    ({"base_hole_pitch_x": 50}, "exceeds the base leg end"),
    ({"base_hole_pitch_y": 58}, "exceeds the bracket width"),
    ({"base_hole_pitch_y": 5}, "column pitch must exceed"),
    ({"bracket_thickness": 75}, "smaller than both leg lengths"),
])
def test_infeasible_inputs_detected(over, fragment):
    assert any(fragment in e for e in g.feasibility_errors(good_inputs(**over)))


def test_hole_layout_counts_and_symmetry():
    p = good_inputs()
    bh = g.base_holes(p)
    assert len(bh) == 4 and sorted({h["y"] for h in bh}) == [-18.0, 18.0]
    assert sorted({h["x"] for h in bh}) == [35.0, 65.0]
    single = good_inputs(upright_hole_rows=1, upright_hole_cols=1)
    assert g.upright_holes(single) == [{"id": "HU11", "z": 30.0, "y": 0.0, "d": 5.5}]


def test_dfm_quantities():
    q = g.dfm_quantities(good_inputs())
    assert q["wall_thickness"] == 6 and q["internal_corner_radius"] == 4
    assert_close(q["fillet_to_thickness_ratio"], 4 / 6)
    # closest free edge: base end 80-65=15 or side 30-18=12 -> 12/6.6 ; upright top 70-58=12 / 5.5
    assert_close(q["hole_edge_distance_ratio"], min(12 / 6.6, 12 / 5.5))
    assert {"item": "M6", "value": 6.6} in q["clearance_holes"]


def test_analytic_volume_matches_independent_formula():
    p = good_inputs(bend_inner_radius=0, base_hole_rows=1, base_hole_cols=1, upright_hole_rows=1, upright_hole_cols=1)
    # sharp inner corner, outer radius = t: L-section = two rectangles minus outer corner (t^2 - pi t^2/4)
    t, w = 6, 60
    area = 80 * t + (70 - t) * t - (t * t - math.pi * t * t / 4)
    holes = math.pi * 6.6 ** 2 / 4 * t + math.pi * 5.5 ** 2 / 4 * t
    assert_close(g.expected_volume_mm3(p), area * w - holes)


def test_volume_matches_value_measured_by_fusion_on_2026_10_05():
    # Fusion 2705.1.11 measured 49367.12102095444 mm3 for these inputs (VeryHigh accuracy)
    assert abs(g.expected_volume_mm3(good_inputs()) - 49367.12102095444) < 1e-6


def test_script_compiles_and_contains_named_parameters_and_features():
    s = g.build_script("BRK-001", "Sensor bracket", good_inputs(), [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    compile(s, "<bracket>", "exec")
    for token in ("brk001", "bracket_thickness", "SK_L_profile", "EX_L_profile", "FL_bend_inner",
                  "CUT_base_holes", "def run(_context: str)"):
        assert token in s


def test_interfaces_mounting_points_on_mounting_faces():
    ifs = g.interfaces(good_inputs(), "plate", "sensor_box")
    base, upr = ifs
    assert base["normal"] == (0.0, 0.0, -1.0) and all(m["position"][2] == 0.0 for m in base["mounting_points"])
    assert upr["normal"] == (-1.0, 0.0, 0.0) and all(m["position"][0] == 0.0 for m in upr["mounting_points"])
    assert len(base["mounting_points"]) == 4 and base["mounting_points"][0]["fastener"] == "M6"


# ---------------- validation against a (fake) inspection report ----------------
def _report_and_expected(volume_scale=1.0, drop_hole=False, param_delta=0.0):
    p = good_inputs()
    fake = FakeFusion(volume_scale=volume_scale)
    script = g.build_script("BRK-001", "B", p, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    fake.run_script(script)
    from fusion.inspect import build_inspect_script
    data = fake.run_script(build_inspect_script(g.fusion_component_name("BRK-001", "B"), "brk001"), read_only=True).data
    if drop_hole:
        data["bodies"][0]["cylinders"].pop()
    rep = GeometryReport.model_validate(data)
    params = g.fusion_parameters("BRK-001", p)
    params["brk001_bracket_thickness"] += param_delta
    exp = ExpectedGeometry(bbox_local=g.expected_bbox_local(p), volume_mm3=g.expected_volume_mm3(p),
                           holes_local=g.expected_holes_local(p), parameters=params, pose=Pose())
    return {r.check_id: r for r in geometry_checks(rep, exp)}


def test_geometry_checks_pass_for_matching_geometry():
    res = _report_and_expected()
    assert all(r.status == Status.VERIFIED for r in res.values()), {k: r.message for k, r in res.items()}
    assert set(res) >= {"GEO-BODY-COUNT", "GEO-FEATURE-HEALTH", "GEO-BBOX", "GEO-VOLUME", "GEO-PARAM-SYNC", "IFC-HOLE-GEOMETRY"}


def test_volume_deviation_detected():
    assert _report_and_expected(volume_scale=1.01)["GEO-VOLUME"].status == Status.NON_COMPLIANT


def test_missing_hole_detected():
    assert _report_and_expected(drop_hole=True)["IFC-HOLE-GEOMETRY"].status == Status.NON_COMPLIANT


def test_parameter_desync_detected():
    assert _report_and_expected(param_delta=0.5)["GEO-PARAM-SYNC"].status == Status.NON_COMPLIANT


def test_component_not_found():
    rep = GeometryReport(found=False, component_name="X")
    exp = ExpectedGeometry(bbox_local=((0, 0, 0), (1, 1, 1)), volume_mm3=1, holes_local=[], parameters={})
    (r,) = geometry_checks(rep, exp)
    assert r.check_id == "GEO-FOUND" and r.status == Status.NON_COMPLIANT


# ---------------- hand calculation ----------------
def test_plate_bending_hand_calc():
    r = plate_bending_check(force_n=100, lever_arm_mm=40, section_width_mm=50, thickness_mm=4, yield_mpa=276,
                            required_sf=2, inputs_assumed=True, note="")
    # sigma = 6*4000/(50*16) = 30 MPa -> SF 9.2
    assert r.measured["stress_MPa"] == 30.0 and r.measured["safety_factor"] == 9.2
    assert r.status == Status.ASSUMPTION
    weak = plate_bending_check(1000, 100, 10, 2, 276, 2, False, "")
    assert weak.status == Status.NON_COMPLIANT


@pytest.mark.parametrize("force,arm", [(0.0, 0.0), (0.0, 40.0), (98.1, 0.0)])
def test_plate_bending_without_load_case_is_not_run_and_not_blocking(force, arm):
    """Part 001 (2026-10-06) had force 0 / lever arm 0 and was recorded as a passed ASSUMPTION with SF = inf.
    No load case means nothing was checked: NOT_VERIFIED / NOT_RUN, advisory (the precheck must not loop on it)."""
    r = plate_bending_check(force, arm, 70, 12, 276, 1.0, True, "note")
    assert r.status == Status.NOT_VERIFIED and r.method == "NOT_RUN" and r.severity == Severity.ADVISORY
    assert not r.blocking_failure and r.label == "STRUCTURAL_CHECK_NOT_VERIFIED"
    assert "No load case" in r.message
    json.dumps(r.model_dump(mode="json"), allow_nan=False)          # no inf / NaN in the record


def _historical_load_cases():
    out = []
    for f in sorted(DATA.glob("*/runs/*/run.json")):
        run = json.loads(f.read_text(encoding="utf-8"))
        stored = [v for v in run.get("validation") or [] if v["check_id"] == "STR-PLATE-BENDING"]
        if run.get("plan") and stored and run["plan"]["load_case"]["force_n"] > 0:
            out.append(pytest.param(run, stored[0], id=f"{f.parents[2].name}/{f.parent.name[:15]}"))
    return out


@pytest.mark.parametrize("run,stored", _historical_load_cases())
def test_historical_load_case_results_are_unchanged(run, stored):
    """BRK-001/BRK-002 (prototype_bench) and the UI E2E BRK-001 have real load cases: recomputing them with the
    current code gives exactly the stored result."""
    plan = run["plan"]
    p = g.INPUTS.from_values({k: v["value"] for k, v in plan["parameters"].items()}, plan.get("design_inputs") or {})
    mat = load_materials()[plan["manufacturing"]["material"]]
    lc, sec = plan["load_case"], g.structural_section(p)
    r = plate_bending_check(lc["force_n"], lc["lever_arm_mm"], sec["width"], sec["thickness"], mat.yield_strength_mpa,
                            lc["required_safety_factor"], inputs_assumed=True, note="").model_dump(mode="json")
    stored = ValidationResult.model_validate(stored).model_dump(mode="json")   # legacy records: scope is derived
    for k in ("status", "severity", "method", "measured", "limit", "unit", "scope"):
        assert r[k] == stored[k], k


def test_fusion_names_are_namespaced_per_project():
    # original project (no namespace) keeps the BRK-001/002 names already in Fusion
    assert g.param_prefix("BRK-001") == "brk001" and g.fusion_component_name("BRK-001", "B") == "BRK-001 B"
    assert g.param_prefix("BRK-001", "uie2etest") == "uie2etest_brk001"
    assert g.fusion_component_name("BRK-001", "B", "uie2etest") == "uie2etest BRK-001 B"
    s = g.build_script("BRK-001", "B", good_inputs(), [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], namespace="uie2etest")
    assert '"component_key": "uie2etest BRK-001 "' in s and '"prefix": "uie2etest_brk001"' in s
    assert "refusing to overwrite it" in s          # never silently fails to clear a parameter
    assert set(g.fusion_parameters("BRK-001", good_inputs(), "uie2etest")) == \
        {f"uie2etest_brk001_{k}" for k in g.LENGTH_PARAMS} | {"uie2etest_brk001_bend_outer_radius"}
