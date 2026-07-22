from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]


def load_cleaner():
    path = REPO / "tools" / "build" / "clean.py"
    spec = importlib.util.spec_from_file_location("studio_clean", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["studio_clean"] = module
    spec.loader.exec_module(module)
    return module


cleaner = load_cleaner()


class CleanTests(unittest.TestCase):
    def test_collects_only_known_generated_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            generated = [
                root / "build",
                root / "assets-generated",
                root / "services" / "target",
                root / "games" / "demo" / "project" / ".godot",
                root / "games" / "demo" / "project" / "assets" / "generated",
                root / "games" / "demo" / "server" / "target",
            ]
            for path in generated:
                path.mkdir(parents=True)
            (root / "games" / "demo" / "project" / "project.godot").write_text("", encoding="utf-8")
            (root / "games" / "demo" / "server" / "Cargo.toml").write_text("", encoding="utf-8")
            source = root / "games" / "demo" / "project" / "scenes" / "game.gd"
            source.parent.mkdir(parents=True)
            source.write_text("extends Node\n", encoding="utf-8")

            self.assertEqual(set(cleaner.collect_targets(root)), set(generated))
            self.assertTrue(source.is_file())

    def test_dry_run_preserves_outputs_and_clean_removes_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "build"
            output.mkdir()
            (output / "artifact.bin").write_bytes(b"generated")

            self.assertEqual(cleaner.clean(root, dry_run=True), [output])
            self.assertTrue(output.is_dir())
            self.assertEqual(cleaner.clean(root), [output])
            self.assertFalse(output.exists())

    def test_remove_tree_retries_transient_permission_errors(self) -> None:
        with (
            mock.patch.object(
                cleaner.shutil,
                "rmtree",
                side_effect=[PermissionError("locked"), None],
            ) as rmtree,
            mock.patch.object(cleaner.time, "sleep") as sleep,
        ):
            cleaner.remove_tree(Path("generated"), retries=2, delay=0.01)

        self.assertEqual(rmtree.call_count, 2)
        sleep.assert_called_once_with(0.01)

    def test_refuses_repository_root_and_outside_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            root.mkdir()
            outside = root.parent / "outside"
            with self.assertRaises(ValueError):
                cleaner.ensure_inside(root, root)
            with self.assertRaises(ValueError):
                cleaner.ensure_inside(outside, root)


if __name__ == "__main__":
    unittest.main()
