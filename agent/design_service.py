"""Fast-mode application service for the web UI: starts / continues design runs in a background thread and turns
run.json into a view model. No engineering logic here (that is agent/design_run.py)."""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Optional

from agent.attachments import MAX_IMAGES, decode_upload
from agent.design_run import (DEFAULT_PROJECT, TERMINAL, Orchestrator, create_assembly_rebuild, create_design_run,
                              load_design_run, record_answer, runs_dir)
from vehicle.mirror import staleness
from vehicle.palette import load_palette
from vehicle.store import ProjectStore

VIEWS = ("iso", "front", "top")
REV_ID_RE = re.compile(r"^R\d{2,3}$")
RENDER_ID_RE = re.compile(r"^RD\d{2,3}$")
STRIP = [("PLAN", "Plan"), ("PARTS", "Parts"), ("ASSEMBLE", "Assemble"), ("CHECK", "Check"), ("DONE", "Done")]
_PHASE_INDEX = {"PLAN": 0, "PARTS": 1, "ASSEMBLE": 2, "CHECK": 3, "SCREENSHOT": 3, "DONE": 4}


class DesignService:
    def __init__(self, project: str = DEFAULT_PROJECT, root=None, fusion=None, reasoner_factory=None,
                 background: bool = True, revise_reasoner_factory=None):
        self.store = ProjectStore(project, root=root)
        self.orch = Orchestrator(self.store, fusion=fusion, reasoner_factory=reasoner_factory)
        self._revise_reasoner_factory = revise_reasoner_factory      # rev_dir -> Reasoner (default: claude -p)
        self.background = background
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._worker_run: Optional[str] = None
        self._errors: dict[str, str] = {}

    # ------------------------------------------------------------------ commands
    def busy_run(self) -> Optional[str]:
        return self._worker_run if self._worker and self._worker.is_alive() else None

    def _run_bg(self, run_id: str, fn) -> None:
        """One design run works at a time: Fusion is a single shared application."""
        with self._lock:
            if self.busy_run():
                raise ValueError(f"run {self.busy_run()} is still working; wait for it to finish")
            self._errors.pop(run_id, None)

            def work():
                try:
                    fn()
                except Exception as e:                       # shown in the UI, never swallowed
                    self._errors[run_id] = f"{type(e).__name__}: {e}"
            if not self.background:
                self._worker, self._worker_run = None, None
                work()
                return
            self._worker = threading.Thread(target=work, daemon=True, name=f"design-{run_id}")
            self._worker_run = run_id
            self._worker.start()

    def start(self, brief: str, attachments: Optional[list] = None, visual_review: bool = False) -> str:
        if attachments and len(attachments) > MAX_IMAGES:
            raise ValueError(f"at most {MAX_IMAGES} images per brief")
        if self.busy_run():
            raise ValueError(f"run {self.busy_run()} is still working; wait for it to finish")
        images = [decode_upload(a) for a in attachments or []]
        run = create_design_run(self.store, brief, images=images, entered_via="ui: web interface",
                                visual_review=bool(visual_review))
        self._run_bg(run.id, lambda: self.orch.advance(load_design_run(self.store, run.id)))
        return run.id

    def answer(self, run_id: str, text: str) -> None:
        run = load_design_run(self.store, run_id)
        record_answer(run, text, entered_via="ui: web interface")
        self._run_bg(run_id, lambda: self.orch.advance(load_design_run(self.store, run_id)))

    def resume(self, run_id: str) -> None:
        load_design_run(self.store, run_id)
        self._run_bg(run_id, lambda: self.orch.advance(load_design_run(self.store, run_id)))

    def rebuild(self, run_id: str, part_id: str) -> None:
        run = load_design_run(self.store, run_id)
        if part_id not in (run["parts"] or {}):
            raise KeyError(f"{part_id} is not part of this run")
        self._run_bg(run_id, lambda: self.orch.rebuild(load_design_run(self.store, run_id), part_id))

    def rebuild_mirror(self, run_id: str, part_id: str) -> None:
        """Re-derive a derived (mirror_of) part from its source's latest version, then re-measure + re-shoot."""
        run = load_design_run(self.store, run_id)
        if part_id not in (run["parts"] or {}):
            raise KeyError(f"{part_id} is not part of this run")
        if not self.store.get_part(part_id).derived:
            raise ValueError(f"{part_id} is not a derived part")
        self._run_bg(run_id, lambda: self.orch.rebuild(load_design_run(self.store, run_id), part_id,
                                                       latest_source=True))

    def rebuild_assembly(self, run_id: str) -> str:
        """New run: every registered part of `run_id` rebuilt into a fresh Fusion design (zero Claude calls)."""
        if self.busy_run():
            raise ValueError(f"run {self.busy_run()} is still working; wait for it to finish")
        run = create_assembly_rebuild(self.store, run_id, entered_via="ui: web interface")
        self._run_bg(run.id, lambda: self.orch.advance(load_design_run(self.store, run.id)))
        return run.id

    def recolor(self, run_id: str) -> None:
        """Apply the project palette to the run's open Fusion design (no geometry change), then re-shoot."""
        run = load_design_run(self.store, run_id)
        if run["status"] not in TERMINAL:
            raise ValueError(f"the run is {run['status']}; recolour a finished run")
        load_palette(self.store.root)                        # an invalid palette file is refused here (400)
        self._run_bg(run_id, lambda: self.orch.recolor(load_design_run(self.store, run_id)))

    def render(self, run_id: str, views=None, options: Optional[dict] = None) -> None:
        """Render the run's open Fusion design (default iso, standard preset); progress in the view model."""
        from agent.render_run import parse_options, validate_views
        run = load_design_run(self.store, run_id)
        if run["status"] not in TERMINAL:
            raise ValueError(f"the run is {run['status']}; render a finished run")
        views = validate_views(views or ["iso"])
        opts = parse_options(options, known_environments(run.data))
        self._run_bg(run_id, lambda: self.orch.render(load_design_run(self.store, run_id), views, opts))

    def render_path(self, run_id: str, rd_id: str, view: str) -> Path:
        """<view> = the shown image (cropped when there is a crop), <view>_full = the full render."""
        full = view.endswith("_full")
        view = view[:-5] if full else view
        if not RENDER_ID_RE.match(rd_id or "") or view not in VIEWS:
            raise KeyError(f"no render {rd_id}/{view}")
        run = load_design_run(self.store, run_id)
        rd = next((r for r in run.data.get("renders") or [] if r["id"] == rd_id), None)
        it = next((i for i in (rd or {}).get("items", []) if i["view"] == view and i.get("path")), None)
        rel = (it or {}).get("render_full") if full else (it or {}).get("path")
        if not rel:
            raise KeyError(f"no {view}{'_full' if full else ''} image for render {rd_id}")
        return run.dir / rel

    def _reviser(self):
        from agent.revise import Reviser
        return Reviser(self.store, fusion=self.orch.fusion(), reasoner_factory=self._revise_reasoner_factory)

    def revise(self, run_id: str, target: str, instruction: str) -> None:
        """Revise one part (or 'assembly') of a finished run in its current Fusion design (agent/revise.py)."""
        run = load_design_run(self.store, run_id)
        target, instruction = (target or "").strip(), (instruction or "").strip()
        if not instruction:
            raise ValueError("empty revision instruction")
        if target != "assembly" and target not in (run["parts"] or {}):
            raise KeyError(f"{target} is not part of this run")
        if run["status"] != "DONE":
            raise ValueError(f"the run is {run['status']}; only a finished run can be revised")
        self._run_bg(run_id, lambda: self._reviser().revise(load_design_run(self.store, run_id), target, instruction,
                                                            entered_via="ui: web interface"))

    def revert(self, run_id: str, part_id: str, version) -> None:
        run = load_design_run(self.store, run_id)
        if part_id not in (run["parts"] or {}):
            raise KeyError(f"{part_id} is not part of this run")
        try:
            version = int(version)
        except (TypeError, ValueError):
            raise ValueError("version must be an integer") from None
        if run["status"] != "DONE":
            raise ValueError(f"the run is {run['status']}; only a finished run can be reverted")
        self._run_bg(run_id, lambda: self._reviser().revert(load_design_run(self.store, run_id), part_id, version,
                                                            entered_via="ui: web interface"))

    def revision_image(self, run_id: str, rev_id: str, name: str) -> Path:
        """before_<view>.png / after_<view>.png of one revision."""
        m = re.fullmatch(r"(before|after)_(iso|front|top)", name or "")
        if not REV_ID_RE.match(rev_id or "") or not m:
            raise KeyError(f"no revision image {rev_id}/{name}")
        run = load_design_run(self.store, run_id)
        rev = next((r for r in run.data.get("revisions", []) if r["id"] == rev_id), None)
        rel = ((rev or {}).get("screenshots") or {}).get(m.group(1), {}).get(m.group(2))
        if not rel:
            raise KeyError(f"no {name} image for revision {rev_id}")
        return run.dir / rel

    def _registry(self, d: dict) -> dict:
        """Per part of the run: active registry version and the versions a revert can go back to."""
        out = {}
        stale = staleness(self.store.list_parts())
        for pid in d.get("parts") or {}:
            try:
                rec = self.store.get_part(pid)
            except KeyError:
                continue
            out[pid] = {"active": rec.version, "versions": [h.version for h in rec.history if h.version != rec.version],
                        "derived": stale.get(pid)}
        return out

    # ------------------------------------------------------------------ queries
    def list_runs(self) -> list[dict]:
        out = []
        d = runs_dir(self.store)
        for p in sorted(d.glob("*/run.json"), reverse=True) if d.exists() else []:
            r = load_design_run(self.store, p.parent.name).data
            out.append({"run_id": r["run_id"], "brief": r["brief"][:120], "status": r["status"], "phase": r["phase"],
                        "created": r["created"], "label": run_label(r)})
        return out

    def run_view(self, run_id: str) -> dict:
        d = load_design_run(self.store, run_id).data
        return build_design_view(d, busy=self.busy_run() == run_id, error=self._errors.get(run_id),
                                 registry=self._registry(d))

    def screenshot_path(self, run_id: str, view: str) -> Path:
        if view not in VIEWS:
            raise KeyError(f"no view {view}")
        run = load_design_run(self.store, run_id)
        rel = run["screenshots"].get(view)
        if not rel:
            raise KeyError(f"no {view} screenshot for this run")
        return run.dir / rel

    def summary_text(self, run_id: str) -> str:
        p = load_design_run(self.store, run_id).dir / "summary.md"
        if not p.exists():
            raise KeyError("summary not written yet")
        return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------- view model (presentation only)
