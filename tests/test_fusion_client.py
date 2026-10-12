"""Protocol-level tests of the MCP client against a fake HTTP transport (no Fusion needed)."""
import json

import pytest

from fusion.client import (FusionError, FusionMCPClient, FusionOutputLost, FusionScriptError, FusionUnavailable,
                           extract_result)


class FakeTransport:
    def __init__(self, tool_reply):
        self.tool_reply = tool_reply
        self.calls = []

    def __call__(self, url, payload, headers, timeout):
        self.calls.append((payload, dict(headers)))
        m = payload["method"]
        if m == "initialize":
            return 200, {"mcp-session-id": "S1", "content-type": "application/json"}, json.dumps(
                {"jsonrpc": "2.0", "id": payload["id"], "result": {"serverInfo": {"name": "fake"}}})
        if m == "notifications/initialized":
            return 202, {}, ""
        if headers.get("MCP-Session-Id") != "S1":
            return 200, {"content-type": "application/json"}, json.dumps(
                {"jsonrpc": "2.0", "id": payload["id"], "error": {"code": -32600, "message": "Session not initialized"}})
        return 200, {"content-type": "application/json"}, json.dumps(
            {"jsonrpc": "2.0", "id": payload["id"], "result": {"content": [self.tool_reply]}})


def test_session_handshake_and_result_extraction():
    out = 'hello\n@@RESULT@@{"a": 1}\n'
    t = FakeTransport({"type": "text", "text": json.dumps({"success": True, "message": out})})
    c = FusionMCPClient(transport=t)
    r = c.run_script("def run(_context: str): pass", read_only=True)
    assert r.data == {"a": 1} and "hello" in r.output
    methods = [p["method"] for p, _ in t.calls]
    assert methods == ["initialize", "notifications/initialized", "tools/call"]
    args = t.calls[-1][0]["params"]["arguments"]
    assert args["featureType"] == "script" and args["object"]["readOnly"] is True


def test_script_failure_raises_with_traceback():
    t = FakeTransport({"type": "text", "text": json.dumps(
        {"success": False, "error": "Traceback ...\nRuntimeError: 3 : over constrained\n"})})
    with pytest.raises(FusionScriptError) as e:
        FusionMCPClient(transport=t).run_script("x")
    assert "over constrained" in str(e.value) and "Traceback" in e.value.output


def test_unreachable_server_maps_to_unavailable():
    def down(*a):
        raise FusionUnavailable("refused")
    with pytest.raises(FusionUnavailable):
        FusionMCPClient(transport=down).ping()


def test_http_error_maps_to_unavailable():
    with pytest.raises(FusionUnavailable):
        FusionMCPClient(transport=lambda *a: (500, {}, "boom")).connect()


def test_image_content_returned_for_screenshot():
    import base64
    t = FakeTransport({"type": "image", "mimeType": "image/png", "data": base64.b64encode(b"PNG").decode()})
    assert FusionMCPClient(transport=t).screenshot() == b"PNG"


def test_unexpected_result_raises():
    t = FakeTransport({"type": "resource"})
    with pytest.raises(FusionError):
        FusionMCPClient(transport=t).run_script("x")


def test_extract_result_takes_last_marker_line():
    assert extract_result('@@RESULT@@{"a":1}\n@@RESULT@@{"a":2}') == {"a": 2}
    assert extract_result("no marker") is None


def test_success_without_result_line_raises_output_lost():
    """Live Fusion 2705.x: the MCP add-in's stdout wrapper leak makes scripts return success with an empty message."""
    for message in ("", "some text but no marker"):
        t = FakeTransport({"type": "text", "text": json.dumps({"success": True, "message": message})})
        with pytest.raises(FusionOutputLost):
            FusionMCPClient(transport=t).run_script("x")


def test_output_lost_is_a_fusion_error_and_opt_out_returns_none():
    assert issubclass(FusionOutputLost, FusionError) and not issubclass(FusionOutputLost, FusionScriptError)
    t = FakeTransport({"type": "text", "text": json.dumps({"success": True, "message": ""})})
    assert FusionMCPClient(transport=t).run_script("x", expect_result=False).data is None
