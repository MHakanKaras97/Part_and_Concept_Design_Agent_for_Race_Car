"""Fast mode P3: design-run orchestrator with a fake Fusion and a scripted Claude."""
import json

import pytest

from agent.design_run import (Orchestrator, create_design_run, load_design_run, record_answer, render_summary)
from agent.fast_prompts import MINI_F1_KIT
from agent.fast_reasoning import ClaudeFastReasoner, ScriptedReasoner
from tests.helpers import MINI_BOX_BODY, FakePartFusion, mini_f1_plan
from vehicle.store import ProjectStore

BRIEF = "Mini F1: slim monocoque, two-element front wing, flat floor with diffuser, rear wing with one flap."
IDS = [k["id"] for k in MINI_F1_KIT]
FAIL_BODY = MINI_BOX_BODY.replace('    part.extrude(', '    x = 1  # FAIL_AT_RUNTIME\n    part.extrude(')


def envelopes(plan=None):
    return {p["id"]: (p["envelope_min"], p["envelope_max"]) for p in (plan or mini_f1_plan())["parts"]}


def setup(tmp_path, responses, fusion=None, plan=None):
    store = ProjectStore("mini_f1", root=tmp_path)
    fake = fusion or FakePartFusion(envelopes=envelopes(plan))
    reasoner = ScriptedReasoner(responses)
    return store, fake, reasoner, Orchestrator(store, fusion=fake, reasoner_factory=lambda run: reasoner)


def bodies(n=4, body=MINI_BOX_BODY):
    return [{"body": body} for _ in range(n)]


def test_a_run_without_the_fia_source_completes_with_no_fia_status(tmp_path, no_fia_source):
    from fia_rules.retrieval import NOT_INSTALLED_NOTE
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()], "part": bodies()})
    run = orch.advance(create_design_run(store, BRIEF))
    d = run.data
    assert d["status"] == "DONE", (d["error"], d["events"][-3:])
    assert d["snippets"] == {i: [] for i in IDS} and d["fia_source_sha256"] is None
    assert any(NOT_INSTALLED_NOTE in e["msg"] for e in d["events"])
    assert all(f["status"] != "VERIFIED" for st in d["parts"].values() for f in st["fia"])
    assert [p.id for p in store.list_parts()] == sorted(IDS)


def test_happy_path_counts_registry_screenshots(tmp_path):
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()], "part": bodies()})
    run = orch.advance(create_design_run(store, BRIEF))
    d = run.data
    assert d["status"] == "DONE" and d["phase"] == "DONE", (d["error"], d["events"][-3:])
    assert d["counters"]["claude_calls"] == 5 and reasoner.calls == 5          # 1 plan + 4 parts
    assert d["counters"]["script_calls"] == 4 + 1 + 3 == len(fake.scripts)       # parts + assembly + cameras
    assert d["counters"]["depth_first"] == 2 and d["counters"]["depth_last"] >= 6
    assert all(st["state"] == "done" and st["version"] == 1 for st in d["parts"].values())
    assert [p.id for p in store.list_parts()] == sorted(IDS) and store.list_components() == []
    assert set(d["screenshots"]) == {"iso", "front", "top"}
    assert all((run.dir / f).exists() for f in d["screenshots"].values())
    assert [r["status"] for r in d["assembly"]["results"]] == ["VERIFIED"] * 3
    assert all(f["status"] == "VERIFIED" for st in d["parts"].values() for f in st["fia"] if f["article"] == "C2.3.1")
    assert all(a["flag"] == "ASSUMPTION" for a in d["plan"]["assumptions"])
    summary = (run.dir / "summary.md").read_text(encoding="utf-8")
    assert "no FIA compliance" in summary and "Claude calls: 5" in summary
    # every built part is a tagged-document script; nothing else was written
    assert {json.loads(json.dumps(fake.built[p]["doc_tag"])) for p in fake.built} == {d["doc_tag"]}


def test_part_prompts_carry_the_spec_not_the_brief_and_share_one_system_prompt(tmp_path):
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()], "part": [{"body": FAIL_BODY}] + bodies(),
                                                   "repair": bodies(1)})
    orch.advance(create_design_run(store, BRIEF))
    part_calls = [c for c in reasoner.log if c["name"].startswith(("part_", "repair_"))]
    assert len({c["system"] for c in part_calls}) == 1
    assert all(BRIEF not in c["user"] for c in part_calls)
    assert BRIEF in reasoner.log[0]["user"] and reasoner.log[0]["name"] == "plan"


