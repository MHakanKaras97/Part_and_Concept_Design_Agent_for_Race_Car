"""Fast mode: one brief -> an assembled concept in ONE Fusion design (default path; strict mode = agent/workflow.py).

    PLAN (1 Claude call) -> [one blocking QUESTION] -> PARTS (1 call per part, <= 2 repairs each)
        -> ASSEMBLE (1 script) -> CHECK (deterministic) -> SCREENSHOT (3 scripts + 3 screenshots) -> DONE

State: data/<project>/design_runs/<run_id>/run.json, saved after every step, so a run resumes where it stopped
(Fusion restarted, process killed) without repeating Claude calls (stored responses are reused) or finished parts.
Budgets: Fusion script calls per run segment (MCP stdout wrapper leak; a resume after a Fusion block starts a new
segment) and repairs per part (agent/fast_config.py).
Nothing here judges geometry by AI: checks are validation/part_checks.py, the summary is a Python template.
"""
from __future__ import annotations

import json
import re
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from pydantic import ValidationError

from agent import fast_config
from agent.attachments import save_attachments
from agent.display_labels import FIA_WIDTH_TOOLTIP, PART_CHECK_LEGEND, check_label, fia_label, mate_label
from agent.fast_prompts import (PLAN_SYSTEM, VISUAL_SYSTEM, PartResponse, PlanResponse,
                                VisualReviewResponse, gate_plan, kit_for_brief, part_system, part_user, plan_user,
                                repair_user, schema)
from agent.fast_reasoning import ClaudeFastReasoner, Reasoner
from agent.reasoning import ReasoningBackendError
from fia_rules.retrieval import EXTENT_RULES, NOT_INSTALLED_NOTE, fia_status, retrieve, source_installed, source_sha256
from fusion.assembly import mate_pairs, measure_assembly, overlap_axes, screenshot_views
from fusion.client import FusionError, FusionMCPClient, FusionOutputLost, FusionUnavailable
from fusion.paint import compare, mismatches, recolor, recolor_summary
from fusion.part_runner import PartBuild, build_part, compact_error, derive_part, rebuild_part, to_record
from validation.part_checks import geometry_of, mate_face_checks, mate_results, repairable
from vehicle.mirror import derive_spec, derived_note
from vehicle.models import Project, now_iso
from vehicle.palette import Paint, load_palette, paint_for, palette_sha256
from vehicle.parts import PART_ID_PATTERN, FiaRef, PartSpec
from vehicle.store import ProjectStore, atomic_write_text, read_json, write_json

DEFAULT_PROJECT = "mini_f1"
PHASES = ["PLAN", "PARTS", "ASSEMBLE", "CHECK", "SCREENSHOT", "DONE"]
TERMINAL = {"DONE", "FAILED"}
RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9-]{0,40}$")
PART_REF_RE = re.compile(rf"\b{PART_ID_PATTERN}\b")
RESTART_HINT = ("Fusion's MCP output channel is exhausted (stdout wrapper leak). Restart Fusion, enable the MCP "
                "server, then press Continue: the run resumes where it stopped.")


class BudgetExceeded(Exception):
    pass


class DesignRun:
    def __init__(self, store: ProjectStore, run_id: str, data: dict):
        self.store, self.id, self.data = store, run_id, data

    @property
    def dir(self) -> Path:
        return self.store.root / "design_runs" / self.id

    def save(self) -> None:
        write_json(self.dir / "run.json", self.data)

    def log(self, msg: str) -> None:
        self.data["events"].append({"t": now_iso(), "msg": msg})

    def __getitem__(self, k):
        return self.data[k]


def ensure_project(store: ProjectStore) -> Project:
    if store.exists():
        return store.load_project()
    ns = re.sub(r"[^a-z0-9]", "", store.project_id)[:6] or "fm"
    if store.project_id == DEFAULT_PROJECT:
        ns = "mf1"
    p = Project(id=store.project_id, name="Mini F1" if store.project_id == DEFAULT_PROJECT else store.project_id,
                kind="vehicle", fusion_namespace=ns,
                description="Fast-mode concept assemblies (prompt -> Fusion). Concept level: no FIA compliance, "
                            "structural adequacy or race readiness is claimed.",
                coordinate_system="VCS: +X front, +Y left, +Z up, mm; origin front-axle centreline / plane of "
                                  "symmetry / reference plane (docs/coordinate_system.md)")
    store.save_project(p)
    return p


def runs_dir(store: ProjectStore) -> Path:
    return store.root / "design_runs"


def create_design_run(store: ProjectStore, brief: str, images: Optional[list] = None, kit: Optional[list] = None,
                      entered_via: str = "cli", visual_review: bool = False) -> DesignRun:
    brief = (brief or "").strip()
    if not brief:
        raise ValueError("empty brief")
    if len(brief) > 8000:
        raise ValueError("brief too long (max 8000 characters)")
    project = ensure_project(store)
    slug = re.sub(r"[^a-z0-9]+", "-", brief.lower()).strip("-")[:32]
    run_id = base = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}"
    k = 2
    while (runs_dir(store) / run_id).exists():          # two briefs with the same slug in the same second
        run_id, k = f"{base}-{k}", k + 1
    d = {"run_id": run_id, "mode": "fast", "project": store.project_id, "namespace": project.fusion_namespace,
         "brief": brief, "entered_via": entered_via, "created": now_iso(), "status": "RUNNING", "phase": "PLAN",
         "doc_tag": f"{project.fusion_namespace}:{run_id}", "kit": kit or kit_for_brief(brief),
         "visual_review": visual_review,
         "snippets": {}, "question": None, "answer": None, "plan": None, "parts": {}, "assembly": None,
         "screenshots": {}, "counters": {"script_calls": 0, "claude_calls": 0, "depth_first": None, "depth_last": None},
         "attachments": [], "events": [], "error": None, "banner": None}
    run = DesignRun(store, run_id, d)
    run.dir.mkdir(parents=True, exist_ok=False)
    if images:
        d["attachments"] = save_attachments(run.dir, images, entered_via)
    run.log("Run created")
    run.save()
    return run


