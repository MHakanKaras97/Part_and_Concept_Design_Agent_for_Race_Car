"""Workflow gates and state handling, with a scripted reasoner and a fake (perfect) CAD system."""
import json
from pathlib import Path

import pytest

from agent.reasoning import FileExchangeBackend
from agent.workflow import Engine, create_run, load_run, record_answer
from fusion.client import ScriptResult
from fusion.inspect import GeometryReport
from tests.helpers import (LOAD_QUESTION, REQUEST, FakeFusion, ScriptedBackend, analysis_response,
                           plan_response)
from vehicle.store import ProjectStore, write_json

ACCEPT = {"decision": "ACCEPT", "rationale": "all blocking checks pass"}


def _engine(tmp_path, responses, fusion=None):
    store = ProjectStore("bench", root=tmp_path)
    backend = ScriptedBackend(responses)
    eng = Engine(store, backend_factory=lambda run: backend, fusion=fusion or FakeFusion())
    return store, eng, backend


def test_full_run_registers_component_with_traceable_record(tmp_path):
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [plan_response()], "review": [ACCEPT]})
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "COMPLETED", run["events"]
    comp = store.get_component("BRK-001")
    assert comp.lifecycle == "CHECKED" and comp.revision == 1
    assert comp.parameters["bracket_thickness"].trace == ["A01"]
    assert {i.id for i in comp.interfaces} == {"IF-BASE", "IF-UPRIGHT"}
    assert all(i.hole_geometry_status.value == "VERIFIED" and i.mating_status.value == "NOT_VERIFIED" for i in comp.interfaces)
    assert "ASSUMPTION_BASED" in comp.provenance
    report = (run.dir / "report.md").read_text(encoding="utf-8")
    assert "No statement of FIA compliance" in report and "A01" in report
    assert "FIA compliant" not in report.replace("No statement of FIA compliance", "")


def test_run_waits_for_reasoning_and_resumes(tmp_path):
    store, eng, backend = _engine(tmp_path, {})
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "AWAITING_REASONING" and run["stage"] == "ANALYSIS"
    backend.responses = {"analysis": [analysis_response()], "plan": [plan_response()], "review": [ACCEPT]}
    run = eng.advance(load_run(store, run.id))
    assert run["status"] == "COMPLETED"


def test_critical_missing_info_cannot_be_assumed(tmp_path):
    store, eng, backend = _engine(tmp_path, {"analysis": [analysis_response(critical_assumed=True)]})
    run = eng.advance(create_run(store, REQUEST))
    assert run["stage"] == "ANALYSIS" and run["status"] == "AWAITING_REASONING"
    assert any("CRITICAL" in e for e in run["feedback"]["errors"])
    assert backend.tasks[-1].context["feedback"]["rejected"] == "analysis"


def test_required_info_must_be_covered(tmp_path):
    a = analysis_response()
    a["missing_information"] = []
    a["assumptions"] = []
    store, eng, _ = _engine(tmp_path, {"analysis": [a]})
    run = eng.advance(create_run(store, REQUEST))
    assert any("'load'" in e for e in run["feedback"]["errors"])


ANSWER = "The box weighs 2 kg and sees up to 5 g of vibration."


def test_critical_question_goes_to_user_then_continues(tmp_path):
    a2 = analysis_response(load_answer="weighs 2 kg and sees up to 5 g")
    store, eng, backend = _engine(tmp_path, {"analysis": [analysis_response(ask_load=True), a2],
                                             "plan": [plan_response()], "review": [ACCEPT]})
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "AWAITING_USER" and run["questions"][0]["question"] == LOAD_QUESTION
    record_answer(run, "M01", ANSWER, entered_via="test")
    run = eng.advance(run)
    assert run["status"] == "COMPLETED", run["events"]
    # the reasoner receives the user's verbatim answer, with the question it answers
    got = backend.tasks[1].context["user_answers"]["M01"]
    assert got["answer"] == ANSWER and got["question"] == LOAD_QUESTION
    # the interpretation is stored as an AI interpretation that quotes the answer
    r07 = next(r for r in run["analysis"]["requirements"] if r["id"] == "R07")
    assert r07["source"] == "USER_ANSWER" and r07["answer_id"] == "M01" and r07["interpreted_by"] == "AI"
    report = (run.dir / "report.md").read_text(encoding="utf-8")
    assert ANSWER in report and "Customer answers (verbatim, authoritative)" in report


