"""Workflow engine: one engineering task = one run, executed as an explicit, resumable state machine.

    ANALYSIS (AI) -> [AWAITING_USER] -> PLAN (AI) -> PRECHECK -> CAD -> INSPECT -> VALIDATE
        -> REVIEW (AI) -> REGISTER -> REPORT -> DONE
    (PLAN/PRECHECK failures and REVIEW=REVISE loop back, bounded by policy.max_revision_loops)

All state lives in data/<project>/runs/<run_id>/run.json, so a run survives restarts and can be
audited. Gates are enforced here in code, not by prompt instructions.
"""
from __future__ import annotations

import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from agent.reasoning import (AnalysisResponse, FileExchangeBackend, PlanResponse, ReasoningBackend,
                             ReviewResponse, make_task)
from fia_rules.rules import RuleSet
from fusion.client import FusionError, FusionMCPClient, FusionOutputLost, FusionScriptError, FusionUnavailable
from fusion.generators import GENERATORS
from fusion.inspect import GeometryReport, inspect_component
from manufacturing.dfm import load_materials, run_dfm
from agent.attachments import check_image, save_attachments
from agent.provenance import describe_numbers, invented_numbers, question_problems, quote_found
from validation.checks import (ExpectedGeometry, cad_build_result, geometry_checks, mating_interface_results,
                               plate_bending_check, structural_adequacy_result)
from vehicle.models import (Component, FusionRef, Interface, Parameter, ParamSource, Pose, Project, Severity,
                            Status, ValidationResult, blocking_failures, now_iso)
from vehicle.store import ProjectStore, read_json, write_json, atomic_write_text
from vehicle.transforms import matrix_to_fusion_cm, pose_to_matrix

TERMINAL = {"COMPLETED", "STOPPED"}


class Run:
    """Thin wrapper around run.json."""

    def __init__(self, store: ProjectStore, run_id: str, data: dict):
        self.store, self.id, self.data = store, run_id, data

    @property
    def dir(self) -> Path:
        return self.store.runs_dir / self.id

    def save(self) -> None:
        write_json(self.dir / "run.json", self.data)

    def log(self, message: str) -> None:
        self.data["events"].append({"time": now_iso(), "stage": self.data["stage"], "message": message})

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v


def _slug(text: str, n: int = 32) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n].strip("-")


def ensure_bench_project(store: ProjectStore) -> Project:
    if store.exists():
        return store.load_project()
    project = Project(id=store.project_id, name="Prototype bench", kind="bench",
                      description="Stand-alone components used to develop and prove the agent workflow (Prototype 1+).",
                      fusion_namespace=re.sub(r"[^a-z0-9]", "", store.project_id)[:16])
    store.save_project(project)
    return project


def create_run(store: ProjectStore, request: str, images: Optional[list] = None, entered_via: str = "cli") -> Run:
    """images: [(bytes, original filename)] - user-supplied source evidence stored with the run."""
    ensure_bench_project(store)
    for data_, name in images or []:                      # validate before anything is written
        check_image(data_, name)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + _slug(request, 24)
    data = {"run_id": run_id, "project_id": store.project_id, "request": request, "created": now_iso(),
            "status": "IN_PROGRESS", "stage": "ANALYSIS", "seq": 0, "loops": 0, "feedback": None,
            "user_answers": {}, "analysis": None, "plan": None, "assumptions": [], "precheck": [],
            "component_id": None, "cad": None, "geometry": None, "validation": [], "reviews": [],
            "iterations": [], "pending": None, "events": [], "attachments": []}
    run = Run(store, run_id, data)
    if images:
        run["attachments"] = save_attachments(run.dir, images, entered_via)
    run.log("Run created" + (f" with {len(images)} image attachment(s)" if images else ""))
    run.save()
    return run


def record_answer(run: Run, question_id: str, text: str, entered_via: str) -> None:
    """Store the user's answer verbatim. This text - not any AI reading of it - is the authoritative USER_ANSWER."""
    open_ids = {q["id"] for q in run.data.get("questions", [])}
    if question_id not in open_ids:
        raise ValueError(f"{question_id} is not an open question of run {run.id}; open: {sorted(open_ids)}")
    if question_id in run["user_answers"]:
        raise ValueError(f"{question_id} has already been answered; answers are not overwritten")
    if not text.strip():
        raise ValueError("empty answer")
    q = next(q for q in run["questions"] if q["id"] == question_id)
    run["user_answers"][question_id] = {"question": q["question"], "answer": text, "received": now_iso(),
                                        "entered_via": entered_via}
    run.log(f"User answer recorded verbatim for {question_id}")


