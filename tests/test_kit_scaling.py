"""18-part Mini F1: catalog kit from the brief, side-suffixed part ids, keep-clear / shallow-overlap mates,
far-apart pair skipping and the per-segment script budget (fake Fusion, scripted Claude)."""
import pytest

from agent.design_run import Orchestrator, create_design_run, load_design_run
from agent.fast_prompts import MINI_F1_CATALOG, MINI_F1_KIT, PlanResponse, gate_plan, kit_for_brief
from agent.fast_reasoning import ScriptedReasoner
from agent.revise import parse_assembly, Rejected
from fia_rules.retrieval import retrieve
from fusion.assembly import assembly_script, mate_pairs
from tests.helpers import MINI_BOX_BODY, FakePartFusion, decode_part_cfg
from validation.part_checks import mate_face_checks, mate_results, planned_mate_problem
from vehicle.models import Status
from vehicle.parts import PartSpec
from vehicle.store import ProjectStore

ALL_IDS = [k["id"] for k in MINI_F1_CATALOG]
BRIEF18 = "Mini F1 with every part: " + ", ".join(ALL_IDS) + "."


def _part(pid, lo, hi):
    return {"id": pid, "name": pid, "role": pid.lower(), "notes": "", "position_mm": list(lo),
            "rotation_deg": [0, 0, 0], "envelope_min": list(lo), "envelope_max": list(hi),
            "dims": {"length": hi[0] - lo[0], "width": hi[1] - lo[1], "height": hi[2] - lo[2]},
            "fia_refs_used": [] if pid.startswith("WHL") else ["C2.3.1"], "reuse": False}


def _mirror(lo, hi):
    return (lo[0], -hi[1], lo[2]), (hi[0], -lo[1], hi[2])


def plan18() -> dict:
    """A gate-valid 18-part box layout (test numbers only): left parts at +Y, right parts mirrored."""
    left = {"WHL-F": ((-330, 750, 0), (330, 1100, 660)), "WHL-R": ((-3330, 750, 0), (-2670, 1100, 660)),
            "SUF": ((-200, 395, 250), (200, 750, 450)), "SUR": ((-3100, 300, 200), (-2900, 750, 400)),
            "SDP": ((-2300, 400, 30), (-800, 700, 500)), "MIR": ((-700, 380, 730), (-550, 560, 840))}
    parts = [_part("MON-001", (-2400, -400, 30), (600, 400, 730)),
             _part("FWG-001", (600, -900, 60), (1000, 900, 300)),
             _part("FLR-001", (-3400, -700, 0), (-100, 700, 30)),
             _part("RWG-001", (-3900, -500, 30), (-3400, 500, 950)),
             _part("ENG-001", (-3300, -300, 30), (-2400, 300, 700)),
             _part("HAL-001", (-1200, -350, 730), (-400, 350, 950))]
    for key, (lo, hi) in left.items():
        lid, rid = (key + "L", key + "R") if key.startswith("WHL") else (key + "-L", key + "-R")
        parts += [_part(lid, lo, hi), _part(rid, *_mirror(lo, hi))]
    mates = [{"a": "MON-001", "b": "FLR-001", "expect": "touching", "value_mm": 0},
             {"a": "MON-001", "b": "FWG-001", "expect": "touching", "value_mm": 0},
             {"a": "RWG-001", "b": "FLR-001", "expect": "gap", "value_mm": 50},
             {"a": "ENG-001", "b": "MON-001", "expect": "touching", "value_mm": 0},
             {"a": "ENG-001", "b": "FLR-001", "expect": "touching", "value_mm": 0},
             {"a": "HAL-001", "b": "MON-001", "expect": "touching", "value_mm": 0}]
    for s in "LR":
        mates += [{"a": f"SUF-{s}", "b": "MON-001", "expect": "overlap", "value_mm": 5},
                  {"a": f"SUF-{s}", "b": f"WHL-F{s}", "expect": "touching", "value_mm": 0},
                  {"a": f"SUR-{s}", "b": "ENG-001", "expect": "touching", "value_mm": 0},
                  {"a": f"SUR-{s}", "b": f"WHL-R{s}", "expect": "touching", "value_mm": 0},
                  {"a": f"SDP-{s}", "b": "MON-001", "expect": "touching", "value_mm": 0},
                  {"a": f"MIR-{s}", "b": "MON-001", "expect": "touching", "value_mm": 0},
                  {"a": f"MIR-{s}", "b": "HAL-001", "expect": "clear", "value_mm": 20}]
    return {"question": None, "parts": parts, "mates": mates, "assumptions": ["Concept proportions only"]}


