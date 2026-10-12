"""Fast-mode revision (agent/revise.py): v+1 on success, rollback on failure, gates, neighbour pose adjustment,
assembly clauses, revert, CLI - with the fake Fusion (geometry from the parameters) and a scripted Claude."""
import json

import pytest

from agent import __main__ as cli
from agent.design_run import Orchestrator, create_assembly_rebuild, create_design_run, load_design_run
from agent.fast_prompts import revise_system
from agent.fast_reasoning import ScriptedReasoner
from agent.revise import Reviser, parse_assembly, Rejected
from tests.helpers import MINI_BOX_BODY, FakePartFusion, mini_f1_plan
from vehicle.store import ProjectStore, read_json, write_json

FAIL = MINI_BOX_BODY + "    x = 1  # FAIL_AT_RUNTIME\n"


def built(tmp_path, fake=None):
    """A finished Mini F1 run (fake geometry = the planned boxes) + a reviser on the same fake."""
    store = ProjectStore("mini_f1", root=tmp_path)
    fake = fake or FakePartFusion(from_params=True, geometric_mates=True)
    r0 = ScriptedReasoner({"plan": [mini_f1_plan()], "part": [{"body": MINI_BOX_BODY}] * 4})
    run = Orchestrator(store, fusion=fake, reasoner_factory=lambda r: r0).advance(create_design_run(store, "Mini F1"))
    assert run["status"] == "DONE" and all(r["status"] == "VERIFIED" for r in run["assembly"]["results"]), run["error"]
    return store, fake, run


def reviser(store, fake, responses):
    rs = ScriptedReasoner(responses)
    return Reviser(store, fusion=fake, reasoner_factory=lambda d: rs), rs


def resp(body=MINI_BOX_BODY, summary="changed", **delta):
    return {"spec_delta": delta, "body": body, "change_summary": summary, "assumptions": [],
            "neighbour_adjustments": []}


NARROW = dict(dims={"width": 1700.0}, envelope_min=[600.0, -850.0, 60.0], envelope_max=[1000.0, 850.0, 300.0])


# ---------------------------------------------------------------- success, history
def test_successful_revision_creates_v2_and_keeps_v1(tmp_path):
    store, fake, run = built(tmp_path)
    v1_file = store.components_dir / "FWG-001.json"
    v1_bytes = v1_file.read_bytes()
    rv, rs = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "    # narrower\n", "span 1800 -> 1700 mm",
                                                   **NARROW)]})
    n0 = len(fake.scripts)
    rev = rv.revise(run, "FWG-001", "Make the front wing span 1700 mm.")
    assert rev["state"] == "DONE", (rev["error"], rev["events"][-4:])
    c = rev["counters"]
    assert c["claude_calls"] == 1 and rs.calls == 1
    assert c["script_calls"] == len(fake.scripts) - n0 == 1 + 1 + 1 + 3 <= 10     # probe, build, mates, iso/front/top
    assert c["depth_first"] is not None and c["depth_last"] >= c["depth_first"]
    rec = store.get_part("FWG-001")
    assert rec.version == 2 and rec.spec.dims["width"] == 1700.0 and rec.bbox_world[0][1] == -850.0
    assert rec.history[-1].kind == "revise" and rec.history[-1].instruction == "Make the front wing span 1700 mm."
    assert rec.revision["change_summary"] == "span 1800 -> 1700 mm" and rec.revision["base_version"] == 1
    assert rec.revision["frame_validation"]["status"] == "VERIFIED" and rec.revision["mates"]
    assert store.part_history_path("FWG-001", 1).read_bytes() == v1_bytes             # full v1 kept verbatim
    assert [store.get_part(p).version for p in ("MON-001", "FLR-001", "RWG-001")] == [1, 1, 1]
    step = rev["steps"][0]
    assert step["bbox_delta"] == {"min": [0.0, 50.0, 0.0], "max": [0.0, -50.0, 0.0]}
    assert [m["status"] for m in rev["mates_after"]] == ["VERIFIED"] and rev["mates_after"][0]["before"] == "VERIFIED"
    d = load_design_run(store, run.id)
    assert d["parts"]["FWG-001"]["version"] == 2 and d["revisions"][0]["state"] == "DONE"
    rdir = run.dir / "revisions" / "R01"
    assert set(rev["screenshots"]["after"]) == {"iso", "front", "top"} == set(rev["screenshots"]["before"])
    assert all((run.dir / f).exists() for f in rev["screenshots"]["after"].values())
    assert (rdir / "snapshot.json").exists() and not (rdir / "diagnostic.json").exists()
    assert "## Revisions" in (run.dir / "summary.md").read_text(encoding="utf-8")
    # a second revision: v3; the v1 and v2 history snapshots stay byte-identical
    v2_bytes = v1_file.read_bytes()
    rv2, _ = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "    # lower\n", "height 240 -> 230 mm",
                                                   dims={"height": 230.0}, envelope_min=[600.0, -850.0, 60.0],
                                                   envelope_max=[1000.0, 850.0, 290.0])]})
    rev2 = rv2.revise(load_design_run(store, run.id), "FWG-001", "Make the wing 10 mm lower.")
    assert rev2["state"] == "DONE" and store.get_part("FWG-001").version == 3
    assert store.part_history_path("FWG-001", 1).read_bytes() == v1_bytes
    assert store.part_history_path("FWG-001", 2).read_bytes() == v2_bytes


