"""Coordinate-frame contract: part-local scripts, frame-mismatch detection, the MON-001 v1 double offset and the
MON-001 v2 legacy_world compatibility path (docs/fusion_script_contract.md)."""
import json

from agent.design_run import Orchestrator, create_design_run
from agent.fast_prompts import part_system, part_user
from agent.fast_reasoning import ScriptedReasoner
from fusion.part_runner import build_part, compact_error, rebuild_part
from fusion.prelude import PRELUDE, RUNNER
from tests.helpers import MINI_BOX_BODY, FakePartFusion, mini_f1_plan
from validation.part_checks import FRAME_MISMATCH, frame_check, repairable
from vehicle.models import Severity, Status
from vehicle.parts import PartRecord, PartSpec
from vehicle.store import DATA_ROOT, ProjectStore, read_json

MON_V1 = DATA_ROOT / "mini_f1" / "components" / "history" / "MON-001.v1.json"
MON_V2 = DATA_ROOT / "mini_f1" / "components" / "history" / "MON-001.v2.json"
# MON-001's real measured geometry in its script's own coordinates (v1 bbox_world minus its pose z = 30;
# identical to the v2 bbox_world, built at the identity pose)
MON_LOCAL = ([-3700.0, -450.1972, 30.0], [550.0, 450.1972, 740.0])


def frame(b):
    return next(c for c in b.checks if c.check_id == "PART-FRAME")


def box_spec(pos=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0), lo=(0.0, -25.0, 0.0), hi=(100.0, 25.0, 30.0)):
    return PartSpec(id="TST-001", name="box", role="test", dims={"length": 100.0, "width": 50.0, "height": 30.0},
                    position_mm=pos, rotation_deg=rot, envelope_min=lo, envelope_max=hi)


# ---------------------------------------------------------------- MON-001 v1: the real double offset
def test_mon001_v1_double_offset_is_a_repairable_frame_mismatch():
    rec = PartRecord.model_validate(read_json(MON_V1))
    assert rec.version == 1 and "zb = 30.0" in rec.script_body and rec.spec.position_mm[2] == 30.0
    fake = FakePartFusion(local_bboxes={"MON-001": MON_LOCAL})
    b = build_part(fake, rec.spec, rec.script_body, "mf1", "t", frame_mode=rec.frame_mode)
    m = b.data["measure"]["bbox_world"]
    assert m == rec.bbox_world                                   # the fake reproduces the recorded v1 geometry
    res = {c.check_id: c for c in b.checks}
    assert res["PART-BBOX"].status == Status.VERIFIED            # why it was registered: z 60..770 inside 30..790
    f = res["PART-FRAME"]
    assert f.status == Status.NON_COMPLIANT and f.blocking_failure and repairable(b.checks)
    assert f.message.startswith(FRAME_MISMATCH)
    assert "expected local bbox [(-3700,-450,0),(550,450,760)]" in f.message
    assert "measured [(-3700,-450,30),(550,450,740)]" in f.message and "pose position [0, 0, 30]" in f.message
    e = compact_error(b)
    assert e["measured_bbox_local"] == [list(MON_LOCAL[0]), list(MON_LOCAL[1])]
    assert e["expected_local_envelope"] == [[-3700.0, -450.0, 0.0], [550.0, 450.0, 760.0]]
    assert any(FRAME_MISMATCH in x for x in e["failing_checks"])


