"""Live tests for the quality gate: check.materials, gameready.review, and the
export.asset gate. Regression coverage for the '8 materials, all the same
brown' failure — an asset whose materials are perceptually identical must not
ship without an explicit override.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge.client import DaemonError, Forge, ForgeError, find_blender  # noqa: E402

FORGE: Forge | None = None
TEMP: tempfile.TemporaryDirectory | None = None


def setUpModule():
    global FORGE, TEMP
    if os.environ.get("BFORGE_SKIP_LIVE"):
        raise unittest.SkipTest("BFORGE_SKIP_LIVE is set")
    try:
        find_blender()
    except DaemonError as exc:
        raise unittest.SkipTest(f"Blender not available: {exc}") from exc
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_gate_test_")
    FORGE = Forge(workdir=TEMP.name, out_dir=str(Path(TEMP.name) / "out"))
    FORGE.start()


def tearDownModule():
    if FORGE is not None:
        FORGE.stop()
    if TEMP is not None:
        TEMP.cleanup()


class ForgeCase(unittest.TestCase):
    def setUp(self):
        FORGE.call("session.reset")

    @property
    def forge(self) -> Forge:
        return FORGE


def _three_mud_materials(forge: Forge, name="blob"):
    """One mesh with three perceptually-identical brown materials: the warden."""
    forge.call("build.box", name=name, size=[1.0, 1.0, 1.0])
    for slot, (brown, mat_name) in enumerate(
        (("#4a3828", "m_mud_a"), ("#4b3929", "m_mud_b"), ("#493827", "m_mud_c"))
    ):
        forge.call(
            "material.set",
            object=name,
            preset="metal",
            name=mat_name,
            slot=slot,
            color=brown,
            roughness=0.7,
            metallic=0.0,
        )
    return name


class Materials(ForgeCase):
    def setUp(self):
        FORGE.call("session.reset")

    def test_mud_blob_is_caught(self):
        name = _three_mud_materials(FORGE)
        result = FORGE.call("check.materials", objects=[name])
        self.assertFalse(result["separated"])
        self.assertLess(result["max_delta_e"], 12.0)
        issues = [f["issue"] for f in result["findings"]]
        self.assertIn("perceptually identical materials", issues)
        errors = [f for f in result["findings"] if f["severity"] == "error"]
        self.assertTrue(errors, "mud blob must be an error-level finding")
        self.assertIn("paint.cavity", errors[0]["fix"])

    def test_separated_materials_pass(self):
        FORGE.call("build.box", name="good", size=[1.0, 1.0, 1.0])
        FORGE.call(
            "material.set",
            object="good",
            preset="metal",
            name="m_red_cloth",
            slot=0,
            color="#8c1f1f",
            roughness=0.85,
            metallic=0.0,
        )
        FORGE.call(
            "material.set",
            object="good",
            preset="metal",
            name="m_brass",
            slot=1,
            color="#c8b06a",
            roughness=0.3,
            metallic=1.0,
        )
        FORGE.call(
            "material.set",
            object="good",
            preset="metal",
            name="m_slate",
            slot=2,
            color="#2a4a6a",
            roughness=0.6,
            metallic=0.0,
        )
        result = FORGE.call("check.materials", objects=["good"])
        self.assertTrue(result["separated"], f"unexpected findings: {result['findings']}")
        self.assertGreater(result["max_delta_e"], 12.0)

    def test_single_and_dual_material_assets_are_not_punished(self):
        FORGE.call("prop.barrel", name="barrel", height=1.1, bands=3, seed=7)
        result = FORGE.call("check.materials", objects=["barrel"])
        errors = [f for f in result["findings"] if f["severity"] == "error"]
        self.assertEqual(errors, [], "two distinct materials must not trip the blob detector")


class Review(ForgeCase):
    def setUp(self):
        FORGE.call("session.reset")

    def test_review_fails_the_mud_blob(self):
        name = _three_mud_materials(FORGE)
        result = FORGE.call("gameready.review", objects=[name])
        self.assertFalse(result["passed"])
        self.assertGreater(result["blocking"], 0)

    def test_review_passes_a_clean_prop(self):
        FORGE.call("prop.barrel", name="barrel", height=1.1, bands=3, seed=7)
        result = FORGE.call("gameready.review", objects=["barrel"])
        self.assertTrue(result["passed"], f"findings: {result['findings']}")

    def test_realistic_style_fails_all_flat_materials(self):
        FORGE.call("prop.barrel", name="barrel", height=1.1, bands=3, seed=7)
        result = FORGE.call("gameready.review", objects=["barrel"], style="realistic")
        self.assertFalse(result["passed"])
        issues = [f["issue"] for f in result["findings"]]
        self.assertIn("flat colours only under a realistic brief", issues)


class ExportGate(ForgeCase):
    def setUp(self):
        FORGE.call("session.reset")

    def test_gate_blocks_the_mud_blob(self):
        name = _three_mud_materials(FORGE)
        FORGE.call("uv.unwrap", object=name, style="smart_packed")
        with self.assertRaises(ForgeError) as ctx:
            FORGE.call("export.asset", asset_id="mud_blob", objects=[name], contact_sheet=False)
        self.assertIn("gameready.review", str(ctx.exception))
        self.assertIn("gate=false", str(ctx.exception))

    def test_gate_false_exports_anyway(self):
        name = _three_mud_materials(FORGE)
        FORGE.call("uv.unwrap", object=name, style="smart_packed")
        result = FORGE.call(
            "export.asset",
            asset_id="mud_blob_forced",
            objects=[name],
            contact_sheet=False,
            gate=False,
        )
        self.assertEqual(result["asset_id"], "mud_blob_forced")

    def test_gate_passes_a_clean_prop(self):
        FORGE.call("prop.barrel", name="barrel", height=1.1, bands=3, seed=7)
        result = FORGE.call(
            "export.asset", asset_id="barrel_gated", objects=["barrel"], contact_sheet=False
        )
        self.assertEqual(result["asset_id"], "barrel_gated")


if __name__ == "__main__":
    unittest.main()