def test_revision_only_carries_the_relevant_context(tmp_path):
    store, fake, run = built(tmp_path)
    rv, rs = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "    # n\n", "narrower", **NARROW)]})
    rv.revise(run, "FWG-001", "Make the front wing span 1700 mm.")
    call = rs.log[0]
    assert call["name"] == "revise_FWG-001" and call["system"] == revise_system() and call["images"] == 0
    u = json.loads(call["user"])
    assert set(u) == {"task", "instruction", "part", "current_script", "measured", "neighbours", "planned_mates", "fia"}
    assert u["instruction"] == "Make the front wing span 1700 mm." and u["current_script"] == MINI_BOX_BODY
    assert [n["id"] for n in u["neighbours"]] == ["MON-001"]                          # mated neighbours only
    assert all("FWG-001" in (m["a"], m["b"]) for m in u["planned_mates"])
    assert "Mini F1" not in call["user"] and "RWG-001" not in call["user"]            # no brief, no unrelated parts
    assert [f["article"] for f in u["fia"]] == ["C2.3.1"] and u["part"]["frame_mode"] == "part_local"


# ---------------------------------------------------------------- failure -> rollback
def test_failed_revision_restores_the_old_part_and_registers_nothing(tmp_path):
    store, fake, run = built(tmp_path)
    files = {p: p.read_bytes() for p in store.components_dir.rglob("*.json")}
    old_cfg = fake.built["FWG-001"]
    rv, rs = reviser(store, fake, {"revise": [resp(FAIL, "narrower", **NARROW)],
                                   "repair": [{"body": FAIL}, {"body": FAIL}]})
    rev = rv.revise(run, "FWG-001", "Make the front wing span 1700 mm.")
    assert rev["state"] == "FAILED" and "after 2 repairs" in rev["error"]
    assert rev["counters"]["claude_calls"] == 3 == rs.calls                          # 1 + 2 repairs, no more
    assert rev["counters"]["script_calls"] == 1 + 3 + 1 + 1 <= 10                    # probe, 3 builds, restore, mates
    assert rev["rollback"]["verified"] and rev["rollback"]["parts"] == [
        {"part_id": "FWG-001", "restored_version": 1, "passed": True, "error": None}]
    assert all(m["status"] == "VERIFIED" for m in rev["rollback"]["mates"])
    assert fake.built["FWG-001"]["params"] == old_cfg["params"]                       # the old part is back in Fusion
    assert {p: p.read_bytes() for p in store.components_dir.rglob("*.json")} == files  # registry untouched
    assert load_design_run(store, run.id)["parts"]["FWG-001"]["version"] == 1
    diag = read_json(run.dir / "revisions" / "R01" / "diagnostic.json")
    assert diag["state"] == "FAILED" and len(diag["steps"][0]["attempts"]) == 3
    assert (run.dir / "revisions" / "R01" / "parts" / "FWG-001" / "attempt_3.py").exists()


def test_repair_then_success_counts_two_calls(tmp_path):
    store, fake, run = built(tmp_path)
    rv, rs = reviser(store, fake, {"revise": [resp(FAIL, "narrower", **NARROW)],
                                   "repair": [{"body": MINI_BOX_BODY + "    # fixed\n"}]})
    rev = rv.revise(run, "FWG-001", "Make the front wing span 1700 mm.")
    assert rev["state"] == "DONE" and rev["counters"]["claude_calls"] == 2
    rep = next(c for c in rs.log if c["name"] == "repair_FWG-001_1")
    assert rep["system"] == rs.log[0]["system"]                                        # one static prefix
    u = json.loads(rep["user"])
    assert u["failure"]["stage"] == "body" and u["part"]["instruction"].startswith("Make the front wing")
    assert store.get_part("FWG-001").script_body == MINI_BOX_BODY + "    # fixed\n"


