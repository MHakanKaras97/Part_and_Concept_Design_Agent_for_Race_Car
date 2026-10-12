"""Reasoning layer interface (AI-provider agnostic).

The workflow engine never talks to a specific AI. It creates a ReasoningTask (instructions,
context, JSON schema of the expected answer) and asks a ReasoningBackend for a response.
The response is validated with pydantic before the engine uses it.

Backends (all implement `request(task) -> dict | None`):
  * FileExchangeBackend - writes the task to the run folder and waits for a response file. Any reasoner
    can answer: a Claude Code session, a human, another tool. (MVP 1.0/1.1 default, CLI default, UI fallback.)
  * ClaudeCodeBackend - runs Claude Code non-interactively (`claude -p --json-schema ... --output-format json`,
    all tools disabled) and returns its structured output. Uses the local Claude Code login; no API key.
  * FallbackBackend - tries a primary backend and falls back to another when the primary is unavailable.
  * An API backend (planned) - would implement the same `request()`; no engine or UI change needed.
Every backend leaves the same audit trail in reasoning/: NN_kind.request.md/.json and NN_kind.response.json
(+ NN_kind.meta.json for automatic backends: which reasoner answered, model, duration).
"""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from vehicle.models import Assumption, Manufacturing, MissingInfo, ParamSource, Requirement
from vehicle.store import read_json, write_json, atomic_write_text

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


# --------------------------------------------------------------------------
# Response schemas (what the reasoner must return)
# --------------------------------------------------------------------------
class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisResponse(Strict):
    component_type: str = Field(description="Generator id that fits the request, e.g. 'l_bracket', or 'unsupported'")
    summary: str
    requirements: list[Requirement]
    missing_information: list[MissingInfo]
    assumptions: list[Assumption]


class PlannedParam(Strict):
    value: float
    unit: Literal["mm", "deg", "N", "kg", "count", ""]
    source: ParamSource
    trace: list[str] = Field(default_factory=list)
    rationale: str


class LoadCase(Strict):
    description: str
    force_n: float = Field(ge=0)
    lever_arm_mm: float = Field(ge=0)
    required_safety_factor: float = Field(gt=0)
    trace: list[str]


class PlannedPlacement(Strict):
    """Pose of the component's local frame in the project coordinate system (vehicle.models.Pose convention)."""
    position_mm: list[float] = Field(min_length=3, max_length=3, description="Origin of the local frame (x, y, z) in mm")
    rotation_deg: list[float] = Field(min_length=3, max_length=3,
                                      description="(roll, pitch, yaw) in degrees about X, Y, Z; R = Rz(yaw)·Ry(pitch)·Rx(roll)")
    source: ParamSource
    trace: list[str] = Field(default_factory=list)
    rationale: str


class PlanResponse(Strict):
    generator: str
    component_name: str
    steps: list[str]
    parameters: dict[str, PlannedParam]
    design_inputs: dict[str, Optional[str]] = Field(
        description="Non-numeric generator inputs, e.g. base_fastener, upright_fastener, base_mates_with, upright_mates_with")
    manufacturing: Manufacturing
    load_case: LoadCase
    new_assumptions: list[Assumption] = Field(default_factory=list)
    verification_plan: list[str]
    placement: Optional[PlannedPlacement] = Field(
        default=None, description="Only if the user specified where the component is placed; omitted = identity pose")


class ReviewResponse(Strict):
    decision: Literal["ACCEPT", "REVISE", "STOP"]
    rationale: str
    parameter_changes: dict[str, PlannedParam] = Field(default_factory=dict)
    new_assumptions: list[Assumption] = Field(default_factory=list)


RESPONSE_MODELS = {"analysis": AnalysisResponse, "plan": PlanResponse, "review": ReviewResponse}


# --------------------------------------------------------------------------
# Task + backends
# --------------------------------------------------------------------------
class ReasoningTask(Strict):
    run_id: str
    seq: int                         # increasing number of reasoning requests within a run
    kind: Literal["analysis", "plan", "review"]
    instructions: str
    context: dict
    response_schema: dict
    attachments: list[dict] = Field(default_factory=list)   # image records of the run (file relative to run dir)

    @property
    def stem(self) -> str:
        return f"{self.seq:02d}_{self.kind}"


