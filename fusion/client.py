"""Minimal client for Autodesk Fusion's built-in MCP server (streamable HTTP, JSON-RPC 2.0).

Fusion exposes the server at http://127.0.0.1:27182/mcp when enabled under
Preferences > General > API > Fusion MCP Server. The only CAD capability it offers is
`fusion_mcp_execute` with featureType "script": run a Fusion-API Python script whose
run(_context) function's print() output is returned. Everything in fusion/ builds on that.

Result protocol used by our generated scripts: the script prints one line
    @@RESULT@@{...json...}
which this client extracts as ScriptResult.data.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests

DEFAULT_URL = os.environ.get("FUSION_MCP_URL", "http://127.0.0.1:27182/mcp")
RESULT_MARKER = "@@RESULT@@"
PROTOCOL_VERSION = "2025-06-18"


class FusionError(Exception):
    """Base class for Fusion integration failures."""


class FusionUnavailable(FusionError):
    """Fusion is not running, or its MCP server is disabled / unreachable."""


class FusionOutputLost(FusionError):
    """Fusion reported success but the script's @@RESULT@@ line never arrived. Seen live (Fusion 2705.x): the MCP
    add-in wraps sys.stdout/sys.stderr once more on every script call and never unwraps them; after many calls
    printed output is lost. The script may or may not have run - restart the Fusion MCP add-in (or Fusion)."""


class FusionScriptError(FusionError):
    """The script raised inside Fusion. .output holds stdout + traceback returned by Fusion."""

    def __init__(self, message: str, output: str = ""):
        super().__init__(message)
        self.output = output


@dataclass
class ScriptResult:
    output: str                    # full printed output
    data: Optional[dict] = None    # parsed @@RESULT@@ payload, if the script printed one


# transport(url, payload, headers, timeout) -> (status_code, headers_dict, body_text)
Transport = Callable[[str, dict, dict, float], tuple[int, dict, str]]


def _requests_transport(url: str, payload: dict, headers: dict, timeout: float) -> tuple[int, dict, str]:
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise FusionUnavailable(f"Cannot reach Fusion MCP server at {url}: {e}") from e
    return r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.text


def _parse_body(body: str, content_type: str) -> dict:
    if "text/event-stream" in content_type:
        datas = [ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")]
        body = datas[-1] if datas else "{}"
    return json.loads(body) if body.strip() else {}


def extract_result(output: str) -> Optional[dict]:
    for line in reversed(output.splitlines()):
        if line.startswith(RESULT_MARKER):
            return json.loads(line[len(RESULT_MARKER):])
    return None


class FusionMCPClient:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 180.0, transport: Transport | None = None):
        self.url = url
        self.timeout = timeout
        self._transport = transport or _requests_transport
        self._session: Optional[str] = None
        self._next_id = 1

    # ---- protocol -------------------------------------------------------
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._session:
            h["MCP-Session-Id"] = self._session
        return h

    def _rpc(self, method: str, params: dict | None = None, notification: bool = False) -> dict:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            payload["id"] = self._next_id
            self._next_id += 1
        status, headers, body = self._transport(self.url, payload, self._headers(), self.timeout)
        if method == "initialize" and headers.get("mcp-session-id"):
            self._session = headers["mcp-session-id"]
        if notification:
            return {}
        if status >= 400:
            raise FusionUnavailable(f"Fusion MCP HTTP {status}: {body[:300]}")
        msg = _parse_body(body, headers.get("content-type", ""))
        if "error" in msg:
            err = msg["error"]
            raise FusionError(f"MCP error: {err.get('message', err) if isinstance(err, dict) else err}")
        return msg.get("result", {})

    def connect(self) -> dict:
        info = self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                        "clientInfo": {"name": "ai-f1-engineering-agent", "version": "0.1"}})
        self._rpc("notifications/initialized", notification=True)
        return info

    def call_tool(self, name: str, arguments: dict) -> dict:
        if not self._session:
            self.connect()
        try:
            result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        except FusionError as e:
            if "session" not in str(e).lower():
                raise
            self._session = None          # Fusion restarted -> new session, retry once
            self.connect()
            result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", [])
        images = [c for c in content if c.get("type") == "image"]
        if images:
            return {"success": True, "base64Data": images[0].get("data"), "mimeType": images[0].get("mimeType")}
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        if not texts:
            raise FusionError(f"Unexpected tool result from {name}: {str(result)[:300]}")
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            return {"success": not result.get("isError", False), "message": texts[0]}

    # ---- operations -------------------------------------------------------
    def run_script(self, script: str, read_only: bool = False, expect_result: bool = True) -> ScriptResult:
        """Run a script. With expect_result (the default for all our scripts, which print one @@RESULT@@ line),
        a success without that line raises FusionOutputLost instead of returning data=None."""
        obj: dict[str, Any] = {"script": script}
        if read_only:
            obj["readOnly"] = True
        reply = self.call_tool("fusion_mcp_execute", {"featureType": "script", "object": obj})
        if not reply.get("success", False):
            out = str(reply.get("error") or reply.get("message") or reply)
            last = out.strip().splitlines()[-1] if out.strip() else "unknown error"
            raise FusionScriptError(f"Fusion script failed: {last}", output=out)
        output = str(reply.get("message", ""))
        data = extract_result(output)
        if expect_result and data is None:
            raise FusionOutputLost(f"Fusion reported success but returned no {RESULT_MARKER} line "
                                   f"({len(output)} chars of output); restart the Fusion MCP add-in")
        return ScriptResult(output=output, data=data)

    def screenshot(self, direction: str = "iso-top-right", width: int = 1200, height: int = 800) -> bytes:
        reply = self.call_tool("fusion_mcp_read", {"queryType": "screenshot", "direction": direction,
                                                   "width": width, "height": height,
                                                   "transparentBackground": False})
        data = reply.get("base64Data")
        if not data:
            raise FusionError(f"Screenshot returned no image data: {str(reply)[:200]}")
        return base64.b64decode(data)

    def undo(self) -> dict:
        return self.call_tool("fusion_mcp_update", {"featureType": "undo"})

    def ping(self) -> dict:
        """Read-only connectivity check: Fusion version and active document."""
        script = (
            "import adsk.core, adsk.fusion, json\n"
            "def run(_context: str):\n"
            "    app = adsk.core.Application.get()\n"
            "    doc = app.activeDocument\n"
            "    d = adsk.fusion.Design.cast(app.activeProduct)\n"
            f"    print('{RESULT_MARKER}' + json.dumps({{'fusion_version': app.version,"
            " 'active_document': doc.name if doc else None, 'has_design': d is not None}))\n"
        )
        return self.run_script(script, read_only=True).data or {}