def create_assembly_rebuild(store: ProjectStore, source_run_id: str,
                            pose_overrides: Optional[dict] = None, reason: str = "",
                            entered_via: str = "cli") -> DesignRun:
    """A NEW run that rebuilds every registered part of `source_run_id` into a fresh Fusion design from the
    registry (stored scripts + specs, latest versions) with zero Claude calls, then re-measures the planned mates and
    re-shoots. The source run is not modified.

    pose_overrides {part_id: (x, y, z)} is a deterministic correction of a part's position only (rotation, envelope
    and script unchanged); the changed spec makes the registry assign that part a new version."""
    src = load_design_run(store, source_run_id)
    if not src["plan"]:
        raise ValueError(f"run {source_run_id} has no plan")
    overrides = {k: tuple(float(v) for v in pos) for k, pos in (pose_overrides or {}).items()}
    plan_ids = [p["id"] for p in src["plan"]["parts"]]
    unknown = sorted(set(overrides) - set(plan_ids))
    if unknown:
        raise KeyError(f"not parts of run {source_run_id}: {unknown}")
    derived = sorted(p["id"] for p in src["plan"]["parts"] if p.get("mirror_of") and p["id"] in overrides)
    if derived:
        raise ValueError(f"{derived}: a derived part's pose follows its source; correct the source instead")
    if overrides and not reason.strip():
        raise ValueError("a pose correction needs a reason (it is written into the registry history)")
    registry = {p.id: p for p in store.list_parts()}
    specs, missing = [], []
    for pid in plan_ids:
        rec = registry.get(pid)
        if rec is None:
            missing.append(pid)
            continue
        spec = rec.spec.model_copy(update={"reuse": True})
        if pid in overrides:
            spec = spec.model_copy(update={"position_mm": overrides[pid]})
        specs.append(spec)
    if not specs:
        raise ValueError(f"none of the parts of {source_run_id} is registered")
    run = create_design_run(store, f"Rebuild assembly of {source_run_id} from the registry"
                            + (f" - correction: {reason.strip()}" if overrides else ""),
                            kit=src["kit"], entered_via=entered_via)
    d = run.data
    d.update(mode="assembly_rebuild", source_run=source_run_id, snippets=src["snippets"],
             correction={"pose_overrides": {k: list(v) for k, v in overrides.items()}, "reason": reason.strip()}
             if overrides else None,
             plan={"parts": [s.model_dump(mode="json") for s in specs], "mates": src["plan"]["mates"],
                   "assumptions": src["plan"]["assumptions"], "ignored_question": None},
             parts={s.id: {"state": "todo", "attempts": [], "reuse": True} for s in specs}, phase="PARTS")
    for pid in missing:
        run.log(f"{pid}: not registered (it failed in {source_run_id}); not rebuilt")
    for pid, pos in overrides.items():
        run.log(f"{pid}: pose corrected to {list(pos)} - {reason.strip()}")
    run.log(f"Assembly rebuild of {source_run_id}: {len(specs)} parts from the registry, zero Claude calls")
    run.save()
    return run


def load_design_run(store: ProjectStore, run_id: str) -> DesignRun:
    if not RUN_ID_RE.match(run_id or ""):
        raise KeyError(f"unknown design run '{run_id}'")
    p = runs_dir(store) / run_id / "run.json"
    if not p.exists():
        raise KeyError(f"unknown design run '{run_id}'")
    return DesignRun(store, run_id, read_json(p))


def record_answer(run: DesignRun, text: str, entered_via: str) -> None:
    if run["status"] != "AWAITING_USER" or not run["question"]:
        raise ValueError("this run is not waiting for an answer")
    text = (text or "").strip()
    if not text:
        raise ValueError("empty answer")
    run.data["answer"] = {"question": run["question"]["text"], "answer": text, "received": now_iso(),
                          "entered_via": entered_via}
    run.data["status"] = "RUNNING"
    run.log("Answer recorded (verbatim)")
    run.save()


