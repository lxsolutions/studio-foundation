"""bforge MCP server — stdio JSON-RPC, stdlib only.

    python tools/bforge/bforge/mcp_server.py [--workdir DIR] [--out DIR] [--tools grouped|full]

Two exposure modes, because 89 ops is more than most MCP clients handle well:

**grouped** (default) — five tools: discover, describe, run, run_batch, session.
Small tool list, full discoverability, and `bforge_run_batch` lets an agent build
an entire asset in a single round trip instead of ten.

**full** — every op as its own MCP tool, for clients that prefer native schema
validation and can cope with a large tool list.

The Blender daemon starts lazily on the first op, so `tools/list` at client
startup stays instant.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import schema as schema_mod  # noqa: E402
from bforge.client import DaemonError, Forge, ForgeError  # noqa: E402

SERVER_NAME = "bforge"
SERVER_VERSION = "0.1.0"
SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

GROUPED_TOOLS = [
    {
        "name": "bforge_ops",
        "description": (
            "List available bforge operations with one-line summaries. Filter by tag "
            "(prop, kit, env, char, build, material, uv, gameready, render, check, export) "
            "or by a search string. Start here if you are not sure what exists."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "Filter by tag"},
                "search": {"type": "string", "description": "Substring of the op name or summary"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "bforge_describe",
        "description": (
            "Full parameter schema, types and defaults for one or more ops. Call this "
            "before using an op you have not used before."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ops": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Op names, e.g. ['prop.crate', 'export.asset']",
                }
            },
            "required": ["ops"],
            "additionalProperties": False,
        },
    },
    {
        "name": "bforge_run",
        "description": (
            "Run one bforge operation in the live Blender session. Scene state persists "
            "between calls, so ops compose. Returns the op's structured result plus any "
            "advisory notes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "op": {"type": "string", "description": "Dotted op name, e.g. 'prop.barrel'"},
                "args": {"type": "object", "description": "Op arguments"},
                "timeout": {
                    "type": "number",
                    "description": "Seconds before giving up (renders and bakes need more)",
                },
            },
            "required": ["op"],
            "additionalProperties": False,
        },
    },
    {
        "name": "bforge_run_batch",
        "description": (
            "Run several ops in order in one round trip. This is the efficient way to build "
            "an asset: reset, generate, unwrap, collide, render, export — all in one call. "
            "Stops at the first failure unless continue_on_error is set."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "Ordered steps, each {op, args}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string"},
                            "args": {"type": "object"},
                        },
                        "required": ["op"],
                    },
                },
                "continue_on_error": {"type": "boolean", "default": False},
                "timeout": {"type": "number", "description": "Per-step timeout in seconds"},
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
    {
        "name": "bforge_session",
        "description": (
            "Inspect or control the Blender session: status shows what is loaded, reset "
            "clears the scene, restart replaces the Blender process (use if it becomes "
            "unresponsive)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "reset", "restart", "stop"],
                    "default": "status",
                }
            },
            "additionalProperties": False,
        },
    },
]


class Server:
    def __init__(self, workdir=None, out_dir=None, mode="grouped", blender=None):
        self.mode = mode
        self.forge = Forge(blender=blender, workdir=workdir, out_dir=out_dir)
        self._catalog: list[dict] | None = None

    # -- catalogue ------------------------------------------------------
    def catalog(self) -> list[dict]:
        """Prefer the committed snapshot; fall back to asking a live Blender."""
        if self._catalog is None:
            try:
                self._catalog = schema_mod.load_catalog()
            except (FileNotFoundError, json.JSONDecodeError):
                self._catalog = self.forge.catalog()
        return self._catalog

    def tools(self) -> list[dict]:
        if self.mode == "full":
            return schema_mod.to_mcp_tools(self.catalog())
        return GROUPED_TOOLS

    # -- dispatch -------------------------------------------------------
    def call(self, name: str, arguments: dict) -> tuple[bool, str]:
        try:
            if self.mode == "full" and name not in {t["name"] for t in GROUPED_TOOLS}:
                return self._run(name.replace("_", ".", 1), arguments, None)
            if name == "bforge_ops":
                rows = schema_mod.compact(
                    self.catalog(), arguments.get("tag", ""), arguments.get("search", "")
                )
                return False, json.dumps({"ops": rows, "count": len(rows)}, indent=2)
            if name == "bforge_describe":
                wanted = set(arguments.get("ops") or [])
                found = [o for o in self.catalog() if o["name"] in wanted]
                missing = sorted(wanted - {o["name"] for o in found})
                payload: dict = {"ops": found}
                if missing:
                    payload["not_found"] = missing
                    payload["hint"] = "Call bforge_ops to list valid names."
                return bool(missing and not found), json.dumps(payload, indent=2)
            if name == "bforge_run":
                return self._run(
                    arguments.get("op", ""), arguments.get("args") or {}, arguments.get("timeout")
                )
            if name == "bforge_run_batch":
                return self._batch(arguments)
            if name == "bforge_session":
                return self._session(arguments.get("action", "status"))
            return True, json.dumps({"error": f"unknown tool '{name}'"})
        except DaemonError as exc:
            return True, json.dumps(
                {
                    "error": str(exc),
                    "kind": "daemon",
                    "recovery": "Call bforge_session action='restart'. Scene state is lost; "
                    "rebuild from session.reset.",
                }
            )
        except Exception as exc:  # noqa: BLE001 — never kill the server on a tool error
            return True, json.dumps({"error": f"{type(exc).__name__}: {exc}", "kind": "server"})

    def _run(self, op: str, args: dict, timeout) -> tuple[bool, str]:
        if not op:
            return True, json.dumps({"error": "missing 'op'"})
        try:
            result = self.forge.call(op, _timeout=timeout, **args)
        except ForgeError as exc:
            return True, json.dumps({"error": str(exc), "op": op, "kind": exc.kind}, indent=2)
        return False, json.dumps({"op": op, "result": result}, indent=2, default=str)

    def _batch(self, arguments: dict) -> tuple[bool, str]:
        steps = arguments.get("steps") or []
        if not isinstance(steps, list) or not steps:
            return True, json.dumps({"error": "'steps' must be a non-empty array"})
        keep_going = bool(arguments.get("continue_on_error"))
        timeout = arguments.get("timeout")
        results = []
        failed = False
        for index, step in enumerate(steps):
            op = (step or {}).get("op", "")
            args = (step or {}).get("args") or {}
            try:
                results.append(
                    {
                        "step": index,
                        "op": op,
                        "ok": True,
                        "result": self.forge.call(op, _timeout=timeout, **args),
                    }
                )
            except ForgeError as exc:
                failed = True
                results.append({"step": index, "op": op, "ok": False, "error": str(exc)})
                if not keep_going:
                    results.append(
                        {
                            "step": index + 1,
                            "skipped": len(steps) - index - 1,
                            "reason": "stopped at first failure; pass continue_on_error to override",
                        }
                    )
                    break
        return failed, json.dumps({"steps": results}, indent=2, default=str)

    def _session(self, action: str) -> tuple[bool, str]:
        if action == "reset":
            return self._run("session.reset", {}, None)
        if action == "restart":
            info = self.forge.restart()
            return False, json.dumps({"restarted": True, "daemon": info}, indent=2)
        if action == "stop":
            self.forge.stop()
            return False, json.dumps({"stopped": True})
        running = self.forge.process is not None and self.forge.process.poll() is None
        payload = {
            "daemon_running": running,
            "blender": self.forge.info.get("blender"),
            "workdir": str(self.forge.workdir),
            "out_dir": str(self.forge.out_dir),
            "ops": len(self.catalog()),
            "exposure_mode": self.mode,
        }
        if running:
            try:
                payload["scene"] = self.forge.call("session.info")
            except (ForgeError, DaemonError):
                pass
        return False, json.dumps(payload, indent=2, default=str)


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------


def _result(request_id, payload):
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_message(server: Server, message: dict):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(
            message.get("id") if isinstance(message, dict) else None,
            INVALID_REQUEST,
            "not a JSON-RPC 2.0 message",
        )
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        requested = str(params.get("protocolVersion", SUPPORTED_VERSIONS[0]))
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return _result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": schema_mod.PRIMER,
            },
        )
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": server.tools()})
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            return _error(request_id, INVALID_PARAMS, "params.name must be a string")
        # Validate BEFORE defaulting: `arguments: []` is falsy, so `or {}` would
        # quietly accept a malformed request as an empty one.
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _error(request_id, INVALID_PARAMS, "params.arguments must be an object")
        is_error, text = server.call(name, arguments)
        return _result(
            request_id, {"content": [{"type": "text", "text": text}], "isError": is_error}
        )
    if "id" not in message:
        return None
    return _error(request_id, METHOD_NOT_FOUND, f"method not supported: {method}")


def serve_stdio(server: Server) -> int:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    try:
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
                stdout.write((json.dumps(_error(None, PARSE_ERROR, "parse error")) + "\n").encode())
                stdout.flush()
                continue
            response = handle_message(server, message)
            if response is not None:
                stdout.write((json.dumps(response, default=str) + "\n").encode("utf-8"))
                stdout.flush()
    finally:
        server.forge.stop()


def self_check(server: Server) -> int:
    """Registry + dispatch sanity with no Blender process and no network."""
    tools = server.tools()
    assert tools, "no tools exposed"
    for tool in tools:
        assert tool["name"] and tool["inputSchema"]["type"] == "object"
    init = handle_message(
        server,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
    )
    assert init and init["result"]["serverInfo"]["name"] == SERVER_NAME
    unknown = handle_message(server, {"jsonrpc": "2.0", "id": 2, "method": "bogus/method"})
    assert unknown and unknown["error"]["code"] == METHOD_NOT_FOUND
    is_error, text = server.call("bforge_ops", {"tag": "prop"})
    assert not is_error and json.loads(text)["count"] > 0
    is_error, text = server.call("bforge_describe", {"ops": ["prop.crate"]})
    assert not is_error and json.loads(text)["ops"][0]["name"] == "prop.crate"
    is_error, _text = server.call("bogus_tool", {})
    assert is_error
    print(f"bforge-mcp self-check ok ({len(tools)} tools, {len(server.catalog())} ops)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="bforge MCP server (stdio)")
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--blender", default=None)
    parser.add_argument("--tools", choices=["grouped", "full"], default="grouped")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args(argv)

    server = Server(workdir=args.workdir, out_dir=args.out, mode=args.tools, blender=args.blender)
    if args.self_check:
        return self_check(server)
    return serve_stdio(server)


if __name__ == "__main__":
    sys.exit(main())
