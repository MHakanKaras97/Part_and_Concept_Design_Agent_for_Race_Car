"""Persistence layer: human-readable JSON files under data/<project_id>/.

data/<project_id>/project.json
data/<project_id>/components/<COMPONENT-ID>.json
data/<project_id>/runs/<run_id>/...            (written by the workflow engine)

Writes are atomic (temp file + os.replace) so a crash never leaves a half-written record.
On Windows, OneDrive sync / antivirus / editors can briefly lock a file; the replace is retried.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from vehicle.models import Component, Project, RevisionEntry, now_iso
from vehicle.parts import PartRecord, next_version

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        _replace_with_retry(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _replace_with_retry(src: str, dst: Path, attempts: int = 20, delay: float = 0.1) -> None:
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay * (1 + i))


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class ProjectStore:
    def __init__(self, project_id: str, root: Path | None = None):
        self.root = (root or DATA_ROOT) / project_id
        self.project_id = project_id

    # ---- project -------------------------------------------------------
    @property
    def project_file(self) -> Path:
        return self.root / "project.json"

    def exists(self) -> bool:
        return self.project_file.exists()

    def load_project(self) -> Project:
        return Project.model_validate(read_json(self.project_file))

    def save_project(self, project: Project) -> None:
        if project.id != self.project_id:
            raise ValueError(f"project id {project.id} does not match store {self.project_id}")
        write_json(self.project_file, project.model_dump(mode="json"))

    # ---- components ----------------------------------------------------
    @property
    def components_dir(self) -> Path:
        return self.root / "components"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def component_path(self, component_id: str) -> Path:
        return self.components_dir / f"{component_id}.json"

    def list_components(self) -> list[Component]:
        if not self.components_dir.exists():
            return []
        out = []
        for p in sorted(self.components_dir.glob("*.json")):
            data = read_json(p)
            if data.get("record_type") != "part":          # fast-mode parts are listed by list_parts()
                out.append(Component.model_validate(data))
        return out

    # ---- free-form parts (fast mode) -------------------------------------
    def list_parts(self) -> list[PartRecord]:
        if not self.components_dir.exists():
            return []
        return [PartRecord.model_validate(d) for d in (read_json(p) for p in sorted(self.components_dir.glob("*.json")))
                if d.get("record_type") == "part"]

    def get_part(self, part_id: str) -> PartRecord:
        p = self.component_path(part_id)
        data = read_json(p) if p.exists() else None
        if not data or data.get("record_type") != "part":
            raise KeyError(f"part {part_id} not found in project {self.project_id}")
        return PartRecord.model_validate(data)

    def save_part(self, part: PartRecord, run_id: str | None, summary: str, force_new: bool = False,
                  kind: str = "", instruction: str = "") -> PartRecord:
        """Register a part; the version is assigned here (see vehicle.parts.next_version).

        A version's record is written once: rebuilding an unchanged part (same script + spec) returns the stored
        record untouched, and before a new version replaces the current file the full previous record is kept as
        components/history/<ID>.v<N>.json (never rewritten once written). force_new: always a new version (revert)."""
        p = self.component_path(part.id)
        previous = None
        if p.exists():
            data = read_json(p)
            if data.get("record_type") != "part":
                raise ValueError(f"{part.id} is a strict-mode component record; refusing to overwrite it")
            previous = PartRecord.model_validate(data)
        rec = next_version(previous, part, run_id, summary, force_new=force_new, kind=kind, instruction=instruction)
        if previous is not None and rec.version == previous.version:
            return previous
        if previous is not None:
            snap = self.part_history_path(part.id, previous.version)
            if not snap.exists():
                write_json(snap, previous.model_dump(mode="json"))
        write_json(p, rec.model_dump(mode="json"))
        return rec

    def part_history_path(self, part_id: str, version: int) -> Path:
        return self.components_dir / "history" / f"{part_id}.v{version}.json"

    def get_part_version(self, part_id: str, version: int) -> PartRecord:
        cur = self.get_part(part_id)
        if cur.version == version:
            return cur
        p = self.part_history_path(part_id, version)
        if not p.exists():
            raise KeyError(f"{part_id} v{version} not in the registry history")
        return PartRecord.model_validate(read_json(p))

    def get_component(self, component_id: str) -> Component:
        p = self.component_path(component_id)
        if not p.exists():
            raise KeyError(f"component {component_id} not found in project {self.project_id}")
        return Component.model_validate(read_json(p))

    def next_component_id(self, prefix: str) -> str:
        nums = [int(c.id.split("-")[1]) for c in self.list_components() if c.id.startswith(prefix + "-")]
        return f"{prefix}-{(max(nums) + 1) if nums else 1:03d}"

    def register(self, component: Component, summary: str, run_id: str | None = None) -> Component:
        """Store a new component (rev 1) or a new revision of an existing one.

        The revision number is assigned here, never by the caller, so history stays consistent.
        Idempotent per run: if the latest revision was written by the same run_id (e.g. the run
        crashed after registering), that revision is rewritten instead of creating a new one.
        """
        component = component.model_copy(deep=True)
        path = self.component_path(component.id)
        if path.exists():
            previous = self.get_component(component.id)
            if run_id and previous.history and previous.history[-1].run_id == run_id:
                component.revision = previous.revision
                component.history = previous.history
                Component.model_validate(component.model_dump())
                write_json(path, component.model_dump(mode="json"))
                return component
            component.revision = previous.revision + 1
            component.history = previous.history + [
                RevisionEntry(revision=component.revision, date=now_iso(), run_id=run_id, summary=summary)]
        else:
            component.revision = 1
            component.history = [RevisionEntry(revision=1, date=now_iso(), run_id=run_id, summary=summary)]
        Component.model_validate(component.model_dump())          # re-validate before writing
        write_json(path, component.model_dump(mode="json"))
        return component