def test_broken_mate_after_build_rolls_back(tmp_path):
    """Envelope says touching, the built geometry does not reach: the measured mate fails -> restore."""
    store, fake, run = built(tmp_path)
    rv, rs = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "    # SHORT_NOSE\n", "flap tweak",
                                                    dims={"height": 230.0}, envelope_min=[600.0, -900.0, 60.0],
                                                    envelope_max=[1000.0, 900.0, 290.0])]})
    rev = rv.revise(run, "FWG-001", "Tiny flap tweak.")
    assert rev["state"] == "FAILED" and "mate broken" in rev["error"] and "MON-001 / FWG-001 touching" in rev["error"]
    assert rs.calls == 1                                       # a broken mate is not sent to Claude: rollback
    assert rev["rollback"]["verified"] and store.get_part("FWG-001").version == 1
    assert [m["status"] for m in rev["rollback"]["mates"]] == ["VERIFIED"]


def test_rollback_failure_is_critical(tmp_path):
    from tests.helpers import decode_part_cfg

    class Broken(FakePartFusion):
        broken = False

        def run_script(self, script, read_only=False, expect_result=True):
            if "BODY START" in script and decode_part_cfg(script).get("part_id") == "FWG-001" and self.broken:
                self.fail_next["FWG-001"] = "    y = 2  # FAIL_AT_RUNTIME"
            return super().run_script(script, read_only, expect_result)
    store, fake, run = built(tmp_path, Broken(from_params=True, geometric_mates=True))
    fake.broken = True                                         # from now on every FWG-001 build fails, also the restore
    rv, _ = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "    # n\n", "narrower", **NARROW)]})
    rev = rv.revise(run, "FWG-001", "Make the front wing span 1700 mm.")
    assert rev["state"] == "CRITICAL" and "ROLLBACK FAILED" in rev["error"] and "NOT restored" in rev["error"]
    assert load_design_run(store, run.id)["banner"].startswith("Revision R01")
    assert store.get_part("FWG-001").version == 1                                      # nothing registered


def test_fusion_lost_mid_revision_is_critical_and_registry_unchanged(tmp_path):
    store, fake, run = built(tmp_path)
    fake.lose_output_after = len(fake.scripts) + 1                                     # probe ok, build lost
    rv, _ = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "    # n\n", "narrower", **NARROW)]})
    rev = rv.revise(run, "FWG-001", "Make the front wing span 1700 mm.")
    assert rev["state"] == "CRITICAL" and store.get_part("FWG-001").version == 1     # the build may have run
    assert "registry is unchanged" in rev["error"] and "NOT verified restored" in rev["error"]


# ---------------------------------------------------------------- deterministic gates
@pytest.mark.parametrize("response,needle", [
    ({"body": MINI_BOX_BODY}, "malformed revision output"),
    (resp(summary="two\nlines", **NARROW), "one non-empty line"),
    (dict(resp(**NARROW), neighbour_adjustments=[{"part_id": "XYZ-009", "position_mm": [0, 0, 0], "reason": "r"}]),
     "out-of-scope"),
    (resp(), "changes nothing"),
    (resp(dims={"Bad Name": 1.0}), "lower_snake"),
    (resp(dims={"width": 2000.0}, envelope_min=[600.0, -1000.0, 60.0], envelope_max=[1000.0, 1000.0, 300.0]),
     "violates C2.3.1"),
    (resp(MINI_BOX_BODY + "# m\n", envelope_min=[650.0, -900.0, 800.0], envelope_max=[1050.0, 900.0, 1040.0],
          position_mm=[650.0, 0.0, 800.0]), "no unambiguous neighbour adjustment"),
])
def test_rejections_touch_nothing_and_cost_no_repair(tmp_path, response, needle):
    store, fake, run = built(tmp_path)
    files = {p: p.read_bytes() for p in store.components_dir.rglob("*.json")}
    n0 = len(fake.scripts)
    rv, rs = reviser(store, fake, {"revise": [response]})
    rev = rv.revise(run, "FWG-001", "Change it.")
    assert rev["state"] == "REJECTED" and needle in rev["error"], rev["error"]
    assert rs.calls == 1 and len(fake.scripts) - n0 == 1                               # the probe only
    assert {p: p.read_bytes() for p in store.components_dir.rglob("*.json")} == files