def make_task(run_id: str, seq: int, kind: str, context: dict, attachments: Optional[list] = None) -> ReasoningTask:
    instructions = (PROMPTS_DIR / "common.md").read_text(encoding="utf-8") + "\n\n" + \
        (PROMPTS_DIR / f"{kind}.md").read_text(encoding="utf-8")
    return ReasoningTask(run_id=run_id, seq=seq, kind=kind, instructions=instructions, context=context,
                         response_schema=RESPONSE_MODELS[kind].model_json_schema(), attachments=attachments or [])


def _attachment_lines(task: ReasoningTask, for_files: bool) -> str:
    if not task.attachments:
        return ""
    lines = ["## Attached images (user-supplied source evidence)", ""]
    for a in task.attachments:
        where = f"file ../{a['file']}" if for_files else "attached to this message"
        lines.append(f"- {a['id']}: '{a['original_name']}' ({a['media_type']}, sha256 {a['sha256'][:12]}...) - {where}")
    lines += ["", "Anything you read from an image is IMAGE evidence (source IMAGE, attachment_id, image_evidence),",
              "never the user's words and never a user answer.", ""]
    return "\n".join(lines) + "\n"


class ReasoningBackend(Protocol):
    def request(self, task: ReasoningTask) -> Optional[dict]:
        """Return the raw response dict, or None if the answer is not available yet."""


class ReasoningBackendError(Exception):
    """An automatic backend could not produce a response (unavailable, failed, no structured output)."""


class FileExchangeBackend:
    """reasoning/<NN>_<kind>.request.md  (+ .request.json)  ->  reasoning/<NN>_<kind>.response.json"""

    name = "file_exchange"

    def __init__(self, run_dir: Path):
        self.dir = run_dir / "reasoning"
        self.last_source = "file_exchange (external reasoner)"

    def request_path(self, task: ReasoningTask) -> Path:
        return self.dir / f"{task.stem}.request.md"

    def response_path(self, task: ReasoningTask) -> Path:
        return self.dir / f"{task.stem}.response.json"

    def request(self, task: ReasoningTask) -> Optional[dict]:
        resp = self.response_path(task)
        if resp.exists():
            return read_json(resp)
        if not self.request_path(task).exists():
            write_json(self.dir / f"{task.stem}.request.json", task.model_dump())
            atomic_write_text(self.request_path(task), render_task_markdown(task, resp.name))
        return None


def render_task_markdown(task: ReasoningTask, response_name: str) -> str:
    return (
        f"# Reasoning task {task.stem} (run {task.run_id})\n\n"
        f"Write your answer as JSON to `{response_name}` in this folder, then run:\n\n"
        f"    python -m agent step {task.run_id}\n\n"
        f"---\n\n{task.instructions}\n\n---\n\n{_attachment_lines(task, True)}## Context\n\n```json\n"
        f"{json.dumps(task.context, indent=2, ensure_ascii=False)}\n```\n\n"
        f"## Response JSON schema\n\n```json\n{json.dumps(task.response_schema, indent=2)}\n```\n"
    )


def render_prompt(task: ReasoningTask) -> str:
    """Prompt for automatic backends: instructions + context. The schema is enforced separately."""
    return (f"{task.instructions}\n\n{_attachment_lines(task, False)}## Context\n\n```json\n"
            f"{json.dumps(task.context, indent=2, ensure_ascii=False)}\n```\n\n"
            "Return your answer as the structured output only.")


# runner(cmd, prompt, cwd, timeout) -> (returncode, stdout, stderr)
Runner = Callable[[list, str, Path, float], tuple]


def _subprocess_runner(cmd: list, prompt: str, cwd: Path, timeout: float) -> tuple:
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=cwd,
                       timeout=timeout, shell=False)
    return p.returncode, p.stdout, p.stderr


# stream-json in/out lets the prompt carry image blocks; Claude Code requires --verbose for stream-json output.
CLAUDE_FLAGS = ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--tools", "",
                "--no-session-persistence", "--strict-mcp-config"]


