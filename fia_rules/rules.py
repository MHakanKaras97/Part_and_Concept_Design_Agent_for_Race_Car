"""Rule layer: structured, source-cited rules (FIA regulations, project DFM rules, standards).

Rules are data (YAML). Checkers are code. Two statuses are kept apart:
  * rule.verification_status   - is the *transcription* of the rule human-verified?
  * ValidationResult.status    - did a *design* pass the rule? (see vehicle.models.check_status)
A design result can only be VERIFIED when the rule itself is VERIFIED.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from vehicle.models import Severity, Status, ValidationResult, check_status

REPO_ROOT = Path(__file__).resolve().parent.parent
RULE_DIRS = [REPO_ROOT / "fia_rules" / "rules", REPO_ROOT / "manufacturing" / "rules"]


class RuleSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: str
    issue: Optional[str] = None
    date: Optional[str] = None
    article: Optional[str] = None       # article / section number in the source
    page: Optional[int] = None
    file: Optional[str] = None          # repo-relative path of the stored source
    sha256: Optional[str] = None
    url: Optional[str] = None


class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["min", "max", "range", "table_match", "info"]
    quantity: str                       # name of the measured/derived quantity a checker provides
    value: Optional[float] = None       # min / max limit, or lower bound for range
    value_max: Optional[float] = None   # upper bound for range
    unit: Optional[str] = None
    table: Optional[dict[str, float]] = None
    tolerance: Optional[float] = None

    @model_validator(mode="after")
    def _complete(self):
        if self.type in ("min", "max") and self.value is None:
            raise ValueError(f"{self.type} constraint needs value")
        if self.type == "range" and (self.value is None or self.value_max is None):
            raise ValueError("range constraint needs value and value_max")
        if self.type == "table_match" and not self.table:
            raise ValueError("table_match constraint needs table")
        return self


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    authority: Literal["REGULATION", "STANDARD", "PROJECT_RULE", "GUIDELINE"]
    category: str
    requirement_text: str               # verbatim quotation of the source where possible
    applies_to: list[str]               # component types, process names, or "vehicle"
    process: Optional[str] = None       # manufacturing process the rule is for (DFM rules)
    constraint: Constraint
    severity: Severity = Severity.BLOCKING
    validation_method: str              # PARAMETER_CHECK | FUSION_MEASUREMENT | MANUAL | ...
    source: RuleSource
    regulation_version: Optional[str] = None
    verification_status: Literal["VERIFIED", "NOT_VERIFIED"] = "NOT_VERIFIED"
    verified_by: Optional[str] = None
    verified_on: Optional[str] = None
    notes: str = ""

    @property
    def is_verified(self) -> bool:
        return self.verification_status == "VERIFIED"


class RuleSet:
    def __init__(self, rules: list[Rule], files: dict[str, Path] | None = None):
        ids = [r.id for r in rules]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate rule ids: {sorted(dupes)}")
        self.rules = {r.id: r for r in rules}
        self._files = files or {}

    @classmethod
    def load(cls, dirs: list[Path] | None = None) -> "RuleSet":
        rules: list[Rule] = []
        files: dict[str, Path] = {}
        for d in dirs or RULE_DIRS:
            for f in sorted(Path(d).glob("*.yaml")):
                for raw in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
                    r = Rule.model_validate(raw)
                    rules.append(r)
                    files[r.id] = f
        return cls(rules, files)

    def get(self, rule_id: str) -> Rule:
        return self.rules[rule_id]

    def applicable(self, component_type: str, process: str | None = None) -> list[Rule]:
        out = []
        for r in self.rules.values():
            if component_type not in r.applies_to and "any_component" not in r.applies_to:
                continue
            if r.process and r.process != process:
                continue
            out.append(r)
        return out

    def mark_verified(self, rule_id: str, by: str) -> Rule:
        """Record a human review of a rule transcription (writes back to its YAML file)."""
        rule = self.rules[rule_id]
        rule.verification_status = "VERIFIED"
        rule.verified_by = by
        rule.verified_on = date.today().isoformat()
        f = self._files[rule_id]
        same_file = [r for r in self.rules.values() if self._files.get(r.id) == f]
        f.write_text(yaml.safe_dump([r.model_dump(mode="json", exclude_none=True) for r in same_file],
                                    sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
        return rule


def evaluate(rule: Rule, measured: Any, inputs_assumed: bool = False, category: str = "MANUFACTURING",
             method: str = "PARAMETER_CHECK", target: str = "") -> ValidationResult:
    """Evaluate one rule against a measured/derived quantity. measured=None -> NOT_VERIFIED."""
    c = rule.constraint
    scope = "FIA" if category == "FIA" else "MANUFACTURING_RULE"
    claim = (f"Design value of '{c.quantity}' satisfies rule {rule.id} as transcribed "
             f"(transcription {rule.verification_status}).")
    base = dict(check_id=f"{rule.id}{'@' + target if target else ''}", title=rule.title, category=category,
                scope=scope, claim=claim, severity=rule.severity, rule_id=rule.id, unit=c.unit)
    if c.type == "info":
        return ValidationResult(**base, status=Status.NOT_VERIFIED, method="NOT_RUN",
                                message="Informational rule; no automated check.")
    if measured is None:
        return ValidationResult(**base, status=Status.NOT_VERIFIED, method="NOT_RUN",
                                message=f"Quantity '{c.quantity}' not available; rule not checked.")
    if c.type == "table_match":
        # measured: list of {"item": "M6", "value": 6.6}
        tol = c.tolerance if c.tolerance is not None else 1e-6
        bad, unknown = [], []
        for m in measured:
            ref = c.table.get(str(m["item"]))
            if ref is None:
                unknown.append(m["item"])
            elif abs(float(m["value"]) - ref) > tol:
                bad.append(f"{m['item']}: {m['value']} (table {ref})")
        if unknown:
            return ValidationResult(**base, status=Status.NOT_VERIFIED, method=method, measured=measured,
                                    message=f"Items not in rule table: {unknown}")
        passed = not bad
        return ValidationResult(**base, status=check_status(passed, rule.is_verified, inputs_assumed),
                                method=method, measured=measured, limit=c.table,
                                message="; ".join(bad) if bad else "All items match the table.")
    value = float(measured)
    if c.type == "min":
        passed, limit = value >= c.value - 1e-9, f">= {c.value}"
    elif c.type == "max":
        passed, limit = value <= c.value + 1e-9, f"<= {c.value}"
    else:
        passed, limit = c.value - 1e-9 <= value <= c.value_max + 1e-9, f"[{c.value}, {c.value_max}]"
    status = check_status(passed, rule.is_verified, inputs_assumed)
    msg = "" if passed else f"{c.quantity} = {value:g} violates {limit}"
    if passed and not rule.is_verified:
        msg = "Passes; rule transcription not yet human-verified."
    return ValidationResult(**base, status=status, method=method, measured=round(value, 4), limit=limit, message=msg)
