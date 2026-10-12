import hashlib
import re
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from fia_rules.rules import REPO_ROOT, Rule, RuleSet, evaluate
from manufacturing.dfm import load_materials, run_dfm
from vehicle.models import Status


def _rule(**over):
    data = dict(id="T-1", title="t", authority="PROJECT_RULE", category="manufacturing/test",
                requirement_text="x", applies_to=["any_component"],
                constraint={"type": "min", "quantity": "wall_thickness", "value": 2.0, "unit": "mm"},
                validation_method="PARAMETER_CHECK", source={"document": "doc"})
    data.update(over)
    return Rule.model_validate(data)


def test_all_rule_files_load_and_every_rule_has_a_source():
    rs = RuleSet.load()
    assert len(rs.rules) >= 10
    for r in rs.rules.values():
        assert r.source.document
        assert r.verification_status in ("VERIFIED", "NOT_VERIFIED")


@pytest.mark.fia_source
def test_fia_rules_cite_the_stored_regulation_and_hash_matches():
    rs = RuleSet.load()
    fia = [r for r in rs.rules.values() if r.authority == "REGULATION"]
    assert fia
    for r in fia:
        assert r.source.article and r.source.page and r.source.file and r.source.sha256
        pdf = REPO_ROOT / r.source.file
        assert hashlib.sha256(pdf.read_bytes()).hexdigest() == r.source.sha256


def _norm(s: str) -> str:
    s = s.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("−", "-").replace("’", "'")
    s = s.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


@pytest.mark.fia_source
def test_fia_requirement_texts_are_verbatim_from_the_source():
    """Guards against invented regulation text: every quoted FIA requirement must exist in the PDF text."""
    text = _norm((REPO_ROOT / "fia_rules/source/fia_2026_section_c_iss20.txt").read_text(encoding="utf-8"))
    for r in RuleSet.load().rules.values():
        if r.authority != "REGULATION":
            continue
        quote = _norm(r.requirement_text)
        # the info rule quotes a multi-clause definition; check each sentence separately
        for part in [p.strip() for p in re.split(r"(?<=\.)\s+(?=[a-c]\.)", quote) if p.strip()]:
            assert part in text, f"{r.id}: '{part[:80]}' not found in source"


def test_duplicate_rule_ids_rejected():
    with pytest.raises(ValueError):
        RuleSet([_rule(), _rule()])


def test_constraint_requires_values():
    with pytest.raises(ValidationError):
        _rule(constraint={"type": "range", "quantity": "q", "value": 1})


@pytest.mark.parametrize("measured,verified,expected", [
    (2.5, "NOT_VERIFIED", Status.ASSUMPTION),
    (2.5, "VERIFIED", Status.VERIFIED),
    (1.5, "VERIFIED", Status.NON_COMPLIANT),
    (1.5, "NOT_VERIFIED", Status.NON_COMPLIANT),
    (None, "VERIFIED", Status.NOT_VERIFIED),
])
def test_evaluate_min_rule(measured, verified, expected):
    assert evaluate(_rule(verification_status=verified), measured).status == expected


def test_evaluate_range_and_max():
    r = _rule(verification_status="VERIFIED", constraint={"type": "range", "quantity": "q", "value": 1830, "value_max": 2030})
    assert evaluate(r, 1830).status == Status.VERIFIED
    assert evaluate(r, 2031).status == Status.NON_COMPLIANT
    r = _rule(verification_status="VERIFIED", constraint={"type": "max", "quantity": "q", "value": 950})
    assert evaluate(r, 950).status == Status.VERIFIED and evaluate(r, 951).status == Status.NON_COMPLIANT


def test_evaluate_table_match():
    r = _rule(verification_status="VERIFIED",
              constraint={"type": "table_match", "quantity": "clearance_holes", "table": {"M6": 6.6}, "tolerance": 0.01})
    assert evaluate(r, [{"item": "M6", "value": 6.6}]).status == Status.VERIFIED
    assert evaluate(r, [{"item": "M6", "value": 6.0}]).status == Status.NON_COMPLIANT
    assert evaluate(r, [{"item": "M7", "value": 7.0}]).status == Status.NOT_VERIFIED


def test_info_rule_is_never_reported_as_verified():
    r = _rule(verification_status="VERIFIED", constraint={"type": "info", "quantity": "q"})
    assert evaluate(r, 1).status == Status.NOT_VERIFIED


def test_applicability_by_type_and_process():
    rs = RuleSet.load()
    ids = {r.id for r in rs.applicable("l_bracket", "machined")}
    assert "DFM-MACH-WALL-MIN" in ids and "FIA26-C2.3.1" not in ids
    assert "DFM-MACH-WALL-MIN" not in {r.id for r in rs.applicable("l_bracket", "sheet_metal")}
    assert "FIA26-C2.3.3" in {r.id for r in rs.applicable("vehicle")}


def test_mark_verified_writes_back(tmp_path):
    d = tmp_path / "rules"
    d.mkdir()
    shutil.copy(REPO_ROOT / "manufacturing/rules/machined.yaml", d / "machined.yaml")
    rs = RuleSet.load([d])
    rs.mark_verified("DFM-MACH-WALL-MIN", "tester")
    again = RuleSet.load([d]).get("DFM-MACH-WALL-MIN")
    assert again.verification_status == "VERIFIED" and again.verified_by == "tester"
    assert RuleSet.load([d]).get("DFM-MACH-INNER-RADIUS-MIN").verification_status == "NOT_VERIFIED"


def test_run_dfm_reports_unchecked_quantities_as_not_verified():
    rs = RuleSet.load()
    res = {r.rule_id: r for r in run_dfm(rs, "l_bracket", "machined", {"wall_thickness": 1.5})}
    assert res["DFM-MACH-WALL-MIN"].status == Status.NON_COMPLIANT
    assert res["DFM-MACH-INNER-RADIUS-MIN"].status == Status.NOT_VERIFIED


def test_materials_load():
    m = load_materials()
    assert m["AL6061-T6"].yield_strength_mpa > 0 and m["AL6061-T6"].verification_status == "NOT_VERIFIED"
