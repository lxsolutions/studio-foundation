"""MCP stdio server core: JSON-RPC 2.0, newline-delimited, over stdin/stdout.

Implements the subset of the Model Context Protocol needed for tools-only
servers (initialize / initialized / ping / tools/list / tools/call). Written
against protocol revision 2025-06-18; older revisions in SUPPORTED_VERSIONS
are accepted for compatibility. Stdlib only, by policy (auditable, offline).
"""

from __future__ import annotations

import json
import sys

from studio_tools.mcp import tools

SERVER_NAME = "studio-mcp"
SERVER_VERSION = "0.1.0"
SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


def _result(request_id, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_message(message: dict) -> dict | None:
    """Dispatch one JSON-RPC message. Returns the response dict, or None for
    notifications (no id) and unknown notifications."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(message.get("id") if isinstance(message, dict) else None,
                      INVALID_REQUEST, "not a JSON-RPC 2.0 message")
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    is_notification = "id" not in message

    if method == "initialize":
        requested = str(params.get("protocolVersion", SUPPORTED_VERSIONS[0]))
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return _result(request_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Narrow, allowlisted studio operations. Paths are repository-relative. "
                "No shell access; long engine builds run via `just` in a terminal."
            ),
        })
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": tools.list_tools()})
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            return _error(request_id, INVALID_PARAMS, "params.name must be a string")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _error(request_id, INVALID_PARAMS, "params.arguments must be an object")
        is_error, text = tools.call_tool(name, arguments)
        return _result(request_id, {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        })
    if is_notification:
        return None
    return _error(request_id, METHOD_NOT_FOUND, f"method not supported: {method}")


def serve_stdio() -> int:
    """Blocking read loop: one JSON-RPC message per line."""
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        line = stdin.readline()
        if not line:
            return 0
        stripped = line.strip()
        if not stripped:
            continue
        try:
            message = json.loads(stripped.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            response = _error(None, PARSE_ERROR, "parse error")
            stdout.write((json.dumps(response) + "\n").encode("utf-8"))
            stdout.flush()
            continue
        response = handle_message(message)
        if response is not None:
            stdout.write((json.dumps(response) + "\n").encode("utf-8"))
            stdout.flush()


def self_check() -> int:
    """Registry + dispatch sanity without touching the network or subprocesses."""
    listed = tools.list_tools()
    assert len(listed) >= 20, f"expected >=20 tools, got {len(listed)}"
    for tool in listed:
        assert tool["name"] and tool["inputSchema"]["type"] == "object"
    init = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18"}})
    assert init and init["result"]["serverInfo"]["name"] == SERVER_NAME
    unknown = handle_message({"jsonrpc": "2.0", "id": 2, "method": "bogus/method"})
    assert unknown and unknown["error"]["code"] == METHOD_NOT_FOUND
    bad_tool = handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                               "params": {"name": "not_a_tool", "arguments": {}}})
    assert bad_tool and bad_tool["result"]["isError"] is True
    print(f"studio-mcp self-check ok ({len(listed)} tools)")
    return 0
