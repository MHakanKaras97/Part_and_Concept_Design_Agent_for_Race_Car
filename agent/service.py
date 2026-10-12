"""Application service: a thin facade over the existing workflow for user interfaces (web UI, later others).

It contains NO engineering logic. It only:
  * starts runs, records verbatim answers and advances runs through the existing Engine (in a background
    thread, because automatic reasoning and CAD take seconds to minutes);
  * selects the reasoning backend (Claude Code non-interactive with file-exchange fallback, or file exchange);
  * translates the persisted run/component records into a view model for display.
Every value shown comes from records written by the engine (run.json, components/*.json).
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Literal, Optional

from agent.attachments import MAX_IMAGES, decode_upload
from agent.reasoning import ClaudeCodeBackend, FallbackBackend, FileExchangeBackend
from agent.workflow import TERMINAL, Engine, create_run, load_run, record_answer
from fusion.client import FusionError, FusionMCPClient
from vehicle.store import ProjectStore

ReasonerMode = Literal["auto", "claude_code", "file_exchange"]
RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9-]{0,40}$")

# Engine stages -> the user-facing pipeline (presentation only)
PIPELINE = [("REQUIREMENTS", "Requirements"), ("QUESTIONS", "Questions"), ("ASSUMPTIONS", "Assumptions"),
            ("PLAN", "Engineering plan"), ("CAD", "CAD generation"), ("VALIDATION", "Validation"),
            ("REVIEW", "Review"), ("REGISTERED", "Registered")]
STAGE_TO_STEP = {"ANALYSIS": "REQUIREMENTS", "AWAITING_USER": "QUESTIONS", "PLAN": "PLAN", "PRECHECK": "PLAN",
                 "CAD": "CAD", "INSPECT": "VALIDATION", "VALIDATE": "VALIDATION", "REVIEW": "REVIEW",
                 "REGISTER": "REGISTERED", "REPORT": "REGISTERED"}


class AgentService:
    def __init__(self, project: str = "prototype_bench", root=None, reasoner: ReasonerMode = "auto",
                 fusion: Optional[FusionMCPClient] = None, backend_factory=None, background: bool = True,
                 claude_executable: str = "claude", claude_model: Optional[str] = None):
        self.store = ProjectStore(project, root=root)
        self.fusion = fusion
        self.background = background
        self._lock = threading.Lock()
        self._workers: dict[str, threading.Thread] = {}
        self._errors: dict[str, str] = {}
        self._fusion_cache: tuple[float, dict] = (0.0, {})
        self._fusion_info: dict = {}                          # version/document from the last script ping
        self._status_client: Optional[FusionMCPClient] = None
        self.claude_executable, self.claude_model = claude_executable, claude_model
        if backend_factory is not None:                       # injected (tests)
            self.reasoner = {"mode": "custom", "available": True, "detail": "injected backend"}
            self._backend_factory = backend_factory
        else:
            self.reasoner = self._select_reasoner(reasoner)
            self._backend_factory = self._make_factory(self.reasoner["mode"])
        self.engine = Engine(self.store, backend_factory=self._backend_factory, fusion=fusion)

    # ------------------------------------------------------------------ reasoner selection
    def _select_reasoner(self, mode: ReasonerMode) -> dict:
        if mode == "file_exchange":
            return {"mode": "file_exchange", "available": True,
                    "detail": "File exchange: an external reasoner answers reasoning/*.request.md"}
        ok, detail = ClaudeCodeBackend.available(self.claude_executable)
        if ok:
            return {"mode": "claude_code", "available": True,
                    "detail": f"Claude Code non-interactive ({detail}); falls back to file exchange on failure"}
        if mode == "claude_code":
            return {"mode": "claude_code", "available": False, "detail": detail}
        return {"mode": "file_exchange", "available": True,
                "detail": f"Claude Code unavailable ({detail}); using file exchange"}

    def _make_factory(self, mode: str):
        if mode == "claude_code":
            return lambda run: FallbackBackend(ClaudeCodeBackend(run.dir, self.claude_executable, self.claude_model),
                                               FileExchangeBackend(run.dir))
        return lambda run: FileExchangeBackend(run.dir)

    # ------------------------------------------------------------------ commands
    def start_run(self, request: str, attachments: Optional[list] = None) -> str:
        """attachments: [{"filename", "data_base64"}] - images only; stored with the run as source evidence."""
        request = (request or "").strip()
        if not request:
            raise ValueError("empty request")
        if len(request) > 4000:
            raise ValueError("request too long (max 4000 characters)")
        if attachments and len(attachments) > MAX_IMAGES:
            raise ValueError(f"at most {MAX_IMAGES} images per request")
        images = [decode_upload(a) for a in attachments or []]
        with self._lock:
            run = create_run(self.store, request, images=images, entered_via="ui: web interface")
        self._schedule(run.id)
        return run.id

    def attachment(self, run_id: str, attachment_id: str):
        """(path, media_type) of a stored image; only ids recorded in the run are served."""
        self._check_id(run_id)
        d = load_run(self.store, run_id).data
        for a in d.get("attachments") or []:
            if a["id"] == attachment_id:
                return self.store.runs_dir / run_id / a["file"], a["media_type"]
        raise KeyError(f"no attachment {attachment_id}")

    def answer(self, run_id: str, question_id: str, text: str) -> None:
        self._check_id(run_id)
        if self.is_busy(run_id):
            raise ValueError("the agent is still working on this run")
        with self._lock:
            run = load_run(self.store, run_id)
            record_answer(run, question_id, text, entered_via="ui: web interface")
            run.save()
        self._schedule(run_id)

    def advance(self, run_id: str) -> None:
        """Continue a run (e.g. after a file-exchange response was written, or Fusion came back)."""
        self._check_id(run_id)
        self._schedule(run_id)

    def is_busy(self, run_id: str) -> bool:
        t = self._workers.get(run_id)
        return bool(t and t.is_alive())

    def _schedule(self, run_id: str) -> None:
        if self.is_busy(run_id):
            return
        self._errors.pop(run_id, None)
        if not self.background:
            self._advance(run_id)
            return
        t = threading.Thread(target=self._advance, args=(run_id,), daemon=True, name=f"advance-{run_id}")
        self._workers[run_id] = t
        t.start()

    def _advance(self, run_id: str) -> None:
        try:
            run = load_run(self.store, run_id)
            if run["status"] not in TERMINAL:
                self.engine.advance(run)
        except Exception as e:                                 # surfaced in the UI, never swallowed silently
            self._errors[run_id] = f"{type(e).__name__}: {e}"

    def _check_id(self, run_id: str) -> None:
        if not RUN_ID_RE.match(run_id or "") or not (self.store.runs_dir / run_id / "run.json").exists():
            raise KeyError(f"unknown run '{run_id}'")

    # ------------------------------------------------------------------ queries
    def fusion_status(self, max_age_s: float = 60.0) -> dict:
        """Fusion connectivity for the UI status poll.

        Polls use the MCP handshake only (no script): the Fusion MCP add-in (2705.x) wraps sys.stdout/sys.stderr once
        more on every *script* call and never unwraps them, so a script ping per poll degrades the output channel
        within hours of an open UI. Version and active document come from one script ping per (re)connection; the
        document is therefore the one active at that check."""
        ts, cached = self._fusion_cache
        if cached and time.time() - ts < max_age_s:
            return cached
        if self.fusion is not None:                           # injected client (tests)
            client = self.fusion
        else:                                                 # own client: never reset the engine's session
            client = self._status_client = self._status_client or FusionMCPClient(timeout=10)
        try:
            client.connect()
            if not self._fusion_info:
                info = client.ping()
                self._fusion_info = {"version": info.get("fusion_version"), "document": info.get("active_document"),
                                     "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            status = {"connected": True, **self._fusion_info}
        except FusionError as e:
            self._fusion_info = {}                            # re-read version/document after reconnecting
            status = {"connected": False, "error": str(e)[:200]}
        self._fusion_cache = (time.time(), status)
        return status

    def system_status(self) -> dict:
        return {"project": self.store.project_id, "reasoner": self.reasoner, "fusion": self.fusion_status()}

    def list_runs(self) -> list[dict]:
        out = []
        if self.store.runs_dir.exists():
            for p in sorted(self.store.runs_dir.glob("*/run.json"), reverse=True):
                d = load_run(self.store, p.parent.name).data
                out.append({"run_id": d["run_id"], "request": d["request"], "status": d["status"],
                            "stage": d["stage"], "created": d.get("created"),
                            "component": (d.get("registered") or {}).get("id") or d.get("component_id")})
        return out

    def run_view(self, run_id: str) -> dict:
        self._check_id(run_id)
        d = load_run(self.store, run_id).data
        return build_run_view(d, self.store, busy=self.is_busy(run_id), error=self._errors.get(run_id))

    def report_text(self, run_id: str) -> Optional[str]:
        self._check_id(run_id)
        p = self.store.runs_dir / run_id / "report.md"
        return p.read_text(encoding="utf-8") if p.exists() else None

    def screenshot_path(self, run_id: str):
        self._check_id(run_id)
        p = self.store.runs_dir / run_id / "screenshot.png"
        return p if p.exists() else None


# ---------------------------------------------------------------------- view model (presentation only)
def _answer_text(a: Any) -> str:
    return a["answer"] if isinstance(a, dict) else str(a)        # MVP 1.0 runs stored plain strings


def _attachment_view(d: dict) -> list[dict]:
    return [{"id": a["id"], "original_name": a["original_name"], "media_type": a["media_type"], "bytes": a["bytes"],
             "sha256": a["sha256"], "url": f"/api/runs/{d['run_id']}/attachments/{a['id']}"}
            for a in d.get("attachments") or []]


def _pipeline(d: dict) -> list[dict]:
    keys = [k for k, _ in PIPELINE]
    stage, status = d["stage"], d["status"]
    asked = d.get("asked") or ({q["id"]: q for q in d.get("questions", [])} if d.get("questions") else {})
    current = "REGISTERED" if d.get("registered") else STAGE_TO_STEP.get(stage, "REQUIREMENTS")
    idx = keys.index(current)
    steps = []
    for i, (k, label) in enumerate(PIPELINE):
        if d.get("registered") or i < idx:
            state = "done"
        elif i == idx:
            if status == "STOPPED":
                state = "failed"
            elif status in ("AWAITING_USER", "AWAITING_REASONING", "BLOCKED_FUSION"):
                state = "waiting"
            else:
                state = "current"
        else:
            state = "todo"
        if k == "QUESTIONS" and state == "done" and not asked:
            state = "skipped"
        steps.append({"key": k, "label": label, "state": state})
    return steps


def _validation_summary(vals: list[dict]) -> dict:
    labels: dict[str, int] = {}
    for v in vals:
        lab = f"{v.get('scope', '?')}_{v['status']}"
        labels[lab] = labels.get(lab, 0) + 1
    blocking = [v["check_id"] for v in vals if v.get("severity") == "BLOCKING"
                and v["status"] in ("NON_COMPLIANT", "NOT_VERIFIED")]
    fia = [f"{v.get('scope', 'FIA')}_{v['status']}" for v in vals if v.get("category") == "FIA"]
    return {"labels": labels, "blocking_failures": blocking, "fia": fia[0] if fia else None}


def _messages(d: dict) -> list[dict]:
    """Chat timeline built from the run record. Every item is tagged with its layer."""
    m: list[dict] = [{"role": "user", "layer": "USER_REQUEST", "title": "Engineering request", "text": d["request"],
                      "attachments": _attachment_view(d)}]
    answers = d.get("user_answers") or {}
    asked = d.get("asked") or {}
    listed = {q["id"]: q["question"] for q in d.get("questions") or []}
    for qid, a in answers.items():
        q = (asked.get(qid, {}).get("question") or (a.get("question") if isinstance(a, dict) else None)
             or listed.get(qid))
        follows = asked.get(qid, {}).get("follows_up")
        m.append({"role": "agent", "layer": "QUESTION", "id": qid, "title": f"Question {qid}"
                  + (f" (clarifies {follows})" if follows else ""), "text": q or "(question text not recorded)",
                  "criticality": asked.get(qid, {}).get("criticality")})
        m.append({"role": "user", "layer": "USER_ANSWER", "id": qid, "title": f"Your answer to {qid} (verbatim)",
                  "text": _answer_text(a), "received": a.get("received") if isinstance(a, dict) else None})
    a = d.get("analysis")
    if a:
        m.append({"role": "agent", "layer": "AI_INTERPRETATION", "title": "AI interpretation of your words",
                  "text": a.get("summary", ""),
                  "items": [{"id": r["id"], "key": r["key"], "source": r["source"], "answer_id": r.get("answer_id"),
                             "quote": r.get("quote"), "attachment_id": r.get("attachment_id"),
                             "image_evidence": r.get("image_evidence"), "interpretation": r["text"],
                             "value": r.get("value"), "unit": r.get("unit")} for r in a["requirements"]]})
    if d.get("assumptions"):
        m.append({"role": "agent", "layer": "ASSUMPTION", "title": "Engineering assumptions (not stated by you)",
                  "items": [{"id": x["id"], "text": x["text"], "rationale": x.get("rationale", "")}
                            for x in d["assumptions"]]})
    p = d.get("plan")
    if p:
        m.append({"role": "agent", "layer": "ENGINEERING_DECISION", "title": "Engineering plan and decisions",
                  "text": "\n".join(f"{i}. {s}" for i, s in enumerate(p["steps"], 1)),
                  "items": [{"name": k, "value": v["value"], "unit": v["unit"], "source": v["source"],
                             "trace": v["trace"], "rationale": v["rationale"]} for k, v in p["parameters"].items()],
                  "load_case": p.get("load_case"), "manufacturing": p.get("manufacturing")})
    for it in d.get("iterations") or []:
        m.append({"role": "system", "layer": "REVISION", "title": f"Revision loop {it['loop']} ({it['reason']})",
                  "text": str(it.get("changes") or it.get("findings"))})
    if d.get("cad"):
        c = d["cad"]
        m.append({"role": "system", "layer": "CAD", "title": "Fusion 360 CAD build",
                  "text": (f"Built {c['result'].get('component_name')} in '{c['result'].get('document')}'"
                           if c.get("ok") else f"CAD build failed: {c.get('error')}")})
    if d.get("validation"):
        m.append({"role": "agent", "layer": "VALIDATION", "title": "Validation evidence",
                  "items": [{"label": f"{v.get('scope', '?')}_{v['status']}", "status": v["status"],
                             "check_id": v["check_id"], "claim": v.get("claim", ""), "severity": v.get("severity"),
                             "measured": v.get("measured"), "message": v.get("message", "")} for v in d["validation"]]})
    for rv in d.get("reviews") or []:
        m.append({"role": "agent", "layer": "REVIEW", "title": f"Review decision: {rv['decision']}",
                  "text": rv["rationale"]})
    if d.get("registered"):
        r = d["registered"]
        m.append({"role": "agent", "layer": "RESULT", "title": "Component registered",
                  "text": f"{r['id']} rev {r['revision']} registered as CHECKED (concept level). "
                          f"See the report for verified / assumed / not verified items."})
    elif d.get("stop_reason"):
        m.append({"role": "agent", "layer": "RESULT", "title": "Run stopped", "text": d["stop_reason"]})
    # open questions last, where the user is looking
    for q in d.get("questions") or []:
        if q["id"] not in answers and d["status"] == "AWAITING_USER":
            m.append({"role": "agent", "layer": "QUESTION", "id": q["id"], "pending": True,
                      "title": f"Question {q['id']}" + (f" (clarifies {q['follows_up']})" if q.get("follows_up") else ""),
                      "text": q["question"], "criticality": q.get("criticality")})
    return m


def build_run_view(d: dict, store: ProjectStore, busy: bool = False, error: Optional[str] = None) -> dict:
    vals = d.get("validation") or []
    comp = None
    cid = (d.get("registered") or {}).get("id")
    if cid:
        try:
            c = store.get_component(cid)
            comp = {"id": c.id, "name": c.name, "revision": c.revision, "lifecycle": c.lifecycle,
                    "mass_kg": c.derived.get("mass_kg"),
                    "interfaces": [{"id": i.id, "mates_with": i.mates_with,
                                    "hole_geometry": i.hole_geometry_status.value, "mating": i.mating_status.value}
                                   for i in c.interfaces]}
        except KeyError:
            comp = None
    open_q = [q for q in d.get("questions") or []
              if q["id"] not in (d.get("user_answers") or {}) and d["status"] == "AWAITING_USER"]
    reasoning_events = [e["message"] for e in d.get("events", []) if "Reasoning" in e["message"]
                        or "rejected" in e["message"] or "Waiting for reasoning" in e["message"]]
    return {
        "run_id": d["run_id"], "request": d["request"], "created": d.get("created"),
        "stage": d["stage"], "status": d["status"], "busy": busy, "error": error, "loops": d.get("loops", 0),
        "pending_reasoning": d.get("pending") if d["status"] in ("AWAITING_REASONING", "REASONING") else None,
        "open_questions": [{"id": q["id"], "question": q["question"], "criticality": q.get("criticality"),
                            "follows_up": q.get("follows_up")} for q in open_q],
        "pipeline": _pipeline(d),
        "messages": _messages(d),
        "assumptions": [{"id": x["id"], "text": x["text"]} for x in d.get("assumptions") or []],
        "attachments": _attachment_view(d),
        "validation": _validation_summary(vals) if vals else None,
        "component": comp,
        "component_id": cid or d.get("component_id"),
        "has_report": (store.runs_dir / d["run_id"] / "report.md").exists(),
        "has_screenshot": (store.runs_dir / d["run_id"] / "screenshot.png").exists(),
        "reasoning_log": reasoning_events[-8:],
        "events": d.get("events", [])[-30:],
    }
