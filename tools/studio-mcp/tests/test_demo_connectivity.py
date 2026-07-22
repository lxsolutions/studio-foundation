from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]


def load_demo():
    path = REPO / "tools" / "godot" / "demo_connectivity.py"
    spec = importlib.util.spec_from_file_location("studio_demo_connectivity", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["studio_demo_connectivity"] = module
    spec.loader.exec_module(module)
    return module


demo = load_demo()


class ResultContractTests(unittest.TestCase):
    def test_extracts_last_machine_readable_result(self) -> None:
        output = "\n".join(
            [
                "Godot Engine",
                'CONNECTIVITY_RESULT {"api_health": false}',
                'CONNECTIVITY_RESULT {"api_health": true, "db_roundtrip": true, '
                '"ws_handshake": true, "session": "session-1"}',
            ]
        )
        result = demo.extract_result(output)
        self.assertEqual(result["session"], "session-1")
        self.assertEqual(demo.result_failures(result), [])

    def test_database_roundtrip_and_session_are_mandatory(self) -> None:
        result = {
            "api_health": True,
            "db_roundtrip": False,
            "ws_handshake": True,
            "session": "",
        }
        self.assertEqual(demo.result_failures(result), ["db_roundtrip", "session"])

    def test_missing_or_invalid_result_is_actionable(self) -> None:
        with self.assertRaisesRegex(demo.ConnectivityError, "did not print"):
            demo.extract_result("Godot Engine")
        with self.assertRaisesRegex(demo.ConnectivityError, "invalid.*JSON"):
            demo.extract_result("CONNECTIVITY_RESULT {broken")


class DiscoveryTests(unittest.TestCase):
    def test_project_requires_client_check_and_game_server(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game = root / "games" / "sample"
            project = game / "project"
            (project / "tests").mkdir(parents=True)
            (project / "project.godot").write_text("", encoding="utf-8")
            (project / "tests" / "connectivity_check.gd").write_text("", encoding="utf-8")
            (game / "server").mkdir()
            (game / "server" / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
            self.assertEqual(demo.project_dir("games/sample", root), project.resolve())

            (game / "server" / "Cargo.toml").unlink()
            with self.assertRaisesRegex(demo.ConnectivityError, "server/Cargo.toml"):
                demo.project_dir("games/sample", root)

    def test_project_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            root.mkdir()
            with self.assertRaisesRegex(demo.ConnectivityError, "inside the repository"):
                demo.project_dir("../outside", root)

    def test_cargo_command_targets_workspace_package_or_game_manifest(self) -> None:
        manifest = Path("services/Cargo.toml")
        self.assertEqual(
            demo.cargo_command("cargo", manifest, "studio-control-api"),
            [
                "cargo",
                "run",
                "--quiet",
                "--locked",
                "--manifest-path",
                str(manifest),
                "-p",
                "studio-control-api",
            ],
        )
        self.assertEqual(
            demo.cargo_command("cargo", Path("game/server/Cargo.toml")),
            [
                "cargo",
                "run",
                "--quiet",
                "--locked",
                "--manifest-path",
                str(Path("game/server/Cargo.toml")),
            ],
        )


class OrchestrationTests(unittest.TestCase):
    def test_owned_servers_are_stopped_in_reverse_order(self) -> None:
        project = REPO / "templates" / "godot-game" / "project"
        control, dedicated = object(), object()
        result = {
            "api_health": True,
            "db_roundtrip": True,
            "ws_handshake": True,
            "session": "session-1",
        }
        with (
            mock.patch.dict(os.environ, {"DATABASE_URL": "postgres://local/test"}, clear=False),
            mock.patch.object(demo.senv, "load_dotenv"),
            mock.patch.object(demo, "project_dir", return_value=project),
            mock.patch.object(demo.senv, "find_godot", return_value="godot"),
            mock.patch.object(demo.senv, "find_cargo", return_value="cargo"),
            mock.patch.object(demo, "prepare_project"),
            mock.patch.object(demo, "free_loopback_port", side_effect=[18080, 18081]),
            mock.patch.object(demo, "start_server", side_effect=[control, dedicated]) as start,
            mock.patch.object(demo, "wait_for_server") as wait,
            mock.patch.object(demo, "check_client", return_value=result),
            mock.patch.object(demo, "stop_server") as stop,
        ):
            self.assertEqual(demo.run_demo("templates/godot-game", 30, 90), result)

        self.assertEqual(start.call_count, 2)
        self.assertEqual(wait.call_args_list[0].args[1:], (18080, 90))
        self.assertEqual(wait.call_args_list[1].args[1:], (18081, 90))
        self.assertEqual([call.args[0] for call in stop.call_args_list], [dedicated, control])

    def test_database_configuration_is_required_before_launch(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(demo.senv, "load_dotenv"),
            self.assertRaisesRegex(demo.ConnectivityError, "DATABASE_URL is not set"),
        ):
            demo.run_demo("templates/godot-game", 30, 90)


if __name__ == "__main__":
    unittest.main()
