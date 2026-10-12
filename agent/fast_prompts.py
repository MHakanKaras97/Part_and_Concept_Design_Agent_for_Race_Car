"""Fast-mode prompts and response schemas (plan, part, repair) + the deterministic plan gate.

Token rules: static system prompts (identical bytes per kind -> prompt cache), compact JSON inputs, no history,
compact schemas, no prose in responses.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from vehicle.mirror import derive_mates, derive_spec
from vehicle.parts import DIM_NAME_RE, PART_ID_PATTERN, PartSpec

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "docs" / "fusion_script_contract.md"
MAX_ASSUMPTIONS = 8

# The first target: Mini F1. Each kit part: id, name, what it is.
MINI_F1_KIT = [
    {"id": "MON-001", "name": "Monocoque", "role": "survival cell / chassis tub with nose and cockpit opening"},
    {"id": "FWG-001", "name": "Front wing", "role": "front wing: main plane, flap(s), endplates; ahead of the front axle"},
    {"id": "FLR-001", "name": "Floor", "role": "floor plate under the car with rear diffuser ramp"},
    {"id": "RWG-001", "name": "Rear wing", "role": "rear wing: main plane, flap, endplates, central support"},
]

# Optional Mini F1 parts: a run plans one only when the brief names its id (kit_for_brief). Left = +Y, right = -Y.
MINI_F1_OPTIONAL = [
    {"id": "WHL-FL", "name": "Wheel front left", "role": "front-left wheel and tyre on the front axle (X=0), +Y side"},
    {"id": "WHL-FR", "name": "Wheel front right", "role": "front-right wheel and tyre on the front axle (X=0), -Y side"},
    {"id": "WHL-RL", "name": "Wheel rear left", "role": "rear-left wheel and tyre on the rear axle, +Y side"},
    {"id": "WHL-RR", "name": "Wheel rear right", "role": "rear-right wheel and tyre on the rear axle, -Y side"},
    {"id": "SUF-L", "name": "Front suspension left", "role": "front-left suspension links: monocoque to WHL-FL"},
    {"id": "SUF-R", "name": "Front suspension right", "role": "front-right suspension links: monocoque to WHL-FR"},
    {"id": "SUR-L", "name": "Rear suspension left", "role": "rear-left suspension links: car body to WHL-RL"},
    {"id": "SUR-R", "name": "Rear suspension right", "role": "rear-right suspension links: car body to WHL-RR"},
    {"id": "SDP-L", "name": "Sidepod left", "role": "left sidepod bodywork with radiator inlet, beside the monocoque"},
    {"id": "SDP-R", "name": "Sidepod right", "role": "right sidepod bodywork with radiator inlet, beside the monocoque"},
    {"id": "ENG-001", "name": "Engine cover", "role": "power unit / engine cover behind the cockpit, above the floor"},
    {"id": "HAL-001", "name": "Halo", "role": "halo cockpit protection hoop over the cockpit opening"},
    {"id": "MIR-L", "name": "Mirror left", "role": "left rear-view mirror housing on its stalk beside the cockpit"},
    {"id": "MIR-R", "name": "Mirror right", "role": "right rear-view mirror housing on its stalk beside the cockpit"},
]
MINI_F1_CATALOG = MINI_F1_KIT + MINI_F1_OPTIONAL


def kit_for_brief(brief: str) -> list[dict]:
    """The four core parts + every optional catalog part whose id the brief names (catalog order)."""
    named = set(re.findall(rf"\b{PART_ID_PATTERN}\b", brief or ""))
    return MINI_F1_KIT + [k for k in MINI_F1_OPTIONAL if k["id"] in named]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanPart(Strict):
    id: str
    name: str
    role: str = Field(max_length=200)
    notes: str = Field(default="", max_length=600, description="design intent from the brief for the script writer")
    dims: dict[str, float] = Field(default_factory=dict, description="key dimensions in mm, lower_snake names")
    position_mm: Optional[list[float]] = Field(default=None, min_length=3, max_length=3,
                                               description="part frame origin in VCS")
    rotation_deg: list[float] = Field(default=[0.0, 0.0, 0.0], min_length=3, max_length=3,
                                      description="roll, pitch, yaw")
    envelope_min: Optional[list[float]] = Field(default=None, min_length=3, max_length=3,
                                                description="expected world bbox min (VCS)")
    envelope_max: Optional[list[float]] = Field(default=None, min_length=3, max_length=3)
    fia_refs_used: list[str] = Field(default_factory=list, description="article ids from the given snippets only")
    reuse: bool = Field(default=False, description="true only for an id listed under registry")
    mirror_of: Optional[str] = Field(default=None, description="derived right part: the left source part's id")
    mirror_mode: Optional[Literal["mirror", "yaw180"]] = Field(default=None,
                                                               description="mirror: handed parts; yaw180: wheels")


class PlanMate(Strict):
    a: str
    b: str
    expect: Literal["touching", "overlap", "gap", "clear"]
    value_mm: float = Field(default=0.0, ge=0, description="overlap: max depth; gap: max gap; clear: min clearance; "
                                                           "0 for touching")


class PlanResponse(Strict):
    question: Optional[str] = Field(default=None, description="ONLY if critical info is missing; else null")
    parts: list[PlanPart]
    mates: list[PlanMate]
    assumptions: list[str] = Field(max_length=MAX_ASSUMPTIONS)


class PartResponse(Strict):
    body: str = Field(description="python source defining build(part)")


class VisualReviewResponse(Strict):
    issues: list[str] = Field(max_length=8, description="visible geometry problems; empty if none")


VISUAL_SYSTEM = ("You look at a screenshot of a concept CAD assembly (iso view; +X front, +Z up) and list visible "
                 "geometry problems only: parts floating apart, intersecting, missing, wildly out of proportion. "
                 "No praise, no compliance statements. Output ONLY the structured JSON.")


def schema(model: type[BaseModel]) -> dict:
    return model.model_json_schema()


# ---------------------------------------------------------------------------------------------- system prompts
PLAN_SYSTEM = """You plan a concept-level Formula 1 style assembly that a CAD script writer will build part by part
in Autodesk Fusion. Output ONLY the structured JSON.

