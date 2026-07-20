"""MCP JSON-RPC protocol behaviour tests (in-process dispatch)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pylib"))

from studio_tools.mcp import server_core  # noqa: E402


def rpc(method: str, params: dict | None = None, request_id: int | None = 1) -> dict | None:
    message: dict = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    return server_core.handle_message(message)


class Lifecycle(unittest.TestCase):
    def test_initialize_negotiates_version(self):
        response = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "studio-mcp")
        self.assertIn("tools", result["capabilities"])

    def test_initialize_unknown_version_falls_back(self):
        response = rpc("initialize", {"protocolVersion": "1999-01-01"})
        self.assertIn(response["result"]["protocolVersion"], server_core.SUPPORTED_VERSIONS)

    def test_initialized_notification_silent(self):
        self.assertIsNone(rpc("notifications/initialized", request_id=None))

    def test_ping(self):
        self.assertEqual(rpc("ping")["result"], {})


class ToolsSurface(unittest.TestCase):
    def test_tools_list_shape(self):
        result = rpc("tools/list")["result"]
        self.assertGreaterEqual(len(result["tools"]), 20)
        for tool in result["tools"]:
            self.assertTrue(tool["name"])
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_tools_call_unknown_tool_is_tool_error(self):
        response = rpc("tools/call", {"name": "nope", "arguments": {}})
        self.assertTrue(response["result"]["isError"])

    def test_tools_call_bad_params_shape(self):
        response = rpc("tools/call", {"name": 42})
        self.assertEqual(response["error"]["code"], server_core.INVALID_PARAMS)
        response = rpc("tools/call", {"name": "studio_get_status", "arguments": []})
        self.assertEqual(response["error"]["code"], server_core.INVALID_PARAMS)

    def test_fast_tool_roundtrip(self):
        response = rpc("tools/call", {"name": "studio_list_projects", "arguments": {}})
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertIn("templates/godot-game", result["content"][0]["text"])


class Errors(unittest.TestCase):
    def test_unknown_method(self):
        response = rpc("resources/list")
        self.assertEqual(response["error"]["code"], server_core.METHOD_NOT_FOUND)

    def test_invalid_message(self):
        response = server_core.handle_message({"not": "jsonrpc"})
        self.assertEqual(response["error"]["code"], server_core.INVALID_REQUEST)


if __name__ == "__main__":
    unittest.main()