# ---------------------------------------------------------------- MON-001 v2: legacy_world compatibility
def test_mon001_v2_is_legacy_world_and_rebuilds_unchanged():
    v1, v2 = PartRecord.model_validate(read_json(MON_V1)), PartRecord.model_validate(read_json(MON_V2))
    assert v2.version == 2 and v2.frame_mode == "legacy_world" and "compatibility exception" in v2.frame_note
    assert v2.script_body == v1.script_body and v2.script_sha256 == v1.script_sha256   # script unchanged
    assert v2.spec.position_mm == (0.0, 0.0, 0.0) and v2.spec.rotation_deg == (0.0, 0.0, 0.0)
    fake = FakePartFusion(local_bboxes={"MON-001": MON_LOCAL})
    b = rebuild_part(fake, v2, "mf1", "t")
    assert b.passed and b.frame_mode == "legacy_world", [(c.check_id, c.message) for c in b.checks if c.blocking_failure]
    assert frame(b).status == Status.VERIFIED and "legacy_world compatibility exception" in frame(b).message
    assert v2.script_body.rstrip() in fake.scripts[0]
    assert b.data["measure"]["bbox_world"] == v2.bbox_world


def test_legacy_world_script_with_a_non_identity_pose_is_rejected():
    v2 = PartRecord.model_validate(read_json(MON_V2))
    moved = v2.spec.model_copy(update={"position_mm": (0.0, 0.0, 30.0)})
    b = build_part(FakePartFusion(local_bboxes={"MON-001": MON_LOCAL}), moved, v2.script_body, "mf1", "t",
                   frame_mode="legacy_world")
    assert frame(b).blocking_failure and "would apply the offset twice" in frame(b).message


def test_the_same_box_is_valid_as_legacy_but_not_as_part_local_when_posed():
    """legacy_world is an explicit path: identical geometry, different contract."""
    s = box_spec(pos=(500.0, 0.0, 100.0), lo=(500.0, -25.0, 100.0), hi=(600.0, 25.0, 130.0))
    data = {"bbox_local": [[500.0, -25.0, 100.0], [600.0, 25.0, 130.0]]}           # world values in the script
    assert frame_check(s, data, "part_local").message.startswith(FRAME_MISMATCH)
    assert "offset twice" in frame_check(s, data, "legacy_world").message


# ---------------------------------------------------------------- part-local validation
def test_part_local_script_with_an_offset_pose_passes():
    s = box_spec(pos=(500.0, 0.0, 100.0), lo=(500.0, -25.0, 100.0), hi=(600.0, 25.0, 130.0))
    b = build_part(FakePartFusion(envelopes={"TST-001": (s.envelope_min, s.envelope_max)}), s, MINI_BOX_BODY, "x", "t")
    assert b.passed and frame(b).status == Status.VERIFIED
    assert b.data["bbox_local"] == [[0.0, -25.0, 0.0], [100.0, 25.0, 30.0]]


def test_world_coordinate_script_with_an_offset_pose_is_detected():
    s = box_spec(pos=(500.0, 0.0, 100.0), lo=(500.0, -25.0, 100.0), hi=(600.0, 25.0, 130.0))
    fake = FakePartFusion(envelopes={"TST-001": (s.envelope_min, s.envelope_max)})
    b = build_part(fake, s, MINI_BOX_BODY + "    # WORLD_COORDS\n", "x", "t")
    f = frame(b)
    assert f.blocking_failure and f.message.startswith(FRAME_MISMATCH) and repairable(b.checks)
    assert "expected local bbox [(0,-25,0),(100,25,30)]" in f.message
    assert "measured [(500,-25,100),(600,25,130)]" in f.message
    assert f.measured["faces_on_world_envelope"] == 6 and f.measured["faces_on_local_envelope"] == 2


