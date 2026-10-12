"""Fast-mode revision: a natural-language change of a registered part of a finished design run (or a few parts, one
after the other), applied in that run's CURRENT Fusion design as a transaction.

    PREFLIGHT  1 read-only script: the run's document is open, wrapper depth <= REVISE_MAX_DEPTH
    per step   1 Claude call (part instruction) | deterministic pose change (assembly clause, 0 calls)
      GATES    deterministic, before Fusion: output schema/scope, frame contract (legacy_world = identity pose only),
               planned envelope + mate consistency (the plan gate's own check) with an unambiguous minimum
               neighbour-pose adjustment, FIA width on the planned envelope. A rejection costs no further Claude
               call and touches nothing.
      BUILD    into the run's design (the prelude removes the previous build; static safety validator first; the
               local-frame bbox is measured in the same call); <= MAX_REPAIRS repair calls on repairable failures
      MATES    1 script (all pairs + as-built joints): a mate that was verified must stay verified
    COMMIT     every changed part v+1 (older versions stay untouched in components/history), run state updated
    SHOTS      after: iso (+ front/top when the bbox changed in their plane); before: the run's previous shots

Any failure after Fusion was touched -> ROLLBACK: every touched part rebuilt from its stored (old) record, placement
and mates re-verified, nothing registered. A failed rollback is CRITICAL: the design is NOT claimed restored.
Revert to vN = the same transaction with vN's script/spec, registered as a NEW version ("reverted to vN").

State: run.json "revisions" (one entry per revision, saved after every step) + design_runs/<run>/revisions/<R..>/
(recovery snapshot, Claude exchange, attempt bodies, before/after screenshots, failure diagnostic).
"""
from __future__ import annotations

import json
import re
import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from pydantic import ValidationError

from agent import fast_config
from agent.design_run import DesignRun, PART_REF_RE
from agent.fast_prompts import (PartResponse, ReviseResponse, mate_consistency, revise_repair_user, revise_system,
                                revise_user, schema)
from agent.fast_reasoning import ClaudeFastReasoner, Reasoner
from agent.reasoning import ReasoningBackendError
from fia_rules.retrieval import EXTENT_RULES, fia_status
from fusion.assembly import mate_pairs, measure_assembly, overlap_axes, probe_design, screenshot_views
from fusion.client import FusionError, FusionMCPClient, FusionOutputLost, FusionUnavailable
from fusion.part_runner import PartBuild, build_part, compact_error, rebuild_part, to_record
from fusion.script_safety import check_body
from validation.checks import ANGLE_TOL_DEG, LENGTH_TOL_MM
from validation.part_checks import (box_separation, geometry_of, mate_face_checks, mate_results,
                                    planned_mate_problem, repairable)
from vehicle.models import now_iso
from vehicle.palette import Paint, load_palette, paint_for
from vehicle.parts import DIM_NAME_RE, PART_ID_PATTERN, FiaRef, PartRecord, PartSpec, same_design
from vehicle.store import ProjectStore, atomic_write_text, write_json