def envelopes(plan):
    return {p["id"]: (p["envelope_min"], p["envelope_max"]) for p in plan["parts"]}


def snippets(kit):
    return {k["id"]: [s.as_dict() for s in retrieve(k["id"])] for k in kit}


# ---------------------------------------------------------------- ids and kit
@pytest.mark.parametrize("pid", ["WHL-FL", "SUF-L", "MIR-R", "ENG-001", "HAL-001", "MON-001"])
def test_side_suffixed_and_numbered_ids_are_valid_part_ids(pid):
    lo, hi = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    assert PartSpec(id=pid, name=pid, role="", dims={"a": 1.0}, position_mm=lo, envelope_min=lo, envelope_max=hi).id


@pytest.mark.parametrize("pid", ["WHL-FLX", "SU-L", "WHL-1", "mon-001", "MON-01"])
def test_malformed_ids_are_rejected(pid):
    with pytest.raises(ValueError):
        PartSpec(id=pid, name=pid, role="", dims={"a": 1.0}, position_mm=(0, 0, 0), envelope_min=(0, 0, 0),
                 envelope_max=(1, 1, 1))


def test_kit_is_the_core_four_plus_catalog_parts_the_brief_names():
    assert kit_for_brief("A Mini F1.") == MINI_F1_KIT
    kit = kit_for_brief("Mini F1 with HAL-001, WHL-FL and WHL-FR; no LOW-DF trick, no XYZ-L part.")
    assert [k["id"] for k in kit] == [k["id"] for k in MINI_F1_KIT] + ["WHL-FL", "WHL-FR", "HAL-001"]
    assert [k["id"] for k in kit_for_brief(BRIEF18)] == ALL_IDS and len(ALL_IDS) == 18


def test_gate_accepts_an_18_part_plan_with_clear_and_overlap_mates():
    kit = kit_for_brief(BRIEF18)
    specs, mates, problems, notes = gate_plan(PlanResponse.model_validate(plan18()), kit, set(), snippets(kit))
    assert problems == [] and len(specs) == 18 and len(mates) == 20
    assert {m["expect"] for m in mates} == {"touching", "overlap", "gap", "clear"}
    assert not [n for n in notes if "dropped mate" in n]


def test_gate_still_requires_exactly_the_kit():
    kit = kit_for_brief(BRIEF18)
    plan = plan18()
    plan["parts"] = [p for p in plan["parts"] if p["id"] != "MIR-R"]
    problems = gate_plan(PlanResponse.model_validate(plan), kit, set(), snippets(kit))[2]
    assert any("parts must be exactly" in p for p in problems)


def test_wheels_are_exempt_from_the_vehicle_width_rule():
    assert "C2.3.1" not in {s.article for s in retrieve("WHL-FL")}
    assert retrieve("SDP-L")[0].article == "C2.3.1"


def test_assembly_clause_accepts_side_suffixed_ids():
    ids = ["MON-001", "SUF-L", "SUF-R"]
    assert parse_assembly("SUF-L move=0,10,0; SUF-R thinner LOW-DF links", ids) == [
        ("pose", "SUF-L", "move", (0.0, 10.0, 0.0)), ("revise", "SUF-R", "SUF-R thinner LOW-DF links")]
    with pytest.raises(Rejected):
        parse_assembly("SUF-L and SUF-R wider", ids)


# ---------------------------------------------------------------- mate semantics
def _meas(gap, vol=0.0, depth=0.0):
    return {"pairs": [{"a": "HAL-001", "b": "MIR-L", "min_distance_mm": gap, "overlap_mm3": vol,
                       "overlap_depth_mm": depth}]}


@pytest.mark.parametrize("gap,vol,depth,ok", [(25.0, 0, 0, True), (20.0, 0, 0, True), (19.0, 0, 0, False),
                                              (0.0, 0, 0, False), (0.0, 500.0, 2.0, False)])
def test_clear_mate_needs_the_minimum_clearance(gap, vol, depth, ok):
    m = [{"a": "MIR-L", "b": "HAL-001", "expect": "clear", "value_mm": 20}]
    r = mate_results(m, _meas(gap, vol, depth))[0]
    assert (r.status == Status.VERIFIED) is ok and r.title == "MIR-L / HAL-001 clear >= 20 mm"


@pytest.mark.parametrize("gap,vol,depth,ok", [(0.0, 900.0, 4.0, True), (0.0, 0, 0, True), (0.0, 900.0, 6.0, False),
                                              (3.0, 0, 0, False)])