class Orchestrator:
    def __init__(self, store: ProjectStore, fusion: Optional[FusionMCPClient] = None,
                 reasoner_factory: Optional[Callable[[DesignRun], Reasoner]] = None):
        self.store = store
        self._fusion = fusion
        self._reasoner_factory = reasoner_factory or (lambda run: ClaudeFastReasoner(run.dir))
        self.render_sleep, self.render_clock = time.sleep, time.monotonic      # injectable for tests

    def fusion(self) -> FusionMCPClient:
        if self._fusion is None:
            self._fusion = FusionMCPClient()
        return self._fusion

    def paint(self, run: DesignRun, spec: PartSpec) -> Paint:
        """The part's colour from the project palette (vehicle/palette.py); cosmetic, never part of a version. An
        invalid palette file never stops a build: the built-in default colour is used and the problem logged once."""
        try:
            palette = load_palette(self.store.root)
        except ValueError as e:
            msg = f"Palette ignored (default colours): {e}"
            if not any(ev["msg"] == msg for ev in run.data.get("events", [])):
                run.log(msg)
            palette = None
        return paint_for(spec.id, spec.mirror_of, palette)

    # ------------------------------------------------------------------ driver
    def advance(self, run: DesignRun, on_step: Optional[Callable[[DesignRun], None]] = None) -> DesignRun:
        if run["status"] in TERMINAL or run["status"] == "AWAITING_USER":
            return run
        if run["status"] == "BLOCKED_FUSION":           # Continue after the restart the banner asked for
            c = run.data["counters"]
            c["budget_base"] = c["script_calls"]
            run.log(f"Resumed after a Fusion block: script-call budget restarts at call {c['script_calls']}")
        run.data["status"], run.data["banner"], run.data["error"] = "RUNNING", None, None
        reasoner = self._reasoner_factory(run)
        steps = {"PLAN": self._plan, "PARTS": self._parts, "ASSEMBLE": self._assemble, "CHECK": self._check,
                 "SCREENSHOT": self._screenshot, "DONE": self._done}
        try:
            while run["status"] == "RUNNING":
                phase = run["phase"]
                cont = steps[phase](run, reasoner)
                run.save()
                if on_step:
                    on_step(run)
                if not cont:
                    break
        except FusionOutputLost as e:
            self._block(run, f"Fusion output lost: {e}", RESTART_HINT)
        except FusionUnavailable as e:
            self._block(run, f"Fusion not reachable: {e}", "Start Fusion and enable Preferences > General > API > "
                                                          "Fusion MCP Server, then press Continue.")
        except BudgetExceeded as e:
            self._block(run, str(e), RESTART_HINT)
        except Exception as e:                          # recorded, never swallowed silently
            run.data["status"], run.data["error"] = "FAILED", f"{type(e).__name__}: {e}"
            run.log(f"Run failed: {type(e).__name__}: {e}")
            atomic_write_text(run.dir / "error.txt", traceback.format_exc())
        run.save()
        return run

    def _block(self, run: DesignRun, error: str, banner: str) -> None:
        run.data["status"], run.data["error"], run.data["banner"] = "BLOCKED_FUSION", error, banner
        run.log(error)

    # ------------------------------------------------------------------ helpers
    def _count_claude(self, run: DesignRun, reasoner: Reasoner, before: int) -> None:
        run.data["counters"]["claude_calls"] += reasoner.calls - before

    def _ask(self, run: DesignRun, reasoner: Reasoner, name: str, system: str, user: str, model) -> dict:
        before = reasoner.calls
        try:
            return reasoner.call(name, system, user, schema(model))
        finally:
            self._count_claude(run, reasoner, before)

    def _script_calls(self, run: DesignRun, n: int, depth: Optional[int]) -> None:
        c = run.data["counters"]
        c["script_calls"] += n
        if depth is not None:
            c["depth_first"] = depth if c["depth_first"] is None else c["depth_first"]
            c["depth_last"] = depth

    def _budget(self, run: DesignRun, need: int = 1) -> None:
        """SCRIPT_CALL_BUDGET counts calls since the run started or last resumed from BLOCKED_FUSION (the banner asks
        for a Fusion restart, which resets the stdout wrapper depth), so a large run continues after a restart."""
        budget = fast_config.get("SCRIPT_CALL_BUDGET")
        c = run.data["counters"]
        if c["script_calls"] - c.get("budget_base", 0) + need > budget:
            raise BudgetExceeded(f"Fusion script-call budget reached ({budget} calls since the run started or "
                                 f"resumed)")

    # ------------------------------------------------------------------ PLAN
    def _plan(self, run: DesignRun, reasoner: Reasoner) -> bool:
        kit = run["kit"]
        if not run["snippets"]:
            run.data["snippets"] = {k["id"]: [s.as_dict() for s in retrieve(k["id"])] for k in kit}
            run.data["fia_source_sha256"] = source_sha256()
            if not source_installed():
                run.log(f"{NOT_INSTALLED_NOTE} (no FIA snippets; every FIA status stays NOT_VERIFIED)")
        registry = {p.id: p for p in self.store.list_parts()}
        reg_view = [{"id": p.id, "name": p.name, "version": p.version, "dims": p.spec.dims,
                     "envelope_min": list(p.spec.envelope_min), "envelope_max": list(p.spec.envelope_max)}
                    for p in registry.values()]
        answer = run["answer"]
        user = plan_user(run["brief"], kit, run["snippets"], reg_view,
                         {"question": answer["question"], "answer": answer["answer"]} if answer else None)
        name = "plan_answered" if answer else "plan"
        run.log("Planning (Claude)")
        problems: list[str] = []
        for attempt in (0, 1):
            nm = name if attempt == 0 else name + "_retry"
            u = user if attempt == 0 else json.dumps({"previous_plan_rejected": problems[:10],
                                                      "input": json.loads(user)}, separators=(",", ":"))
            raw = self._ask(run, reasoner, nm, PLAN_SYSTEM, u, PlanResponse)
            try:
                plan = PlanResponse.model_validate(raw)
            except ValidationError as e:
                problems = [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()][:10]
                run.log(f"Plan rejected by schema: {problems[:3]}")
                continue
            specs, mates, problems, notes = gate_plan(plan, kit, set(registry), run["snippets"])
            for n in notes:
                run.log(f"Plan corrected: {n}")
            if problems:
                run.log(f"Plan rejected: {problems[:3]}")
                continue
            if plan.question and not answer:
                run.data["question"] = {"text": plan.question.strip()[:500], "asked": now_iso()}
                run.data["status"] = "AWAITING_USER"
                run.log("Blocking question for the user")
                return False
            specs = self._apply_reuse(run, specs, registry)
            run.data["plan"] = {"parts": [s.model_dump(mode="json") for s in specs], "mates": mates,
                                "assumptions": [{"id": f"A{i + 1:02d}", "text": a.strip()[:300], "flag": "ASSUMPTION"}
                                                for i, a in enumerate(plan.assumptions[:8])],
                                "ignored_question": plan.question if (plan.question and answer) else None}
            run.data["parts"] = {s.id: {"state": "todo", "attempts": [], "reuse": s.reuse}
                                 | ({"derived_from": s.mirror_of, "mirror_mode": s.mirror_mode} if s.mirror_of else {})
                                 for s in specs}
            run.data["phase"] = "PARTS"
            run.log(f"Plan accepted: {len(specs)} parts, {len(mates)} mates")
            return True
        run.data["status"], run.data["error"] = "FAILED", "plan rejected twice: " + "; ".join(problems[:5])
        run.log(run.data["error"])
        return False

    def _apply_reuse(self, run: DesignRun, specs: list[PartSpec], registry: dict) -> list[PartSpec]:
        """A part id written in the brief that exists in the registry is rebuilt from its stored script."""
        named = set(PART_REF_RE.findall(run["brief"]))
        out = []
        for s in specs:
            rec = registry.get(s.id)
            if s.mirror_of:                               # derived parts follow their source (below)
                out.append(s)
                continue
            if rec is not None and (s.reuse or s.id in named):
                stored = rec.spec
                if tuple(stored.rotation_deg) == tuple(s.rotation_deg):     # translation only: shift the envelope
                    d = [a - b for a, b in zip(s.position_mm, stored.position_mm)]
                    stored = stored.model_copy(update={
                        "position_mm": tuple(s.position_mm),
                        "envelope_min": tuple(v + dv for v, dv in zip(stored.envelope_min, d)),
                        "envelope_max": tuple(v + dv for v, dv in zip(stored.envelope_max, d))})
                out.append(stored.model_copy(update={"reuse": True}))
                run.log(f"{s.id}: reusing registered v{rec.version} (rebuilt from its stored script)")
            else:
                out.append(s.model_copy(update={"reuse": False}))
        by_id = {s.id: s for s in out}
        return [derive_spec(by_id[s.mirror_of], s.id, s.mirror_mode, name=s.name, role=s.role).model_copy(
                    update={"fia_refs_used": s.fia_refs_used, "notes": s.notes}) if s.mirror_of else s for s in out]

    # ------------------------------------------------------------------ PARTS
    def specs(self, run: DesignRun) -> dict[str, PartSpec]:
        return {p["id"]: PartSpec.model_validate(p) for p in run["plan"]["parts"]}

    def _parts(self, run: DesignRun, reasoner: Reasoner) -> bool:
        specs = self.specs(run)
        for pid, spec in sorted(specs.items(), key=lambda kv: bool(kv[1].mirror_of)):   # sources first
            st = run["parts"][pid]
            if st["state"] in ("done", "failed"):
                continue
            st["state"] = "building"
            run.save()
            self._build_one(run, reasoner, spec, st)
            run.save()
        run.data["phase"] = "ASSEMBLE"
        return True

    def _build_one(self, run: DesignRun, reasoner: Reasoner, spec: PartSpec, st: dict) -> None:
        pid, snippets = spec.id, run["snippets"].get(spec.id, [])
        if spec.mirror_of:
            return self._derive_one(run, spec, st)
        if spec.reuse:
            rec = self.store.get_part(pid)
            self._budget(run)
            b = rebuild_part(self.fusion(), rec, run["namespace"], run["doc_tag"], spec=spec,
                             paint=self.paint(run, spec))
            self._script_calls(run, b.script_calls, b.depth)
            self._record_attempt(run, st, "rebuild", None, b)
            if b.passed:
                self._finish(run, st, b)
            else:
                self._fail(run, st, b, "rebuild from the stored script failed")
            return
        max_rep = fast_config.get("MAX_REPAIRS")
        while True:
            n = len(st["attempts"])
            if n:
                last = st["attempts"][-1]
                if not last["repairable"]:
                    return self._fail_last(run, pid, st, "failure not fixable by rewriting the script")
                if n > max_rep:
                    return self._fail_last(run, pid, st, f"still failing after {max_rep} repairs")
                name, user = f"repair_{pid}_{n}", repair_user(spec, snippets, last["error"], n)
                run.log(f"{pid}: repair {n} (Claude)")
            else:
                name, user = f"part_{pid}", part_user(spec, snippets)
                run.log(f"{pid}: writing script (Claude)")
            try:
                body = self._ask(run, reasoner, name, part_system(), user, PartResponse)["body"]
            except (ReasoningBackendError, KeyError, TypeError) as e:
                st.update(state="failed", error=f"reasoning failed: {e}")
                run.log(f"{pid}: FAILED - reasoning failed: {e}")
                return
            parts_dir = run.dir / "parts" / pid
            atomic_write_text(parts_dir / f"attempt_{n + 1}.py", body)
            self._budget(run)
            b = build_part(self.fusion(), spec, body, run["namespace"], run["doc_tag"], create_doc=True,
                           paint=self.paint(run, spec))
            self._script_calls(run, b.script_calls, b.depth)
            self._record_attempt(run, st, "part" if n == 0 else "repair", f"parts/{pid}/attempt_{n + 1}.py", b)
            run.save()
            if b.passed:
                return self._finish(run, st, b)

    def _derive_one(self, run: DesignRun, spec: PartSpec, st: dict, latest: bool = False) -> None:
        """Derived part (vehicle/mirror.py): ONE script call, zero Claude calls, from the source's stored script.
        Default: from the source as built in this run (or, for a reused derived part, its stored version and the
        source version it was derived from). latest=True (rebuild-mirror): from the source's latest version.
        PART-DERIVED compares against the registry record of the exact source version whose script is mirrored, never
        the run's copy of the source state (that copy can lag behind a revision)."""
        sid = spec.mirror_of
        src_st = run["parts"].get(sid) or {}
        try:
            if spec.reuse and not latest:                 # rebuild the stored derived version as it is
                rec = self.store.get_part(spec.id)
                source = self.store.get_part_version(sid, rec.derived["source_version"])
                spec = rec.spec.model_copy(update={"reuse": True})
            else:
                if not latest and src_st.get("state") != "done":
                    st.update(state="failed", error=f"source {sid} was not built")
                    run.log(f"{spec.id}: FAILED - source {sid} was not built")
                    return
                source = self.store.get_part(sid)
                if latest:
                    spec = derive_spec(source.spec, spec.id, spec.mirror_mode, name=spec.name, role=spec.role)
            if not source.geometry:
                raise ValueError(f"the registry record of {sid} v{source.version} has no measured geometry; "
                                 f"rebuild the source first (python -m agent rebuild {sid})")
            geom = source.geometry
        except (KeyError, ValueError) as e:
            st.update(state="failed", error=f"cannot derive from {sid}: {e}", geometry=None, fia=[])
            run.log(f"{spec.id}: FAILED - cannot derive from {sid}: {e}")
            return
        self._budget(run)
        b = derive_part(self.fusion(), source, geom, spec, run["namespace"], run["doc_tag"],
                        paint=self.paint(run, spec))
        self._script_calls(run, b.script_calls, b.depth)
        self._record_attempt(run, st, "derive", None, b)
        st.update(derived_from=sid, mirror_mode=spec.mirror_mode)
        if b.passed:
            info = {"source_id": sid, "source_version": source.version, "mode": spec.mirror_mode,
                    "note": derived_note(sid, source.version, spec.mirror_mode)}
            stale = latest and self.store.get_part(spec.id).derived.get("source_version") != source.version
            self._finish(run, st, b, derived=info, force_new=stale)
            for p in run["plan"]["parts"]:                 # the plan holds the spec actually built
                if p["id"] == spec.id:
                    p.update(spec.model_dump(mode="json"))
        else:
            self._fail(run, st, b, f"derivation from {sid} v{source.version} failed")

    def _record_attempt(self, run: DesignRun, st: dict, kind: str, body_file: Optional[str], b: PartBuild) -> None:
        st["attempts"].append({"kind": kind, "body_file": body_file, "ok": b.ok, "passed": b.passed,
                               "stage": b.stage, "script_calls": b.script_calls, "repairable": repairable(b.checks),
                               "error": None if b.passed else compact_error(b),
                               "failed_checks": [c.check_id for c in b.checks if c.blocking_failure]})
        run.log(f"{b.spec.id}: {kind} -> " + ("all checks pass" if b.passed else
                                              f"{b.stage}: {(b.error or ', '.join(st['attempts'][-1]['failed_checks']))[:160]}"))

    def _fia(self, spec: PartSpec, snippets: list[dict], bbox) -> list[FiaRef]:
        by_article = {s["article"]: s for s in snippets}
        arts = list(dict.fromkeys(list(spec.fia_refs_used) + [a for a in EXTENT_RULES if a in by_article]))
        out = []
        for a in arts:
            s = by_article[a]
            status, note = fia_status(a, bbox)
            if a not in spec.fia_refs_used:
                note = "evaluated automatically (extent rule); " + note
            out.append(FiaRef(article=a, text=s["text"], page=s.get("page"), sha256=s["sha256"], status=status,
                              note=note))
        return out

    def _finish(self, run: DesignRun, st: dict, b: PartBuild, derived: Optional[dict] = None,
                force_new: bool = False) -> None:
        fia = self._fia(b.spec, run["snippets"].get(b.spec.id, []), (b.data.get("measure") or {}).get("bbox_world"))
        note = self.store.get_part(b.spec.id).frame_note if b.frame_mode != "part_local" else ""
        if derived and b.spec.reuse:                       # a rebuilt stored derived version keeps its derivation
            derived = self.store.get_part(b.spec.id).derived
        rec = self.store.save_part(to_record(b, run["namespace"], run.id, fia, frame_note=note, derived=derived),
                                   run.id, derived["note"] if derived else self._summary(run, b), force_new=force_new)
        st.update(state="done", error=None,               # an earlier failed attempt's error no longer applies
                  version=rec.version, bbox=rec.bbox_world, geometry=geometry_of(b.data),
                  checks=[c.model_dump(mode="json") for c in b.checks],
                  fia=[f.model_dump(mode="json") for f in fia], document=b.data.get("document"))
        run.log(f"{b.spec.id}: registry v{rec.version}" + ("" if rec.run_id == run.id else " (unchanged, not rewritten)"))

    @staticmethod
    def _summary(run: DesignRun, b: PartBuild) -> str:
        corr = run.data.get("correction") or {}
        if b.spec.id in corr.get("pose_overrides", {}):
            return f"pose corrected to {corr['pose_overrides'][b.spec.id]} (script unchanged): {corr['reason']}"
        return "rebuilt from registry" if b.spec.reuse else "built by fast mode"

    def _fail(self, run: DesignRun, st: dict, b: PartBuild, why: str) -> None:
        st.update(state="failed", error=why, checks=[c.model_dump(mode="json") for c in b.checks],
                  bbox=(b.data.get("measure") or {}).get("bbox_world"),
                  geometry=None, fia=[])          # an earlier build's geometry / FIA notes do not describe this one
        run.log(f"{b.spec.id}: FAILED - {why}")

    def _fail_last(self, run: DesignRun, pid: str, st: dict, why: str) -> None:
        last = st["attempts"][-1]
        detail = (last["error"] or {}).get("error") or ", ".join(last["failed_checks"])
        st.update(state="failed", error=f"{why}: {detail}"[:400])
        run.log(f"{pid}: FAILED - {st['error']}")

    # ------------------------------------------------------------------ ASSEMBLE / CHECK
    def built_ids(self, run: DesignRun) -> list[str]:
        return [pid for pid, st in run["parts"].items() if st["state"] == "done"]

    def _assemble(self, run: DesignRun, reasoner: Reasoner) -> bool:
        ids = self.built_ids(run)
        if len(ids) >= 2:
            mates = [m for m in run["plan"]["mates"] if m["a"] in ids and m["b"] in ids]
            joints, pairs = mate_pairs(mates)
            self._budget(run)
            meas = measure_assembly(self.fusion(), run["doc_tag"], run["namespace"], ids, joints, pairs,
                                    overlaps=overlap_axes(mates, self.specs(run)))
            self._script_calls(run, 1, meas.get("depth"))
            run.data["assembly"] = {"measured": meas}
            skipped = sum(1 for p in meas.get("pairs", []) if p.get("skipped"))
            run.log(f"Assembly measured ({len(meas.get('pairs', [])) - skipped} pairs, {skipped} far-apart pairs "
                    f"skipped, {len(meas.get('joints', []))} rigid joints)")
        else:
            run.data["assembly"] = {"measured": None}
            run.log("Assembly skipped: fewer than two parts built")
        run.data["phase"] = "CHECK"
        return True

    def _check(self, run: DesignRun, reasoner: Reasoner) -> bool:
        meas = (run["assembly"] or {}).get("measured")
        ids = set(self.built_ids(run))
        mates = [m for m in run["plan"]["mates"] if m["a"] in ids and m["b"] in ids]
        res = mate_results(mates, meas) if meas else []
        run.data["assembly"]["results"] = [r.model_dump(mode="json") for r in res]
        skipped = [m for m in run["plan"]["mates"] if not (m["a"] in ids and m["b"] in ids)]
        run.data["assembly"]["skipped_mates"] = skipped
        specs = self.specs(run)
        run.data["assembly"]["mate_faces"] = mate_face_checks(
            mates, {pid: specs[pid] for pid in ids}, {pid: run["parts"][pid].get("bbox") for pid in ids})
        run.data["assembly"]["method"] = ("placement-based assembly (each part placed by its pose) + as-built rigid "
                                          "joints for planned mates; contact measured, not constrained")
        run.log(f"Checks: {sum(r.status.value == 'VERIFIED' for r in res)}/{len(res)} assembly results verified")
        run.data["phase"] = "SCREENSHOT"
        return True

    # ------------------------------------------------------------------ SCREENSHOT / DONE
    def _center(self, run: DesignRun):
        boxes = [st["bbox"] for st in run["parts"].values() if st.get("bbox")]
        if not boxes:
            return (0.0, 0.0, 0.0)
        lo = [min(b[0][i] for b in boxes) for i in range(3)]
        hi = [max(b[1][i] for b in boxes) for i in range(3)]
        return tuple((a + b) / 2 for a, b in zip(lo, hi))

    def _screenshot(self, run: DesignRun, reasoner: Reasoner) -> bool:
        if not self.built_ids(run):
            run.data["phase"] = "DONE"
            return True
        self._budget(run, 3)
        images, calls, errors = screenshot_views(self.fusion(), run["doc_tag"], self._center(run))
        self._script_calls(run, calls, None)
        for view, png in images.items():
            (run.dir / "screenshots").mkdir(parents=True, exist_ok=True)
            (run.dir / "screenshots" / f"{view}.png").write_bytes(png)
            run.data["screenshots"][view] = f"screenshots/{view}.png"
        for e in errors:
            run.log(f"Screenshot problem: {e}")
        run.log(f"Screenshots: {', '.join(sorted(images)) or 'none'}")
        if run.data.get("visual_review") and "iso" in images:          # optional, off by default
            before = reasoner.calls
            try:
                r = reasoner.call("visual_review", VISUAL_SYSTEM, json.dumps({"parts": list(run["parts"])}),
                                  schema(VisualReviewResponse), images=[("image/png", images["iso"])])
                run.data["visual_review_issues"] = [str(x)[:200] for x in r.get("issues", [])][:8]
                run.log(f"Visual review (advisory): {len(run.data['visual_review_issues'])} issue(s)")
            except ReasoningBackendError as e:
                run.log(f"Visual review skipped: {e}")
            finally:
                self._count_claude(run, reasoner, before)
        run.data["phase"] = "DONE"
        return True

    def _done(self, run: DesignRun, reasoner: Reasoner) -> bool:
        atomic_write_text(run.dir / "summary.md", render_summary(run.data))
        run.data["status"] = "DONE"
        run.data["finished"] = now_iso()
        run.log("Done")
        return False

    # ------------------------------------------------------------------ rebuild (zero Claude calls)
    def rebuild(self, run: DesignRun, part_id: str, latest_source: bool = False) -> DesignRun:
        """Rebuild one registered part of a finished run from its stored script, then re-measure + re-shoot.
        A derived part is rebuilt as stored and re-verified against the source version it was derived from;
        latest_source=True (rebuild-mirror) re-derives it from its source's LATEST version instead (a new version
        when the source changed; history kept)."""
        if run["status"] not in TERMINAL and run["status"] != "BLOCKED_FUSION":
            raise ValueError("the run is still in progress")
        specs = self.specs(run) if run["plan"] else {}
        if part_id not in specs:
            raise KeyError(f"{part_id} is not part of this run")
        rec = self.store.get_part(part_id)
        if latest_source and not rec.derived:
            raise ValueError(f"{part_id} is not a derived (mirror_of) part")
        st = run["parts"][part_id]
        try:
            if rec.derived:
                self._derive_one(run, rec.spec.model_copy(update={"reuse": not latest_source}), st,
                                 latest=latest_source)
            else:
                self._budget(run)
                b = rebuild_part(self.fusion(), rec, run["namespace"], run["doc_tag"], spec=rec.spec,
                                 paint=self.paint(run, rec.spec))
                self._script_calls(run, b.script_calls, b.depth)
                self._record_attempt(run, st, "rebuild", None, b)
                if b.passed:
                    self._finish(run, st, b)
                else:
                    self._fail(run, st, b, "rebuild from the stored script failed")
        except FusionError as e:
            self._block(run, f"Fusion: {e}", RESTART_HINT if isinstance(e, FusionOutputLost) else str(e))
            run.save()
            return run
        run.data.update(phase="ASSEMBLE", status="RUNNING")
        run.save()
        return self.advance(run)

    # ------------------------------------------------------------------ apply palette (zero Claude calls)
    def recolor(self, run: DesignRun) -> dict:
        """Apply the project palette to the parts in the run's CURRENT Fusion design: ONE script call recolours every
        built part in place (no geometry change, no rebuild, no part version) and reads back each body's colour;
        then iso/front/top are re-shot (3 camera calls). Recorded as run["recolors"][n] (Cnn) with any mismatch.
        Refuses an invalid palette file and a run that is still working; above REVISE_MAX_DEPTH the script itself
        refuses to write anything."""
        if run["status"] not in TERMINAL:
            raise ValueError(f"the run is {run['status']}; recolour a finished run")
        palette = load_palette(self.store.root)               # ValueError: invalid file -> refused, nothing written
        ids = self.built_ids(run)
        if not ids:
            raise ValueError("the run has no built parts")
        specs = self.specs(run) if run["plan"] else {}
        paints = {pid: paint_for(pid, specs[pid].mirror_of if pid in specs else None, palette) for pid in ids}
        recs = run.data.setdefault("recolors", [])
        rc = {"id": f"C{len(recs) + 1:02d}", "created": now_iso(), "palette_sha256": palette_sha256(self.store.root),
              "parts": {}, "mismatches": [], "notes": [], "screenshots": {}, "script_calls": 0, "depth": None,
              "error": None}
        recs.append(rc)
        try:
            data = recolor(self.fusion(), run["doc_tag"], run["namespace"], paints,
                           fast_config.get("REVISE_MAX_DEPTH"),
                           dims={pid: specs[pid].dims for pid in ids if pid in specs})
            rc["script_calls"], rc["depth"] = 1, data.get("depth")
            self._script_calls(run, 1, data.get("depth"))
            if not data.get("ok"):
                rc["error"] = data.get("error") or "recolour script reported no result"
            else:
                rc["parts"] = compare(paints, data)
                rc["mismatches"] = mismatches(rc["parts"])
                rc["notes"] = [f"{pid}: {r['note']}" for pid, r in rc["parts"].items() if r.get("note")]
                images, calls, errors = screenshot_views(self.fusion(), run["doc_tag"], self._center(run))
                rc["script_calls"] += calls
                self._script_calls(run, calls, None)
                rdir = run.dir / "recolors" / rc["id"]
                rdir.mkdir(parents=True, exist_ok=True)
                (run.dir / "screenshots").mkdir(parents=True, exist_ok=True)
                for view, png in images.items():
                    (rdir / f"{view}.png").write_bytes(png)
                    rc["screenshots"][view] = f"recolors/{rc['id']}/{view}.png"
                    (run.dir / "screenshots" / f"{view}.png").write_bytes(png)
                    run.data["screenshots"][view] = f"screenshots/{view}.png"
                rc["notes"] += [f"screenshot problem: {e}" for e in errors]
        except FusionError as e:
            rc["error"] = f"Fusion: {e}"
        run.log(f"{rc['id']}: apply palette - {recolor_summary(rc['parts'], rc['error'])} "
                f"({rc['script_calls']} script call(s))")
        run.save()
        return rc

    # ------------------------------------------------------------------ render (zero Claude calls)
    def render(self, run: DesignRun, views=("iso",), options=None) -> dict:
        """Local render of the run's open Fusion design per view (agent/render_run.py); the MCP screenshot is the
        recorded fallback. No geometry change, no registry write. Recorded as run["renders"][n] (RDnn)."""
        from agent.render_run import RenderRunner
        return RenderRunner(self, sleep=self.render_sleep, clock=self.render_clock).run(run, views, options)


