"""Live tests for env.camp — the settlement composer."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge.client import DaemonError, Forge, find_blender  # noqa: E402

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
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_camp_test_")
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


class Camp(ForgeCase):
    def test_camp_builds_all_structures(self):
        result = FORGE.call(
            "env.camp", name="homeland", radius=8.0, shelters=5, well=True, racks=2, seed=42
        )
        parts = {entry["part"] for entry in result["structures"]}
        for expected in (
            "fire_stones",
            "fire_logs",
            "embers",
            "palisade",
            "well_stones",
            "well_frame",
            "ground",
        ):
            self.assertIn(expected, parts)
        hides = [p for p in parts if p.startswith("shelter_") and p.endswith("_hide")]
        self.assertEqual(len(hides), 5)
        self.assertGreater(result["triangles"], 1000)
        self.assertLess(result["triangles"], 15000)

    def test_gate_leaves_an_opening(self):
        """The palisade ring must skip the gate arc — the one way in."""
        FORGE.call(
            "env.camp", name="gated", radius=8.0, shelters=2, gate_angle=90.0, ground=False, seed=7
        )
        info = FORGE.call("object.inspect", name="gated_palisade")
        # At gate_angle=90 (+Y), no post may sit near (0, radius). Probe by
        # counting palisade triangles: a full ring has ~count*segments*2 tris;
        # the gate arc removes ~11 degrees * 2 of posts.
        full = FORGE.call(
            "env.camp",
            name="ungated",
            radius=8.0,
            shelters=2,
            palisade=True,
            gate_angle=999.0,
            ground=False,
            seed=7,
        )
        gated_tris = info["triangles"]
        full_tris = next(e["triangles"] for e in full["structures"] if e["part"] == "palisade")
        self.assertLess(gated_tris, full_tris, "the gate angle must remove posts from the ring")

    def test_materials_are_separated(self):
        FORGE.call("env.camp", name="homeland", radius=8.0, shelters=3, seed=42)
        result = FORGE.call("check.materials")
        errors = [f for f in result["findings"] if f["severity"] == "error"]
        self.assertEqual(errors, [], f"camp palette must pass the blob gate: {errors}")

    def test_camp_passes_the_quality_gate(self):
        FORGE.call("env.camp", name="homeland", radius=8.0, shelters=3, seed=42)
        review = FORGE.call("gameready.review")
        self.assertTrue(review["passed"], f"findings: {review['findings']}")

    def test_determinism(self):
        def build_once(out):
            FORGE.call("session.reset")
            FORGE.call("env.camp", name="homeland", radius=8.0, shelters=3, seed=42)
            return Path(FORGE.call("export.gltf", out=out)["path"]).read_bytes()

        self.assertEqual(build_once("camp_a.glb"), build_once("camp_b.glb"))


if __name__ == "__main__":
    unittest.main()
