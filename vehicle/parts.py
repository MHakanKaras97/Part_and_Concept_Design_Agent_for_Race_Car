"""Free-form part records (fast mode): the parts library.

A part = a spec (key dimensions, pose, envelope, FIA refs) + the exact body script Claude wrote + what Fusion
measured. Stored next to the strict Component records as data/<project>/components/<ID>.json with
record_type "part"; ProjectStore.list_components() returns only strict Component records.
Rebuilding a part needs only this record (zero Claude calls).
"""
from __future__ import annotations

import hashlib
from typing import Literal, Optional

from pydantic import Field

from vehicle.models import Pose, Record, ValidationResult, now_iso

# PRE-NNN (MON-001) or a side / corner suffix for left-right and per-corner parts (SUF-L, WHL-FR)
PART_ID_PATTERN = r"[A-Z]{3}-(?:\d{3}|[A-Z]{1,2})"
PART_ID_RE = rf"^{PART_ID_PATTERN}$"
DIM_NAME_RE = r"^[a-z][a-z0-9_]{0,30}$"

# Script coordinate frame (docs/fusion_script_contract.md). part_local: the script builds in the part frame and the
# pose alone places the part (every new script). legacy_world: a record written before that contract whose script
# uses VCS coordinates with an identity pose (MON-001 v2) - an explicit compatibility exception, never generated.
FrameMode = Literal["part_local", "legacy_world"]

# Left/right derived parts (vehicle/mirror.py): mirror = the source's script built, mirrored about the component's
# local XZ plane (y -> -y) and placed with the mirrored pose; yaw180 = the source's script unchanged, pose Y negated
# and turned 180 deg about the part's local Z (rotationally symmetric wheels: the hub boss stays inboard).
MirrorMode = Literal["mirror", "yaw180"]


class PartSpec(Record):
    """One part of a plan. Lengths mm, VCS (+X front, +Y left, +Z up); pose R = Rz(yaw)·Ry(pitch)·Rx(roll)."""
    id: str = Field(pattern=PART_ID_RE)
    name: str = Field(min_length=1, max_length=60)
    role: str = Field(max_length=200)
    notes: str = Field(default="", max_length=600)       # design intent from the brief, for the part writer
    dims: dict[str, float]                               # key dimensions (mm) -> Fusion user parameters
    position_mm: tuple[float, float, float]
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    envelope_min: tuple[float, float, float]             # expected world bbox (VCS, mm)
    envelope_max: tuple[float, float, float]
    fia_refs_used: list[str] = Field(default_factory=list)
    reuse: bool = False                                  # rebuild the registered part instead of redesigning it
    mirror_of: Optional[str] = None                      # derived part: its source part id (zero Claude calls)
    mirror_mode: Optional[MirrorMode] = None

    @property
    def pose(self) -> Pose:
        return Pose(position=self.position_mm, rotation_deg=self.rotation_deg)

    def local_envelope(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """The world envelope expressed in the part frame (axis-aligned box around its 8 corners)."""
        from vehicle.transforms import invert, pose_to_matrix, transform_point
        inv = invert(pose_to_matrix(self.pose))
        pts = [transform_point(inv, (x, y, z)) for x in (self.envelope_min[0], self.envelope_max[0])
               for y in (self.envelope_min[1], self.envelope_max[1]) for z in (self.envelope_min[2], self.envelope_max[2])]
        lo = tuple(round(min(p[i] for p in pts), 3) + 0.0 for i in range(3))
        hi = tuple(round(max(p[i] for p in pts), 3) + 0.0 for i in range(3))
        return lo, hi  # type: ignore[return-value]


class FiaRef(Record):
    article: str
    text: str                                            # verbatim snippet of the stored regulation text
    page: Optional[int] = None
    sha256: str                                          # of the snippet text
    status: Literal["VERIFIED", "NOT_VERIFIED", "NON_COMPLIANT"] = "NOT_VERIFIED"
    note: str = ""


class PartHistory(Record):
    version: int
    date: str
    run_id: Optional[str] = None
    script_sha256: str
    summary: str
    kind: str = ""                                       # revise | neighbour_pose | pose | revert ('' = build/rebuild)
    instruction: str = ""                                # the user's revision instruction, verbatim


class PartRecord(Record):
    record_type: Literal["part"] = "part"
    id: str = Field(pattern=PART_ID_RE)
    name: str
    role: str = ""
    version: int = 1
    lifecycle: Literal["CONCEPT"] = "CONCEPT"            # concept geometry: no structural / FIA compliance claim
    frame_mode: FrameMode = "part_local"
    frame_note: str = ""
    spec: PartSpec
    script_body: str
    script_sha256: str
    params: dict[str, float] = Field(default_factory=dict)   # measured user parameters (mm)
    pose: Pose
    bbox_world: Optional[list[list[float]]] = None
    checks: list[ValidationResult] = Field(default_factory=list)
    fia: list[FiaRef] = Field(default_factory=list)
    fusion: dict = Field(default_factory=dict)           # document, component, fusion_version, built_at
    run_id: Optional[str] = None
    history: list[PartHistory] = Field(default_factory=list)
    # how this version was made by a revision / revert (agent/revise.py): instruction, change summary, assumptions,
    # neighbour pose changes, mate states, frame validation; empty for built / rebuilt versions
    revision: dict = Field(default_factory=dict)
    # derived part (vehicle/mirror.py): source_id, source_version, mode, note; empty for designed parts
    derived: dict = Field(default_factory=dict)
    # exact Fusion measurement for derived-part verification: volume_mm3, solids, lumps, bbox_local, bbox_world
    geometry: dict = Field(default_factory=dict)


def script_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def same_design(a: PartSpec, b: PartSpec) -> bool:
    """Specs describe the same part version; `reuse` is how a run obtained it, not part of the design."""
    return a.model_copy(update={"reuse": False}) == b.model_copy(update={"reuse": False})


def next_version(previous: Optional[PartRecord], new: PartRecord, run_id: Optional[str], summary: str,
                 force_new: bool = False, kind: str = "", instruction: str = "") -> PartRecord:
    """Same script + spec as the stored version -> same version (checks refreshed); otherwise version + 1.
    force_new: always version + 1 (an audited operation such as a revert, even to identical content)."""
    new = new.model_copy(deep=True)
    entry = lambda v: PartHistory(version=v, date=now_iso(), run_id=run_id, script_sha256=new.script_sha256,  # noqa: E731
                                  summary=summary, kind=kind, instruction=instruction)
    if previous is None:
        new.version, new.history = 1, [entry(1)]
    elif not force_new and previous.script_sha256 == new.script_sha256 and same_design(previous.spec, new.spec):
        new.version, new.history = previous.version, previous.history
    else:
        new.version = previous.version + 1
        new.history = previous.history + [entry(new.version)]
    return new