def test_answer_recording_rules(tmp_path):
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response(ask_load=True)]})
    run = eng.advance(create_run(store, REQUEST))
    with pytest.raises(ValueError):
        record_answer(run, "M09", "x", "test")            # not an open question
    with pytest.raises(ValueError):
        record_answer(run, "M01", "   ", "test")          # empty
    record_answer(run, "M01", ANSWER, "test")
    assert run["user_answers"]["M01"]["answer"] == ANSWER
    with pytest.raises(ValueError):
        record_answer(run, "M01", "changed my mind", "test")   # never overwritten


def _first_errors(tmp_path, analysis):
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis]})
    run = eng.advance(create_run(store, REQUEST))
    assert run["stage"] == "ANALYSIS", run["events"]
    return run["feedback"]["errors"]


def test_leading_question_with_suggested_values_rejected(tmp_path):
    a = analysis_response(ask_load=True)
    a["missing_information"][0]["question"] = "Should the sensor use 2 x M5 bolts 40 mm apart with CoM 40 mm?"
    errors = _first_errors(tmp_path, a)
    assert any("introduces numeric values not given by the user" in e for e in errors)


def test_question_with_example_marker_rejected(tmp_path):
    a = analysis_response(ask_load=True)
    a["missing_information"][0]["question"] = "What is the load (for example the box mass)?"
    assert any("suggestion marker" in e for e in _first_errors(tmp_path, a))


def test_question_may_repeat_numbers_the_user_wrote(tmp_path):
    a = analysis_response(ask_load=True)
    a["missing_information"][0]["question"] = "Which load acts on the M5 bolted upright?"
    store, eng, _ = _engine(tmp_path, {"analysis": [a]})
    assert eng.advance(create_run(store, REQUEST))["status"] == "AWAITING_USER"


def test_quote_must_be_verbatim_from_request(tmp_path):
    a = analysis_response()
    a["requirements"][0]["quote"] = "a bracket for a camera"
    assert any("not a verbatim excerpt" in e for e in _first_errors(tmp_path, a))


def test_invented_number_in_interpretation_rejected(tmp_path):
    a = analysis_response()
    a["requirements"][3]["text"] = "Four M6 bolts on a 40 mm pitch"      # request says only 'base bolted with M6'
    errors = _first_errors(tmp_path, a)
    assert any("R04: numbers" in e and "40" in e and "4" in e for e in errors)


def test_requirement_cannot_cite_an_answer_that_does_not_exist(tmp_path):
    a = analysis_response()
    a["requirements"].append({"id": "R09", "key": "load", "text": "2 kg", "source": "USER_ANSWER",
                              "answer_id": "M05", "quote": "2 kg"})
    assert any("M05 has no user answer" in e for e in _first_errors(tmp_path, a))


def test_ambiguous_answer_triggers_follow_up_question(tmp_path):
    follow = analysis_response(ask_load=True)
    follow["missing_information"].append(
        {"id": "M02", "key": "load_direction", "topic": "Load direction", "why_it_matters": "bending vs shear",
         "criticality": "CRITICAL", "resolution": "ASK", "follows_up": "M01",
         "question": "You mentioned vibration: in which direction does it act relative to the upright leg?"})
    final = analysis_response(load_answer="weighs 2 kg and sees up to 5 g")
    final["requirements"].append({"id": "R08", "key": "load_direction", "text": "Vibration acts normal to the upright",
                                  "source": "USER_ANSWER", "answer_id": "M02", "quote": "normal to the upright"})
    store, eng, backend = _engine(tmp_path, {"analysis": [analysis_response(ask_load=True), follow, final],
                                             "plan": [plan_response()], "review": [ACCEPT]})
    run = eng.advance(create_run(store, REQUEST))
    record_answer(run, "M01", ANSWER, "test")
    run = eng.advance(run)
    assert run["status"] == "AWAITING_USER" and [q["id"] for q in run["questions"]] == ["M02"]
    record_answer(run, "M02", "Mostly normal to the upright face.", "test")
    run = eng.advance(run)
    assert run["status"] == "COMPLETED", run["events"]
    assert set(run["asked"]) == {"M01", "M02"} and run["asked"]["M02"]["follows_up"] == "M01"