def run_label(d: dict) -> str:
    """The run selector's text; the same function feeds the run list and the run view, so the page can tell when
    its cached option is stale (it was: an option loaded while RUNNING kept saying RUNNING after the run finished)."""
    return f"{d['run_id']} · {d['status']}"


def _strip(d: dict) -> list[dict]:
    cur = _PHASE_INDEX.get(d["phase"], 0)
    out = []
    for i, (key, label) in enumerate(STRIP):
        if d["status"] == "DONE" or i < cur:
            state = "done"
        elif i == cur:
            state = {"FAILED": "failed", "AWAITING_USER": "waiting", "BLOCKED_FUSION": "blocked"}.get(d["status"],
                                                                                                     "current")
        else:
            state = "todo"
        item = {"key": key, "label": label, "state": state}
        if key == "PARTS":
            item["chips"] = [{"id": pid, "state": st["state"]} for pid, st in (d.get("parts") or {}).items()] or \
                            [{"id": k["id"], "state": "todo"} for k in d.get("kit", [])]
        out.append(item)
    return out


def _part_rows(d: dict, registry: Optional[dict] = None) -> list[dict]:
    specs = {p["id"]: p for p in (d.get("plan") or {}).get("parts", [])}
    registry = registry or {}
    rows = []
    for pid, st in (d.get("parts") or {}).items():
        sp = specs.get(pid, {})
        rows.append({"id": pid, "name": sp.get("name", pid), "state": st["state"], "version": st.get("version"),
                     "reuse": st.get("reuse", False), "bbox": st.get("bbox"), "dims": sp.get("dims", {}),
                     "position_mm": sp.get("position_mm"), "error": st.get("error"),
                     "attempts": [a["kind"] for a in st.get("attempts", [])],
                     "checks": [{"id": c["check_id"], "status": c["status"], "message": c.get("message", "")}
                                for c in st.get("checks", [])],
                     "fia": [{"article": f["article"], "status": f["status"], "note": f.get("note", ""),
                              "text": f["text"]} for f in st.get("fia", [])],
                     "rebuildable": st["state"] == "done",
                     "revisable": st["state"] == "done" and d["status"] == "DONE",
                     "active_version": (registry.get(pid) or {}).get("active"),
                     "derived": (registry.get(pid) or {}).get("derived") or (
                         {"source_id": st["derived_from"], "mode": st.get("mirror_mode"), "stale": False}
                         if st.get("derived_from") else None),
                     "revert_versions": (registry.get(pid) or {}).get("versions", [])})
    return rows