def test_runtime_error_is_repaired_with_a_compact_error(tmp_path):
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()], "part": [{"body": FAIL_BODY}] + bodies(3),
                                                   "repair": bodies(1)})
    run = orch.advance(create_design_run(store, BRIEF))
    st = run["parts"]["MON-001"]
    assert run["status"] == "DONE" and st["state"] == "done" and [a["kind"] for a in st["attempts"]] == ["part", "repair"]
    rep = next(c for c in reasoner.log if c["name"] == "repair_MON-001_1")
    failure = json.loads(rep["user"])["failure"]
    assert failure["stage"] == "body" and any("FAIL_AT_RUNTIME" in ln for ln in failure["failing_lines"])
    assert MINI_BOX_BODY.splitlines()[1] not in rep["user"]        # not the whole previous body
    assert run["counters"]["claude_calls"] == 6


def test_part_failing_after_two_repairs_is_failed_and_the_rest_continue(tmp_path):
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()],
                                                   "part": [{"body": FAIL_BODY}] + bodies(3),
                                                   "repair": [{"body": FAIL_BODY}, {"body": FAIL_BODY}]})
    run = orch.advance(create_design_run(store, BRIEF))
    assert run["status"] == "DONE"
    assert run["parts"]["MON-001"]["state"] == "failed" and "after 2 repairs" in run["parts"]["MON-001"]["error"]
    assert [run["parts"][p]["state"] for p in IDS[1:]] == ["done"] * 3
    assert run["counters"]["claude_calls"] == 1 + 4 + 2
    skipped = {(m["a"], m["b"]) for m in run["assembly"]["skipped_mates"]}
    assert ("MON-001", "FLR-001") in skipped and "MON-001" not in [p.id for p in store.list_parts()]
    assert "NOT_VERIFIED (a part was not built)" in (run.dir / "summary.md").read_text(encoding="utf-8")


def test_unsafe_body_never_reaches_fusion_and_is_repaired(tmp_path):
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()],
                                                   "part": [{"body": "import os\ndef build(part):\n    os.remove('x')\n"}]
                                                   + bodies(3), "repair": bodies(1)})
    run = orch.advance(create_design_run(store, BRIEF))
    first = run["parts"]["MON-001"]["attempts"][0]
    assert first["stage"] == "validate" and first["script_calls"] == 0
    assert all("os.remove" not in s for s in fake.scripts)
    assert run["parts"]["MON-001"]["state"] == "done"


def test_one_blocking_question_then_verbatim_answer(tmp_path):
    q = mini_f1_plan(question="Which wheelbase should the car have?")
    again = mini_f1_plan(question="And the track width?")                         # second question is ignored
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [q, again], "part": bodies()})
    run = orch.advance(create_design_run(store, BRIEF))
    assert run["status"] == "AWAITING_USER" and run["question"]["text"].startswith("Which wheelbase")
    assert fake.scripts == []
    record_answer(run, "  3000 mm, keep it simple  ", "test")
    run = orch.advance(load_design_run(store, run.id))
    assert run["status"] == "DONE" and run["answer"]["answer"] == "3000 mm, keep it simple"
    call = next(c for c in reasoner.log if c["name"] == "plan_answered")
    assert json.loads(call["user"])["answer_to_your_question"]["answer"] == "3000 mm, keep it simple"
    assert run["plan"]["ignored_question"] == "And the track width?"
    with pytest.raises(ValueError):
        record_answer(run, "x", "test")


def test_invalid_plan_gets_one_retry_then_fails(tmp_path):
    bad = mini_f1_plan()
    bad["parts"] = bad["parts"][:2]
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [bad, {"parts": "nonsense"}]})
    run = orch.advance(create_design_run(store, BRIEF))
    assert run["status"] == "FAILED" and "plan rejected twice" in run["error"]
    assert [c["name"] for c in reasoner.log] == ["plan", "plan_retry"]
    assert "previous_plan_rejected" in reasoner.log[1]["user"]


def test_output_lost_blocks_with_restart_banner_and_resumes_without_new_claude_calls(tmp_path):
    store = ProjectStore("mini_f1", root=tmp_path)
    plan = mini_f1_plan()
    responses = {"plan": plan, "part": {"body": MINI_BOX_BODY}}
    sent = []

    def runner(cmd, prompt, cwd, timeout):
        name = "plan" if "parts_required" in prompt else "part"
        sent.append(name)
        return 0, json.dumps({"type": "result", "subtype": "success", "structured_output": responses[name],
                              "usage": {}, "modelUsage": {}}), ""

    factory = lambda run: ClaudeFastReasoner(run.dir, runner=runner)              # noqa: E731
    flaky = FakePartFusion(envelopes=envelopes(), lose_output_after=2)
    run = Orchestrator(store, fusion=flaky, reasoner_factory=factory).advance(create_design_run(store, BRIEF))
    assert run["status"] == "BLOCKED_FUSION" and "Restart Fusion" in run["banner"]
    assert [run["parts"][p]["state"] for p in IDS] == ["done", "done", "building", "todo"]
    assert len(sent) == 4                                                        # plan + 3 part scripts asked
    restarted = FakePartFusion(envelopes=envelopes())
    run = Orchestrator(store, fusion=restarted, reasoner_factory=factory).advance(load_design_run(store, run.id))
    assert run["status"] == "DONE", run["error"]
    assert len(sent) == 5                                                        # only RWG-001 was new
    assert len(restarted.scripts) == 2 + 1 + 3                                   # FLR (redo) + RWG + assembly + cameras
    assert run["counters"]["claude_calls"] == 5


