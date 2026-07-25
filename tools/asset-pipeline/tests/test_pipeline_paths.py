"""Pure path-contract tests for the deterministic asset exporter."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PIPELINE_PATH = Path(__file__).resolve().parents[1] / "pipeline.py"
SPEC = importlib.util.spec_from_file_location("asset_pipeline", PIPELINE_PATH)
assert SPEC is not None and SPEC.loader is not None
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


class ExportPaths(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "foundation"
        self.generated = self.repo / "assets-generated"
        self.external = self.root / "external-game"
        self.previous_repo = pipeline.REPO
        self.previous_generated = pipeline.GENERATED
        pipeline.REPO = self.repo
        pipeline.GENERATED = self.generated

    def tearDown(self) -> None:
        pipeline.REPO = self.previous_repo
        pipeline.GENERATED = self.previous_generated
        self.temp_dir.cleanup()

    def test_local_master_keeps_the_existing_generated_path(self) -> None:
        blend = self.repo / "templates/godot-game/assets-source/props/crate/crate.blend"

        result = pipeline.export_path_for(blend)

        self.assertEqual(
            result,
            self.generated / "templates/godot-game/props/crate/crate.glb",
        )
        self.assertEqual(
            pipeline.cache_key_for(result),
            "assets-generated/templates/godot-game/props/crate/crate.glb",
        )

    def test_external_master_without_output_has_actionable_error(self) -> None:
        blend = self.external / "art_source/blender/skimmer.blend"

        with self.assertRaisesRegex(SystemExit, r"outside.*\npass --out <path\.glb>"):
            pipeline.export_path_for(blend)

    def test_explicit_output_allows_an_external_master(self) -> None:
        blend = self.external / "art_source/blender/skimmer.blend"
        requested = self.external / "assets/vehicles/skimmer.glb"

        self.assertEqual(pipeline.export_path_for(blend, requested), requested.resolve())

    def test_candidate_is_a_sibling_glb_for_atomic_replacement(self) -> None:
        output = self.external / "assets/vehicles/skimmer.glb"

        candidate = pipeline.candidate_path_for(output)

        self.assertEqual(candidate.parent, output.parent)
        self.assertEqual(candidate.name, ".skimmer.candidate.glb")

    def test_export_cli_forwards_output_and_required_nodes(self) -> None:
        blend = self.external / "art_source/blender/skimmer.blend"
        requested = self.external / "assets/vehicles/skimmer.glb"
        blend.parent.mkdir(parents=True)
        blend.touch()
        argv = [
            "pipeline.py",
            "export",
            str(blend),
            "--out",
            str(requested),
            "--force",
            "--require-node",
            "AetherDartHull",
            "--require-node",
            "FactionArmor",
        ]

        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(pipeline.senv, "load_dotenv"),
            mock.patch.object(pipeline, "cmd_export", return_value=(0, requested)) as export,
        ):
            self.assertEqual(pipeline.main(), 0)

        export.assert_called_once_with(
            blend.resolve(),
            force=True,
            requested_out=requested,
            required_nodes=("AetherDartHull", "FactionArmor"),
        )

    def test_external_cache_key_is_stable_hashed_and_path_free(self) -> None:
        first = (self.external / "assets/vehicles/skimmer.glb").resolve()
        second = (self.external / "assets/vehicles/dart.glb").resolve()

        first_key = pipeline.cache_key_for(first)

        self.assertEqual(first_key, pipeline.cache_key_for(first))
        self.assertRegex(first_key, r"^external/skimmer\.glb-[0-9a-f]{16}$")
        self.assertNotIn(str(self.external), first_key)
        self.assertNotEqual(first_key, pipeline.cache_key_for(second))


if __name__ == "__main__":
    unittest.main()
