"""Lean Claude Code calls for fast mode (subscription login, no API key).

    claude -p --system-prompt-file <static prompt> --json-schema <compact schema> --output-format json
              --tools "" --no-session-persistence --strict-mcp-config --disable-slash-commands [--model M]

- The static system prompt REPLACES Claude Code's default one (far fewer input tokens) and is byte-identical across
  all part and repair calls, so the prompt cache serves it after the first call.
- The user message is only the per-call input (part spec, snippets, compact error) - never a conversation history.
- Every call leaves reasoning/NN_<name>.request.txt / .response.json / .meta.json (tokens, duration, model). If the
  response file exists the call is NOT repeated (resumable runs cost no new calls).
- Model: Claude Code's default unless env AGENT_MODEL is set.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Protocol

from agent import fast_config
from agent.reasoning import ClaudeCodeBackend, ReasoningBackendError, Runner, _subprocess_runner
from vehicle.store import atomic_write_text, read_json, write_json

FLAGS = ["--output-format", "json", "--tools", "", "--no-session-persistence", "--strict-mcp-config",
         "--disable-slash-commands"]


class Reasoner(Protocol):
    calls: int

    def call(self, name: str, system: str, user: str, schema: dict, images: Optional[list] = None) -> dict: ...


def _result(out: str) -> dict:
    try:
        ev = json.loads(out)
        if isinstance(ev, dict) and ev.get("type") == "result":
            return ev
    except json.JSONDecodeError:
        pass
    return ClaudeCodeBackend.result_event(out)              # stream / multi-line fallback


class ClaudeFastReasoner:
    def __init__(self, run_dir: Path, executable: str = "claude", model: Optional[str] = None,
                 runner: Optional[Runner] = None, timeout: Optional[float] = None):
        self.dir = Path(run_dir) / "reasoning"
        self.executable = executable
        self.model = model or os.environ.get("AGENT_MODEL") or None
        self._run = runner or _subprocess_runner
        self.timeout = timeout or fast_config.get("CLAUDE_TIMEOUT_S")
        self.calls = 0                                      # calls actually sent to Claude in this process
        self.usage: list[dict] = []

    def _seq(self, name: str) -> Path:
        """Stable file stem: NN_name where NN counts existing requests (resume reuses the same numbering)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        done = sorted(self.dir.glob("*.request.txt"))
        for p in done:                                      # same name already asked -> reuse its slot
            if p.name.split("_", 1)[1] == f"{name}.request.txt":
                return p.with_name(p.name.replace(".request.txt", ""))
        return self.dir / f"{len(done) + 1:02d}_{name}"

    def call(self, name: str, system: str, user: str, schema: dict, images: Optional[list] = None) -> dict:
        """images: [(media_type, bytes)] - only for the optional visual review (stream-json input)."""
        stem = self._seq(name)
        resp = stem.with_name(stem.name + ".response.json")
        if resp.exists():
            return read_json(resp)
        sys_path = self.dir / f"system_{hashlib.sha256(system.encode('utf-8')).hexdigest()[:12]}.md"
        if not sys_path.exists():
            atomic_write_text(sys_path, system)
        atomic_write_text(stem.with_name(stem.name + ".request.txt"), user)
        cmd = [self.executable, "-p", "--system-prompt-file", str(sys_path.resolve()),
               "--json-schema", json.dumps(schema, separators=(",", ":"))] + FLAGS
        stdin = user
        if images:                                         # stream-json carries image blocks
            cmd[cmd.index("--output-format") + 1] = "stream-json"
            cmd += ["--input-format", "stream-json", "--verbose"]
            content = [{"type": "text", "text": user}] + [
                {"type": "image", "source": {"type": "base64", "media_type": mt,
                                             "data": base64.b64encode(data).decode("ascii")}} for mt, data in images]
            stdin = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
        if self.model:
            cmd += ["--model", self.model]
        t0 = time.time()
        self.calls += 1
        try:
            code, out, err = self._run(cmd, stdin, self.dir, self.timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ReasoningBackendError(f"claude -p could not run: {e}") from e
        if code != 0:
            raise ReasoningBackendError(f"claude -p exit {code}: {(err or out)[-300:]}")
        ev = _result(out)
        structured = ev.get("structured_output")
        if ev.get("is_error") or ev.get("subtype") != "success" or not isinstance(structured, dict):
            raise ReasoningBackendError(f"claude -p gave no structured output (subtype={ev.get('subtype')})")
        usage = ev.get("usage") or {}
        meta = {"name": name, "models": list((ev.get("modelUsage") or {}).keys()),
                "duration_s": round(time.time() - t0, 1), "num_turns": ev.get("num_turns"),
                "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
                "reported_cost_usd": ev.get("total_cost_usd"), "system_prompt": sys_path.name}
        write_json(resp, structured)
        write_json(stem.with_name(stem.name + ".meta.json"), meta)
        self.usage.append(meta)
        return structured


class ScriptedReasoner:
    """TEST DOUBLE: answers by call-name prefix (plan / part / repair) from queues; records every call."""

    def __init__(self, responses: dict[str, list]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.log: list[dict] = []
        self.calls = 0

    def call(self, name: str, system: str, user: str, schema: dict, images: Optional[list] = None) -> dict:
        self.calls += 1
        self.log.append({"name": name, "system": system, "user": user, "schema": schema, "images": len(images or [])})
        kind = name.split("_")[0]
        q = self.responses.get(kind) or []
        if not q:
            raise ReasoningBackendError(f"scripted reasoner: no response left for {name}")
        r = q.pop(0)
        if callable(r):
            r = r(name, user)
        if isinstance(r, Exception):
            raise r
        return r