def load_run(store: ProjectStore, run_id: str) -> Run:
    return Run(store, run_id, read_json(store.runs_dir / run_id / "run.json"))


class Engine:
    def __init__(self, store: ProjectStore, backend_factory=None, fusion: Optional[FusionMCPClient] = None,
                 rules: Optional[RuleSet] = None):
        self.store = store
        self.project = ensure_bench_project(store)
        self.backend_factory = backend_factory or (lambda run: FileExchangeBackend(run.dir))
        self.fusion = fusion
        self.rules = rules or RuleSet.load()
        self.materials = load_materials()
        self.max_loops = int(self.project.policy.get("max_revision_loops", 3))
        self.max_rejections = int(self.project.policy.get("max_response_rejections", 3))

    # ------------------------------------------------------------------ driver
    def advance(self, run: Run) -> Run:
        """Advance the run as far as possible; stop when waiting for AI/user or done."""
        handlers = {"ANALYSIS": self._analysis, "AWAITING_USER": self._awaiting_user, "PLAN": self._plan,
                    "PRECHECK": self._precheck, "CAD": self._cad, "INSPECT": self._inspect,
                    "VALIDATE": self._validate, "REVIEW": self._review, "REGISTER": self._register,
                    "REPORT": self._report}
        while run["status"] not in TERMINAL:
            stage = run["stage"]
            proceed = handlers[stage](run)
            run.save()
            if not proceed:
                break
        return run

    def _ask(self, run: Run, kind: str, context: dict) -> Optional[dict]:
        """Request reasoning; returns the raw response or None (run waits)."""
        pend = run["pending"]
        if not pend or pend.get("kind") != kind:
            run["seq"] += 1
            run["pending"] = {"kind": kind, "seq": run["seq"]}
        # images are shown to the reasoner where they inform engineering content (analysis, plan)
        atts = (run.data.get("attachments") or []) if kind in ("analysis", "plan") else []
        task = make_task(run.id, run["pending"]["seq"], kind, context, attachments=atts)
        backend: ReasoningBackend = self.backend_factory(run)
        run["status"] = "REASONING"                 # visible to observers while an automatic backend works
        run["pending"]["started"] = now_iso()
        run.save()
        resp = backend.request(task)
        if getattr(backend, "last_error", None):
            run.log(f"Reasoning backend fallback: {backend.last_error}")
        if resp is None:
            run["status"] = "AWAITING_REASONING"
            run["pending"]["request"] = f"reasoning/{task.stem}.request.md"
            run.log(f"Waiting for reasoning: {task.stem}")
            return None
        run["status"] = "IN_PROGRESS"
        run.log(f"Reasoning {task.stem} answered via {getattr(backend, 'last_source', type(backend).__name__)}")
        return resp

    def _reject_response(self, run: Run, kind: str, errors: list[str]) -> None:
        """Response invalid or gate failed: issue a new task of the same kind with the errors.

        Consecutive rejections are capped (policy max_response_rejections) so an automatic reasoner
        that keeps failing the gates cannot loop forever."""
        run.log(f"{kind} response rejected: " + " | ".join(errors))
        run["feedback"] = {"rejected": kind, "errors": errors}
        run["pending"] = None
        run["rejections"] = run.data.get("rejections", 0) + 1
        if run["rejections"] > self.max_rejections:
            run["stop_reason"] = (f"Reasoning responses rejected {run['rejections']} times in a row by the "
                                  f"deterministic gates; last errors: {errors}")
            run["stage"] = "REPORT"

    # ------------------------------------------------------------------ ANALYSIS
    def _context_common(self, run: Run) -> dict:
        return {
            "request": run["request"],
            "project": self.project.model_dump(mode="json"),
            "existing_components": [{"id": c.id, "name": c.name, "type": c.type, "revision": c.revision,
                                     "lifecycle": c.lifecycle} for c in self.store.list_components()],
            "user_answers": run["user_answers"],
            "attachments": [{"id": x["id"], "original_name": x["original_name"], "media_type": x["media_type"]}
                            for x in run.data.get("attachments") or []],
        }

    def _analysis(self, run: Run) -> bool:
        ctx = self._context_common(run)
        ctx["generators"] = {gid: {"description": (g.__doc__ or "").strip().splitlines()[0],
                                   "processes": g.PROCESSES, "required_info": g.REQUIRED_INFO}
                             for gid, g in GENERATORS.items()}
        ctx["feedback"] = run["feedback"]
        raw = self._ask(run, "analysis", ctx)
        if raw is None:
            return False
        try:
            a = AnalysisResponse.model_validate(raw)
        except ValidationError as e:
            self._reject_response(run, "analysis", [str(e)])
            return True
        errors = self.gate_analysis(a, run)
        if errors:
            self._reject_response(run, "analysis", errors)
            return True
        run["analysis"] = a.model_dump(mode="json")
        run["assumptions"] = [x.model_dump(mode="json") for x in a.assumptions]
        run["feedback"], run["pending"] = None, None
        run["rejections"] = 0
        if a.component_type not in GENERATORS:
            run.log(f"Component type '{a.component_type}' is not supported by any generator")
            run["stop_reason"] = f"No generator for component type '{a.component_type}'."
            run["stage"] = "REPORT"
            return True
        open_q = [m for m in a.missing_information if m.resolution == "ASK" and m.id not in run["user_answers"]]
        if open_q:
            run["stage"], run["status"] = "AWAITING_USER", "AWAITING_USER"
            run["questions"] = [m.model_dump(mode="json") for m in open_q]
            asked = run.data.setdefault("asked", {})
            for m in open_q:
                asked[m.id] = {"question": m.question, "criticality": m.criticality, "key": m.key,
                               "follows_up": m.follows_up, "asked_at": now_iso()}
            run.log(f"{len(open_q)} question(s) for the user: " + " | ".join(f"{m.id}: {m.question}" for m in open_q))
            return False
        run.log(f"Analysis accepted: {len(a.requirements)} requirements, {len(a.assumptions)} assumptions")
        run["stage"] = "PLAN"
        return True

    def gate_analysis(self, a: AnalysisResponse, run: Run) -> list[str]:
        errors = []
        ids = [x.id for x in a.requirements] + [x.id for x in a.missing_information] + [x.id for x in a.assumptions]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            errors.append(f"duplicate ids {sorted(dup)}")
        a_ids = {x.id for x in a.assumptions}
        answers = {k: v["answer"] for k, v in run["user_answers"].items()}
        asked = run.data.get("asked", {})
        user_texts = [run["request"]] + list(answers.values())
        allow_sugg = bool(self.project.policy.get("allow_suggested_values_in_questions", False))
        att_ids = {x["id"] for x in run.data.get("attachments") or []}
        image_evidence = {r.attachment_id: [] for r in a.requirements if r.source == "IMAGE"}
        for r in a.requirements:
            if r.source == "IMAGE":
                image_evidence[r.attachment_id].append(r.image_evidence or "")
        for m in a.missing_information:
            if m.resolution == "ASSUME" and m.assumption_id not in a_ids:
                errors.append(f"{m.id} refers to unknown assumption {m.assumption_id}")
            if m.criticality == "CRITICAL" and m.resolution != "ASK" and \
                    self.project.policy.get("critical_missing_info_must_be_asked", True):
                errors.append(f"{m.id} is CRITICAL and must be asked, not assumed (project policy)")
            if m.resolution == "ASK":
                if m.id in asked and asked[m.id]["question"] != m.question:
                    errors.append(f"{m.id} was already asked with different wording; use a new M-id for a new question")
                if m.id not in answers:
                    # a question may repeat values read from an image only if it names that image (IMG-nn),
                    # so the user can see the value comes from their drawing, not from the AI
                    cited = [t for aid, ts in image_evidence.items() if aid and aid in m.question for t in ts]
                    for prob in question_problems(m.question, user_texts + cited, allow_sugg):
                        errors.append(f"{m.id} question {prob}; ask neutrally without proposing engineering values")
            if m.follows_up and m.follows_up not in answers:
                errors.append(f"{m.id} follows up {m.follows_up}, which has no user answer")
        # Requirements are AI interpretations; those attributed to the user must quote the user verbatim
        known = set(ids) | set(answers) | set(self.rules.rules)
        for r in a.requirements:
            if r.source == "LEGACY_V1":
                errors.append(f"{r.id}: source LEGACY_V1 is not accepted for new analyses")
            elif r.source == "USER_REQUEST":
                src = run["request"]
            elif r.source == "USER_ANSWER":
                if r.answer_id not in answers:
                    errors.append(f"{r.id}: answer_id {r.answer_id} has no user answer")
                    continue
                src = answers[r.answer_id]
            elif r.source == "IMAGE":
                # image-derived evidence: must point at an attachment of this run; its numbers must be the ones
                # the AI reports having read (image_evidence) - it is never treated as the user's words
                if r.attachment_id not in att_ids:
                    errors.append(f"{r.id}: attachment_id {r.attachment_id} is not an image of this run")
                interp = f"{r.text} {r.value if r.value is not None else ''}"
                invented = invented_numbers(interp, r.image_evidence)
                if invented:
                    errors.append(f"{r.id}: numbers {describe_numbers(invented, interp)} are not in the stated "
                                  f"image_evidence")
                continue
            else:
                missing = [d for d in r.derived_from if d not in known]
                if missing:
                    errors.append(f"{r.id}: derived_from contains unknown ids {missing}")
                continue
            if r.source in ("USER_REQUEST", "USER_ANSWER"):
                if not quote_found(r.quote, src):
                    errors.append(f"{r.id}: quote is not a verbatim excerpt of the user's {r.source.lower()}")
                interp = f"{r.text} {r.value if r.value is not None else ''}"
                invented = invented_numbers(interp, r.quote)
                if invented:
                    errors.append(f"{r.id}: numbers {describe_numbers(invented, interp)} in the interpretation are not "
                                  f"in the quoted user words; quote the words they come from, drop them, or state them "
                                  f"as an assumption or ask")
        # Every answer must be used: interpreted into requirements, or followed up with a clarification question
        for mid in answers:
            used = any(r.answer_id == mid for r in a.requirements)
            followed = any(m.follows_up == mid and m.resolution == "ASK" for m in a.missing_information)
            if not (used or followed):
                errors.append(f"user answer {mid} is neither interpreted into requirements nor followed up by a "
                              f"clarification question")
        gen = GENERATORS.get(a.component_type)
        if gen:
            covered = {r.key for r in a.requirements} | {m.key for m in a.missing_information}
            for key in gen.REQUIRED_INFO:
                if key not in covered:
                    errors.append(f"required information '{key}' is neither a requirement nor a missing-information item")
        return errors

    # ------------------------------------------------------------------ USER
    def _awaiting_user(self, run: Run) -> bool:
        open_q = [q for q in run.data.get("questions", []) if q["id"] not in run["user_answers"]]
        if open_q:
            run["status"] = "AWAITING_USER"
            return False
        run.log("All questions answered; re-running analysis with the answers")
        run["status"], run["stage"], run["pending"] = "IN_PROGRESS", "ANALYSIS", None
        return True

    # ------------------------------------------------------------------ PLAN
    def _plan_context(self, run: Run) -> dict:
        a = run["analysis"]
        gen = GENERATORS[a["component_type"]]
        ctx = self._context_common(run)
        ctx["analysis"] = a
        ctx["assumptions"] = run["assumptions"]
        ctx["generator"] = {"id": gen.GENERATOR_ID, "version": gen.GENERATOR_VERSION,
                            "description": gen.__doc__, "length_params_mm": gen.LENGTH_PARAMS,
                            "optional_params": sorted(getattr(gen, "OPTIONAL_PARAMS", {})),
                            "count_params": gen.COUNT_PARAMS, "processes": gen.PROCESSES,
                            "design_inputs": ["base_fastener", "upright_fastener", "base_mates_with", "upright_mates_with"]}
        ctx["rules"] = [{"id": r.id, "title": r.title, "authority": r.authority, "requirement_text": r.requirement_text,
                         "process": r.process, "constraint": r.constraint.model_dump(exclude_none=True),
                         "severity": r.severity.value, "verification_status": r.verification_status}
                        for r in self.rules.applicable(gen.GENERATOR_ID, "machined")]
        ctx["materials"] = {k: m.model_dump() for k, m in self.materials.items()}
        ctx["feedback"] = run["feedback"]
        ctx["loops"] = {"used": run["loops"], "max": self.max_loops}
        return ctx

    def _plan(self, run: Run) -> bool:
        raw = self._ask(run, "plan", self._plan_context(run))
        if raw is None:
            return False
        try:
            plan = PlanResponse.model_validate(raw)
        except ValidationError as e:
            self._reject_response(run, "plan", [str(e)])
            return True
        errors = self.gate_plan(run, plan)
        if errors:
            return self._loop_back(run, "plan", errors, kind="plan_gate")
        run["plan"] = plan.model_dump(mode="json")
        run["assumptions"] = run["assumptions"] + [x.model_dump(mode="json") for x in plan.new_assumptions
                                                   if x.id not in {y["id"] for y in run["assumptions"]}]
        run["feedback"], run["pending"] = None, None
        run["rejections"] = 0
        run.log("Plan accepted")
        run["stage"] = "PRECHECK"
        return True

    def _known_ids(self, run: Run, extra_assumptions=()) -> set[str]:
        a = run["analysis"]
        ids = {r["id"] for r in a["requirements"]} | {m["id"] for m in a["missing_information"]}
        ids |= {x["id"] for x in run["assumptions"]} | {x.id for x in extra_assumptions}
        return ids | set(self.rules.rules)

    def gate_plan(self, run: Run, plan: PlanResponse) -> list[str]:
        errors = []
        gen = GENERATORS.get(plan.generator)
        if gen is None or plan.generator != run["analysis"]["component_type"]:
            return [f"generator '{plan.generator}' does not match analysis component_type"]
        optional = set(getattr(gen, "OPTIONAL_PARAMS", {}))
        expected = set(gen.LENGTH_PARAMS) | set(gen.COUNT_PARAMS)
        if not expected - optional <= set(plan.parameters) <= expected:
            missing, extra = expected - optional - set(plan.parameters), set(plan.parameters) - expected
            errors.append(f"parameters must be exactly the generator set (optional: {sorted(optional)}); "
                          f"missing {sorted(missing)}, unknown {sorted(extra)}")
        known = self._known_ids(run, plan.new_assumptions)
        reqs = run["analysis"]["requirements"]
        image_rids = {r["id"] for r in reqs if r["source"] == "IMAGE"}
        user_ids = {r["id"] for r in reqs if r["source"] in ("USER_REQUEST", "USER_ANSWER")} | set(run["user_answers"])
        traced = [(f"parameter {name}", p.source, p.trace) for name, p in plan.parameters.items()]
        if plan.placement is not None:          # the pose is a design value too: same provenance rules
            traced.append(("placement", plan.placement.source, plan.placement.trace))
        for name, source, trace in traced:
            unknown = [t for t in trace if t not in known]
            if unknown:
                errors.append(f"{name}: unknown trace ids {unknown}")
            if source != ParamSource.DERIVED and not trace:
                errors.append(f"{name}: source {source.value} needs a trace")
            # image-derived values keep their label; they never pass as the user's own words
            if source == ParamSource.IMAGE_EVIDENCE and not image_rids & set(trace):
                errors.append(f"{name}: source IMAGE_EVIDENCE must trace to an IMAGE requirement")
            if source in (ParamSource.USER, ParamSource.REQUIREMENT) and trace and not user_ids & set(trace):
                errors.append(f"{name}: source {source.value} must trace to the user's request or "
                              f"answers (use IMAGE_EVIDENCE / ASSUMPTION / DERIVED otherwise)")
        if [t for t in plan.load_case.trace if t not in known]:
            errors.append("load_case trace contains unknown ids")
        mat = self.materials.get(plan.manufacturing.material)
        if mat is None:
            errors.append(f"unknown material '{plan.manufacturing.material}'")
        if plan.manufacturing.process not in gen.PROCESSES:
            errors.append(f"process '{plan.manufacturing.process}' not supported by generator ({gen.PROCESSES})")
        if errors:
            return errors
        try:
            p = gen.INPUTS.from_values({k: v.value for k, v in plan.parameters.items()}, plan.design_inputs)
        except ValidationError as e:
            return [f"invalid generator inputs: {e}"]
        return [f"feasibility: {x}" for x in gen.feasibility_errors(p)]

    def _loop_back(self, run: Run, to_stage_kind: str, errors: list[str], kind: str) -> bool:
        run["loops"] += 1
        run["iterations"].append({"loop": run["loops"], "reason": kind, "findings": errors, "time": now_iso()})
        run.log(f"{kind}: {len(errors)} finding(s) -> back to PLAN (loop {run['loops']}/{self.max_loops})")
        if run["loops"] > self.max_loops:
            run["stop_reason"] = f"Revision loop limit ({self.max_loops}) reached; last findings: {errors}"
            run["stage"] = "REPORT"
            return True
        run["feedback"] = {"rejected": kind, "errors": errors}
        run["pending"] = None
        run["stage"] = "PLAN"
        return True

    # ------------------------------------------------------------------ helpers
    def _inputs(self, run: Run):
        plan = run["plan"]
        gen = GENERATORS[plan["generator"]]
        return gen, gen.INPUTS.from_values({k: v["value"] for k, v in plan["parameters"].items()}, plan["design_inputs"])

    @staticmethod
    def _pose(run: Run) -> Pose:
        """Placement of the component (plan.placement); identity when the plan has none (bench components)."""
        pl = (run["plan"] or {}).get("placement")
        return Pose(position=tuple(pl["position_mm"]), rotation_deg=tuple(pl["rotation_deg"])) if pl else Pose()

    def _assumption_traced(self, run: Run, trace: list[str]) -> bool:
        a_ids = {x["id"] for x in run["assumptions"]}
        return any(t in a_ids for t in trace)

    # ------------------------------------------------------------------ PRECHECK
    def precheck_results(self, run: Run) -> list[ValidationResult]:
        gen, p = self._inputs(run)
        plan = run["plan"]
        results = run_dfm(self.rules, gen.GENERATOR_ID, plan["manufacturing"]["process"], gen.dfm_quantities(p))
        mat = self.materials[plan["manufacturing"]["material"]]
        lc = plan["load_case"]
        sec = gen.structural_section(p)
        results.append(plate_bending_check(
            lc["force_n"], lc["lever_arm_mm"], sec["width"], sec["thickness"], mat.yield_strength_mpa,
            lc["required_safety_factor"],
            inputs_assumed=self._assumption_traced(run, lc["trace"]) or mat.verification_status != "VERIFIED",
            note=f"{sec['note']} Material {mat.id} yield {mat.yield_strength_mpa} MPa ({mat.verification_status})."))
        return results

    def _precheck(self, run: Run) -> bool:
        results = self.precheck_results(run)
        run["precheck"] = [r.model_dump(mode="json") for r in results]
        fails = blocking_failures(results)
        if fails:
            return self._loop_back(run, "plan", [f"{r.check_id}: {r.status.value} {r.message} (measured {r.measured}, limit {r.limit})"
                                                 for r in fails], kind="precheck")
        run.log(f"Pre-CAD checks: {len(results)} results, no blocking failures")
        run["stage"] = "CAD"
        return True

    # ------------------------------------------------------------------ CAD
    def _fusion(self) -> FusionMCPClient:
        if self.fusion is None:
            self.fusion = FusionMCPClient()
        return self.fusion

    def _cad(self, run: Run) -> bool:
        gen, p = self._inputs(run)
        plan = run["plan"]
        if not run["component_id"]:
            run["component_id"] = self.store.next_component_id(gen.ID_PREFIX)
        cid = run["component_id"]
        pose = self._pose(run)
        mat = self.materials[plan["manufacturing"]["material"]]
        script = gen.build_script(cid, plan["component_name"], p, matrix_to_fusion_cm(pose_to_matrix(pose)),
                                  mat.fusion_material, namespace=self.project.fusion_namespace)
        n = len(list((run.dir / "scripts").glob("*_build.py"))) + 1 if (run.dir / "scripts").exists() else 1
        atomic_write_text(run.dir / "scripts" / f"{n:02d}_build.py", script)
        try:
            res = self._fusion().run_script(script)
            if res.data is None:
                raise FusionOutputLost("Fusion reported success but returned no build result")
        except FusionUnavailable as e:
            run["status"] = "BLOCKED_FUSION"
            run.log(f"Fusion unavailable: {e}. Start Fusion / enable its MCP server, then run 'step' again.")
            return False
        except FusionOutputLost as e:
            # the build may or may not have happened; re-running is safe (the script replaces an earlier build)
            run["status"] = "BLOCKED_FUSION"
            run.log(f"CAD build outcome unknown: {e}. Restart the Fusion MCP add-in (or Fusion), then run 'step' again.")
            return False
        except FusionScriptError as e:
            run["cad"] = {"ok": False, "error": str(e), "output": e.output[-4000:], "script": f"scripts/{n:02d}_build.py"}
            run["validation"] = [cad_build_result(False, str(e)).model_dump(mode="json")]
            run.log(f"CAD build failed (partial geometry removed by the script): {e}")
            run["stage"] = "REVIEW"
            return True
        run["cad"] = {"ok": True, "result": res.data, "script": f"scripts/{n:02d}_build.py"}
        run["status"] = "IN_PROGRESS"
        run.log(f"CAD built: {res.data.get('component_name') if res.data else '?'}")
        run["stage"] = "INSPECT"
        return True

    # ------------------------------------------------------------------ INSPECT
    def _inspect(self, run: Run) -> bool:
        gen, _ = self._inputs(run)
        cid, plan = run["component_id"], run["plan"]
        try:
            ns = self.project.fusion_namespace
            rep = inspect_component(self._fusion(), gen.fusion_component_name(cid, plan["component_name"], ns),
                                    gen.param_prefix(cid, ns))
        except FusionUnavailable as e:
            run["status"] = "BLOCKED_FUSION"
            run.log(f"Fusion unavailable during inspection: {e}")
            return False
        except FusionOutputLost as e:
            run["status"] = "BLOCKED_FUSION"
            run.log(f"Inspection output lost: {e}. Restart the Fusion MCP add-in (or Fusion), then run 'step' again.")
            return False
        rep.build_fusion_version = ((run["cad"] or {}).get("result") or {}).get("fusion_version")
        if rep.build_fusion_version and rep.fusion_version and rep.build_fusion_version != rep.fusion_version:
            run.log(f"WARNING: Fusion build changed between CAD build ({rep.build_fusion_version}) and inspection "
                    f"({rep.fusion_version}); re-run the build to validate a model built by the current Fusion build")
        run["geometry"] = rep.model_dump(mode="json")
        write_json(run.dir / "geometry_report.json", run["geometry"])
        try:
            png = self._fusion().screenshot()
            (run.dir / "screenshot.png").write_bytes(png)
        except FusionError as e:
            run.log(f"Screenshot not captured: {e}")
        run.log("Inspection complete (read-only)")
        run["stage"] = "VALIDATE"
        return True

    # ------------------------------------------------------------------ VALIDATE
    def validation_results(self, run: Run) -> list[ValidationResult]:
        gen, p = self._inputs(run)
        cid = run["component_id"]
        rep = GeometryReport.model_validate(run["geometry"])
        exp = ExpectedGeometry(bbox_local=gen.expected_bbox_local(p), volume_mm3=gen.expected_volume_mm3(p),
                               holes_local=gen.expected_holes_local(p), parameters=gen.fusion_parameters(cid, p, self.project.fusion_namespace),
                               pose=self._pose(run))
        plan = run["plan"]
        ifs = gen.interfaces(p, plan["design_inputs"].get("base_mates_with"), plan["design_inputs"].get("upright_mates_with"))
        results = [cad_build_result(True)] + geometry_checks(rep, exp) + mating_interface_results(ifs)
        results += self.precheck_results(run) + [structural_adequacy_result()]
        results.append(self.fia_applicability(gen.GENERATOR_ID))
        return results

    def fia_applicability(self, component_type: str) -> ValidationResult:
        fia = [r for r in self.rules.rules.values() if r.authority == "REGULATION"]
        applicable = [r.id for r in fia if component_type in r.applies_to]
        if applicable:
            return ValidationResult(check_id="FIA-APPLICABILITY", title="FIA rules for this component", category="FIA",
                                    scope="FIA", claim="FIA rules apply to this component but were not checked.",
                                    status=Status.NOT_VERIFIED, severity=Severity.ADVISORY, method="NOT_RUN",
                                    measured=applicable, message="Applicable FIA rules exist but no checker is implemented yet.")
        return ValidationResult(check_id="FIA-APPLICABILITY", title="FIA rules for this component", category="FIA",
                                scope="FIA", claim="None of the structured FIA rules in the project targets this "
                                                   "component type. No FIA compliance statement of any kind.",
                                status=Status.NOT_APPLICABLE, severity=Severity.ADVISORY, method="NOT_RUN",
                                measured=f"{len(fia)} structured FIA rules loaded; 0 apply to '{component_type}'",
                                message="No structured FIA rule applies to this component type; no FIA claim is made.")

    def _validate(self, run: Run) -> bool:
        results = self.validation_results(run)
        run["validation"] = [r.model_dump(mode="json") for r in results]
        n_block = len(blocking_failures(results))
        run.log(f"Validation: {len(results)} results, {n_block} blocking failure(s)")
        run["stage"] = "REVIEW"
        return True

    # ------------------------------------------------------------------ REVIEW
    def _review(self, run: Run) -> bool:
        results = [ValidationResult.model_validate(r) for r in run["validation"]]
        fails = blocking_failures(results)
        ctx = {"request": run["request"], "plan": run["plan"], "assumptions": run["assumptions"],
               "cad": {k: v for k, v in (run["cad"] or {}).items() if k != "output"},
               "cad_error_output": (run["cad"] or {}).get("output"),
               "validation": run["validation"], "blocking_failures": [r.model_dump(mode="json") for r in fails],
               "loops": {"used": run["loops"], "max": self.max_loops}}
        raw = self._ask(run, "review", ctx)
        if raw is None:
            return False
        try:
            rv = ReviewResponse.model_validate(raw)
        except ValidationError as e:
            self._reject_response(run, "review", [str(e)])
            return True
        if rv.decision == "ACCEPT" and fails:
            self._reject_response(run, "review", [f"ACCEPT refused: {len(fails)} blocking failure(s) "
                                                  f"({', '.join(r.check_id for r in fails)})"])
            return True
        run["reviews"].append(rv.model_dump(mode="json"))
        run["pending"] = None
        run["rejections"] = 0
        new_a = [x.model_dump(mode="json") for x in rv.new_assumptions if x.id not in {y["id"] for y in run["assumptions"]}]
        run["assumptions"] = run["assumptions"] + new_a
        if rv.decision == "ACCEPT":
            run.log("Review: ACCEPT")
            run["stage"] = "REGISTER"
            return True
        if rv.decision == "STOP":
            run["stop_reason"] = f"Reviewer stopped the design: {rv.rationale}"
            run.log("Review: STOP")
            run["stage"] = "REPORT"
            return True
        # REVISE
        plan = PlanResponse.model_validate(run["plan"])
        unknown = set(rv.parameter_changes) - set(plan.parameters)
        if unknown or not rv.parameter_changes:
            self._reject_response(run, "review", [f"REVISE needs parameter_changes for existing parameters; unknown {sorted(unknown)}"])
            return True
        old = {k: plan.parameters[k].value for k in rv.parameter_changes}
        plan.parameters.update(rv.parameter_changes)
        errors = self.gate_plan(run, plan)
        if errors:
            self._reject_response(run, "review", [f"revised parameters rejected: {e}" for e in errors])
            run["reviews"].pop()
            return True
        run["loops"] += 1
        run["iterations"].append({"loop": run["loops"], "reason": "review_revise", "time": now_iso(),
                                  "changes": {k: {"from": old[k], "to": v.value} for k, v in rv.parameter_changes.items()},
                                  "rationale": rv.rationale})
        if run["loops"] > self.max_loops:
            run["stop_reason"] = f"Revision loop limit ({self.max_loops}) reached."
            run["stage"] = "REPORT"
            return True
        run["plan"] = plan.model_dump(mode="json")
        run.log(f"Review: REVISE ({', '.join(rv.parameter_changes)}) -> PRECHECK")
        run["stage"] = "PRECHECK"
        return True

    # ------------------------------------------------------------------ REGISTER
    def build_component(self, run: Run) -> Component:
        gen, p = self._inputs(run)
        plan, a = run["plan"], run["analysis"]
        cid = run["component_id"]
        results = [ValidationResult.model_validate(r) for r in run["validation"]]
        rep = GeometryReport.model_validate(run["geometry"])
        mat = self.materials[plan["manufacturing"]["material"]]
        vol = rep.total_volume_mm3
        params = {k: Parameter(name=k, value=v["value"], unit=v["unit"], source=v["source"], trace=v["trace"],
                               rationale=v["rationale"]) for k, v in plan["parameters"].items()}
        ifs = [Interface.model_validate(i) for i in gen.interfaces(p, plan["design_inputs"].get("base_mates_with"),
                                                                    plan["design_inputs"].get("upright_mates_with"))]
        hole_ok = any(r.scope == "HOLE_GEOMETRY" and r.status == Status.VERIFIED for r in results)
        for i in ifs:
            i.hole_geometry_status = Status.VERIFIED if hole_ok else Status.NOT_VERIFIED
            i.mating_status = Status.NOT_VERIFIED     # mating parts are not modelled
        provenance = ["AI_GENERATED", "GEOMETRY_VALIDATED", "RULE_CHECKED"]
        if any(r.status == Status.ASSUMPTION for r in results) or run["assumptions"]:
            provenance.append("ASSUMPTION_BASED")
        b = rep.bodies[0]
        return Component(
            id=cid, name=plan["component_name"], type=gen.GENERATOR_ID, lifecycle="CHECKED",
            pose=self._pose(run), generator={"id": gen.GENERATOR_ID, "version": gen.GENERATOR_VERSION}, parameters=params,
            interfaces=ifs, requirements=a["requirements"], assumptions=run["assumptions"],
            applicable_rules=[r.rule_id for r in results if r.rule_id],
            manufacturing=plan["manufacturing"], validation=results,
            derived={"volume_mm3": round(vol, 3), "mass_kg": round(vol * 1e-9 * mat.density_kg_m3, 4),
                     "mass_basis": f"Fusion volume x {mat.id} density {mat.density_kg_m3} kg/m3 ({mat.verification_status})",
                     "bbox_vcs_mm": {"min": b.bbox_min, "max": b.bbox_max},
                     "design_inputs": plan["design_inputs"], "load_case": plan["load_case"]},
            fusion_ref=FusionRef(document=rep.document, component_name=rep.component_name, built_at=now_iso(),
                                 fusion_version=rep.fusion_version),
            provenance=provenance,
            source_attachments=[{"id": x["id"], "run_id": run.id, "file": x["file"], "original_name": x["original_name"],
                                 "media_type": x["media_type"], "sha256": x["sha256"]}
                                for x in run.data.get("attachments") or []])

    def _register(self, run: Run) -> bool:
        comp = self.build_component(run)
        comp = self.store.register(comp, summary=f"Created by run {run.id}: {run['request'][:80]}", run_id=run.id)
        run["registered"] = {"id": comp.id, "revision": comp.revision}
        run.log(f"Registered {comp.id} rev {comp.revision}")
        run["stage"] = "REPORT"
        return True

    # ------------------------------------------------------------------ REPORT
    def _report(self, run: Run) -> bool:
        from agent.report import render_report
        atomic_write_text(run.dir / "report.md", render_report(run.data, self.rules))
        run["status"] = "COMPLETED" if run.data.get("registered") else "STOPPED"
        run.log(f"Report written; run {run['status']}")
        return True