def test_overlap_mate_is_a_shallow_embedding_up_to_its_depth(gap, vol, depth, ok):
    m = [{"a": "MIR-L", "b": "HAL-001", "expect": "overlap", "value_mm": 5}]
    assert (mate_results(m, _meas(gap, vol, depth))[0].status == Status.VERIFIED) is ok


def test_skipped_far_pairs_are_neither_mates_nor_overlaps():
    meas = {"pairs": [{"a": "WHL-RL", "b": "FWG-001", "skipped": "bounding boxes apart", "bbox_gap_mm": 2500.0}]}
    assert mate_results([], meas) == []
    r = mate_results([{"a": "WHL-RL", "b": "FWG-001", "expect": "gap", "value_mm": 9}], meas)[0]
    assert r.status == Status.NOT_VERIFIED


def test_clear_mate_plan_check_only_notes_and_has_no_mate_face():
    m = {"a": "A", "b": "B", "expect": "clear", "value_mm": 20}
    assert planned_mate_problem(m, ((0, 0, 0), (10, 10, 10)), ((40, 0, 0), (50, 10, 10)), 0.5) == (None, None)
    problem, note = planned_mate_problem(m, ((0, 0, 0), (10, 10, 10)), ((5, 0, 0), (50, 10, 10)), 0.5)
    assert problem is None and "minimum distance decides" in note
    specs = {p["id"]: PartSpec.model_validate(p) for p in plan18()["parts"] if p["id"] in ("MIR-L", "HAL-001")}
    assert mate_face_checks([dict(m, a="MIR-L", b="HAL-001")], specs, {}) == []


def test_keep_clear_pairs_are_measured_but_not_jointed():
    joints, pairs = mate_pairs(plan18()["mates"])
    assert ("MIR-L", "HAL-001") in pairs and ("MIR-L", "HAL-001") not in joints and len(pairs) == 20
    script = assembly_script("t", "mf1", ALL_IDS, joints, pairs)
    compile(script, "assembly", "exec")
    cfg = decode_part_cfg(script)
    assert cfg["near_mm"] == 10.0 and len(cfg["pairs"]) == 20 and len(cfg["joints"]) == 18


# ---------------------------------------------------------------- full run + budget
def _setup(tmp_path, plan, n_bodies, geometric=True):
    store = ProjectStore("mini_f1", root=tmp_path)
    fake = FakePartFusion(envelopes=envelopes(plan), geometric_mates=geometric)
    reasoner = ScriptedReasoner({"plan": [plan], "part": [{"body": MINI_BOX_BODY}] * n_bodies})
    return store, fake, Orchestrator(store, fusion=fake, reasoner_factory=lambda run: reasoner)


def test_18_part_run_fits_the_budget_and_measures_only_near_pairs(tmp_path):
    store, fake, orch = _setup(tmp_path, plan18(), 18)
    run = orch.advance(create_design_run(store, BRIEF18))
    d = run.data
    assert d["status"] == "DONE", (d["error"], d["events"][-3:])
    assert [k["id"] for k in d["kit"]] == ALL_IDS
    assert d["counters"]["script_calls"] == 18 + 1 + 3 and d["counters"]["claude_calls"] == 19
    pairs = d["assembly"]["measured"]["pairs"]
    measured = [p for p in pairs if not p.get("skipped")]
    assert len(pairs) == 153 and 20 <= len(measured) <= 40
    res = {r["check_id"]: r for r in d["assembly"]["results"]}
    mates = [r for r in res.values() if r["check_id"].startswith("MATE-")]
    assert len(mates) == 20 and all(r["status"] == "VERIFIED" for r in mates), \
        [(r["check_id"], r["message"]) for r in mates if r["status"] != "VERIFIED"]
    assert not [r for r in res if r.startswith("OVERLAP-")]
    assert not [f for f in d["parts"]["WHL-FL"]["fia"] if f["article"] == "C2.3.1"]       # wheels excepted


def test_budget_restarts_when_a_blocked_run_is_resumed(tmp_path, monkeypatch):
    monkeypatch.setenv("FAST_SCRIPT_CALL_BUDGET", "4")
    from tests.helpers import mini_f1_plan
    store, fake, orch = _setup(tmp_path, mini_f1_plan(), 4, geometric=False)
    run = orch.advance(create_design_run(store, "A Mini F1."))
    assert run["status"] == "BLOCKED_FUSION" and "budget" in run["error"] and len(fake.scripts) == 4
    run = orch.advance(load_design_run(store, run.id))                    # Continue after a Fusion restart
    assert run["status"] == "DONE", run["error"]
    assert run["counters"]["script_calls"] == 8 and run["counters"]["budget_base"] == 4
    assert any("budget restarts" in e["msg"] for e in run["events"])
