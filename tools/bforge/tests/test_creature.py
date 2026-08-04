"""Live tests for char.creature / char.creature_rig and the quadruped gaits."""

from __future__ import annotations

import json
import os
import struct
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
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_creature_test_")
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


def read_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    assert data[:4] == b"glTF", "not a GLB"
    chunk_len, chunk_type = struct.unpack_from("<I4s", data, 12)
    assert chunk_type == b"JSON"
    return json.loads(data[20 : 20 + chunk_len])


class Creature(ForgeCase):
    def test_body_builds_within_budget(self):
        result = FORGE.call("char.creature", name="hound", length=1.3, shoulder=0.85,
                            plan="canine", seed=5)
        self.assertEqual(result["plan"], "canine")
        self.assertLess(result["triangles"], 6000)
        bounds = result["bounds"]["size"]
        self.assertGreater(bounds[1], bounds[2] * 0.8,
                           "a quadruped is longer than it is tall")

    def test_all_plans_build(self):
        for plan in ("equine", "feline", "generic"):
            result = FORGE.call("char.creature", name=f"beast_{plan}", plan=plan, seed=9)
            self.assertGreater(result["triangles"], 200)

    def test_rig_has_quadruped_bones_and_single_root(self):
        FORGE.call("char.creature", name="hound", length=1.3, shoulder=0.85, seed=5)
        rig = FORGE.call("char.creature_rig", name="hound", length=1.3, shoulder=0.85)
        bones = set(rig["bones"])
        for expected in ("hips", "spine", "chest", "neck", "head", "tail_1", "tail_2",
                         "front_upper_l", "front_lower_l", "front_paw_l",
                         "rear_upper_r", "rear_lower_r", "rear_paw_r"):
            self.assertIn(expected, bones)
        self.assertEqual(rig["bone_count"], 19)
        self.assertGreater(rig["weighted_vertices"], 0)

    def test_gaits_export_as_animation_clips(self):
        FORGE.call("char.creature", name="hound", length=1.3, shoulder=0.85, seed=5)
        rig = FORGE.call("char.creature_rig", name="hound", length=1.3, shoulder=0.85)
        for clip in ("walk", "trot", "gallop", "graze", "idle"):
            result = FORGE.call("char.animate", rig=rig["armature"], clip=clip, length=24)
            self.assertGreater(result["keyframes"], 10, f"{clip} produced no keys")
        glb = FORGE.call("export.gltf", out="hound.glb",
                         objects=[rig["armature"], "hound"])
        parsed = read_glb_json(Path(glb["path"]))
        self.assertEqual(len(parsed.get("skins", [])), 1)
        self.assertEqual(len(parsed["skins"][0]["joints"]), 19)
        self.assertEqual(len(parsed.get("animations", [])), 5)

    def test_wrong_family_clip_is_a_helpful_error(self):
        FORGE.call("char.creature", name="hound", length=1.3, shoulder=0.85, seed=5)
        rig = FORGE.call("char.creature_rig", name="hound", length=1.3, shoulder=0.85)
        with self.assertRaises(ForgeError) as ctx:
            FORGE.call("char.animate", rig=rig["armature"], clip="attack")
        self.assertIn("quadruped", str(ctx.exception))
        FORGE.call("session.reset")
        FORGE.call("char.humanoid", name="warden", height=1.8, seed=3)
        rig2 = FORGE.call("char.rig", name="warden", height=1.8)
        with self.assertRaises(ForgeError) as ctx2:
            FORGE.call("char.animate", rig=rig2["armature"], clip="trot")
        self.assertIn("humanoid", str(ctx2.exception))

    def test_determinism(self):
        def build_once(out):
            FORGE.call("session.reset")
            FORGE.call("char.creature", name="hound", length=1.3, shoulder=0.85, seed=5)
            rig = FORGE.call("char.creature_rig", name="hound", length=1.3, shoulder=0.85)
            FORGE.call("char.animate", rig=rig["armature"], clip="trot", length=24)
            return Path(FORGE.call("export.gltf", out=out)["path"]).read_bytes()

        self.assertEqual(build_once("det_a.glb"), build_once("det_b.glb"))

    def test_creature_passes_the_quality_gate(self):
        FORGE.call("char.creature", name="hound", length=1.3, shoulder=0.85, seed=5)
        review = FORGE.call("gameready.review", objects=["hound"])
        self.assertTrue(review["passed"], f"findings: {review['findings']}")


class Hexapod(ForgeCase):
    def test_insect_body_and_rig(self):
        result = FORGE.call("char.creature", name="scarab", plan="insect",
                            length=0.9, shoulder=0.35, skin="#3d3226", seed=17)
        self.assertEqual(result["plan"], "insect")
        self.assertLess(result["triangles"], 8000)
        rig = FORGE.call("char.creature_rig", name="scarab", plan="insect",
                         length=0.9, shoulder=0.35)
        bones = set(rig["bones"])
        for expected in ("hips", "chest", "head",
                         "front_upper_l", "mid_upper_l", "rear_upper_l",
                         "mid_lower_r", "mid_paw_r", "rear_paw_l"):
            self.assertIn(expected, bones)
        self.assertEqual(rig["bone_count"], 21)
        self.assertGreater(rig["weighted_vertices"], 0)

    def test_tripod_walk_exports(self):
        FORGE.call("char.creature", name="scarab", plan="insect",
                   length=0.9, shoulder=0.35, seed=17)
        rig = FORGE.call("char.creature_rig", name="scarab", plan="insect",
                         length=0.9, shoulder=0.35)
        walk = FORGE.call("char.animate", rig=rig["armature"], clip="walk", length=24)
        self.assertGreater(walk["keyframes"], 10)
        glb = FORGE.call("export.gltf", out="scarab.glb",
                         objects=[rig["armature"], "scarab"])
        parsed = read_glb_json(Path(glb["path"]))
        self.assertEqual(len(parsed["skins"][0]["joints"]), 21)
        self.assertEqual(len(parsed.get("animations", [])), 1)

    def test_quadruped_gait_on_hexapod_is_a_helpful_error(self):
        FORGE.call("char.creature", name="scarab", plan="insect",
                   length=0.9, shoulder=0.35, seed=17)
        rig = FORGE.call("char.creature_rig", name="scarab", plan="insect",
                         length=0.9, shoulder=0.35)
        with self.assertRaises(ForgeError) as ctx:
            FORGE.call("char.animate", rig=rig["armature"], clip="trot")
        self.assertIn("hexapod", str(ctx.exception))

    def test_determinism(self):
        def build_once(out):
            FORGE.call("session.reset")
            FORGE.call("char.creature", name="scarab", plan="insect",
                       length=0.9, shoulder=0.35, seed=17)
            rig = FORGE.call("char.creature_rig", name="scarab", plan="insect",
                             length=0.9, shoulder=0.35)
            FORGE.call("char.animate", rig=rig["armature"], clip="walk", length=24)
            return Path(FORGE.call("export.gltf", out=out)["path"]).read_bytes()

        self.assertEqual(build_once("hex_a.glb"), build_once("hex_b.glb"))


if __name__ == "__main__":
    unittest.main()
