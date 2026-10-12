"""Generator v2 (separate upright thickness), placement through the workflow, and placement-safe validation."""
import json
import math
from pathlib import Path

import pytest

from agent.workflow import Engine, create_run
from fusion.generators import l_bracket as g
from fusion.inspect import GeometryReport, build_inspect_script
from tests.helpers import (FASTENERS, GOOD, REQUEST, FakeFusion, ScriptedBackend, analysis_response, assert_close,
                           good_inputs, plan_response)
from validation.checks import ExpectedGeometry, geometry_checks
from vehicle.models import Pose, Status
from vehicle.store import ProjectStore
from vehicle.transforms import matrix_to_fusion_cm, pose_to_matrix

# Part 001 (F1-inspired front-wing mounting bracket) dimensions
PART001 = dict(leg_base_length=120, leg_upright_height=65, bracket_width=70, bracket_thickness=12,
               upright_thickness=10, bend_inner_radius=5, base_hole_diameter=10, base_hole_x0=70,
               base_hole_pitch_x=0, base_hole_pitch_y=40, upright_hole_diameter=8, upright_hole_z0=40,
               upright_hole_pitch_z=0, upright_hole_pitch_y=40, base_hole_rows=1, base_hole_cols=2,
               upright_hole_rows=1, upright_hole_cols=2)
POSE = Pose(position=(500.0, -250.0, 150.0), rotation_deg=(15.0, 35.0, 60.0))
ACCEPT = {"decision": "ACCEPT", "rationale": "all blocking checks pass"}


def part001(**over) -> g.BracketInputs:
    return g.BracketInputs.from_values(dict(PART001, **over), FASTENERS)


def _cfg(script: str) -> dict:
    return json.loads(script.split('r"""')[1].split('"""')[0])


# ---------------- generator v2 ----------------
def test_v1_inputs_keep_v1_behaviour():
    p = good_inputs()                                   # no upright_thickness: v1 plan/record
    assert p.upright_thickness is None and p.upright_t == 6 and p.outer_radius == 4 + 6
    assert g.fusion_parameters("BRK-001", p)["brk001_upright_thickness"] == 6
    cfg = _cfg(g.build_script("BRK-001", "B", p, matrix_to_fusion_cm(pose_to_matrix(Pose()))))
    assert cfg["linked"] == {"upright_thickness": "bracket_thickness"}   # follows bracket_thickness in Fusion
    assert g.dfm_quantities(p)["wall_thickness"] == 6 and g.structural_section(p)["thickness"] == 6


def test_part001_is_feasible_and_quantities_use_both_thicknesses():
    p = part001()
    assert g.feasibility_errors(p) == []
    assert p.outer_radius == 5 + 12                     # inner + thicker leg: wall at the bend >= 10 mm
    q = g.dfm_quantities(p)
    assert q["wall_thickness"] == 10
    assert_close(q["fillet_to_thickness_ratio"], 5 / 12)
    assert g.structural_section(p)["thickness"] == 10    # the loaded upright leg
    holes = {h["id"]: h for h in g.expected_holes_local(p)}
    assert holes["HB11"]["center"] == (70, -20, 6.0) and holes["HU11"]["center"] == (5.0, -20, 40)
    cfg = _cfg(g.build_script("BRK-001", "B", p, matrix_to_fusion_cm(pose_to_matrix(Pose()))))
    assert cfg["linked"] == {} and cfg["upright_t"] == 10
    s = g.build_script("BRK-001", "B", p, matrix_to_fusion_cm(pose_to_matrix(Pose())))
    assert 'pname("upright_thickness")' in s and "max(" in s


def test_v2_volume_matches_independent_formula():
    p = part001(bend_inner_radius=0)                    # sharp inner corner: outer radius = max(12, 10) = 12
    tb, tu, ro, w = 12, 10, 12, 70
    area = 120 * tb + (65 - tb) * tu - (ro * ro - math.pi * ro * ro / 4)
    holes = 2 * math.pi * 10 ** 2 / 4 * tb + 2 * math.pi * 8 ** 2 / 4 * tu
    assert_close(g.expected_volume_mm3(p), area * w - holes)