Coordinate system (VCS, project convention): +X front, +Y left, +Z up, millimetres. Origin: X=0 on the
front-axle centreline (so the front wing is at X>0 and the rest of the car at X<0), Y=0 on the plane of symmetry,
Z=0 on the reference plane (bottom of the floor). Pose: position of the part frame origin + rotation (roll,
pitch, yaw) deg, R = Rz*Ry*Rx; use rotation [0,0,0] unless a part truly needs another orientation.

Rules:
- Return exactly the parts listed under "parts_required" (same ids). Give each part 3-8 key dimensions (mm,
  lower_snake names, e.g. length, width, height, span, chord); they become Fusion user parameters.
- envelope_min/max: the axis-aligned VCS box the part must lie in. It must contain the whole part, match its key
  dimensions and its position, and be tight (no more than ~10 mm slack per side).
- The parts must form one coherent car: the floor under the monocoque, the front wing ahead of the nose tip area,
  the rear wing above and behind the rear of the floor. mates: list the contacts you intend (touching, overlap with
  value_mm = max depth, gap with value_mm = max gap). Mated parts' envelopes must meet accordingly. For two parts
  that must NOT touch (e.g. a mirror and the halo), add a mate "clear" with value_mm = minimum clearance.
- Left/right pairs (-L/-R, WHL-FL/FR, WHL-RL/RR) that the brief calls exact mirror images: plan the LEFT part
  (+Y) in full and list the right part with only id, name, role, mirror_of = the left id and mirror_mode =
  "mirror" (handed parts: suspension, sidepods, mirrors) or "yaw180" (wheels only). Its geometry, pose, envelope
  and mates are derived from the left part: list no mates for it except one between the pair itself. A wheel
  source's notes must say: axle along the part-local Y axis through the local origin, rotationally symmetric about
  it, hub boss on the inboard (-Y) side. Other left/right parts: plan both, mirror images about Y=0.