POSE_CLAUSE_RE = re.compile(rf"^\s*({PART_ID_PATTERN})\s+(position|move)\s*=?\s*"
                            r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*(?:mm)?\s*$", re.I)
VIEWS = ("iso", "front", "top")
MAX_INSTRUCTION = 2000


class Rejected(Exception):
    """Deterministic rejection: this step changed nothing in Fusion."""


class StepFailed(Exception):
    """A Fusion-side failure after the design was touched: needs a rollback."""


@dataclass
class Change:
    part_id: str
    kind: str                        # revise | pose | neighbour_pose | revert
    base: PartRecord                 # the version in the design before the transaction (restored on rollback)
    spec: PartSpec
    body: str
    frame_mode: str
    summary: str
    instruction: str = ""
    assumptions: list = field(default_factory=list)
    reason: str = ""
    delta: dict = field(default_factory=dict)
    build: Optional[PartBuild] = None
    touched: bool = False            # a script ran for it in Fusion (its old build was removed)
    derived: dict = field(default_factory=dict)   # revert of a derived part: the restored version's derivation


# ---------------------------------------------------------------------------------------------- run context
class RunContext:
    """The parts as they are in the run's Fusion design (record of the version built there) + its planned mates.
    Every part must be at its registry's active version, so a new version is always active + 1."""

    def __init__(self, store: ProjectStore, run: DesignRun):
        if run["status"] != "DONE" or not run["plan"]:
            raise Rejected(f"run {run.id} is {run['status']}; only a finished (DONE) run can be revised")
        self.run, self.ns, self.doc_tag = run, run["namespace"], run["doc_tag"]
        self.records: dict[str, PartRecord] = {}
        stale = []
        for pid, st in run["parts"].items():
            if st["state"] != "done":
                continue
            rec = store.get_part_version(pid, st["version"])
            active = store.get_part(pid).version
            if active != rec.version:
                stale.append(f"{pid} v{rec.version} (active v{active})")
            self.records[pid] = rec
        if stale:
            raise Rejected(f"the Fusion design of run {run.id} holds {', '.join(stale)}; use Rebuild assembly to get a "
                           f"design with the active versions and revise there")
        self.mates = [m for m in run["plan"]["mates"] if m["a"] in self.records and m["b"] in self.records]
        self.specs = {pid: r.spec for pid, r in self.records.items()}
        self.changed: set[str] = set()

    def record(self, pid: str) -> PartRecord:
        if pid not in self.records:
            raise Rejected(f"{pid} is not a built part of run {self.run.id} (have {sorted(self.records)})")
        return self.records[pid]

    def neighbours(self, pid: str) -> list[str]:
        return sorted({m["b"] if m["a"] == pid else m["a"] for m in self.mates if pid in (m["a"], m["b"])})

    def apply(self, changes: list[Change]) -> None:
        for ch in changes:
            self.specs[ch.part_id] = ch.spec
            self.changed.add(ch.part_id)


def _box(spec: PartSpec):
    return spec.envelope_min, spec.envelope_max


def _identity(spec: PartSpec) -> bool:
    return (max(abs(v) for v in spec.position_mm) <= LENGTH_TOL_MM
            and max(abs(v) for v in spec.rotation_deg) <= ANGLE_TOL_DEG)


def _shift(spec: PartSpec, vec) -> PartSpec:
    return spec.model_copy(update={
        "position_mm": tuple(round(a + b, 6) + 0.0 for a, b in zip(spec.position_mm, vec)),
        "envelope_min": tuple(round(a + b, 6) + 0.0 for a, b in zip(spec.envelope_min, vec)),
        "envelope_max": tuple(round(a + b, 6) + 0.0 for a, b in zip(spec.envelope_max, vec)), "reuse": False})


def apply_delta(base: PartSpec, delta, frame_mode: str) -> tuple[PartSpec, dict]:
    """New spec from a validated SpecDelta. A position change without an envelope moves the envelope with it; a
    rotation change needs an explicit envelope. Raises Rejected for anything invalid."""
    bad = [k for k, v in delta.dims.items() if not re.match(DIM_NAME_RE, k) or not v > 0]
    if bad:
        raise Rejected(f"spec_delta.dims: lower_snake names and positive mm values required ({bad})")
    upd: dict = {"dims": {**base.dims, **{k: float(v) for k, v in delta.dims.items()}}, "reuse": False}
    if (delta.envelope_min is None) != (delta.envelope_max is None):
        raise Rejected("spec_delta: give envelope_min and envelope_max together")
    if delta.rotation_deg is not None and tuple(delta.rotation_deg) != tuple(base.rotation_deg) \
            and delta.envelope_min is None:
        raise Rejected("spec_delta: a rotation change needs an explicit envelope")
    if delta.envelope_min is not None:
        upd["envelope_min"], upd["envelope_max"] = tuple(delta.envelope_min), tuple(delta.envelope_max)
    if delta.rotation_deg is not None:
        upd["rotation_deg"] = tuple(delta.rotation_deg)
    if delta.position_mm is not None:
        upd["position_mm"] = tuple(delta.position_mm)
        if delta.envelope_min is None:
            d = [a - b for a, b in zip(delta.position_mm, base.position_mm)]
            upd["envelope_min"] = tuple(a + b for a, b in zip(base.envelope_min, d))
            upd["envelope_max"] = tuple(a + b for a, b in zip(base.envelope_max, d))
    try:
        spec = PartSpec.model_validate({**base.model_dump(), **upd})
    except ValidationError as e:
        raise Rejected(f"spec_delta invalid: {e.errors()[0]['msg']}") from e
    if any(a >= b for a, b in zip(spec.envelope_min, spec.envelope_max)):
        raise Rejected("spec_delta: envelope_min must be < envelope_max on every axis")
    if frame_mode == "legacy_world" and not _identity(spec):
        raise Rejected("legacy_world part (VCS-coordinate script): its pose must stay identity; move it by changing "
                       "the script's coordinates, or rewrite it in the part-local frame first")
    changed = {k: v for k, v in delta.model_dump().items() if v not in (None, {}, [])}
    return spec, changed


def parse_assembly(instruction: str, part_ids: list[str]) -> list[tuple]:
    """Assembly instruction -> ordered single-part steps. Clauses are separated by ';' and each names exactly one
    part id: '<ID> position=x,y,z' / '<ID> move=dx,dy,dz' (mm) is a deterministic pose change (no Claude call);
    anything else is that part's revision instruction. Only the named parts may change."""
    out, seen = [], set()
    for clause in [c.strip() for c in instruction.split(";") if c.strip()]:
        # a lettered suffix (SUF-L) only counts when it is a part of this run: words like "LOW-DF" are not ids
        ids = {i for i in PART_REF_RE.findall(clause) if i in part_ids or i[4:].isdigit()}
        if len(ids) != 1:
            raise Rejected(f"assembly clause '{clause[:80]}' must name exactly one part id ({', '.join(part_ids)}); "
                           f"separate clauses with ';'")
        pid = ids.pop()
        if pid not in part_ids:
            raise Rejected(f"{pid} is not a built part of this run ({', '.join(part_ids)})")
        if pid in seen:
            raise Rejected(f"{pid} is named in two clauses; give one clause per part")
        seen.add(pid)
        m = POSE_CLAUSE_RE.match(clause)
        if m:
            out.append(("pose", pid, m.group(2).lower(), tuple(float(m.group(i)) for i in (3, 4, 5))))
        else:
            out.append(("revise", pid, clause))
    if not out:
        raise Rejected("empty assembly instruction")
    return out


# ---------------------------------------------------------------------------------------------- the reviser
class Reviser:
    def __init__(self, store: ProjectStore, fusion: Optional[FusionMCPClient] = None,
                 reasoner_factory: Optional[Callable[[Path], Reasoner]] = None):
        self.store = store
        self._fusion = fusion
        self._reasoner_factory = reasoner_factory or (lambda d: ClaudeFastReasoner(d))

    def fusion(self) -> FusionMCPClient:
        if self._fusion is None:
            self._fusion = FusionMCPClient()
        return self._fusion

    def _paint(self, spec: PartSpec) -> Paint:
        """Project palette colour (cosmetic); an invalid palette file falls back to the default colour."""
        try:
            palette = load_palette(self.store.root)
        except ValueError:
            palette = None
        return paint_for(spec.id, spec.mirror_of, palette)

    # ------------------------------------------------------------------ entry points
    def revise(self, run: DesignRun, target: str, instruction: str, entered_via: str = "cli") -> dict:
        instruction = (instruction or "").strip()
        if not instruction:
            raise ValueError("empty revision instruction")
        if len(instruction) > MAX_INSTRUCTION:
            raise ValueError(f"instruction too long (max {MAX_INSTRUCTION} characters)")
        target = target.strip()
        if target.lower() != "assembly" and not re.fullmatch(PART_ID_PATTERN, target):
            raise ValueError("target must be a part id (e.g. FWG-001) or 'assembly'")
        derived = {p["id"]: p["mirror_of"] for p in (run["plan"] or {}).get("parts", []) if p.get("mirror_of")}
        if target in derived:
            raise ValueError(f"{target} is derived from {derived[target]}: revise {derived[target]}, then "
                             f"re-derive with: python -m agent rebuild-mirror {target}")
        rev = self._open(run, "assembly" if target.lower() == "assembly" else target, "revise", instruction,
                         entered_via)

        def steps(ctx: RunContext):
            if rev["target"] == "assembly":
                out = parse_assembly(instruction, sorted(ctx.records))
                bad = [s[1] for s in out if s[1] in derived]
                if bad:
                    raise Rejected(f"{bad} derived (mirror_of) part(s): change the source, then rebuild-mirror")
                return out
            ctx.record(target)
            return [("revise", target, instruction)]
        return self._execute(run, rev, steps)

    def revert(self, run: DesignRun, part_id: str, version: int, entered_via: str = "cli") -> dict:
        rev = self._open(run, part_id, "revert", f"revert {part_id} to v{version}", entered_via)
        return self._execute(run, rev, lambda ctx: [("revert", part_id, int(version))])

    # ------------------------------------------------------------------ record keeping
    def _open(self, run: DesignRun, target: str, kind: str, instruction: str, entered_via: str) -> dict:
        revs = run.data.setdefault("revisions", [])
        rev = {"id": f"R{len(revs) + 1:02d}", "target": target, "kind": kind, "instruction": instruction,
               "entered_via": entered_via, "created": now_iso(), "state": "RUNNING", "error": None, "events": [],
               "steps": [], "neighbour_adjustments": [], "notes": [], "mates_before": [], "mates_after": [],
               "mate_faces": [], "screenshots": {"before": {}, "after": {}}, "stale_run_views": [],
               "rollback": None, "counters": {"claude_calls": 0, "script_calls": 0, "depth_first": None,
                                              "depth_last": None}}
        revs.append(rev)
        self._log(run, rev, f"{rev['id']}: {kind} {target} - {instruction[:120]}")
        return rev

    @staticmethod
    def _log(run: DesignRun, rev: dict, msg: str) -> None:
        rev["events"].append({"t": now_iso(), "msg": msg})
        run.log(msg if msg.startswith(rev["id"]) else f"{rev['id']}: {msg}")
        run.save()

    @staticmethod
    def _dir(run: DesignRun, rev: dict) -> Path:
        return run.dir / "revisions" / rev["id"]

    def _scripts(self, rev: dict, n: int, depth: Optional[int]) -> None:
        c = rev["counters"]
        c["script_calls"] += n
        if depth is not None:
            c["depth_first"] = depth if c["depth_first"] is None else c["depth_first"]
            c["depth_last"] = depth

    def _budget(self, rev: dict) -> int:
        return fast_config.get("REVISE_SCRIPT_BUDGET") * max(1, rev.get("_steps", 1))

    def _spend(self, rev: dict, n: int, tx: list[Change], current: Optional[Change] = None) -> None:
        """Refuse a script call that would not leave room for a full rollback inside the budget."""
        touched = [c for c in tx if c.touched or c is current]
        reserve = (len(touched) + 1) if touched else 0           # rebuild each touched part + one mate measurement
        if rev["counters"]["script_calls"] + n + reserve > self._budget(rev):
            raise StepFailed(f"revision script budget ({self._budget(rev)} calls) would not leave room for a rollback")

    # ------------------------------------------------------------------ the transaction
    def _execute(self, run: DesignRun, rev: dict, make_steps: Callable[[RunContext], list]) -> dict:
        rdir = self._dir(run, rev)
        rdir.mkdir(parents=True, exist_ok=True)
        tx: list[Change] = []
        reasoner = None
        try:
            ctx = RunContext(self.store, run)
            steps = make_steps(ctx)
            rev["_steps"] = len(steps)
            write_json(rdir / "snapshot.json", {"run_id": run.id, "doc_tag": ctx.doc_tag, "taken": now_iso(),
                                                "parts": {pid: r.model_dump(mode="json") for pid, r in ctx.records.items()}})
            for v in VIEWS:                                    # the run's current pictures = "before"
                src = run.data.get("screenshots", {}).get(v)
                if src and (run.dir / src).exists():
                    shutil.copyfile(run.dir / src, rdir / f"before_{v}.png")
                    rev["screenshots"]["before"][v] = f"revisions/{rev['id']}/before_{v}.png"
            rev["mates_before"] = [r for r in (run["assembly"] or {}).get("results", [])
                                   if r["check_id"].startswith("MATE-")]
            self._preflight(run, rev, ctx)
            reasoner = self._reasoner_factory(rdir)
            rev["_claude0"] = reasoner.calls               # count this revision's calls only (a shared reasoner)
            meas = None
            for step in steps:
                changes = self._prepare(run, rev, ctx, reasoner, step)
                for ch in changes:
                    tx.append(ch)
                    self._build(run, rev, ctx, reasoner, ch, tx)
                meas = self._mates(run, rev, ctx, changes, tx)
                ctx.apply(changes)
            self._commit(run, rev, ctx, tx, meas)
            self._after_shots(run, rev, ctx, tx)
            rev["state"] = "DONE"
            self._log(run, rev, f"revision done: " + ", ".join(f"{s['part_id']} v{s['base_version']} -> "
                                                              f"v{s['new_version']}" for s in rev["steps"]))
        except Rejected as e:
            rev["state"], rev["error"] = "REJECTED", str(e)
            self._log(run, rev, f"rejected: {e}")
            if any(c.touched for c in tx):
                self._rollback(run, rev, tx)
        except StepFailed as e:
            rev["state"], rev["error"] = "FAILED", str(e)
            self._log(run, rev, f"failed: {e}")
            self._rollback(run, rev, tx)
        except (FusionOutputLost, FusionUnavailable) as e:
            touched = any(c.touched for c in tx)
            rev["state"] = "CRITICAL" if touched else "BLOCKED_FUSION"
            rev["error"] = (f"Fusion lost during the revision ({e}). The registry is unchanged (the old versions stay "
                            f"active) but the Fusion design was being modified and is NOT verified restored: restart "
                            f"Fusion and use Rebuild assembly." if touched else
                            f"Fusion not usable ({e}): nothing was changed. Restart Fusion and try again.")
            self._log(run, rev, rev["error"])
            if touched:
                run.data["banner"] = f"Revision {rev['id']}: {rev['error']}"
        except Exception as e:                              # recorded, never swallowed silently
            rev["state"], rev["error"] = "FAILED", f"{type(e).__name__}: {e}"
            atomic_write_text(rdir / "error.txt", traceback.format_exc())
            self._log(run, rev, f"failed: {rev['error']}")
            if any(c.touched for c in tx):
                self._rollback(run, rev, tx)
        finally:
            if reasoner is not None:
                rev["counters"]["claude_calls"] = reasoner.calls - rev["_claude0"]
            rev.pop("_steps", None)
            rev.pop("_claude0", None)
            rev["finished"] = now_iso()
            if rev["state"] != "DONE":
                write_json(rdir / "diagnostic.json", {"state": rev["state"], "error": rev["error"],
                                                      "steps": rev["steps"], "rollback": rev["rollback"],
                                                      "events": rev["events"]})
            if run["status"] == "DONE":
                atomic_write_text(run.dir / "summary.md", _summary(run))
            run.save()
        return rev

    # ------------------------------------------------------------------ preflight
    def _preflight(self, run: DesignRun, rev: dict, ctx: RunContext) -> None:
        try:
            r = probe_design(self.fusion(), ctx.doc_tag, ctx.ns, sorted(ctx.records))
        except (FusionOutputLost, FusionUnavailable):
            raise
        except FusionError as e:
            raise Rejected(f"Fusion probe failed: {e}") from e
        self._scripts(rev, 1, r.get("depth"))
        limit = fast_config.get("REVISE_MAX_DEPTH")
        if r.get("depth") is not None and r["depth"] > limit:
            raise Rejected(f"MCP stdout wrapper depth is {r['depth']} (> {limit}): restart Fusion before revising")
        if not r.get("ok"):
            raise Rejected(f"the run's Fusion design is not available ({r.get('error', 'probe failed')}); use "
                           f"Rebuild assembly to get a fresh design, then revise there")
        missing = [pid for pid, ok in (r.get("present") or {}).items() if not ok]
        if missing:
            raise Rejected(f"the run's Fusion design lacks {missing}; use Rebuild assembly first")
        self._log(run, rev, f"preflight: design open, wrapper depth {r.get('depth')}")

    # ------------------------------------------------------------------ prepare one step (Claude + gates)
    def _part_payload(self, rec: PartRecord, spec: PartSpec) -> dict:
        lo, hi = spec.local_envelope()
        return {"id": spec.id, "name": spec.name, "role": spec.role, "notes": spec.notes, "dims_mm": spec.dims,
                "position_mm": list(spec.position_mm), "rotation_deg": list(spec.rotation_deg),
                "envelope_min": list(spec.envelope_min), "envelope_max": list(spec.envelope_max),
                "local_envelope_min": list(lo), "local_envelope_max": list(hi), "frame_mode": rec.frame_mode}

    def _prepare(self, run: DesignRun, rev: dict, ctx: RunContext, reasoner: Reasoner, step: tuple) -> list[Change]:
        kind, pid = step[0], step[1]
        base = ctx.record(pid)
        if pid in ctx.changed:
            raise Rejected(f"{pid} was already changed in this revision")
        proposed = []
        if kind == "revise":
            ch, proposed = self._ask(run, rev, ctx, reasoner, base, step[2])
        elif kind == "pose":
            mode, xyz = step[2], step[3]
            pos = xyz if mode == "position" else tuple(a + b for a, b in zip(base.spec.position_mm, xyz))
            vec = [a - b for a, b in zip(pos, base.spec.position_mm)]
            spec = _shift(base.spec, vec)
            if base.derived:
                raise Rejected(f"{pid} is derived from {base.derived.get('source_id')}: move the source, then "
                               f"rebuild-mirror")
            if base.frame_mode == "legacy_world" and not _identity(spec):
                raise Rejected(f"{pid} is a legacy_world part (VCS-coordinate script, identity pose only); it cannot "
                               f"be moved by its pose")
            ch = Change(pid, "pose", base, spec, base.script_body, base.frame_mode,
                        f"pose {mode} {list(xyz)} mm (script unchanged)", instruction=f"{pid} {mode}={list(xyz)}",
                        delta={"position_mm": list(spec.position_mm)})
            self._log(run, rev, f"{pid}: deterministic pose change to {list(spec.position_mm)} (no Claude call)")
        else:                                               # revert
            version = step[2]
            if version == base.version:
                raise Rejected(f"v{version} is already the active version of {pid}")
            try:
                old = self.store.get_part_version(pid, version)
            except KeyError as e:
                raise Rejected(str(e).strip("'\"")) from e
            ch = Change(pid, "revert", base, old.spec.model_copy(update={"reuse": False}), old.script_body,
                        old.frame_mode, f"reverted to v{version}", instruction=rev["instruction"],
                        delta={"reverted_from": version}, derived=old.derived)
            if old.frame_mode == "legacy_world" and not _identity(old.spec):
                raise Rejected(f"{pid} v{version} is legacy_world with a non-identity pose; it cannot be rebuilt")
        if ch.body == base.script_body and same_design(ch.spec, base.spec) and kind != "revert":
            raise Rejected(f"{pid}: the revision changes nothing (same script and spec)")
        neighbours = self._gate(run, rev, ctx, ch, proposed)
        rev["steps"].append({"part_id": pid, "kind": ch.kind, "base_version": base.version, "new_version": None,
                             "change_summary": ch.summary, "assumptions": ch.assumptions, "spec_delta": ch.delta,
                             "attempts": [], "bbox_before": base.bbox_world, "bbox_after": None, "bbox_delta": None,
                             "checks": []})
        run.save()
        return [ch] + neighbours

    def _ask(self, run, rev, ctx, reasoner, base: PartRecord, instruction: str):
        pid = base.id
        nb = [{"id": n, "name": ctx.records[n].name, "bbox_world": ctx.records[n].bbox_world,
               "envelope_min": list(ctx.specs[n].envelope_min), "envelope_max": list(ctx.specs[n].envelope_max),
               "position_mm": list(ctx.specs[n].position_mm)} for n in ctx.neighbours(pid)]
        mates = [m for m in ctx.mates if pid in (m["a"], m["b"])]
        fia = [{"article": f.article, "text": f.text} for f in base.fia]
        user = revise_user(instruction, self._part_payload(base, base.spec), base.script_body,
                           {"bbox_world": base.bbox_world, "params": base.params}, nb, mates, fia)
        self._log(run, rev, f"{pid}: revising (Claude)")
        try:
            raw = reasoner.call(f"revise_{pid}", revise_system(), user, schema(ReviseResponse))
        except ReasoningBackendError as e:
            raise Rejected(f"reasoning failed: {e}") from e
        finally:
            rev["counters"]["claude_calls"] = reasoner.calls - rev["_claude0"]
        try:
            resp = ReviseResponse.model_validate(raw)
        except ValidationError as e:
            raise Rejected("malformed revision output: " + "; ".join(
                f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:4])) from e
        summary = resp.change_summary.strip()
        if not summary or "\n" in summary:
            raise Rejected("malformed revision output: change_summary must be one non-empty line")
        if not resp.body.strip():
            raise Rejected("malformed revision output: empty body")
        for a in resp.neighbour_adjustments:
            if a.part_id == pid or a.part_id not in ctx.records:
                raise Rejected(f"out-of-scope output: neighbour adjustment for {a.part_id} (neighbours: "
                               f"{ctx.neighbours(pid)})")
        spec, delta = apply_delta(base.spec, resp.spec_delta, base.frame_mode)
        atomic_write_text(self._dir(run, rev) / "parts" / pid / "revised_1.py", resp.body)
        ch = Change(pid, "revise", base, spec, resp.body, base.frame_mode, summary, instruction=instruction,
                    assumptions=[a.strip()[:300] for a in resp.assumptions if a.strip()], delta=delta)
        return ch, resp.neighbour_adjustments

    # ------------------------------------------------------------------ deterministic gates
    def _gate(self, run, rev, ctx: RunContext, ch: Change, proposed) -> list[Change]:
        specs = dict(ctx.specs)
        specs[ch.part_id] = ch.spec
        notes: list[str] = []
        problems = mate_consistency(list(specs.values()), ctx.mates, notes)
        neighbours: list[Change] = []
        if problems:
            neighbours = self._adjust(run, rev, ctx, ch, specs, problems, proposed)
        elif proposed:
            rev["notes"].append(f"{ch.part_id}: proposed neighbour adjustments not applied - the planned envelopes "
                                f"keep every mate possible without them ({[a.part_id for a in proposed]})")
        for n in notes:
            rev["notes"].append(n)
        for c in [ch] + neighbours:                         # FIA width on the planned envelope (where it applies)
            rec = ctx.records[c.part_id]
            for art in [f.article for f in rec.fia if f.article in EXTENT_RULES]:
                status, note = fia_status(art, [list(c.spec.envelope_min), list(c.spec.envelope_max)])
                if status == "NON_COMPLIANT":
                    raise Rejected(f"{c.part_id}: planned envelope violates {art}: {note.split(';')[0]}")
        self._log(run, rev, f"{ch.part_id}: gates passed (frame contract, envelope/mate consistency, FIA width)"
                  + (f"; neighbour pose adjustments: {[n.part_id for n in neighbours]}" if neighbours else ""))
        return neighbours

    def _adjust(self, run, rev, ctx: RunContext, ch: Change, specs: dict, problems: list[str], proposed) -> list[Change]:
        """The unambiguous minimum neighbour move that makes every broken mate of the changed part possible again:
        exactly one axis apart, one direction, the neighbour's other mates still possible, not legacy_world."""
        tol = fast_config.get("TOUCH_TOL_MM")
        shifts: dict[str, list[float]] = {}
        why: dict[str, str] = {}
        pid = ch.part_id
        for m in ctx.mates:
            if pid not in (m["a"], m["b"]):
                continue
            problem, _ = planned_mate_problem(m, _box(specs[m["a"]]), _box(specs[m["b"]]), tol)
            if not problem:
                continue
            nid = m["b"] if m["a"] == pid else m["a"]
            if nid in ctx.changed:
                raise Rejected(f"{problem}; {nid} was already changed in this revision, no further adjustment")
            sep = box_separation(*_box(specs[pid]), *_box(specs[nid]))
            allowed = tol if m["expect"] in ("touching", "overlap") else (m.get("value_mm") or 0.0) + tol
            apart = [i for i in range(3) if sep[i] > allowed]
            if len(apart) != 1:
                raise Rejected(f"{problem}; no unambiguous neighbour adjustment (apart along "
                               f"{''.join('XYZ'[i] for i in apart)})")
            i = apart[0]
            d = sep[i] - (0.0 if m["expect"] in ("touching", "overlap") else (m.get("value_mm") or 0.0))
            vec = [0.0, 0.0, 0.0]
            vec[i] = -d if specs[nid].envelope_min[i] >= specs[pid].envelope_max[i] else d
            if nid in shifts and any(abs(a - b) > LENGTH_TOL_MM for a, b in zip(shifts[nid], vec)):
                raise Rejected(f"{problem}; two mates need different moves of {nid}: ambiguous")
            shifts[nid] = vec
            why[nid] = f"mate {m['a']}/{m['b']} ({m['expect']}) would be {sep[i]:.1f} mm apart along {'XYZ'[i]}"
        if not shifts:
            raise Rejected("; ".join(problems[:3]))
        moved = dict(specs)
        out = []
        for nid, vec in shifts.items():
            rec = ctx.records[nid]
            if rec.frame_mode == "legacy_world":
                raise Rejected(f"{why[nid]}; the fix would move {nid}, a legacy_world part (identity pose only): "
                               f"keep the mating face of {pid} where it was")
            if rec.derived:
                raise Rejected(f"{why[nid]}; the fix would move {nid}, which is derived from "
                               f"{rec.derived.get('source_id')} (its pose follows the source)")
            moved[nid] = _shift(specs[nid], vec)
        notes: list[str] = []
        still = mate_consistency(list(moved.values()), ctx.mates, notes)
        if still:
            raise Rejected(f"no safe neighbour adjustment: moving {sorted(shifts)} would break: {still[:2]}")
        prop = {a.part_id: a for a in proposed}
        for nid, vec in shifts.items():
            p = prop.pop(nid, None)
            agrees = p is not None and all(abs(a - b) <= LENGTH_TOL_MM
                                           for a, b in zip(p.position_mm, moved[nid].position_mm))
            reason = why[nid] + (f"; Claude: {p.reason}" if p else "")
            adj = {"part_id": nid, "shift_mm": [round(v, 6) + 0.0 for v in vec],
                   "position_from": list(specs[nid].position_mm), "position_to": list(moved[nid].position_mm),
                   "reason": reason, "claude_proposed": list(p.position_mm) if p else None,
                   "claude_agrees": agrees if p else None, "for_part": pid}
            rev["neighbour_adjustments"].append(adj)
            out.append(Change(nid, "neighbour_pose", ctx.records[nid], moved[nid], ctx.records[nid].script_body,
                              ctx.records[nid].frame_mode,
                              f"pose shifted {adj['shift_mm']} mm for revision {rev['id']} of {pid} (script unchanged)",
                              instruction=rev["instruction"], reason=reason,
                              delta={"position_mm": adj["position_to"]}))
            self._log(run, rev, f"{nid}: minimum pose adjustment {adj['shift_mm']} mm - {why[nid]}")
        for nid in prop:
            rev["notes"].append(f"Claude proposed moving {nid}; not needed by any broken mate, not applied")
        return out

    # ------------------------------------------------------------------ build (+ repairs)
    def _build(self, run, rev, ctx: RunContext, reasoner: Reasoner, ch: Change, tx: list[Change]) -> None:
        step = next((s for s in rev["steps"] if s["part_id"] == ch.part_id), None)
        body, n = ch.body, 0
        max_rep = fast_config.get("MAX_REPAIRS")
        while True:
            if not check_body(body):                       # unsafe bodies never reach Fusion (no script call)
                self._spend(rev, 1, tx, ch)
                ch.touched = True                          # before the call: a lost output may still have run
            b = build_part(self.fusion(), ch.spec, body, ctx.ns, ctx.doc_tag, create_doc=False,
                           frame_mode=ch.frame_mode, paint=self._paint(ch.spec))
            self._scripts(rev, b.script_calls, b.depth)
            att = {"n": n + 1, "kind": "build" if n == 0 else "repair", "stage": b.stage, "passed": b.passed,
                   "script_calls": b.script_calls, "failed_checks": [c.check_id for c in b.checks if c.blocking_failure],
                   "error": None if b.passed else compact_error(b)}
            if step is not None and ch.kind != "neighbour_pose":
                step["attempts"].append(att)
                atomic_write_text(self._dir(run, rev) / "parts" / ch.part_id / f"attempt_{n + 1}.py", body)
            self._log(run, rev, f"{ch.part_id}: {ch.kind} build {n + 1} -> " + (
                "all checks pass" if b.passed else f"{b.stage}: {(b.error or ', '.join(att['failed_checks']))[:160]}"))
            if b.passed:
                fia = self._fia(ctx.records[ch.part_id], b)
                bad = [f for f in fia if f.status == "NON_COMPLIANT"]
                if bad:
                    raise StepFailed(f"{ch.part_id}: measured {bad[0].article} NON_COMPLIANT: {bad[0].note[:160]}")
                ch.body, ch.build = body, b
                return
            if ch.kind != "revise" or not repairable(b.checks):
                raise StepFailed(f"{ch.part_id}: {ch.kind} build failed ({b.stage}: "
                                 f"{(b.error or ', '.join(att['failed_checks']))[:200]})")
            if n >= max_rep:
                raise StepFailed(f"{ch.part_id}: still failing after {max_rep} repairs "
                                 f"({(b.error or ', '.join(att['failed_checks']))[:200]})")
            n += 1
            self._log(run, rev, f"{ch.part_id}: repair {n} (Claude)")
            payload = dict(self._part_payload(ch.base, ch.spec), instruction=ch.instruction, failed_body=body)
            try:
                raw = reasoner.call(f"repair_{ch.part_id}_{n}", revise_system(),
                                    revise_repair_user(payload, compact_error(b), n), schema(PartResponse))
                body = PartResponse.model_validate(raw).body
            except (ReasoningBackendError, ValidationError) as e:
                raise StepFailed(f"{ch.part_id}: repair {n} failed: {e}") from e
            finally:
                rev["counters"]["claude_calls"] = reasoner.calls - rev["_claude0"]

    @staticmethod
    def _fia(rec: PartRecord, b: PartBuild) -> list[FiaRef]:
        bbox = (b.data.get("measure") or {}).get("bbox_world")
        out = []
        for f in rec.fia:                                   # re-measured extent rules; the rest keep their status
            if f.article in EXTENT_RULES:
                status, note = fia_status(f.article, bbox)
                auto = "evaluated automatically (extent rule); " if f.note.startswith("evaluated automatically") else ""
                f = f.model_copy(update={"status": status, "note": auto + note})
            out.append(f)
        return out

    # ------------------------------------------------------------------ mates
    def _measure(self, rev, ctx: RunContext) -> dict:
        meas = measure_assembly(self.fusion(), ctx.doc_tag, ctx.ns, sorted(ctx.records), *mate_pairs(ctx.mates),
                                overlaps=overlap_axes(ctx.mates, ctx.specs))
        self._scripts(rev, 1, meas.get("depth"))
        return meas

    def _mates(self, run, rev, ctx: RunContext, changes: list[Change], tx: list[Change]) -> dict:
        self._spend(rev, 1, tx)
        meas = self._measure(rev, ctx)
        if not meas.get("ok") or meas.get("missing"):
            raise StepFailed(f"mate measurement failed: {meas.get('error') or 'missing ' + str(meas.get('missing'))}")
        ids = {c.part_id for c in changes}
        results = [r.model_dump(mode="json") for r in mate_results(ctx.mates, meas)]
        before = {r["check_id"]: r["status"] for r in rev["mates_before"]}
        mine = [r for r in results if r["check_id"].startswith("MATE-") and any(i in r["check_id"] for i in ids)]
        broken = [r for r in mine if r["status"] != "VERIFIED" and before.get(r["check_id"], "VERIFIED") == "VERIFIED"]
        for r in mine:
            r["before"] = before.get(r["check_id"])
        rev["mates_after"] = [r for r in rev["mates_after"] if r["check_id"] not in {x["check_id"] for x in mine}] + mine
        self._log(run, rev, "mates: " + ", ".join(f"{r['title']} {r['status']}" for r in mine))
        if broken:
            raise StepFailed("mate broken: " + "; ".join(f"{r['title']}: {r['message']}" for r in broken))
        return meas

    # ------------------------------------------------------------------ commit
    def _commit(self, run, rev, ctx: RunContext, tx: list[Change], meas: dict) -> None:
        mates_by_part = {}
        for r in rev["mates_after"]:
            for pid in ctx.records:
                if pid in r["check_id"]:
                    mates_by_part.setdefault(pid, []).append({"check_id": r["check_id"], "status": r["status"],
                                                              "measured": r.get("measured")})
        for ch in tx:
            b = ch.build
            fia = self._fia(ch.base, b)
            frame = next((c for c in b.checks if c.check_id == "PART-FRAME"), None)
            rec = to_record(b, ctx.ns, run.id, fia, frame_note=ch.base.frame_note,
                            derived=ch.derived if ch.kind == "revert" else ch.base.derived)
            adjusted = [a for a in rev["neighbour_adjustments"] if a["for_part"] == ch.part_id]
            rec.revision = {"revision_id": rev["id"], "run_id": run.id, "kind": ch.kind, "instruction": ch.instruction,
                            "change_summary": ch.summary, "assumptions": ch.assumptions, "spec_delta": ch.delta,
                            "base_version": ch.base.version, "neighbour_pose_changes": adjusted,
                            "reason": ch.reason or None, "mates": mates_by_part.get(ch.part_id, []),
                            "frame_mode": ch.frame_mode,
                            "frame_validation": {"status": frame.status.value, "message": frame.message} if frame else None}
            saved = self.store.save_part(rec, run.id, ch.summary, force_new=ch.kind == "revert", kind=ch.kind,
                                         instruction=ch.instruction)
            st = run["parts"][ch.part_id]
            bbox = (b.data.get("measure") or {}).get("bbox_world")
            st.update(version=saved.version, bbox=bbox, geometry=geometry_of(b.data),
                      checks=[c.model_dump(mode="json") for c in b.checks], fia=[f.model_dump(mode="json") for f in fia])
            step = next((s for s in rev["steps"] if s["part_id"] == ch.part_id), None)
            if step is not None:
                step.update(new_version=saved.version, bbox_after=bbox, checks=[
                    {"id": c.check_id, "status": c.status.value, "message": c.message} for c in b.checks],
                    bbox_delta=_delta(ch.base.bbox_world, bbox))
            else:
                adj = next(a for a in rev["neighbour_adjustments"] if a["part_id"] == ch.part_id)
                adj.update(base_version=ch.base.version, new_version=saved.version, bbox_after=bbox)
            self._log(run, rev, f"{ch.part_id}: registry v{ch.base.version} -> v{saved.version} ({ch.kind})")
        results = mate_results(ctx.mates, meas)
        asm = run.data.setdefault("assembly", {}) or {}
        asm["measured"] = meas
        asm["results"] = [r.model_dump(mode="json") for r in results]
        asm["mate_faces"] = mate_face_checks(ctx.mates, dict(ctx.specs),
                                             {pid: run["parts"][pid].get("bbox") for pid in ctx.records})
        run.data["assembly"] = asm
        rev["mate_faces"] = [f for f in asm["mate_faces"] if any(c.part_id in (f["a"], f["b"]) for c in tx)]
        atomic_write_text(run.dir / "summary.md", _summary(run))
        run.save()

    # ------------------------------------------------------------------ screenshots (after commit; cosmetic)
    def _after_shots(self, run, rev, ctx: RunContext, tx: list[Change]) -> None:
        tol = fast_config.get("TOUCH_TOL_MM")
        views = ["iso"]
        deltas = [s["bbox_delta"] for s in rev["steps"] if s.get("bbox_delta")] + [
            _delta(c.base.bbox_world, run["parts"][c.part_id].get("bbox")) for c in tx if c.kind == "neighbour_pose"]
        moved = [any(abs(d["min"][i]) > tol or abs(d["max"][i]) > tol for d in deltas if d) for i in range(3)]
        if moved[1] or moved[2]:
            views.append("front")                          # front view shows the YZ plane
        if moved[0] or moved[1]:
            views.append("top")                            # top view shows the XY plane
        room = self._budget(rev) - rev["counters"]["script_calls"]
        views = views[:max(0, room)]
        if not views:
            rev["notes"].append("no script budget left for screenshots")
            return
        images, calls, errors = screenshot_views(self.fusion(), ctx.doc_tag, _center(run), views=tuple(views))
        self._scripts(rev, calls, None)
        rdir = self._dir(run, rev)
        for v, png in images.items():
            (rdir / f"after_{v}.png").write_bytes(png)
            rev["screenshots"]["after"][v] = f"revisions/{rev['id']}/after_{v}.png"
            (run.dir / "screenshots").mkdir(parents=True, exist_ok=True)
            (run.dir / "screenshots" / f"{v}.png").write_bytes(png)
            run.data.setdefault("screenshots", {})[v] = f"screenshots/{v}.png"
        rev["stale_run_views"] = [v for v in VIEWS if v not in images and v in run.data.get("screenshots", {})]
        for e in errors:
            rev["notes"].append(f"screenshot problem: {e}")
        self._log(run, rev, f"screenshots after: {', '.join(sorted(images)) or 'none'}")

    # ------------------------------------------------------------------ rollback
    def _rollback(self, run, rev, tx: list[Change]) -> None:
        touched = [c for c in tx if c.touched]
        info = {"parts": [], "verified": False, "mates": []}
        rev["rollback"] = info
        if not touched:
            info["verified"] = True
            return
        ctx_ns, doc_tag = run["namespace"], run["doc_tag"]
        try:
            for ch in reversed(touched):
                b = rebuild_part(self.fusion(), ch.base, ctx_ns, doc_tag, spec=ch.base.spec, create_doc=False,
                                 paint=self._paint(ch.base.spec))
                self._scripts(rev, b.script_calls, b.depth)
                ok = b.passed
                info["parts"].append({"part_id": ch.part_id, "restored_version": ch.base.version, "passed": ok,
                                      "error": None if ok else (b.error or [c.check_id for c in b.checks
                                                                             if c.blocking_failure])})
                if not ok:
                    raise StepFailed(f"{ch.part_id} v{ch.base.version} could not be rebuilt")
            ids = sorted(pid for pid, st in run["parts"].items() if st["state"] == "done")
            mates = [m for m in run["plan"]["mates"] if m["a"] in ids and m["b"] in ids]
            plan_specs = {p["id"]: PartSpec.model_validate(p) for p in run["plan"]["parts"]}
            meas = measure_assembly(self.fusion(), doc_tag, ctx_ns, ids, *mate_pairs(mates),
                                    overlaps=overlap_axes(mates, plan_specs))
            self._scripts(rev, 1, meas.get("depth"))
            before = {r["check_id"]: r["status"] for r in rev["mates_before"]}
            res = [r.model_dump(mode="json") for r in mate_results(mates, meas)] if meas.get("ok") else []
            mine = [r for r in res if any(c.part_id in r["check_id"] for c in touched)]
            info["mates"] = [{"check_id": r["check_id"], "status": r["status"], "before": before.get(r["check_id"]),
                              "measured": r.get("measured")} for r in mine]
            regress = [r for r in mine if before.get(r["check_id"]) == "VERIFIED" and r["status"] != "VERIFIED"]
            if not meas.get("ok") or regress:
                raise StepFailed("restored mates differ from before: " + (
                    meas.get("error") or "; ".join(f"{r['title']}: {r['message']}" for r in regress)))
            info["verified"] = True
            self._log(run, rev, "rollback verified: " + ", ".join(f"{p['part_id']} v{p['restored_version']}"
                                                                  for p in info["parts"]) + " restored, mates as before")
        except (StepFailed, FusionError) as e:
            rev["state"] = "CRITICAL"
            rev["error"] = f"{rev['error']} | ROLLBACK FAILED: {e}. The Fusion design is NOT restored; the registry is " \
                           f"unchanged (old versions active). Restart Fusion and use Rebuild assembly."
            run.data["banner"] = f"Revision {rev['id']}: rollback failed - the Fusion design is not restored"
            self._log(run, rev, f"CRITICAL rollback failure: {e}")


# ---------------------------------------------------------------------- helpers
def _delta(before, after) -> Optional[dict]:
    if not before or not after:
        return None
    return {"min": [round(a - b, 3) + 0.0 for a, b in zip(after[0], before[0])],
            "max": [round(a - b, 3) + 0.0 for a, b in zip(after[1], before[1])]}


def _center(run: DesignRun):
    boxes = [st["bbox"] for st in run["parts"].values() if st.get("bbox")]
    if not boxes:
        return (0.0, 0.0, 0.0)
    lo = [min(b[0][i] for b in boxes) for i in range(3)]
    hi = [max(b[1][i] for b in boxes) for i in range(3)]
    return tuple((a + b) / 2 for a, b in zip(lo, hi))


def _summary(run: DesignRun) -> str:
    from agent.design_run import render_summary
    return render_summary(run.data)


def find_run_for_part(store: ProjectStore, part_id: str) -> str:
    """The design run whose Fusion design holds the part's active version (the run that registered it)."""
    rec = store.get_part(part_id)
    if not rec.run_id:
        raise KeyError(f"{part_id} v{rec.version} was not registered by a design run; give --run")
    return rec.run_id
