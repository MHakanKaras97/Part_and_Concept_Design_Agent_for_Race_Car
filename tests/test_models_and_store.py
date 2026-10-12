import os

import pytest
from pydantic import ValidationError

from vehicle.models import (Assumption, Component, MissingInfo, Parameter, Severity, Status, ValidationResult,
                            blocking_failures, check_status)
from vehicle.store import ProjectStore


def _component(cid="BRK-001", **over):
    data = dict(id=cid, name="Test", type="l_bracket", generator={"id": "l_bracket", "version": "1"},
                parameters={"bracket_thickness": Parameter(name="bracket_thickness", value=6, unit="mm",
                                                           source="ASSUMPTION", trace=["A01"])},
                manufacturing={"process": "machined", "material": "AL6061-T6"})
    data.update(over)
    return Component(**data)


# ---------------- status handling ----------------
@pytest.mark.parametrize("passed,verified,assumed,expected", [
    (True, True, False, Status.VERIFIED),
    (True, False, False, Status.ASSUMPTION),
    (True, True, True, Status.ASSUMPTION),
    (False, True, False, Status.NON_COMPLIANT),
    (False, False, True, Status.NON_COMPLIANT),
])
def test_check_status_combinations(passed, verified, assumed, expected):
    assert check_status(passed, verified, assumed) == expected


def test_blocking_failures_includes_unverified_blocking_but_not_advisory():
    mk = lambda cid, st, sev: ValidationResult(check_id=cid, title=cid, category="GEOMETRY", status=st,
                                               severity=sev, method="ANALYTIC")
    results = [mk("a", Status.NON_COMPLIANT, Severity.BLOCKING), mk("b", Status.NOT_VERIFIED, Severity.BLOCKING),
               mk("c", Status.NON_COMPLIANT, Severity.ADVISORY), mk("d", Status.ASSUMPTION, Severity.BLOCKING)]
    assert [r.check_id for r in blocking_failures(results)] == ["a", "b"]


# ---------------- assumptions / missing info ----------------
def test_missing_info_ask_requires_question_and_assume_requires_assumption():
    with pytest.raises(ValidationError):
        MissingInfo(id="M01", key="load", topic="t", why_it_matters="w", criticality="CRITICAL", resolution="ASK")
    with pytest.raises(ValidationError):
        MissingInfo(id="M01", key="load", topic="t", why_it_matters="w", criticality="MINOR", resolution="ASSUME")
    ok = MissingInfo(id="M01", key="load", topic="t", why_it_matters="w", criticality="MINOR", resolution="ASSUME",
                     assumption_id="A01")
    assert ok.assumption_id == "A01"


def test_assumption_id_format_enforced():
    with pytest.raises(ValidationError):
        Assumption(id="X1", text="t", rationale="r")


# ---------------- component data ----------------
def test_parameter_requires_trace_for_assumption_source_and_snake_case_name():
    with pytest.raises(ValidationError):
        Parameter(name="t", value=1, unit="mm", source="ASSUMPTION")
    with pytest.raises(ValidationError):
        Parameter(name="BracketThickness", value=1, unit="mm", source="DERIVED")
    assert Parameter(name="t_derived", value=1, unit="mm", source="DERIVED").trace == []


def test_component_rejects_bad_id_and_mismatched_parameter_key():
    with pytest.raises(ValidationError):
        _component(cid="bracket-1")
    with pytest.raises(ValidationError):
        _component(parameters={"wrong_key": Parameter(name="bracket_thickness", value=6, unit="mm", source="DERIVED")})


def test_component_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        _component(colour="red")


# ---------------- registration ----------------
def test_register_assigns_revisions_and_history(tmp_path):
    store = ProjectStore("p1", root=tmp_path)
    c1 = store.register(_component(), summary="first", run_id="r1")
    assert c1.revision == 1 and len(c1.history) == 1
    c2 = store.register(_component(revision=99), summary="second", run_id="r2")
    assert c2.revision == 2
    assert [h.summary for h in c2.history] == ["first", "second"]
    assert store.get_component("BRK-001").revision == 2


