from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def load_generator():
    path = REPO / "tools" / "build" / "new_game.py"
    spec = importlib.util.spec_from_file_location("studio_new_game", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["studio_new_game"] = module
    spec.loader.exec_module(module)
    return module


new_game = load_generator()


class NewGameTests(unittest.TestCase):
    def test_validates_safe_names_and_display_names(self) -> None:
        self.assertEqual(new_game.validate_inputs("my_game2", "My Game"), ("my_game2", "My Game"))
        for invalid in ("../escape", "MyGame", "my-game", "2fast", "con", "studio_game_template"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                new_game.validate_inputs(invalid, "Display")
        with self.assertRaises(ValueError):
            new_game.validate_inputs("valid", 'Bad "Display"')

    def test_renders_real_template_without_generated_import_state(self) -> None:
        files = new_game.tracked_template_files(REPO)
        with tempfile.TemporaryDirectory() as temp_dir:
            games_root = Path(temp_dir) / "games"
            destination = new_game.generate_game(
                "orbit_runner",
                "Orbit Runner",
                repo_root=REPO,
                games_root=games_root,
                relative_files=files,
            )

            project = (destination / "project" / "project.godot").read_text(encoding="utf-8")
            config = (destination / "project" / "studio.config.json").read_text(encoding="utf-8")
            cargo = (destination / "server" / "Cargo.toml").read_text(encoding="utf-8")
            server_main = (destination / "server" / "src" / "main.rs").read_text(encoding="utf-8")
            migration = (destination / "server" / "migrations" / "0001_game_init.sql").read_text(
                encoding="utf-8"
            )
            build_info = (destination / "project" / "build_info.json").read_text(encoding="utf-8")

            self.assertIn('config/name="Orbit Runner"', project)
            self.assertIn('"game.id": "orbit_runner"', config)
            self.assertIn('name = "orbit_runner-server"', cargo)
            self.assertIn("game_orbit_runner", migration)
            self.assertIn("SET search_path TO game_orbit_runner", server_main)
            self.assertIn("migrate_game_schema", server_main)
            self.assertIn('"git_commit": "unknown"', build_info)
            self.assertTrue(
                (destination / "project" / "addons" / "studio_core" / "studio.gd").is_file()
            )
            self.assertFalse((destination / "project" / "icon.svg.import").exists())
            self.assertFalse((destination / "project" / "captures").exists())

            for path in destination.rglob("*"):
                if path.is_file():
                    try:
                        text = path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        continue
                    self.assertNotIn("studio_game_template", text, str(path))
                    self.assertNotIn("Studio Game Template", text, str(path))
                    self.assertNotIn("org.studio.template", text, str(path))

    def test_refuses_to_overwrite_an_existing_game(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            games_root = Path(temp_dir) / "games"
            (games_root / "taken").mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                new_game.generate_game(
                    "taken",
                    "Taken",
                    repo_root=REPO,
                    games_root=games_root,
                    relative_files=[],
                )

    def test_renders_template_identity_inside_cargo_lock(self) -> None:
        lock = (REPO / "templates" / "godot-game" / "server" / "Cargo.lock").read_bytes()
        rendered = new_game.render_bytes(lock, "orbit_runner", "Orbit Runner").decode("utf-8")
        self.assertIn('name = "orbit_runner-server"', rendered)
        self.assertNotIn("studio_game_template-server", rendered)


if __name__ == "__main__":
    unittest.main()