def test_unsafe_body_is_repaired_before_reaching_fusion(tmp_path):
    store, fake, run = built(tmp_path)
    rv, rs = reviser(store, fake, {"revise": [resp("import os\ndef build(part):\n    os.remove('x')\n", "n", **NARROW)],
                                   "repair": [{"body": MINI_BOX_BODY + "    # safe\n"}]})
    rev = rv.revise(run, "FWG-001", "Make the front wing span 1700 mm.")
    assert rev["state"] == "DONE" and rs.calls == 2
    assert rev["steps"][0]["attempts"][0]["stage"] == "validate" and rev["steps"][0]["attempts"][0]["script_calls"] == 0
    assert all("os.remove" not in s for s in fake.scripts)


def test_wrapper_depth_above_100_refuses_before_any_claude_call(tmp_path):
    store, fake, run = built(tmp_path)
    fake.depth = 150
    rv, rs = reviser(store, fake, {"revise": [resp(**NARROW)]})
    rev = rv.revise(run, "FWG-001", "Make the front wing span 1700 mm.")
    assert rev["state"] == "REJECTED" and "depth is 151" in rev["error"] and rs.calls == 0


def test_closed_document_refuses_before_any_claude_call(tmp_path):
    store, fake, run = built(tmp_path)
    fake.close_document(run["doc_tag"])
    rv, rs = reviser(store, fake, {"revise": [resp(**NARROW)]})
    rev = rv.revise(run, "FWG-001", "Make the front wing span 1700 mm.")
    assert rev["state"] == "REJECTED" and "Rebuild assembly" in rev["error"] and rs.calls == 0


def test_run_holding_a_stale_version_is_rejected(tmp_path):
    store, fake, run = built(tmp_path)
    rb = Orchestrator(store, fusion=fake).advance(create_assembly_rebuild(store, run.id))
    rv, _ = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "# n\n", "n", **NARROW)]})
    assert rv.revise(rb, "FWG-001", "Make the front wing span 1700 mm.")["state"] == "DONE"
    rv2, rs2 = reviser(store, fake, {"revise": [resp(**NARROW)]})
    rev = rv2.revise(load_design_run(store, run.id), "MON-001", "Anything.")
    assert rev["state"] == "REJECTED" and "FWG-001 v1 (active v2)" in rev["error"] and rs2.calls == 0


# ---------------------------------------------------------------- neighbour pose adjustment
def test_minimum_neighbour_pose_adjustment_is_a_separate_version(tmp_path):
    store, fake, run = built(tmp_path)
    shorter = resp(MINI_BOX_BODY + "    # shorter nose\n", "nose 50 mm shorter", dims={"length": 2950.0},
                   envelope_min=[-2400.0, -400.0, 30.0], envelope_max=[550.0, 400.0, 730.0])
    shorter["neighbour_adjustments"] = [{"part_id": "FWG-001", "position_mm": [550.0, 0.0, 60.0],
                                         "reason": "keep the wing on the nose tip"}]
    rv, rs = reviser(store, fake, {"revise": [shorter]})
    rev = rv.revise(run, "MON-001", "Make the nose 50 mm shorter.")
    assert rev["state"] == "DONE", rev["error"]
    adj = rev["neighbour_adjustments"]
    assert len(adj) == 1 and adj[0]["part_id"] == "FWG-001" and adj[0]["shift_mm"] == [-50.0, 0.0, 0.0]
    assert adj[0]["claude_agrees"] is True and "50.0 mm apart along X" in adj[0]["reason"]
    mon, fwg = store.get_part("MON-001"), store.get_part("FWG-001")
    assert mon.version == 2 and mon.revision["neighbour_pose_changes"][0]["part_id"] == "FWG-001"
    assert fwg.version == 2 and fwg.history[-1].kind == "neighbour_pose" and fwg.script_body == MINI_BOX_BODY
    assert fwg.spec.position_mm == (550.0, 0.0, 60.0) and fwg.spec.envelope_min[0] == 550.0
    assert {m["check_id"]: m["status"] for m in rev["mates_after"]} == {
        "MATE-FLR-001-MON-001": "VERIFIED", "MATE-FWG-001-MON-001": "VERIFIED"}
    assert rs.calls == 1