def test_script_budget_blocks_the_run(tmp_path, monkeypatch):
    monkeypatch.setenv("FAST_SCRIPT_CALL_BUDGET", "3")
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()], "part": bodies()})
    run = orch.advance(create_design_run(store, BRIEF))
    assert run["status"] == "BLOCKED_FUSION" and "budget" in run["error"] and len(fake.scripts) == 3


def test_brief_referencing_a_registered_part_rebuilds_it_without_claude(tmp_path):
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()], "part": bodies()})
    orch.advance(create_design_run(store, BRIEF))
    moved = mini_f1_plan()
    moved["parts"][1]["position_mm"][0] += 50                                    # FWG-001 moved 50 mm forward
    env = envelopes()
    env["FWG-001"] = ([v + (50 if i == 0 else 0) for i, v in enumerate(env["FWG-001"][0])],
                      [v + (50 if i == 0 else 0) for i, v in enumerate(env["FWG-001"][1])])
    store2, fake2, reasoner2, orch2 = setup(tmp_path, {"plan": [moved], "part": bodies(3)},
                                            fusion=FakePartFusion(envelopes=env))
    run = orch2.advance(create_design_run(store2, "Same car but reuse FWG-001 as it is."))
    assert run["status"] == "DONE"
    assert [c["name"] for c in reasoner2.log] == ["plan", "part_MON-001", "part_FLR-001", "part_RWG-001"]
    st = run["parts"]["FWG-001"]
    assert st["reuse"] and st["state"] == "done" and [a["kind"] for a in st["attempts"]] == ["rebuild"]
    spec = next(p for p in run["plan"]["parts"] if p["id"] == "FWG-001")
    assert spec["position_mm"][0] == 650 and spec["envelope_min"][0] == 650     # envelope shifted with the pose
    assert store.get_part("FWG-001").version == 2                                # spec changed (new position)


def test_rebuild_part_uses_zero_claude_calls(tmp_path):
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()], "part": bodies()})
    run = orch.advance(create_design_run(store, BRIEF))
    before_scripts, before_claude = len(fake.scripts), reasoner.calls
    run = orch.rebuild(run, "RWG-001")
    assert run["status"] == "DONE" and reasoner.calls == before_claude
    assert len(fake.scripts) - before_scripts == 1 + 1 + 3
    assert MINI_BOX_BODY in fake.scripts[before_scripts]
    assert run["parts"]["RWG-001"]["attempts"][-1]["kind"] == "rebuild"
    with pytest.raises(KeyError):
        orch.rebuild(run, "XYZ-001")


def test_summary_renders_from_the_record_only(tmp_path):
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()], "part": bodies()})
    run = orch.advance(create_design_run(store, BRIEF))
    assert render_summary(run.data) == (run.dir / "summary.md").read_text(encoding="utf-8")


def test_visual_review_is_off_by_default_and_one_advisory_call_when_on(tmp_path):
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan(), mini_f1_plan()], "part": bodies(8),
                                                   "visual": [{"issues": ["rear wing floats above the floor"]}]})
    run = orch.advance(create_design_run(store, BRIEF))
    assert all(c["images"] == 0 for c in reasoner.log) and "visual_review_issues" not in run.data
    run = orch.advance(create_design_run(store, BRIEF + " v2", visual_review=True))
    vr = [c for c in reasoner.log if c["name"] == "visual_review"]
    assert len(vr) == 1 and vr[0]["images"] == 1
    assert run["visual_review_issues"] == ["rear wing floats above the floor"]
    assert "Visual review (advisory, AI)" in (run.dir / "summary.md").read_text(encoding="utf-8")


def test_same_slug_in_the_same_second_gets_a_unique_run_id(tmp_path):
    store = ProjectStore("mini_f1", root=tmp_path)
    ids = {create_design_run(store, BRIEF).id for _ in range(3)}
    assert len(ids) == 3