def _revision_rows(d: dict) -> list[dict]:
    rid = d["run_id"]
    out = []
    for r in d.get("revisions") or []:
        shots = r.get("screenshots") or {}

        def url(which, v, rev_id=r["id"]):
            return f"/api/design/{rid}/revisions/{rev_id}/{which}_{v}.png"
        pairs = [{"view": v, "before": url("before", v) if v in shots.get("before", {}) else None,
                  "after": url("after", v)} for v in VIEWS if v in shots.get("after", {})]
        out.append({"id": r["id"], "target": r["target"], "kind": r["kind"], "instruction": r["instruction"],
                    "state": r["state"], "error": r.get("error"), "created": r.get("created"),
                    "steps": [{k: s.get(k) for k in ("part_id", "kind", "base_version", "new_version",
                                                     "change_summary", "assumptions", "bbox_delta", "bbox_before",
                                                     "bbox_after")} for s in r.get("steps", [])],
                    "neighbour_adjustments": r.get("neighbour_adjustments", []),
                    "mates": [{"title": m["title"], "status": m["status"], "before": m.get("before"),
                               "measured": m.get("measured"), "message": m.get("message", "")}
                              for m in r.get("mates_after", [])],
                    "mate_faces": r.get("mate_faces", []), "notes": r.get("notes", []),
                    "rollback": r.get("rollback"), "counters": r.get("counters"), "pairs": pairs,
                    "stale_run_views": r.get("stale_run_views", []),
                    "events": [e["msg"] for e in r.get("events", [])][-8:]})
    return out


