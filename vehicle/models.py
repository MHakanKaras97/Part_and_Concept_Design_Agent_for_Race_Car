"""Engineering data model: the persistent records the agent works on.

Everything the agent "knows" about a project, a component or a check lives in
these records (stored as JSON under data/), never only in a conversation.
Units: lengths in mm, angles in degrees, forces in N, mass in kg.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 2   # 2 = MVP 1.1: requirement provenance (quotes), scoped evidence labels

IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------
# Status vocabulary
# --------------------------------------------------------------------------
class Status(str, Enum):
    """Outcome of a check, or verification state of a rule transcription.

    VERIFIED       check ran deterministically and passed, against a human-verified
                   rule (or a pure measurement check), with no assumed inputs.
    ASSUMPTION     check passed, but only under stated assumptions (assumed inputs,
                   or rule transcription not yet human-verified).
    NON_COMPLIANT  check ran and failed.
    NOT_VERIFIED   check could not be performed / rule not yet reviewed.
    NOT_APPLICABLE rule or check does not apply to this item.
    """

    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    NON_COMPLIANT = "NON_COMPLIANT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ASSUMPTION = "ASSUMPTION"


class Severity(str, Enum):
    BLOCKING = "BLOCKING"   # must pass before a component can be registered as CHECKED
    ADVISORY = "ADVISORY"   # reported, does not block


def check_status(passed: bool, rule_verified: bool = True, inputs_assumed: bool = False) -> Status:
    """Single place where a check outcome becomes a status (see Status docstring)."""
    if not passed:
        return Status.NON_COMPLIANT
    if rule_verified and not inputs_assumed:
        return Status.VERIFIED
    return Status.ASSUMPTION


class ParamSource(str, Enum):
    REQUIREMENT = "REQUIREMENT"   # stated by the user
    ASSUMPTION = "ASSUMPTION"     # engineering assumption (must trace to an A-id)
    RULE = "RULE"                 # set by a rule (must trace to a rule id)
    DERIVED = "DERIVED"           # computed from other values
    USER = "USER"                 # answer given by the user to a question
    IMAGE_EVIDENCE = "IMAGE_EVIDENCE"  # read by the AI from a user-supplied image (must trace to an IMAGE requirement)


# --------------------------------------------------------------------------
# Requirements / missing information / assumptions
# --------------------------------------------------------------------------
class Requirement(Record):
    """An engineering requirement AS INTERPRETED BY THE AI from a user source.

    The user's own words are authoritative; this record is the AI's interpretation of them:
      source USER_REQUEST - interpreted from the original request; `quote` = verbatim excerpt of it
      source USER_ANSWER  - interpreted from the user's answer `answer_id`; `quote` = verbatim excerpt
      source DERIVED      - engineering consequence of other records listed in `derived_from`
      source IMAGE        - read by the AI from user-supplied image `attachment_id`; `image_evidence` describes
                            exactly what was read (text, dimension, feature). Extracted evidence, not the user's
                            words and not a user answer.
      source LEGACY_V1    - record written before MVP 1.1 (no verbatim quote); read-only, never accepted
                            from new analyses
    """
    id: str = Field(pattern=r"^R\d{2,3}$")
    key: str                                  # vocabulary key, e.g. "base_fastener"
    text: str                                 # the AI's interpretation
    value: Any = None
    unit: Optional[str] = None
    source: Literal["USER_REQUEST", "USER_ANSWER", "IMAGE", "DERIVED", "LEGACY_V1"]
    quote: Optional[str] = None               # verbatim words of the user supporting this requirement
    answer_id: Optional[str] = None           # M-id of the answer quoted (USER_ANSWER)
    derived_from: list[str] = Field(default_factory=list)
    attachment_id: Optional[str] = None       # IMG-nn the evidence was read from (IMAGE)
    image_evidence: Optional[str] = None      # what the AI read in the image, as seen (IMAGE)
    interpreted_by: Literal["AI"] = "AI"

    @model_validator(mode="after")
    def _provenance(self):
        if self.source in ("USER_REQUEST", "USER_ANSWER") and not (self.quote and self.quote.strip()):
            raise ValueError(f"{self.id}: source {self.source} requires a verbatim quote of the user's words")
        if self.source == "USER_ANSWER" and not self.answer_id:
            raise ValueError(f"{self.id}: source USER_ANSWER requires answer_id")
        if self.source == "IMAGE" and not (self.attachment_id and self.image_evidence and self.image_evidence.strip()):
            raise ValueError(f"{self.id}: source IMAGE requires attachment_id and image_evidence")
        if self.source == "DERIVED" and not self.derived_from:
            raise ValueError(f"{self.id}: source DERIVED requires derived_from")
        return self


class MissingInfo(Record):
    id: str = Field(pattern=r"^M\d{2,3}$")
    key: str
    topic: str
    why_it_matters: str
    criticality: Literal["CRITICAL", "IMPORTANT", "MINOR"]
    resolution: Literal["ASK", "ASSUME"]
    question: Optional[str] = None
    assumption_id: Optional[str] = None
    follows_up: Optional[str] = None          # M-id of an earlier question whose answer was ambiguous

    @model_validator(mode="after")
    def _resolution_fields(self):
        if self.resolution == "ASK" and not self.question:
            raise ValueError(f"{self.id}: resolution ASK requires a question")
        if self.resolution == "ASSUME" and not self.assumption_id:
            raise ValueError(f"{self.id}: resolution ASSUME requires an assumption_id")
        return self


class Assumption(Record):
    id: str = Field(pattern=r"^A\d{2,3}$")
    text: str
    rationale: str
    impact: str = ""
    affects: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Geometry / placement
# --------------------------------------------------------------------------
Vec3 = tuple[float, float, float]


class Pose(Record):
    """Placement of a component's local frame in the vehicle coordinate system (VCS).

    position: origin of the local frame in VCS [mm].
    rotation_deg: (roll, pitch, yaw) about VCS X, Y, Z; applied as R = Rz(yaw)·Ry(pitch)·Rx(roll).
    """

    position: Vec3 = (0.0, 0.0, 0.0)
    rotation_deg: Vec3 = (0.0, 0.0, 0.0)


class Parameter(Record):
    name: str
    value: float
    unit: Literal["mm", "deg", "N", "kg", "count", ""]
    source: ParamSource
    trace: list[str] = Field(default_factory=list)   # R01 / A02 / rule ids / M01
    rationale: str = ""

    @field_validator("name")
    @classmethod
    def _ident(cls, v: str) -> str:
        if not IDENT_RE.match(v):
            raise ValueError(f"parameter name '{v}' must be lower_snake_case")
        return v

    @model_validator(mode="after")
    def _traceable(self):
        if self.source != ParamSource.DERIVED and not self.trace:
            raise ValueError(f"parameter '{self.name}' with source {self.source.value} needs a trace")
        return self


class MountingPoint(Record):
    id: str
    position: Vec3            # local component frame [mm]
    axis: Vec3                # unit vector, local frame
    hole_diameter: float      # [mm]
    fastener: Optional[str] = None


class Interface(Record):
    id: str
    name: str
    type: Literal["BOLTED", "BONDED", "SLIP", "CONTACT", "DATUM"]
    mates_with: Optional[str] = None          # component id or external label ("sensor_box")
    origin: Vec3                              # local frame [mm]
    normal: Vec3                              # outward normal of the mounting face, local frame
    mounting_points: list[MountingPoint] = Field(default_factory=list)
    clearance_min_mm: Optional[float] = None
    # Evidence-specific statuses (never one broad "interface verified"):
    hole_geometry_status: Status = Status.NOT_VERIFIED   # this component's own holes/faces measured in CAD
    mating_status: Status = Status.NOT_VERIFIED          # fit with the mating part (needs that part's geometry)

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data):
        if isinstance(data, dict) and "status" in data:      # MVP 1.0 records had one broad status
            data = dict(data)
            data.setdefault("hole_geometry_status", data.pop("status"))
        return data


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
# What exactly a check result claims. The displayed label is f"{scope}_{status}", e.g.
# HOLE_GEOMETRY_VERIFIED, MATING_INTERFACE_NOT_VERIFIED, STRUCTURAL_ADEQUACY_NOT_VERIFIED, FIA_NOT_APPLICABLE.
Scope = Literal["CAD_BUILD", "GEOMETRY", "PARAMETERS", "PLACEMENT", "HOLE_GEOMETRY", "MATING_INTERFACE",
                "MANUFACTURING_RULE", "STRUCTURAL_CHECK", "STRUCTURAL_ADEQUACY", "FIA"]

_LEGACY_SCOPE = {"PROC-CAD-BUILD": "CAD_BUILD", "GEO-PARAM-SYNC": "PARAMETERS", "IFC-HOLE-PATTERN": "HOLE_GEOMETRY",
                 "STR-PLATE-BENDING": "STRUCTURAL_CHECK", "FIA-APPLICABILITY": "FIA"}


class ValidationResult(Record):
    check_id: str
    title: str
    category: Literal["PROCESS", "GEOMETRY", "INTERFACE", "MANUFACTURING", "STRUCTURAL", "FIA"]
    scope: Scope
    claim: str = ""                     # one sentence: exactly what this result does / does not establish
    status: Status
    severity: Severity = Severity.BLOCKING
    method: Literal["FUSION_MEASUREMENT", "ANALYTIC", "PARAMETER_CHECK", "HAND_CALC", "NOT_RUN"]
    measured: Any = None
    limit: Any = None
    unit: Optional[str] = None
    rule_id: Optional[str] = None
    message: str = ""

    @model_validator(mode="before")
    @classmethod
    def _legacy_scope(cls, data):
        if isinstance(data, dict) and "scope" not in data:
            cid, cat = data.get("check_id", ""), data.get("category")
            scope = _LEGACY_SCOPE.get(cid) or {"GEOMETRY": "GEOMETRY", "MANUFACTURING": "MANUFACTURING_RULE",
                                               "FIA": "FIA", "STRUCTURAL": "STRUCTURAL_CHECK"}.get(cat, "GEOMETRY")
            data = dict(data, scope=scope)
        return data

    @property
    def label(self) -> str:
        return f"{self.scope}_{self.status.value}"

    @property
    def blocking_failure(self) -> bool:
        return self.severity == Severity.BLOCKING and self.status in (Status.NON_COMPLIANT, Status.NOT_VERIFIED)


def blocking_failures(results: list[ValidationResult]) -> list[ValidationResult]:
    return [r for r in results if r.blocking_failure]


# --------------------------------------------------------------------------
# Component / project
# --------------------------------------------------------------------------
class FusionRef(Record):
    document: Optional[str] = None
    component_name: str
    built_at: str
    fusion_version: Optional[str] = None


class RevisionEntry(Record):
    revision: int
    date: str
    run_id: Optional[str] = None
    summary: str


class Manufacturing(Record):
    process: str            # e.g. "machined"
    material: str           # material id from manufacturing/materials.yaml


class Component(Record):
    schema_version: int = SCHEMA_VERSION
    id: str = Field(pattern=r"^[A-Z]{2,5}-\d{3}$")
    name: str
    type: str                                  # e.g. "l_bracket", later "nose", "front_wing"
    revision: int = 1
    lifecycle: Literal["IN_WORK", "CHECKED", "REJECTED", "HUMAN_RELEASED"] = "IN_WORK"
    coordinate_system: str = "VCS"
    pose: Pose = Field(default_factory=Pose)
    generator: dict[str, str]                  # {"id": "l_bracket", "version": "1"}
    parameters: dict[str, Parameter]
    interfaces: list[Interface] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    applicable_rules: list[str] = Field(default_factory=list)
    manufacturing: Manufacturing
    validation: list[ValidationResult] = Field(default_factory=list)
    derived: dict[str, Any] = Field(default_factory=dict)      # mass, volume, bbox (from Fusion)
    fusion_ref: Optional[FusionRef] = None
    source_attachments: list[dict] = Field(default_factory=list)   # user-supplied images (id, run, file, sha256)
    provenance: list[Literal["AI_GENERATED", "RULE_CHECKED", "ASSUMPTION_BASED", "GEOMETRY_VALIDATED",
                             "SIMULATION_VALIDATED", "HUMAN_VERIFIED"]] = Field(default_factory=list)
    history: list[RevisionEntry] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _legacy_v1(cls, data):
        """Schema 1 (MVP 1.0) records had no verbatim quotes: their requirements are read as LEGACY_V1.
        The stored file is not rewritten, and no new verification claim is created."""
        # only records that explicitly say schema 1 are legacy; a newly built component has no key yet
        if isinstance(data, dict) and "schema_version" in data and data["schema_version"] < 2:
            data = dict(data, schema_version=2)
            data["requirements"] = [dict(r, source="LEGACY_V1") if isinstance(r, dict) else r
                                    for r in data.get("requirements", [])]
        return data

    @model_validator(mode="after")
    def _param_keys(self):
        for k, p in self.parameters.items():
            if k != p.name:
                raise ValueError(f"parameter key '{k}' != parameter name '{p.name}'")
        return self

    def param_values(self) -> dict[str, float]:
        return {k: p.value for k, p in self.parameters.items()}


class Project(Record):
    schema_version: int = SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    kind: Literal["bench", "vehicle"] = "bench"
    description: str = ""
    coordinate_system: str = "VCS: +X front, +Y left, +Z up, mm (see docs/architecture.md)"
    regulation: Optional[dict[str, str]] = None
    # prefix of Fusion component/parameter names (Fusion has one namespace per document); "" = no prefix
    fusion_namespace: str = Field(default="", pattern=r"^[a-z0-9]{0,16}$")
    policy: dict[str, Any] = Field(default_factory=lambda: {
        "critical_missing_info_must_be_asked": True,
        "allow_suggested_values_in_questions": False,
        "max_revision_loops": 3,
    })
    created: str = Field(default_factory=now_iso)