def test_answer_that_is_neither_used_nor_followed_up_is_rejected(tmp_path):
    ignored = analysis_response()            # load assumed, M01 answer ignored
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response(ask_load=True), ignored]})
    run = eng.advance(create_run(store, REQUEST))
    record_answer(run, "M01", ANSWER, "test")
    run = eng.advance(run)
    assert any("M01 is neither interpreted" in e for e in run["feedback"]["errors"])


def test_evidence_labels_are_specific(tmp_path):
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [plan_response()], "review": [ACCEPT]})
    run = eng.advance(create_run(store, REQUEST))
    comp = store.get_component("BRK-001")
    labels = {v.label for v in comp.validation}
    assert {"HOLE_GEOMETRY_VERIFIED", "MATING_INTERFACE_NOT_VERIFIED", "STRUCTURAL_CHECK_ASSUMPTION",
            "STRUCTURAL_ADEQUACY_NOT_VERIFIED", "FIA_NOT_APPLICABLE"} <= labels
    assert not any(l.startswith("INTERFACE_") for l in labels)
    for i in comp.interfaces:
        assert i.hole_geometry_status.value == "VERIFIED" and i.mating_status.value == "NOT_VERIFIED"
    assert "MATING_INTERFACE_NOT_VERIFIED" in (run.dir / "report.md").read_text(encoding="utf-8")


def test_infeasible_plan_loops_back_with_feedback(tmp_path):
    store, eng, backend = _engine(tmp_path, {"analysis": [analysis_response()],
                                             "plan": [plan_response(base_hole_x0=8), plan_response()],
                                             "review": [ACCEPT]})
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "COMPLETED" and run["loops"] == 1
    assert run["iterations"][0]["reason"] == "plan_gate"
    assert any("cuts into the bend" in e for e in backend.tasks[2].context["feedback"]["errors"])


def test_dfm_violation_caught_before_cad(tmp_path):
    fusion = FakeFusion()
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response()],
                                       "plan": [plan_response(bracket_thickness=1.5, bend_inner_radius=4)]}, fusion)
    run = eng.advance(create_run(store, REQUEST))
    assert run["stage"] == "PLAN" and fusion.built == {}
    assert any("DFM-MACH-WALL-MIN" in e for e in run["feedback"]["errors"])


def test_accept_refused_when_blocking_failures(tmp_path):
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [plan_response()],
                                       "review": [ACCEPT]}, FakeFusion(volume_scale=1.05))
    run = eng.advance(create_run(store, REQUEST))
    assert run["stage"] == "REVIEW" and run["status"] == "AWAITING_REASONING"
    assert "ACCEPT refused" in run["feedback"]["errors"][0]
    assert store.list_components() == []


def test_revise_changes_parameters_and_rebuilds(tmp_path):
    revise = {"decision": "REVISE", "rationale": "thicker",
              "parameter_changes": {"bracket_thickness": {"value": 8, "unit": "mm", "source": "ASSUMPTION",
                                                          "trace": ["A01"], "rationale": "stiffer"}}}
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [plan_response()],
                                       "review": [revise, ACCEPT]})
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "COMPLETED"
    assert run["iterations"][0]["changes"]["bracket_thickness"] == {"from": 6, "to": 8}
    assert store.get_component("BRK-001").parameters["bracket_thickness"].value == 8


def test_cad_failure_goes_to_review_and_registers_nothing(tmp_path):
    stop = {"decision": "STOP", "rationale": "cannot build"}
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [plan_response()], "review": [stop]},
                            FakeFusion(fail_build=True))
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "STOPPED" and run["cad"]["ok"] is False
    assert store.list_components() == []
    assert "No component registered" in (run.dir / "report.md").read_text(encoding="utf-8")