def test_flat_regions_follow_the_other_legs_thickness():
    # base holes start after the UPRIGHT thickness + radius (10 + 5), upright holes after the BASE thickness (12 + 5)
    assert g.feasibility_errors(part001(base_hole_x0=21)) == []                  # x_min 16 >= 15
    assert any("cuts into the bend" in e for e in g.feasibility_errors(part001(base_hole_x0=21, upright_thickness=12)))
    assert any("cuts into the bend" in e for e in g.feasibility_errors(part001(upright_hole_z0=20)))  # 16 < 17
    assert any("upright_thickness must be smaller" in e for e in g.feasibility_errors(part001(upright_thickness=70)))


# ---------------- validation: rotated placement ----------------
def _checks(p, pose, tamper=None):
    fake = FakeFusion()
    fake.run_script(g.build_script("BRK-001", "B", p, matrix_to_fusion_cm(pose_to_matrix(pose))))
    data = fake.run_script(build_inspect_script(g.fusion_component_name("BRK-001", "B"), "brk001"), read_only=True).data
    if tamper:
        tamper(data)
    exp = ExpectedGeometry(bbox_local=g.expected_bbox_local(p), volume_mm3=g.expected_volume_mm3(p),
                           holes_local=g.expected_holes_local(p), parameters=g.fusion_parameters("BRK-001", p), pose=pose)
    return {r.check_id: r for r in geometry_checks(GeometryReport.model_validate(data), exp)}


def test_rotated_part_passes_all_geometry_checks():
    res = _checks(part001(), POSE)
    assert all(r.status == Status.VERIFIED for r in res.values()), {k: r.message for k, r in res.items()}
    assert {"GEO-BBOX", "GEO-PLACEMENT", "IFC-HOLE-GEOMETRY"} <= set(res)
    assert res["GEO-PLACEMENT"].measured["vertices_checked"] == 12


def test_world_box_comparison_was_a_false_failure_for_rotated_parts():
    def legacy(data):                                   # report without component-frame measurements
        for b in data["bodies"]:
            b.pop("bbox_local_min"); b.pop("bbox_local_max")
    assert _checks(part001(), POSE, legacy)["GEO-BBOX"].status == Status.NON_COMPLIANT
    assert _checks(part001(), Pose(), legacy)["GEO-BBOX"].status == Status.VERIFIED   # identity: still exact


@pytest.mark.parametrize("tamper,fragment", [
    (lambda d: d["occurrence_transform"].__setitem__(3, d["occurrence_transform"][3] + 0.5), "translation"),
    (lambda d: d.__setitem__("occurrence_transform", [float(v) for v in pose_to_matrix(Pose(
        position=(500.0, -250.0, 150.0), rotation_deg=(15.0, 35.0, 61.0))).reshape(-1)]), "rotation"),
    (lambda d: d.__setitem__("pending_snapshot", True), "pending"),
    (lambda d: d["bodies"][0]["vertices_world"][0].__setitem__(2, d["bodies"][0]["vertices_world"][0][2] + 0.1),
     "world vertices"),
])
def test_placement_errors_are_detected(tamper, fragment):
    r = _checks(part001(), POSE, tamper)["GEO-PLACEMENT"]
    assert r.status == Status.NON_COMPLIANT and fragment in r.message


def test_legacy_report_without_transform_has_no_placement_result():
    res = _checks(part001(), Pose(), lambda d: d.pop("occurrence_transform"))
    assert "GEO-PLACEMENT" not in res


# ---------------- workflow: plan -> pose -> Fusion -> validation -> record ----------------
def _engine(tmp_path, responses):
    store = ProjectStore("bench", root=tmp_path)
    backend = ScriptedBackend(responses)
    fusion = FakeFusion()
    return store, Engine(store, backend_factory=lambda run: backend, fusion=fusion), backend, fusion


