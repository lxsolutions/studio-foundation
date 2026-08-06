"""MCP protocol behaviour for the bforge server.

Dispatch is tested in-process against a stub Forge, so no Blender process
starts and the suite stays fast enough for every CI run.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge.client import DaemonError, ForgeError  # noqa: E402

from bforge import mcp_server  # noqa: E402


class StubForge:
    """Records calls and replays canned answers — no subprocess involved."""

    def __init__(self, fail_on=None, daemon_error_on=None):
        self.calls: list[tuple[str, dict]] = []
        self.fail_on = fail_on
        self.daemon_error_on = daemon_error_on
        self.process = None
        self.info = {"blender": "4.5.12 LTS"}
        self.workdir = Path(".")
        self.out_dir = Path("out")
        self.restarted = False
        self.stopped = False

    def call(self, op, _timeout=None, **args):
        self.calls.append((op, args))
        if op == self.daemon_error_on:
            raise DaemonError("blender died")
        if op == self.fail_on:
            raise ForgeError(f"{op} exploded")
        return {"op": op, "echo": args}

    def catalog(self):
        return []

    def restart(self):
        self.restarted = True
        return self.info

    def stop(self):
        self.stopped = True


def make_server(**kwargs) -> mcp_server.Server:
    server = mcp_server.Server()
    server.forge = StubForge(**kwargs)
    return server


def rpc(server, method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    return mcp_server.handle_message(server, message)


class Lifecycle(unittest.TestCase):
    def test_initialize_negotiates_and_ships_a_primer(self):
        response = rpc(make_server(), "initialize", {"protocolVersion": "2025-06-18"})
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "bforge")
        self.assertIn("session.reset", result["instructions"])

    def test_unknown_protocol_falls_back(self):
        response = rpc(make_server(), "initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(response["result"]["protocolVersion"], mcp_server.SUPPORTED_VERSIONS[0])

    def test_notifications_get_no_response(self):
        self.assertIsNone(rpc(make_server(), "notifications/initialized", request_id=None))

    def test_unknown_method_errors(self):
        response = rpc(make_server(), "bogus/method")
        self.assertEqual(response["error"]["code"], mcp_server.METHOD_NOT_FOUND)

    def test_non_jsonrpc_message_rejected(self):
        response = mcp_server.handle_message(make_server(), {"id": 1, "method": "ping"})
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_REQUEST)


class ToolListing(unittest.TestCase):
    def test_grouped_mode_keeps_the_tool_list_small(self):
        tools = rpc(make_server(), "tools/list")["result"]["tools"]
        self.assertEqual(len(tools), 5)
        self.assertEqual(
            {t["name"] for t in tools},
            {
                "bforge_ops",
                "bforge_describe",
                "bforge_run",
                "bforge_run_batch",
                "bforge_session",
            },
        )

    def test_full_mode_exposes_every_op(self):
        server = mcp_server.Server(mode="full")
        server.forge = StubForge()
        tools = rpc(server, "tools/list")["result"]["tools"]
        self.assertGreater(len(tools), 50)
        self.assertTrue(all("." not in t["name"] for t in tools), "MCP names must not contain dots")


class Discovery(unittest.TestCase):
    def test_ops_filters_by_tag(self):
        is_error, text = make_server().call("bforge_ops", {"tag": "prop"})
        payload = json.loads(text)
        self.assertFalse(is_error)
        self.assertTrue(payload["count"] > 0)
        self.assertTrue(all("prop" in row["tags"] for row in payload["ops"]))

    def test_describe_returns_full_schema(self):
        is_error, text = make_server().call("bforge_describe", {"ops": ["prop.crate"]})
        payload = json.loads(text)
        self.assertFalse(is_error)
        self.assertIn("size", payload["ops"][0]["inputSchema"]["properties"])

    def test_describe_reports_unknown_names_with_a_hint(self):
        is_error, text = make_server().call("bforge_describe", {"ops": ["nope.nope"]})
        payload = json.loads(text)
        self.assertTrue(is_error)
        self.assertEqual(payload["not_found"], ["nope.nope"])
        self.assertIn("hint", payload)


class Running(unittest.TestCase):
    def test_run_forwards_op_and_args(self):
        server = make_server()
        is_error, text = server.call("bforge_run", {"op": "prop.crate", "args": {"seed": 3}})
        self.assertFalse(is_error)
        self.assertEqual(server.forge.calls, [("prop.crate", {"seed": 3})])
        self.assertEqual(json.loads(text)["op"], "prop.crate")

    def test_run_without_op_is_an_error(self):
        is_error, text = make_server().call("bforge_run", {})
        self.assertTrue(is_error)
        self.assertIn("missing", json.loads(text)["error"])

    def test_op_failure_is_reported_not_raised(self):
        server = make_server(fail_on="prop.crate")
        is_error, text = server.call("bforge_run", {"op": "prop.crate"})
        self.assertTrue(is_error)
        self.assertIn("exploded", json.loads(text)["error"])

    def test_daemon_failure_includes_recovery_advice(self):
        server = make_server(daemon_error_on="prop.crate")
        is_error, text = server.call("bforge_run", {"op": "prop.crate"})
        payload = json.loads(text)
        self.assertTrue(is_error)
        self.assertEqual(payload["kind"], "daemon")
        self.assertIn("restart", payload["recovery"])


class Batching(unittest.TestCase):
    def test_batch_runs_every_step_in_order(self):
        server = make_server()
        is_error, text = server.call(
            "bforge_run_batch",
            {
                "steps": [
                    {"op": "session.reset"},
                    {"op": "prop.crate", "args": {"seed": 1}},
                    {"op": "export.gltf", "args": {"out": "a.glb"}},
                ]
            },
        )
        self.assertFalse(is_error)
        self.assertEqual(
            [c[0] for c in server.forge.calls], ["session.reset", "prop.crate", "export.gltf"]
        )
        self.assertEqual(len(json.loads(text)["steps"]), 3)

    def test_batch_stops_at_first_failure_by_default(self):
        server = make_server(fail_on="prop.crate")
        is_error, text = server.call(
            "bforge_run_batch",
            {
                "steps": [
                    {"op": "session.reset"},
                    {"op": "prop.crate"},
                    {"op": "export.gltf"},
                ]
            },
        )
        self.assertTrue(is_error)
        self.assertNotIn("export.gltf", [c[0] for c in server.forge.calls])
        self.assertEqual(json.loads(text)["steps"][-1]["skipped"], 1)

    def test_batch_can_continue_past_failures(self):
        server = make_server(fail_on="prop.crate")
        is_error, _text = server.call(
            "bforge_run_batch",
            {
                "steps": [{"op": "prop.crate"}, {"op": "export.gltf"}],
                "continue_on_error": True,
            },
        )
        self.assertTrue(is_error, "still reports failure")
        self.assertIn("export.gltf", [c[0] for c in server.forge.calls])

    def test_empty_batch_rejected(self):
        is_error, _text = make_server().call("bforge_run_batch", {"steps": []})
        self.assertTrue(is_error)


class Session(unittest.TestCase):
    def test_status_reports_without_starting_blender(self):
        server = make_server()
        is_error, text = server.call("bforge_session", {"action": "status"})
        payload = json.loads(text)
        self.assertFalse(is_error)
        self.assertFalse(payload["daemon_running"])
        self.assertEqual(server.forge.calls, [], "status must not boot Blender")

    def test_restart_and_stop(self):
        server = make_server()
        server.call("bforge_session", {"action": "restart"})
        self.assertTrue(server.forge.restarted)
        server.call("bforge_session", {"action": "stop"})
        self.assertTrue(server.forge.stopped)


class Robustness(unittest.TestCase):
    def test_unknown_tool_is_an_error_not_a_crash(self):
        is_error, text = make_server().call("bforge_nope", {})
        self.assertTrue(is_error)
        self.assertIn("unknown tool", json.loads(text)["error"])

    def test_tools_call_requires_a_string_name(self):
        response = rpc(make_server(), "tools/call", {"name": 42})
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_PARAMS)

    def test_tools_call_requires_object_arguments(self):
        response = rpc(make_server(), "tools/call", {"name": "bforge_ops", "arguments": []})
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_PARAMS)

    def test_self_check_passes(self):
        self.assertEqual(mcp_server.self_check(make_server()), 0)


if __name__ == "__main__":
    unittest.main()