def known_environments(d: dict) -> list:
    """Environment library names as Fusion listed them in the latest render preflight (never guessed)."""
    for r in reversed(d.get("renders") or []):
        envs = (r.get("preflight") or {}).get("environments")
        if envs:
            return [e for e in envs if not e.endswith("...")]          # "Custom..." is a placeholder
    return []


def _render_rows(d: dict) -> list[dict]:
    rid = d["run_id"]
    out = []
    for r in (d.get("renders") or [])[-3:]:
        out.append({"id": r["id"], "status": r["status"], "error": r.get("error"), "created": r.get("created"),
                    "finished": r.get("finished"), "quality": r.get("quality"), "environment": r.get("environment"),
                    "preset": r.get("preset"), "options": r.get("options"), "seconds": r.get("seconds"),
                    "resolution": r.get("resolution"), "script_calls": r.get("script_calls"),
                    "items": [{k: it.get(k) for k in ("view", "state", "progress", "method", "size_bytes", "width",
                                                      "height", "quality", "seconds", "note", "error", "full_size")}
                              | {"url": f"/api/design/{rid}/renders/{r['id']}/{it['view']}.png" if it.get("path")
                                 else None,
                                 "url_full": f"/api/design/{rid}/renders/{r['id']}/{it['view']}_full.png"
                                 if it.get("render_cropped") else None} for it in r.get("items", [])]})
    return out


def build_design_view(d: dict, busy: bool = False, error: Optional[str] = None,
                      registry: Optional[dict] = None) -> dict:
    a = d.get("assembly") or {}
    rid = d["run_id"]
    return {
        "run_id": rid, "run_label": run_label(d), "mode": d.get("mode", "fast"), "source_run": d.get("source_run"),
        "correction": d.get("correction"), "brief": d["brief"], "created": d["created"], "status": d["status"],
        "phase": d["phase"], "busy": busy, "error": error or d.get("error"), "banner": d.get("banner"),
        "strip": _strip(d),
        "log": [e["msg"] for e in d.get("events", [])][-15:],
        "question": {"text": d["question"]["text"]} if d["status"] == "AWAITING_USER" and d.get("question") else None,
        "answer": d.get("answer"),
        "screenshots": {v: f"/api/design/{rid}/screenshots/{v}.png" for v in VIEWS if v in (d.get("screenshots") or {})},
        "parts": _part_rows(d, registry),
        "revisions": _revision_rows(d),
        "revisable": d["status"] == "DONE" and not busy,
        "recolors": [{"id": r["id"], "created": r.get("created"), "error": r.get("error"),
                      "mismatches": r.get("mismatches", []), "notes": r.get("notes", []),
                      "parts": len(r.get("parts") or {}), "script_calls": r.get("script_calls")}
                     for r in d.get("recolors") or []][-3:],
        "renders": _render_rows(d),
        "render_environments": known_environments(d),
        "assumptions": (d.get("plan") or {}).get("assumptions", []),
        "assembly": [{"id": r["check_id"], "title": r["title"], "status": r["status"], "severity": r["severity"],
                      "measured": r.get("measured"), "message": r.get("message", "")} for r in a.get("results", [])],
        "assembly_method": a.get("method"),
        "skipped_mates": a.get("skipped_mates", []),
        "mate_faces": a.get("mate_faces", []),
        "visual_review_issues": d.get("visual_review_issues"),
        "counters": d["counters"],
        "has_summary": d["status"] == "DONE",
        "terminal": d["status"] in TERMINAL,
        "attachments": [{"id": x["id"], "original_name": x["original_name"]} for x in d.get("attachments") or []],
    }