def test_adjustment_that_would_move_a_legacy_part_is_rejected(tmp_path):
    plan = mini_f1_plan()
    mon = plan["parts"][0]
    mon["position_mm"] = [0, 0, 0]                                                     # legacy: VCS script, identity
    store = ProjectStore("mini_f1", root=tmp_path)
    fake = FakePartFusion(from_params=True, geometric_mates=True,
                          local_bboxes={"MON-001": ([-2400.0, -400.0, 30.0], [600.0, 400.0, 730.0])})
    r0 = ScriptedReasoner({"plan": [plan], "part": [{"body": MINI_BOX_BODY}] * 4})
    run = Orchestrator(store, fusion=fake, reasoner_factory=lambda r: r0).advance(create_design_run(store, "Mini F1"))
    assert run["status"] == "DONE"
    p = store.component_path("MON-001")
    d = read_json(p)
    d["frame_mode"] = "legacy_world"
    write_json(p, d)
    rv, rs = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "# s\n", "shorter mount", dims={"length": 350.0},
                                                   envelope_min=[650.0, -900.0, 60.0], envelope_max=[1000.0, 900.0, 300.0],
                                                   position_mm=[650.0, 0.0, 60.0])]})
    rev = rv.revise(run, "FWG-001", "Shorten the mount by 50 mm at the back.")
    assert rev["state"] == "REJECTED" and "legacy_world" in rev["error"] and "MON-001" in rev["error"]
    rv2, _ = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "# m\n", "move", position_mm=[10.0, 0.0, 0.0])]})
    rev2 = rv2.revise(load_design_run(store, run.id), "MON-001", "Move it 10 mm forward.")
    assert rev2["state"] == "REJECTED" and "pose must stay identity" in rev2["error"]


# ---------------------------------------------------------------- assembly-level
def test_parse_assembly_clauses():
    ids = ["FLR-001", "FWG-001", "MON-001", "RWG-001"]
    assert parse_assembly("RWG-001 move=0,0,20; FWG-001: span 1700 mm", ids) == [
        ("pose", "RWG-001", "move", (0.0, 0.0, 20.0)), ("revise", "FWG-001", "FWG-001: span 1700 mm")]
    assert parse_assembly("MON-001 position = -2400, 0, 25 mm", ids)[0] == ("pose", "MON-001", "position",
                                                                             (-2400.0, 0.0, 25.0))
    for bad in ("make everything lighter", "FWG-001 and RWG-001 wider", "FWG-001 a; FWG-001 b", "XYZ-001 wider"):
        with pytest.raises(Rejected):
            parse_assembly(bad, ids)


def test_assembly_revision_changes_only_the_named_parts_each_its_own_version(tmp_path):
    store, fake, run = built(tmp_path)
    rv, rs = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "# n\n", "span 1700", **NARROW)]})
    rev = rv.revise(run, "assembly", "RWG-001 move=0,0,20; FWG-001: make the span 1700 mm")
    assert rev["state"] == "DONE", rev["error"]
    assert rs.calls == 1 and [s["part_id"] for s in rev["steps"]] == ["RWG-001", "FWG-001"]
    assert store.get_part("RWG-001").version == 2 and store.get_part("RWG-001").history[-1].kind == "pose"
    assert store.get_part("RWG-001").spec.position_mm == (-3900.0, 0.0, 50.0)
    assert store.get_part("FWG-001").version == 2
    assert [store.get_part(p).version for p in ("MON-001", "FLR-001")] == [1, 1]


def test_assembly_revision_failing_late_rolls_back_every_step(tmp_path):
    store, fake, run = built(tmp_path)
    rv, rs = reviser(store, fake, {"revise": [resp(FAIL, "span 1700", **NARROW)], "repair": [{"body": FAIL}] * 2})
    rev = rv.revise(run, "assembly", "RWG-001 move=0,0,20; FWG-001: make the span 1700 mm")
    assert rev["state"] == "FAILED" and rev["rollback"]["verified"]
    assert [p["part_id"] for p in rev["rollback"]["parts"]] == ["FWG-001", "RWG-001"]
    assert store.get_part("RWG-001").version == 1 and store.get_part("FWG-001").version == 1
    assert fake.built["RWG-001"]["matrix_cm"][11] == pytest.approx(3.0)                # back at z = 30 mm