- FIA: only the snippets given for each part may be cited (fia_refs_used = their article ids). Take a dimension
  from a rule only when the rule text gives it unambiguously; otherwise choose a value and state it as an
  assumption. Never claim compliance, structural adequacy or race readiness: this is concept geometry.
- assumptions: at most 8 short strings, each a decision not stated in the brief.
- notes per part: the brief's intent for that part in <= 600 characters (features, counts, shapes). Give any
  coordinates in notes in the PART frame (relative to position_mm), never as VCS values: the script writer
  builds in the part frame and the pose alone places the part.
- registry lists already built parts; set reuse=true only if the brief asks to reuse that id (then keep its dims).
- question: null unless information is missing that makes the design impossible (not merely unspecified -
  unspecified things become assumptions). Never ask more than one question."""


def part_system() -> str:
    """Static prefix for part + repair calls (identical bytes for every call)."""
    return ("You write Fusion 360 Python part scripts. Output ONLY the structured JSON {\"body\": \"<python source>\"}."
            " The body must follow this contract exactly.\n\n" + CONTRACT.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------- user messages
def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def plan_user(brief: str, kit: list[dict], snippets: dict[str, list[dict]], registry: list[dict],
              answer: Optional[dict] = None) -> str:
    msg = {"brief": brief, "parts_required": kit,
           "fia_snippets": {pid: [{"article": s["article"], "title": s["title"], "text": s["text"]} for s in ss]
                            for pid, ss in snippets.items()},
           "registry": registry}
    if answer:
        msg["answer_to_your_question"] = answer          # verbatim user answer; ask nothing further
    return _dump(msg)


def part_payload(spec: PartSpec, snippets: list[dict]) -> dict:
    lo, hi = spec.local_envelope()
    return {"id": spec.id, "name": spec.name, "role": spec.role, "notes": spec.notes, "dims_mm": spec.dims,
            "local_envelope_min": list(lo), "local_envelope_max": list(hi),
            "world_to_local": {"position_mm": list(spec.position_mm), "rotation_deg": list(spec.rotation_deg)},
            "fia": [{"article": s["article"], "text": s["text"]} for s in snippets if s["article"] in spec.fia_refs_used]}


def part_user(spec: PartSpec, snippets: list[dict]) -> str:
    return _dump({"task": "write the body", "part": part_payload(spec, snippets)})


def repair_user(spec: PartSpec, snippets: list[dict], error: dict, attempt: int) -> str:
    return _dump({"task": f"the previous body failed (repair {attempt}); write a complete corrected body",
                  "part": part_payload(spec, snippets), "failure": error})


# ---------------------------------------------------------------------------------------------- plan gate
def gate_plan(plan: PlanResponse, kit: list[dict], registry_ids: set[str],
              snippets: dict[str, list[dict]]) -> tuple[list[PartSpec], list[dict], list[str], list[str]]:
    """Deterministic plan check. Returns (specs, mates, problems, notes). problems = reasons to reject the plan
    (one retry); notes = harmless corrections applied (logged)."""
    problems, notes = [], []
    want = [k["id"] for k in kit]
    got = [p.id for p in plan.parts]
    if sorted(got) != sorted(want):
        problems.append(f"parts must be exactly {want}, got {got}")
    by_id = {p.id: p for p in plan.parts}
    derived = {}                                         # derived id -> source id
    for p in plan.parts:
        if p.id not in want:
            continue
        problem = _mirror_problem(p, by_id)
        if problem:
            problems.append(problem)
        elif p.mirror_of:
            derived[p.id] = p.mirror_of
    specs = []
    for p in plan.parts:
        if p.id not in want or p.mirror_of:
            continue
        if p.position_mm is None or p.envelope_min is None or p.envelope_max is None:
            problems.append(f"{p.id}: position_mm, envelope_min and envelope_max are required (it is not derived)")
            continue
        bad_dims = [k for k, v in p.dims.items() if not re.match(DIM_NAME_RE, k) or not v > 0]
        if bad_dims or not p.dims:
            problems.append(f"{p.id}: dims need lower_snake names and positive mm values ({bad_dims or 'none given'})")
        if any(a >= b for a, b in zip(p.envelope_min, p.envelope_max)):
            problems.append(f"{p.id}: envelope_min must be < envelope_max on every axis")
        allowed = {s["article"] for s in snippets.get(p.id, [])}
        refs = [r for r in p.fia_refs_used if r in allowed]
        if len(refs) != len(p.fia_refs_used):
            notes.append(f"{p.id}: dropped FIA refs not among its snippets: "
                         f"{sorted(set(p.fia_refs_used) - allowed)}")
        reuse = p.reuse and p.id in registry_ids
        if p.reuse and not reuse:
            notes.append(f"{p.id}: reuse requested but the id is not registered; designing it")
        if bad_dims or any(a >= b for a, b in zip(p.envelope_min, p.envelope_max)):
            continue
        specs.append(PartSpec(id=p.id, name=p.name[:60] or p.id, role=p.role, notes=p.notes, dims=p.dims,
                              position_mm=tuple(p.position_mm), rotation_deg=tuple(p.rotation_deg),
                              envelope_min=tuple(p.envelope_min), envelope_max=tuple(p.envelope_max),
                              fia_refs_used=refs, reuse=reuse))
    specs += derived_specs(specs, derived, by_id, snippets, notes)
    mates = []
    for m in plan.mates:
        if m.a not in want or m.b not in want or m.a == m.b:
            notes.append(f"dropped mate {m.a}/{m.b}: unknown or identical parts")
            continue
        mates.append(m.model_dump())
    mates, mate_notes = derive_mates(mates, derived)
    notes += mate_notes
    problems += mate_consistency(specs, mates, notes)
    return specs, mates, problems, notes


def _mirror_problem(p: PlanPart, by_id: dict) -> Optional[str]:
    """A derived part must point at a planned SOURCE part (not itself, not another derived part) of its own kind."""
    if p.mirror_mode and not p.mirror_of:
        return f"{p.id}: mirror_mode without mirror_of"
    if not p.mirror_of:
        return None
    src = by_id.get(p.mirror_of)
    if p.mirror_of == p.id:
        return f"{p.id}: mirror_of points to itself"
    if src is None:
        return f"{p.id}: mirror_of {p.mirror_of} is not a planned part"
    if src.mirror_of:
        return f"{p.id}: mirror_of {p.mirror_of} is itself derived (mirror_of {src.mirror_of}); point at its source"
    if not p.mirror_mode:
        return f"{p.id}: mirror_of needs mirror_mode (mirror | yaw180)"
    if p.id.split("-")[0] != src.id.split("-")[0]:
        return f"{p.id}: mirror_of {src.id} is a different kind of part"
    if p.mirror_mode == "yaw180" and not p.id.startswith("WHL-"):
        return f"{p.id}: yaw180 is for wheels only (rotationally symmetric); use mirror"
    return None


def derived_specs(sources: list[PartSpec], derived: dict[str, str], by_id: dict, snippets: dict,
                  notes: list[str]) -> list[PartSpec]:
    """Specs of derived parts from their (gated) source specs; a derived part of a rejected source is skipped (the
    source's own problem already rejects the plan)."""
    src = {s.id: s for s in sources}
    out = []
    for pid, sid in derived.items():
        if sid not in src:
            continue
        p = by_id[pid]
        if p.reuse:
            notes.append(f"{pid}: reuse ignored for a derived part (always derived from {sid})")
        d = derive_spec(src[sid], pid, p.mirror_mode, name=p.name[:60] or pid, role=p.role)
        allowed = {s["article"] for s in snippets.get(pid, [])}
        out.append(d.model_copy(update={"fia_refs_used": [r for r in d.fia_refs_used if r in allowed]}))
    return out


def mate_consistency(specs: list[PartSpec], mates: list[dict], notes: list[str]) -> list[str]:
    """Before any part is built: every planned mate must be possible with the planned envelopes."""
    from agent import fast_config
    from validation.part_checks import planned_mate_problem
    boxes = {s.id: (s.envelope_min, s.envelope_max) for s in specs}
    problems = []
    for m in mates:
        if m["a"] not in boxes or m["b"] not in boxes:
            continue
        problem, note = planned_mate_problem(m, boxes[m["a"]], boxes[m["b"]], fast_config.get("TOUCH_TOL_MM"))
        if problem:
            problems.append(problem)
        if note:
            notes.append(note)
    return problems


# ---------------------------------------------------------------------------------------------- revision (revise)
MAX_REVISE_ASSUMPTIONS = 4


class SpecDelta(Strict):
    """Only what the instruction requires. Omitted fields keep their stored value."""
    dims: dict[str, float] = Field(default_factory=dict, description="changed or new key dimensions only (mm)")
    envelope_min: Optional[list[float]] = Field(default=None, min_length=3, max_length=3,
                                                description="new world envelope min (VCS) if the extents change")
    envelope_max: Optional[list[float]] = Field(default=None, min_length=3, max_length=3)
    position_mm: Optional[list[float]] = Field(default=None, min_length=3, max_length=3,
                                               description="new pose position only if the part must move")
    rotation_deg: Optional[list[float]] = Field(default=None, min_length=3, max_length=3)


class NeighbourAdjustment(Strict):
    part_id: str
    position_mm: list[float] = Field(min_length=3, max_length=3, description="intended new pose position (VCS)")
    reason: str = Field(max_length=200)


class ReviseResponse(Strict):
    spec_delta: SpecDelta
    body: str = Field(description="the COMPLETE modified python source defining build(part)")
    change_summary: str = Field(max_length=160, description="one line: what changed")
    assumptions: list[str] = Field(default_factory=list, max_length=MAX_REVISE_ASSUMPTIONS,
                                   description="new or changed assumptions only")
    neighbour_adjustments: list[NeighbourAdjustment] = Field(default_factory=list, max_length=3,
                                                             description="only if a mate would otherwise break")


def revise_system() -> str:
    """Static prefix for revise + revise-repair calls (identical bytes for every call -> prompt cache)."""
    return ("You revise ONE existing Fusion 360 part script of a concept assembly. Output ONLY the structured JSON.\n"
            "Rules: change only what the instruction requires; keep every other feature, name, dimension and "
            "parameter exactly as in the current script; never add features, parts or requirements the instruction "
            "does not ask for. body = the complete modified script. spec_delta = only the changed dimensions, "
            "envelope (world VCS) and pose; if the extents change, give the new envelope. Keep mates with the listed "
            "neighbours possible; if one must break, propose a neighbour pose adjustment with its reason (the agent "
            "verifies and may reject it). Never claim FIA compliance. assumptions: only new or changed ones.\n"
            "If part.frame_mode is legacy_world the script uses VCS coordinates at an identity pose: keep that "
            "convention and the identity pose. Otherwise follow the part-local frame contract below.\n\n"
            + CONTRACT.read_text(encoding="utf-8"))


def revise_user(instruction: str, part: dict, script_body: str, measured: dict, neighbours: list[dict],
                mates: list[dict], fia: list[dict]) -> str:
    return _dump({"task": "revise the part as instructed", "instruction": instruction, "part": part,
                  "current_script": script_body, "measured": measured, "neighbours": neighbours,
                  "planned_mates": mates, "fia": fia})


def revise_repair_user(part: dict, error: dict, attempt: int) -> str:
    return _dump({"task": f"the revised body failed (repair {attempt}); write a complete corrected body",
                  "part": part, "failure": error})