def _placement(**over):
    return dict({"position_mm": list(POSE.position), "rotation_deg": list(POSE.rotation_deg), "source": "ASSUMPTION",
                 "trace": ["A01"], "rationale": "test placement"}, **over)


def test_plan_placement_reaches_fusion_validation_and_record(tmp_path):
    plan = plan_response(upright_thickness=5)
    plan["placement"] = _placement()
    store, eng, _, fusion = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [plan], "review": [ACCEPT]})
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "COMPLETED", run["events"]
    (built,) = fusion.built.values()
    assert built["transform"] == matrix_to_fusion_cm(pose_to_matrix(POSE)) and built["upright_t"] == 5
    v = {r["check_id"]: r for r in run["validation"]}
    assert v["GEO-PLACEMENT"]["status"] == "VERIFIED" and v["GEO-BBOX"]["status"] == "VERIFIED"
    comp = store.get_component("BRK-001")
    assert comp.pose == POSE and comp.generator["version"] == g.GENERATOR_VERSION == "3"
    assert comp.parameters["upright_thickness"].value == 5


def test_plan_without_placement_keeps_identity_pose(tmp_path):
    store, eng, _, fusion = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [plan_response()],
                                               "review": [ACCEPT]})
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "COMPLETED"
    assert next(iter(fusion.built.values()))["transform"] == matrix_to_fusion_cm(pose_to_matrix(Pose()))
    assert store.get_component("BRK-001").pose == Pose()


@pytest.mark.parametrize("placement,fragment", [
    (_placement(trace=["A99"]), "placement: unknown trace ids"),
    (_placement(source="USER"), "placement: source USER must trace to the user's request"),
    (_placement(trace=[]), "placement: source ASSUMPTION needs a trace"),
])
def test_placement_provenance_is_gated(tmp_path, placement, fragment):
    bad = plan_response()
    bad["placement"] = placement
    store, eng, backend, fusion = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [bad]})
    run = eng.advance(create_run(store, REQUEST))
    assert fusion.built == {} and any(fragment in e for e in run["feedback"]["errors"]), run["feedback"]


def test_unknown_parameter_still_rejected_but_optional_one_accepted(tmp_path):
    bad = plan_response()
    bad["parameters"]["wall_colour"] = dict(bad["parameters"]["bracket_thickness"])
    store, eng, _, _ = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [bad]})
    run = eng.advance(create_run(store, REQUEST))
    assert any("unknown ['wall_colour']" in e for e in run["feedback"]["errors"])
    assert set(GOOD) | {"upright_thickness"} == set(g.LENGTH_PARAMS) | set(g.COUNT_PARAMS)


# ---------------- placement anchor + read-back (generator 3) ----------------
# Live Fusion (2705.1.11 and 2705.1.30): transform2 on the ONLY root occurrence is silently ignored. The build keeps an
# empty identity anchor occurrence first and raises if the placement read-back differs. Unit tests cannot reproduce
# the Fusion behaviour (FakeFusion applies any transform); tests/integration/test_fusion_live.py covers it live.

def _run_body(script: str) -> str:
    return script[script.index("def run(_context: str):"):]


def test_build_creates_the_anchor_before_the_part_and_reads_back_the_placement():
    s = g.build_script("BRK-001", "B", part001(), matrix_to_fusion_cm(pose_to_matrix(POSE)), namespace="f1parts")
    compile(s, "build", "exec")
    assert _cfg(s)["anchor_name"] == g.ANCHOR_NAME == "VCS origin"
    body = _run_body(s)
    assert (body.index("remove_previous(design, root)") < body.index("ensure_anchor(root)")
            < body.index("root.occurrences.addNewComponent"))
    assert body.index("design.snapshots.add()") < body.index("Fusion did not apply the placement")
    assert body.index("Fusion did not apply the placement") < body.index("except Exception:")   # partial build removed