def test_fusion_unavailable_blocks_without_losing_state(tmp_path):
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [plan_response()],
                                       "review": [ACCEPT]}, FakeFusion(unavailable=True))
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "BLOCKED_FUSION" and run["stage"] == "CAD"
    eng.fusion = FakeFusion()
    run = eng.advance(load_run(store, run.id))
    assert run["status"] == "COMPLETED"


def test_loop_limit_stops_run(tmp_path):
    bad = plan_response(base_hole_x0=8)
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [bad] * 5})
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "STOPPED" and "loop limit" in run["stop_reason"]


def test_file_exchange_backend_round_trip(tmp_path):
    store = ProjectStore("bench", root=tmp_path)
    eng = Engine(store, fusion=FakeFusion())
    run = eng.advance(create_run(store, REQUEST))
    req = run.dir / run["pending"]["request"]
    assert req.exists() and "Response JSON schema" in req.read_text(encoding="utf-8")
    write_json(req.with_name(req.name.replace(".request.md", ".response.json")), analysis_response())
    run = eng.advance(load_run(store, run.id))
    assert run["stage"] == "PLAN" and run["status"] == "AWAITING_REASONING"


@pytest.mark.parametrize("lose_at", ["cad", "inspect"])
def test_lost_fusion_output_blocks_instead_of_continuing(tmp_path, lose_at):
    """A build/inspection that 'succeeds' without a result (degraded MCP output channel) must not be treated as built."""
    fusion = FakeFusion(lose_output=(lose_at == "cad"))
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [plan_response()],
                                       "review": [ACCEPT]}, fusion)
    if lose_at == "inspect":
        real = fusion.run_script
        fusion.run_script = lambda script, read_only=False: (ScriptResult("", None) if read_only
                                                             else real(script, read_only))
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "BLOCKED_FUSION"
    assert run["stage"] == ("CAD" if lose_at == "cad" else "INSPECT")
    assert "geometry" not in run.data or run.data.get("geometry") is None
    assert store.list_components() == []
    if lose_at == "cad":
        eng.fusion = FakeFusion()               # channel restored (Fusion/add-in restarted); the build is re-run
    else:
        del fusion.run_script                   # channel restored; the part built before is still in Fusion
    run = eng.advance(load_run(store, run.id))
    assert run["status"] == "COMPLETED"


@pytest.mark.parametrize("inspect_version", ["test", "test-2"])
def test_geometry_report_records_both_fusion_builds(tmp_path, inspect_version):
    """The geometry report records the Fusion build that inspected the model and the one that built it; a change
    between the two (Fusion auto-updated, e.g. 2705.1.11 -> 2705.1.30) is logged and flagged in the report."""
    store, eng, _ = _engine(tmp_path, {"analysis": [analysis_response()], "plan": [plan_response()],
                                       "review": [ACCEPT]}, FakeFusion(inspect_version=inspect_version))
    run = eng.advance(create_run(store, REQUEST))
    assert run["status"] == "COMPLETED"
    geo = json.loads((run.dir / "geometry_report.json").read_text(encoding="utf-8"))
    assert geo["fusion_version"] == inspect_version and geo["build_fusion_version"] == "test"
    report = (run.dir / "report.md").read_text(encoding="utf-8")
    assert f"Fusion build: inspected with {inspect_version}, built with test" in report
    changed = inspect_version != "test"
    assert ("WARNING: different Fusion builds" in report) is changed
    assert any("Fusion build changed between CAD build" in e["message"] for e in run["events"]) is changed


@pytest.mark.parametrize("path", sorted((Path(__file__).resolve().parents[1] / "data").glob("*/runs/*/geometry_report.json")),
                         ids=lambda f: f.parent.name[:15])
def test_historical_geometry_reports_still_validate(path):
    raw = path.read_bytes()
    rep = GeometryReport.model_validate_json(raw)
    # build_fusion_version exists only in reports written after it was added (e.g. f1_parts 20261010-105534)
    assert rep.fusion_version and (rep.build_fusion_version is None or rep.build_fusion_version.startswith("2705."))
    assert path.read_bytes() == raw