def test_next_component_id_and_listing(tmp_path):
    store = ProjectStore("p1", root=tmp_path)
    assert store.next_component_id("BRK") == "BRK-001"
    store.register(_component("BRK-001"), "a")
    store.register(_component("BRK-002"), "b")
    assert store.next_component_id("BRK") == "BRK-003"
    assert store.next_component_id("NOS") == "NOS-001"
    assert [c.id for c in store.list_components()] == ["BRK-001", "BRK-002"]


def test_get_unknown_component_raises(tmp_path):
    with pytest.raises(KeyError):
        ProjectStore("p1", root=tmp_path).get_component("BRK-404")


def test_atomic_write_leaves_no_temp_files(tmp_path):
    store = ProjectStore("p1", root=tmp_path)
    store.register(_component(), "a")
    assert [f for f in os.listdir(store.components_dir) if f.endswith(".tmp")] == []


def test_register_is_idempotent_for_the_same_run(tmp_path):
    """A run that crashes after registering and is resumed must not create a bogus extra revision."""
    store = ProjectStore("p1", root=tmp_path)
    store.register(_component(), "first", run_id="r1")
    again = store.register(_component(), "first (resumed)", run_id="r1")
    assert again.revision == 1 and len(again.history) == 1
    assert store.register(_component(), "second", run_id="r2").revision == 2


def test_atomic_write_retries_transient_permission_error(tmp_path, monkeypatch):
    import vehicle.store as st
    calls = {"n": 0}
    real = os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("locked by sync client")
        real(src, dst)

    monkeypatch.setattr(st.os, "replace", flaky)
    st.write_json(tmp_path / "x.json", {"a": 1})
    assert (tmp_path / "x.json").read_text(encoding="utf-8").strip().endswith("}") and calls["n"] == 3


# ---------------- MVP 1.1: provenance + legacy records ----------------
def test_user_sourced_requirement_needs_verbatim_quote():
    from vehicle.models import Requirement
    with pytest.raises(ValidationError):
        Requirement(id="R01", key="k", text="t", source="USER_REQUEST")
    with pytest.raises(ValidationError):
        Requirement(id="R01", key="k", text="t", source="USER_ANSWER", quote="q")       # needs answer_id
    with pytest.raises(ValidationError):
        Requirement(id="R01", key="k", text="t", source="DERIVED")                      # needs derived_from
    r = Requirement(id="R01", key="k", text="t", source="USER_ANSWER", quote="q", answer_id="M01")
    assert r.interpreted_by == "AI"


def test_mvp10_component_record_still_loads_with_honest_legacy_labels():
    """BRK-001 was written by MVP 1.0; it must load without being rewritten, and must not gain new claims."""
    from pathlib import Path
    from vehicle.store import read_json
    p = Path(__file__).resolve().parent.parent / "data/prototype_bench/components/BRK-001.json"
    c = Component.model_validate(read_json(p))
    assert {r.source for r in c.requirements} == {"LEGACY_V1"}
    assert '"schema_version": 1' in p.read_text(encoding="utf-8")
    assert all(i.mating_status == Status.NOT_VERIFIED for i in c.interfaces)
    assert any(v.label == "HOLE_GEOMETRY_VERIFIED" for v in c.validation)


def test_new_component_keeps_requirement_provenance():
    """Regression (found in Milestone 1.2): a component built without an explicit schema_version must not be
    treated as a schema-1 legacy record (BRK-002.json was stored with requirements relabelled LEGACY_V1)."""
    from vehicle.models import Requirement
    req = Requirement(id="R01", key="k", text="t", source="USER_REQUEST", quote="q")
    c = _component(requirements=[req])
    assert c.requirements[0].source == "USER_REQUEST" and c.schema_version == 2
    again = Component.model_validate(c.model_dump(mode="json"))
    assert again.requirements[0].source == "USER_REQUEST"


def test_new_projects_get_a_fusion_namespace_existing_project_keeps_none(tmp_path):
    from agent.workflow import ensure_bench_project
    assert ensure_bench_project(ProjectStore("ui_e2e_test", root=tmp_path)).fusion_namespace == "uie2etest"
    assert ProjectStore("prototype_bench").load_project().fusion_namespace == ""