def test_rotated_pose_uses_the_inverse_pose_on_all_corners():
    # yaw 90: local +X points to VCS +Y (the live suite's TST-003 nose)
    s = PartSpec(id="TST-003", name="nose", role="test", dims={"length": 120.0, "width": 60.0, "height": 40.0},
                 position_mm=(300.0, 0.0, 100.0), rotation_deg=(0.0, 0.0, 90.0),
                 envelope_min=(270.0, 0.0, 100.0), envelope_max=(330.0, 120.0, 140.0))
    lo, hi = s.local_envelope()
    assert (lo, hi) == ((0.0, -30.0, 0.0), (120.0, 30.0, 40.0))       # a translation alone would give (-30, 0, 0)..
    ok = frame_check(s, {"bbox_local": [[0.0, -30.0, 0.0], [120.0, 30.0, 40.0]]})
    assert ok.status == Status.VERIFIED, ok.message
    translated_only = frame_check(s, {"bbox_local": [[-30.0, 0.0, 0.0], [30.0, 120.0, 40.0]]})
    assert translated_only.blocking_failure and "outside the local envelope" in translated_only.message
    world = frame_check(s, {"bbox_local": [[270.0, 0.0, 100.0], [330.0, 120.0, 140.0]]})
    assert world.blocking_failure and world.message.startswith(FRAME_MISMATCH)
    fake = FakePartFusion(envelopes={"TST-003": (s.envelope_min, s.envelope_max)})
    assert frame(build_part(fake, s, MINI_BOX_BODY, "x", "t")).status == Status.VERIFIED


def test_smaller_part_inside_the_local_envelope_passes():
    s = box_spec(pos=(500.0, 0.0, 100.0), lo=(500.0, -25.0, 100.0), hi=(600.0, 25.0, 130.0))
    r = frame_check(s, {"bbox_local": [[0.0, -20.0, 0.0], [90.0, 20.0, 25.0]]})
    assert r.status == Status.VERIFIED


def test_missing_local_bbox_is_not_verified_and_not_blocking():
    r = frame_check(box_spec(), {})
    assert r.status == Status.NOT_VERIFIED and r.severity == Severity.ADVISORY and not r.blocking_failure


def test_prelude_measures_the_local_bbox_in_the_build_script_before_placement():
    assert "def _bbox_local(comp)" in PRELUDE
    i, j = RUNNER.index("res[\"bbox_local\"] = _bbox_local"), RUNNER.index("finish_part(design, occ")
    assert i < j


# ---------------------------------------------------------------- contract, prompts, design run
def test_contract_and_part_prompt_state_the_part_local_frame():
    sysp = part_system()
    assert "part-local frame" in sysp and "must NOT encode the part's world/vehicle position" in sysp
    s = box_spec(pos=(500.0, 0.0, 100.0), lo=(500.0, -25.0, 100.0), hi=(600.0, 25.0, 130.0))
    payload = json.loads(part_user(s, []))["part"]
    assert payload["local_envelope_min"] == [0.0, -25.0, 0.0]
    assert payload["world_to_local"] == {"position_mm": [500.0, 0.0, 100.0], "rotation_deg": [0.0, 0.0, 0.0]}


def test_design_run_repairs_a_frame_mismatch_with_the_diagnostic(tmp_path):
    plan = mini_f1_plan()
    envs = {p["id"]: (p["envelope_min"], p["envelope_max"]) for p in plan["parts"]}
    store = ProjectStore("mini_f1", root=tmp_path)
    reasoner = ScriptedReasoner({"plan": [plan], "part": [{"body": MINI_BOX_BODY + "    # WORLD_COORDS\n"}]
                                 + [{"body": MINI_BOX_BODY}] * 3, "repair": [{"body": MINI_BOX_BODY}]})
    orch = Orchestrator(store, fusion=FakePartFusion(envelopes=envs), reasoner_factory=lambda r: reasoner)
    run = orch.advance(create_design_run(store, "Mini F1"))
    st = run["parts"]["MON-001"]
    assert run["status"] == "DONE" and st["state"] == "done" and [a["kind"] for a in st["attempts"]] == ["part", "repair"]
    assert st["attempts"][0]["failed_checks"] == ["PART-BBOX", "PART-FRAME"]     # shifted twice: also outside
    failure = json.loads(next(c for c in reasoner.log if c["name"] == "repair_MON-001_1")["user"])["failure"]
    assert any(FRAME_MISMATCH in x for x in failure["failing_checks"])
    assert failure["expected_local_envelope"] == [[0.0, -400.0, 0.0], [3000.0, 400.0, 700.0]]
    assert store.get_part("MON-001").frame_mode == "part_local"