# ---------------------------------------------------------------- revert
def test_revert_writes_a_new_version_and_keeps_history(tmp_path):
    store, fake, run = built(tmp_path)
    rv, _ = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "# n\n", "span 1700", **NARROW)]})
    rv.revise(run, "FWG-001", "Make the front wing span 1700 mm.")
    v1, v2 = store.get_part_version("FWG-001", 1), store.get_part("FWG-001")
    h1 = store.part_history_path("FWG-001", 1).read_bytes()
    rev = Reviser(store, fusion=fake).revert(load_design_run(store, run.id), "FWG-001", 1)
    assert rev["state"] == "DONE" and rev["counters"]["claude_calls"] == 0, rev["error"]
    v3 = store.get_part("FWG-001")
    assert v3.version == 3 and v3.script_body == v1.script_body and v3.spec == v1.spec.model_copy(update={"reuse": False})
    assert v3.history[-1].summary == "reverted to v1" and v3.history[-1].kind == "revert"
    assert [h.version for h in v3.history] == [1, 2, 3]
    assert store.part_history_path("FWG-001", 1).read_bytes() == h1                    # untouched
    assert store.get_part_version("FWG-001", 2) == v2                                  # v2 kept in full
    assert all(m["status"] == "VERIFIED" for m in rev["mates_after"])
    run = load_design_run(store, run.id)
    assert Reviser(store, fusion=fake).revert(run, "FWG-001", 3)["state"] == "REJECTED"   # already active
    assert "not in the registry history" in Reviser(store, fusion=fake).revert(run, "FWG-001", 9)["error"]


# ---------------------------------------------------------------- CLI
def test_cli_revise_and_rebuild_version_parsing(tmp_path, monkeypatch, capsys):
    store, fake, run = built(tmp_path)
    monkeypatch.setattr("vehicle.store.DATA_ROOT", tmp_path)
    seen = {}

    def fake_revise(self, r, target, instruction, entered_via="cli"):
        seen["revise"] = (r.id, target, instruction, entered_via)
        return {"id": "R01", "kind": "revise", "target": target, "state": "DONE", "steps": [], "notes": [],
                "neighbour_adjustments": [], "mates_after": [], "rollback": None, "error": None,
                "counters": {"claude_calls": 1, "script_calls": 6, "depth_first": 9, "depth_last": 14}}

    def fake_revert(self, r, part_id, version, entered_via="cli"):
        seen["revert"] = (r.id, part_id, version)
        return fake_revise(self, r, part_id, f"revert to v{version}")
    monkeypatch.setattr("agent.revise.Reviser.revise", fake_revise)
    monkeypatch.setattr("agent.revise.Reviser.revert", fake_revert)
    assert cli.main(["revise", run.id, "FWG-001", "Make the span 1700 mm"]) == 0
    assert seen["revise"] == (run.id, "FWG-001", "Make the span 1700 mm", "cli: python -m agent revise")
    assert "revision R01 revise FWG-001: DONE  claude_calls=1  script_calls=6  depth=9->14" in capsys.readouterr().out
    assert cli.main(["rebuild", "FWG-001", "--version", "1"]) == 0                     # run found from the registry
    assert seen["revert"] == (run.id, "FWG-001", 1)
    assert cli.main(["rebuild", "FWG-001", "--version", "1", "--run", run.id]) == 0
    assert cli.main(["revise", "20991010-000000-nope", "FWG-001", "x"]) == 2           # unknown run: rejected


def test_claude_call_count_is_per_revision_with_a_shared_reasoner(tmp_path):
    store, fake, run = built(tmp_path)
    rv, rs = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "# n\n", "n", **NARROW), resp(FAIL, "f", **NARROW)],
                                   "repair": [{"body": FAIL}] * 2})
    assert rv.revise(run, "FWG-001", "Make the span 1700 mm.")["counters"]["claude_calls"] == 1
    rev = rv.revise(load_design_run(store, run.id), "FWG-001", "Taller endplates.")
    assert rev["state"] == "FAILED" and rev["counters"]["claude_calls"] == 3 and rs.calls == 4
    assert "_claude0" not in load_design_run(store, run.id)["revisions"][1]


def test_revision_reports_advisory_mate_faces_of_the_changed_part(tmp_path):
    store, fake, run = built(tmp_path)
    rv, _ = reviser(store, fake, {"revise": [resp(MINI_BOX_BODY + "# n\n", "n", **NARROW)]})
    rev = rv.revise(run, "FWG-001", "Make the span 1700 mm.")
    faces = {f["face"]: f["status"] for f in rev["mate_faces"]}
    assert faces == {"MON-001 +X": "PASS", "FWG-001 -X": "PASS"}