def test_anchor_is_on_by_default_and_off_only_explicitly():
    m = matrix_to_fusion_cm(pose_to_matrix(POSE))
    assert _cfg(g.build_script("BRK-001", "B", part001(), m))["anchor_name"] == g.ANCHOR_NAME
    assert _cfg(g.build_script("BRK-001", "B", part001(), m, anchor=False))["anchor_name"] is None


@pytest.mark.parametrize("cid,ns", [("BRK-001", ""), ("BRK-002", ""), ("BRK-001", "f1parts"), ("BRK-001", "uie2etest"),
                                    ("BRK-999", "itest"), ("BRK-001", "diag")])
def test_anchor_name_never_matches_a_component_key(cid, ns):
    """remove_previous deletes occurrences whose component name starts with the component key; the anchor must
    survive every re-run of every component."""
    assert not g.ANCHOR_NAME.startswith(g.component_key(cid, ns))
    assert not g.ANCHOR_NAME.startswith(g.param_prefix(cid, ns))


DATA = Path(__file__).resolve().parents[1] / "data"
_ALL_RECORDS = sorted(DATA.glob("*/components/*.json"))
HISTORICAL_COMPONENTS = [f for f in _ALL_RECORDS
                         if json.loads(f.read_text(encoding="utf-8")).get("record_type") != "part"]
HISTORICAL_PARTS = [f for f in _ALL_RECORDS if f not in HISTORICAL_COMPONENTS]
HISTORICAL_PLANS = [f for f in sorted(DATA.glob("*/runs/*/run.json"))
                    if json.loads(f.read_text(encoding="utf-8")).get("plan")]


def test_historical_records_exist():
    assert {f"{f.parent.parent.name}/{f.stem}" for f in HISTORICAL_COMPONENTS} >= {
        "prototype_bench/BRK-001", "prototype_bench/BRK-002", "ui_e2e_test/BRK-001"}
    assert len(HISTORICAL_PLANS) >= 4


@pytest.mark.parametrize("path", HISTORICAL_COMPONENTS, ids=lambda f: f"{f.parent.parent.name}/{f.stem}")
def test_historical_component_records_validate_unchanged(path):
    """No generator change may invalidate or rewrite an existing record (each keeps the generator version it was
    built with; f1_parts/BRK-001 was registered with generator 3)."""
    raw = path.read_bytes()
    comp = ProjectStore(path.parent.parent.name, root=DATA).get_component(path.stem)
    assert comp.generator["id"] == "l_bracket" and comp.generator["version"] in ("1", "2", "3")
    assert path.read_bytes() == raw


@pytest.mark.parametrize("path", HISTORICAL_PARTS, ids=lambda f: f"{f.parent.parent.name}/{f.stem}")
def test_historical_part_records_validate_unchanged(path):
    """Fast-mode part records (first Mini F1 run) stay valid and are not rewritten by loading them."""
    from vehicle.parts import PartRecord, script_hash
    raw = path.read_bytes()
    rec = PartRecord.model_validate_json(raw)
    assert rec.script_sha256 == script_hash(rec.script_body) and rec.version >= 1
    assert path.read_bytes() == raw


@pytest.mark.parametrize("path", HISTORICAL_PLANS, ids=lambda f: f"{f.parents[2].name}/{f.parent.name[:15]}")
def test_historical_v1_v2_plans_still_build(path):
    raw = path.read_bytes()
    plan = json.loads(raw)["plan"]
    p = g.INPUTS.from_values({k: v["value"] for k, v in plan["parameters"].items()}, plan.get("design_inputs") or {})
    s = g.build_script("BRK-001", "historical", p, matrix_to_fusion_cm(pose_to_matrix(Pose())))
    compile(s, "build", "exec")
    cfg = _cfg(s)
    assert cfg["values"] == p.model_dump() and cfg["anchor_name"] == g.ANCHOR_NAME
    assert path.read_bytes() == raw
