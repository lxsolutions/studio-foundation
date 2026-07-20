"""Security tests for studio-mcp: authorization boundaries, path validation,
injection attempts, output caps, and redaction. Run: just test-mcp"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pylib"))

from studio_tools.mcp import security, tools  # noqa: E402
from studio_tools.mcp.security import ToolArgError  # noqa: E402


class PathValidation(unittest.TestCase):
    def test_rejects_traversal(self):
        for bad in ["../secrets", "a/../../b", "..", "a/..", "docs/../../etc/passwd"]:
            with self.assertRaises(ToolArgError, msg=bad):
                security.repo_relative_path(bad)

    def test_rejects_absolute_and_home(self):
        for bad in ["/etc/passwd", "C:/Windows/system32", "C:\\Windows", "~/x", "\\\\server\\share"]:
            with self.assertRaises(ToolArgError, msg=bad):
                security.repo_relative_path(bad)

    def test_rejects_empty_and_nonstring(self):
        for bad in ["", "   ", None, 42]:
            with self.assertRaises(ToolArgError):
                security.repo_relative_path(bad)  # type: ignore[arg-type]

    def test_accepts_repo_relative(self):
        path = security.repo_relative_path("templates/godot-game")
        self.assertTrue(str(path).startswith(str(security.senv.repo_root())))

    def test_suffix_enforced(self):
        with self.assertRaises(ToolArgError):
            security.repo_relative_path("README.md", suffix=".blend")


class ArgSchemaValidation(unittest.TestCase):
    SCHEMA = {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{2,29}$"},
            "count": {"type": "integer", "minimum": 1, "maximum": 8, "default": 1},
            "flag": {"type": "boolean"},
            "mode": {"type": "string", "enum": ["a", "b"]},
        },
    }

    def test_unknown_argument_rejected(self):
        with self.assertRaises(ToolArgError):
            security.validate_args(self.SCHEMA, {"name": "abc", "evil": "x"})

    def test_missing_required_rejected(self):
        with self.assertRaises(ToolArgError):
            security.validate_args(self.SCHEMA, {})

    def test_pattern_rejects_injection_shapes(self):
        for bad in ["abc; rm -rf /", "abc$(id)", "abc`x`", "ABC", "a", "x" * 40]:
            with self.assertRaises(ToolArgError, msg=bad):
                security.validate_args(self.SCHEMA, {"name": bad})

    def test_type_and_range(self):
        with self.assertRaises(ToolArgError):
            security.validate_args(self.SCHEMA, {"name": "abc", "count": "3"})
        with self.assertRaises(ToolArgError):
            security.validate_args(self.SCHEMA, {"name": "abc", "count": 99})
        with self.assertRaises(ToolArgError):
            security.validate_args(self.SCHEMA, {"name": "abc", "count": True})
        with self.assertRaises(ToolArgError):
            security.validate_args(self.SCHEMA, {"name": "abc", "mode": "c"})

    def test_defaults_applied(self):
        cleaned = security.validate_args(self.SCHEMA, {"name": "abc"})
        self.assertEqual(cleaned["count"], 1)


class SqlGuard(unittest.TestCase):
    def test_select_and_explain_allowed(self):
        self.assertTrue(security.validate_readonly_sql("SELECT 1"))
        self.assertTrue(security.validate_readonly_sql("  explain select * from platform.account  "))
        self.assertTrue(security.validate_readonly_sql("WITH x AS (SELECT 1) SELECT * FROM x"))

    def test_writes_rejected(self):
        for bad in [
            "INSERT INTO platform.account VALUES (1)",
            "DELETE FROM platform.account",
            "DROP TABLE platform.account",
            "UPDATE platform.account SET display_name='x'",
            "CREATE TABLE t (a int)",
            "GRANT ALL ON platform.account TO public",
            "TRUNCATE platform.audit_log",
        ]:
            with self.assertRaises(ToolArgError, msg=bad):
                security.validate_readonly_sql(bad)

    def test_multi_statement_rejected(self):
        with self.assertRaises(ToolArgError):
            security.validate_readonly_sql("SELECT 1; DROP TABLE platform.account")

    def test_sneaky_write_inside_select_rejected(self):
        with self.assertRaises(ToolArgError):
            security.validate_readonly_sql("SELECT * FROM (INSERT INTO t VALUES (1) RETURNING *) q")

    def test_remote_database_refused(self):
        for url in [
            "postgres://user:pw@db.prod.example.com/studio",
            "postgres://user:pw@10.0.0.5/studio",
        ]:
            with self.assertRaises(ToolArgError, msg=url):
                security.assert_local_database(url)
        security.assert_local_database("postgres://studio:pw@127.0.0.1:5432/studio")


class OutputAndRedaction(unittest.TestCase):
    def test_output_capped(self):
        capped = security.cap_output("x" * (security.MAX_OUTPUT_BYTES + 500))
        self.assertLess(len(capped.encode()), security.MAX_OUTPUT_BYTES + 100)
        self.assertIn("truncated", capped)

    def test_redaction(self):
        redacted = security.redact({"query": "SELECT 1", "db_password": "hunter2", "api_token": "t"})
        self.assertEqual(redacted["query"], "SELECT 1")
        self.assertEqual(redacted["db_password"], "<redacted>")
        self.assertEqual(redacted["api_token"], "<redacted>")


class RegistryBoundaries(unittest.TestCase):
    def test_unknown_tool_is_error_not_crash(self):
        is_error, text = tools.call_tool("shell", {"cmd": "id"})
        self.assertTrue(is_error)
        self.assertIn("unknown tool", text)

    def test_no_generic_shell_tool_exposed(self):
        names = {tool["name"] for tool in tools.list_tools()}
        for forbidden in ["shell", "exec", "eval", "python", "sql", "run_command", "bash"]:
            self.assertNotIn(forbidden, names)

    def test_engine_build_disabled(self):
        is_error, text = tools.call_tool("engine_build", {})
        self.assertTrue(is_error)
        self.assertIn("just engine-build", text)

    def test_invalid_args_never_execute(self):
        is_error, text = tools.call_tool(
            "studio_create_game_from_template", {"name": "Bad Name; rm -rf"}
        )
        self.assertTrue(is_error)
        self.assertIn("invalid arguments", text)

    def test_blend_path_validation(self):
        is_error, text = tools.call_tool("blender_validate_asset", {"file": "../../evil.blend"})
        self.assertTrue(is_error)
        self.assertIn("invalid arguments", text)

    def test_server_stop_refuses_unmanaged(self):
        is_error, text = tools.call_tool("server_stop_local", {"service": "control-api"})
        self.assertTrue(is_error)
        self.assertIn("refusing", text)


class TimeoutBehaviour(unittest.TestCase):
    def test_run_timeout_enforced(self):
        code, output = tools._run(
            [sys.executable, "-c", "import time; time.sleep(5)"], timeout=1
        )
        self.assertEqual(code, 124)
        self.assertIn("timed out", output)


if __name__ == "__main__":
    unittest.main()