class ClaudeCodeBackend:
    """Claude Code in non-interactive mode as the reasoner.

    Verified 2026-10-05 with Claude Code 2.1.289: `claude -p --json-schema <schema>` returns the validated object
    in the `structured_output` field of the result event. Input/output use stream-json so the user message can
    carry image blocks (attachments are read from the run folder and hash-checked). All tools are
    disabled (`--tools ""`), so the reasoner can only answer: it cannot read or change files, run code or
    reach Fusion. The engine still validates and gates every response.
    """

    name = "claude_code"

    def __init__(self, run_dir: Path, executable: str = "claude", model: Optional[str] = None,
                 timeout: float = 900.0, runner: Optional[Runner] = None):
        self.dir = run_dir / "reasoning"
        self.executable = executable
        self.model = model
        self.timeout = timeout
        self._run = runner or _subprocess_runner
        self.last_source = "claude_code"

    @staticmethod
    def available(executable: str = "claude") -> tuple:
        if not shutil.which(executable):
            return False, f"'{executable}' not found on PATH"
        try:
            p = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"'{executable} --version' failed: {e}"
        if p.returncode != 0:
            return False, f"'{executable} --version' exit {p.returncode}"
        return True, p.stdout.strip()

    def command(self, task: ReasoningTask) -> list:
        cmd = [self.executable, "-p", "--json-schema", json.dumps(task.response_schema)] + CLAUDE_FLAGS
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def stream_input(self, task: ReasoningTask) -> str:
        """One stream-json user message: the prompt text plus one image block per attachment."""
        from agent.attachments import load_attachment
        content: list = [{"type": "text", "text": render_prompt(task)}]
        run_dir = self.dir.parent
        for a in task.attachments:
            try:
                data = load_attachment(run_dir, a)
            except (OSError, ValueError) as e:
                raise ReasoningBackendError(f"attachment {a.get('id')} unavailable: {e}") from e
            content.append({"type": "image", "source": {"type": "base64", "media_type": a["media_type"],
                                                        "data": base64.b64encode(data).decode("ascii")}})
        return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"

    @staticmethod
    def result_event(out: str) -> dict:
        for line in reversed(out.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict) and ev.get("type") == "result":
                return ev
        raise ReasoningBackendError(f"claude -p produced no result event: {out[:200]}")

    def request(self, task: ReasoningTask) -> Optional[dict]:
        resp_path = self.dir / f"{task.stem}.response.json"
        if resp_path.exists():                              # already answered (by any backend)
            return read_json(resp_path)
        write_json(self.dir / f"{task.stem}.request.json", task.model_dump())
        atomic_write_text(self.dir / f"{task.stem}.request.md", render_task_markdown(task, resp_path.name))
        t0 = time.time()
        try:
            code, out, err = self._run(self.command(task), self.stream_input(task), self.dir, self.timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ReasoningBackendError(f"claude -p could not run: {e}") from e
        if code != 0:
            raise ReasoningBackendError(f"claude -p exit {code}: {(err or out)[-300:]}")
        env = self.result_event(out)
        structured = env.get("structured_output")
        if env.get("is_error") or env.get("subtype") != "success" or not isinstance(structured, dict):
            raise ReasoningBackendError(f"claude -p gave no structured output (subtype={env.get('subtype')}, "
                                        f"is_error={env.get('is_error')})")
        models = list((env.get("modelUsage") or {}).keys())
        write_json(resp_path, structured)
        write_json(self.dir / f"{task.stem}.meta.json", {
            "answered_by": "claude_code",
            "command": "claude -p --json-schema <schema> " + " ".join(f if f else '""' for f in CLAUDE_FLAGS)
                       + (f" --model {self.model}" if self.model else ""),
            "attachments_sent": [a["id"] for a in task.attachments],
            "models": models, "duration_s": round(time.time() - t0, 1), "num_turns": env.get("num_turns"),
            "reported_cost_usd": env.get("total_cost_usd")})          # no session id (not needed, private)
        self.last_source = f"claude_code ({', '.join(models) or 'unknown model'})"
        return structured


class FallbackBackend:
    """Use `primary`; if it raises ReasoningBackendError, hand the task to `fallback` (e.g. file exchange)."""

    def __init__(self, primary, fallback):
        self.primary, self.fallback = primary, fallback
        self.name = f"{primary.name}+{fallback.name}"
        self.last_source = primary.name
        self.last_error: Optional[str] = None

    def request(self, task: ReasoningTask) -> Optional[dict]:
        self.last_error = None
        try:
            resp = self.primary.request(task)
            self.last_source = self.primary.last_source
            return resp
        except ReasoningBackendError as e:
            self.last_error = f"{self.primary.name} unavailable: {e}"
            self.last_source = self.fallback.last_source
            return self.fallback.request(task)
