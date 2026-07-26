"""Sync-path rules for `pipeline.py cook` — pure, no Blender required.

The cook's export step needs Blender; where its outputs land does not. These
tests pin the path math that decides the synced tree's shape and the --dest
routing that lets a consuming repo (ADR 0015) receive a cooked pack without
the foundation conjuring a project/ directory inside an asset-only game.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

PIPELINE_PATH = Path(__file__).resolve().parents[1] / "pipeline.py"
spec = importlib.util.spec_from_file_location("asset_pipeline", PIPELINE_PATH)
pipeline = importlib.util.module_from_spec(spec)
sys.modules.setdefault("asset_pipeline", pipeline)
spec.loader.exec_module(pipeline)


class CookedRelativeTests(unittest.TestCase):
    def test_strips_game_segments_and_keeps_category_tree(self) -> None:
        out = pipeline.GENERATED / "games" / "asha_world" / "deep" / "deep_ore_vein.glb"
        relative = pipeline.cooked_relative(out, "games/asha_world")
        self.assertEqual(relative, Path("deep") / "deep_ore_vein.glb")

    def test_nested_categories_survive(self) -> None:
        out = pipeline.GENERATED / "games" / "asha_world" / "props" / "crate_a" / "crate_a.glb"
        relative = pipeline.cooked_relative(out, "games/asha_world")
        self.assertEqual(relative, Path("props") / "crate_a" / "crate_a.glb")

    def test_template_game_path(self) -> None:
        out = pipeline.GENERATED / "templates" / "godot-game" / "props" / "box.glb"
        relative = pipeline.cooked_relative(out, "templates/godot-game")
        self.assertEqual(relative, Path("props") / "box.glb")


class CookSyncRootTests(unittest.TestCase):
    def test_default_is_the_game_project_generated_dir(self) -> None:
        root = Path("/repo/games/asha_world")
        self.assertEqual(
            pipeline.cook_sync_root(root, None),
            root / "project" / "assets" / "generated",
        )

    def test_dest_overrides_and_resolves(self) -> None:
        root = Path("/repo/games/asha_world")
        dest = pipeline.cook_sync_root(root, "external/pack")
        self.assertTrue(dest.is_absolute())
        self.assertEqual(dest.name, "pack")
        self.assertNotIn("project", dest.parts)


if __name__ == "__main__":
    unittest.main()