# ---------------------------------------------------------------- assembly rebuild / pose correction
def test_rebuild_assembly_into_a_fresh_design_with_zero_claude_calls(tmp_path):
    from agent.design_run import create_assembly_rebuild
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()], "part": bodies()})
    src = orch.advance(create_design_run(store, BRIEF))
    src_json = (src.dir / "run.json").read_bytes()
    files = {p: p.read_bytes() for p in store.components_dir.glob("*.json")}
    calls, n = reasoner.calls, len(fake.scripts)
    run = orch.advance(create_assembly_rebuild(store, src.id))
    assert run["status"] == "DONE" and run["mode"] == "assembly_rebuild" and run["source_run"] == src.id
    assert reasoner.calls == calls and run["counters"]["claude_calls"] == 0
    assert len(fake.scripts) - n == 4 + 1 + 3 == run["counters"]["script_calls"]
    assert run["doc_tag"] != src["doc_tag"]                                          # a fresh Fusion design
    assert {fake.built[p]["doc_tag"] for p in IDS} == {run["doc_tag"]}
    assert all(MINI_BOX_BODY in s for s in fake.scripts[n:n + 4])
    assert (src.dir / "run.json").read_bytes() == src_json                           # source run untouched
    assert {p: p.read_bytes() for p in store.components_dir.glob("*.json")} == files  # unchanged parts not rewritten
    assert [st["version"] for st in run["parts"].values()] == [1] * 4
    assert [r["status"] for r in run["assembly"]["results"]] == ["VERIFIED"] * 3
    assert set(run["screenshots"]) == {"iso", "front", "top"}


def test_pose_correction_creates_v2_and_keeps_v1_in_history(tmp_path):
    from agent.design_run import create_assembly_rebuild
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()], "part": bodies()})
    src = orch.advance(create_design_run(store, BRIEF))
    v1 = store.get_part("MON-001")
    with pytest.raises(ValueError):
        create_assembly_rebuild(store, src.id, {"MON-001": (-2400, 0, 0)})            # reason required
    with pytest.raises(KeyError):
        create_assembly_rebuild(store, src.id, {"XYZ-001": (0, 0, 0)}, "x")
    run = orch.advance(create_assembly_rebuild(store, src.id, {"MON-001": (-2400, 0, 0)}, "double Z offset"))
    assert run["status"] == "DONE" and reasoner.calls == 5
    v2 = store.get_part("MON-001")
    assert v2.version == 2 and v2.script_body == v1.script_body and v2.pose.position == (-2400.0, 0.0, 0.0)
    assert v2.spec.envelope_min == v1.spec.envelope_min                               # envelope unchanged
    assert "double Z offset" in v2.history[-1].summary and [h.version for h in v2.history] == [1, 2]
    assert store.get_part_version("MON-001", 1) == v1                                 # full v1 record kept
    assert store.get_part("FWG-001").version == 1
    assert "Correction: double Z offset" in (run.dir / "summary.md").read_text(encoding="utf-8")
    run2 = orch.advance(create_assembly_rebuild(store, src.id))                       # uses the latest version
    assert run2["parts"]["MON-001"]["version"] == 2
    spec = next(p for p in run2["plan"]["parts"] if p["id"] == "MON-001")
    assert spec["position_mm"] == [-2400.0, 0.0, 0.0]


def test_rebuild_assembly_skips_parts_that_were_never_registered(tmp_path):
    from agent.design_run import create_assembly_rebuild
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [mini_f1_plan()], "part": [{"body": FAIL_BODY}] + bodies(3),
                                                   "repair": [{"body": FAIL_BODY}] * 2})
    src = orch.advance(create_design_run(store, BRIEF))
    run = orch.advance(create_assembly_rebuild(store, src.id))
    assert list(run["parts"]) == IDS[1:] and any("MON-001: not registered" in e["msg"] for e in run["events"])


def test_inconsistent_plan_is_re_planned_before_any_part_is_built(tmp_path):
    bad = mini_f1_plan()
    bad["parts"][0]["envelope_min"][2] = 60
    store, fake, reasoner, orch = setup(tmp_path, {"plan": [bad, mini_f1_plan()], "part": bodies()})
    run = orch.advance(create_design_run(store, BRIEF))
    assert run["status"] == "DONE" and [c["name"] for c in reasoner.log][:2] == ["plan", "plan_retry"]
    rejected = json.loads(reasoner.log[1]["user"])["previous_plan_rejected"]
    assert "MON-001/FLR-001" in rejected[0] and "30.0 mm apart along Z" in rejected[0]
    assert len(fake.scripts) == 8                                       # nothing built from the bad plan
