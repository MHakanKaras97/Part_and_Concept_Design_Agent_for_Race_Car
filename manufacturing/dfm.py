"""Basic manufacturability (DFM) checks driven by rule data.

A component generator provides named quantities (wall_thickness, internal_corner_radius, ...);
every applicable rule whose constraint.quantity is provided gets evaluated. Rules whose quantity
the generator cannot provide are reported as NOT_VERIFIED ("not checked"), never silently skipped.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from fia_rules.rules import RuleSet, evaluate
from vehicle.models import ValidationResult

MATERIALS_FILE = Path(__file__).resolve().parent / "materials.yaml"


class Material(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    density_kg_m3: float
    yield_strength_mpa: float
    processes: list[str]
    fusion_material: str | None = None
    source: str
    verification_status: str


def load_materials(path: Path = MATERIALS_FILE) -> dict[str, Material]:
    return {m["id"]: Material.model_validate(m) for m in yaml.safe_load(path.read_text(encoding="utf-8"))}


def run_dfm(rules: RuleSet, component_type: str, process: str, quantities: dict[str, Any],
            assumed_quantities: set[str] | None = None) -> list[ValidationResult]:
    assumed_quantities = assumed_quantities or set()
    results = []
    for rule in rules.applicable(component_type, process):
        if not rule.category.startswith("manufacturing"):
            continue
        q = rule.constraint.quantity
        results.append(evaluate(rule, quantities.get(q), inputs_assumed=q in assumed_quantities,
                                category="MANUFACTURING", method="PARAMETER_CHECK"))
    return results
