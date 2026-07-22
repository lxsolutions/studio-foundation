from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock

DB_PATH = Path(__file__).resolve().parents[1] / "db.py"
SPEC = importlib.util.spec_from_file_location("studio_infra_db", DB_PATH)
assert SPEC is not None and SPEC.loader is not None
db = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(db)


class TestDatabaseLifecycleTests(unittest.TestCase):
    def test_existing_test_database_is_reused_without_create_error(self) -> None:
        existing = CompletedProcess(["psql"], 0, stdout=b"1\n", stderr=b"")
        with (
            mock.patch.object(db, "compose", side_effect=lambda *args: list(args)),
            mock.patch.object(db.subprocess, "run", return_value=existing) as run,
        ):
            self.assertEqual(db.ensure_test_database("studio"), 0)

        self.assertEqual(run.call_count, 1)
        self.assertIn("SELECT 1 FROM pg_database", run.call_args.args[0][-1])

    def test_missing_test_database_is_created_with_stop_on_error(self) -> None:
        missing = CompletedProcess(["psql"], 0, stdout=b"", stderr=b"")
        created = CompletedProcess(["psql"], 0, stdout=b"", stderr=b"")
        with (
            mock.patch.object(db, "compose", side_effect=lambda *args: list(args)),
            mock.patch.object(db.subprocess, "run", side_effect=[missing, created]) as run,
        ):
            self.assertEqual(db.ensure_test_database("studio"), 0)

        create_command = run.call_args_list[1].args[0]
        self.assertIn("ON_ERROR_STOP=1", create_command)
        self.assertEqual(create_command[-1], "CREATE DATABASE studio_test")

    def test_database_check_failure_is_not_ignored(self) -> None:
        failure = CompletedProcess(["psql"], 9, stdout=b"", stderr=b"unreachable")
        with (
            mock.patch.object(db, "compose", side_effect=lambda *args: list(args)),
            mock.patch.object(db.subprocess, "run", return_value=failure),
            mock.patch("sys.stderr.write"),
        ):
            self.assertEqual(db.ensure_test_database("studio"), 9)


if __name__ == "__main__":
    unittest.main()