# ---------------------------------------------------------------------- summary (deterministic template)
def _fmt_bbox(b) -> str:
    if not b:
        return "-"
    return " .. ".join("(" + ", ".join(f"{v:.0f}" for v in p) + ")" for p in b)


def render_summary(d: dict) -> str:
    lines = [f"# Design run {d['run_id']}", "",
             "Concept level only: no FIA compliance, structural adequacy or race readiness is claimed.", "",
             "## Brief", "", d["brief"], ""]
    if d.get("mode") == "assembly_rebuild":
        lines += [f"Assembly rebuild of run {d['source_run']} from the registry (zero Claude calls, fresh Fusion "
                  f"design `{d['doc_tag']}`).", ""]
        if d.get("correction"):
            lines += [f"Correction: {d['correction']['reason']} - poses {json.dumps(d['correction']['pose_overrides'])}", ""]
    if d.get("answer"):
        lines += ["## Question and verbatim answer", "", f"Q: {d['answer']['question']}", "",
                  f"A: {d['answer']['answer']}", ""]
    lines += ["## Parts", "", f"Checks: {PART_CHECK_LEGEND} FIA: {FIA_WIDTH_TOOLTIP}", "",
              "| Part | State | Version | World bbox (mm) | Checks | FIA |", "|---|---|---|---|---|---|"]
    for pid, st in d["parts"].items():
        checks = ", ".join(f"{c['check_id']}:{check_label(c['check_id'], c['status'])}" for c in st.get("checks", []))
        fia = ", ".join(fia_label(f["article"], f["status"]) for f in st.get("fia", []))
        drv = f" (derived from {st['derived_from']}, {st.get('mirror_mode')})" if st.get("derived_from") else ""
        lines.append(f"| {pid} | {st['state'].upper()}{' (reused)' if st.get('reuse') else ''}{drv} | "
                     f"{st.get('version', '-')} | {_fmt_bbox(st.get('bbox'))} | {checks or st.get('error', '-')} | "
                     f"{fia or '-'} |")
    a = d.get("assembly") or {}
    lines += ["", "## Assembly", "", a.get("method", "-"), ""]
    for r in a.get("results", []):
        lines.append(f"- {r['check_id']}: {mate_label(r['status'], r.get('measured'), r.get('limit'))} "
                     f"{r.get('message') or ''} {json.dumps(r.get('measured'))}")
    for f in a.get("mate_faces", []):
        lines.append(f"- mate face (advisory) {f['face']}: {f['status']} - {f['note']}")
    for m in a.get("skipped_mates", []):
        lines.append(f"- mate {m['a']}/{m['b']}: NOT_VERIFIED (a part was not built)")
    if d.get("revisions"):
        lines += ["", "## Revisions", ""]
        for r in d["revisions"]:
            steps = ", ".join(f"{s['part_id']} v{s['base_version']}->v{s['new_version'] or '-'}: {s['change_summary']}"
                              for s in r.get("steps", []))
            adj = "; ".join(f"{a['part_id']} pose {a['position_from']}->{a['position_to']}"
                            for a in r.get("neighbour_adjustments", []))
            lines.append(f"- {r['id']} {r['kind']} {r['target']}: {r['state']} - \"{r['instruction'][:160]}\""
                         + (f" - {steps}" if steps else "") + (f" - neighbour poses: {adj}" if adj else "")
                         + (f" - {r['error']}" if r.get("error") else ""))
    if d.get("visual_review_issues") is not None:
        lines += ["", "## Visual review (advisory, AI)", ""]
        lines += [f"- {x}" for x in d["visual_review_issues"]] or ["- no issues reported"]
    lines += ["", "## Assumptions", ""]
    lines += [f"- {x['id']} ASSUMPTION: {x['text']}" for x in (d.get("plan") or {}).get("assumptions", [])] or ["- none"]
    c = d["counters"]
    lines += ["", "## Counts", "", f"- Claude calls: {c['claude_calls']}", f"- Fusion script calls: {c['script_calls']}",
              f"- MCP stdout wrapper depth: first {c['depth_first']}, last {c['depth_last']}", ""]
    return "\n".join(lines)
