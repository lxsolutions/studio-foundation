"""Live tests for char.gait — motion synthesis from limb morphology."""

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
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_gait_test_")
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


class Humanoid(ForgeCase):
    def _rig(self):
        FORGE.call("char.humanoid", name="warden", height=1.8, seed=3)
        return FORGE.call("char.rig", name="warden", height=1.8)

    def test_slow_is_walk_fast_is_run(self):
        rig = self._rig()
        slow = FORGE.call("char.gait", rig=rig["armature"], speed=0.9)
        fast = FORGE.call("char.gait", rig=rig["armature"], speed=3.5)
        self.assertEqual(slow["style"], "walk")
        self.assertEqual(fast["style"], "run")
        self.assertLess(slow["froude"], 0.55)
        self.assertGreater(fast["froude"], 0.55)
        self.assertGreater(slow["frames"], fast["frames"],
                           "a slower cadence means more frames per cycle")

    def test_explicit_style_and_cadence_math(self):
        rig = self._rig()
        result = FORGE.call("char.gait", rig=rig["armature"], speed=1.0, style="walk")
        self.assertEqual(result["family"], "humanoid")
        self.assertGreater(result["cadence_steps_per_s"], 0.5)
        self.assertLess(result["cadence_steps_per_s"], 4.0)
        self.assertGreater(result["keyframes"], 10)

    def test_gait_exports_as_animation(self):
        rig = self._rig()
        FORGE.call("char.gait", rig=rig["armature"], speed=1.4)
        glb = FORGE.call("export.gltf", out="gait.glb",
                         objects=[rig["armature"], "warden"])
        parsed = read_glb_json(Path(glb["path"]))
        names = [a.get("name", "") for a in parsed.get("animations", [])]
        self.assertTrue(any("gait_walk" in n for n in names))


class Creature(ForgeCase):
    def test_quadruped_transitions_by_froude(self):
        FORGE.call("char.creature", name="hound", plan="canine", length=1.3,
                   shoulder=0.85, seed=5)
        rig = FORGE.call("char.creature_rig", name="hound", plan="canine",
                         length=1.3, shoulder=0.85)
        walk = FORGE.call("char.gait", rig=rig["armature"], speed=0.8)
        trot = FORGE.call("char.gait", rig=rig["armature"], speed=2.0)
        gallop = FORGE.call("char.gait", rig=rig["armature"], speed=5.0)
        self.assertEqual(walk["style"], "walk")
        self.assertEqual(trot["style"], "trot")
        self.assertEqual(gallop["style"], "gallop")
        self.assertLess(walk["froude"], trot["froude"])
        self.assertLess(trot["froude"], gallop["froude"])

    def test_hexapod_gets_tripod_gait(self):
        FORGE.call("char.creature", name="scarab", plan="insect", length=0.9,
                   shoulder=0.35, seed=17)
        rig = FORGE.call("char.creature_rig", name="scarab", plan="insect",
                         length=0.9, shoulder=0.35)
        result = FORGE.call("char.gait", rig=rig["armature"], speed=0.4)
        self.assertEqual(result["family"], "hexapod")
        self.assertEqual(result["style"], "walk")
        self.assertGreater(result["keyframes"], 20)

    def test_determinism(self):
        def build_once(out):
            FORGE.call("session.reset")
            FORGE.call("char.creature", name="hound", plan="canine", length=1.3,
                       shoulder=0.85, seed=5)
            rig = FORGE.call("char.creature_rig", name="hound", plan="canine",
                             length=1.3, shoulder=0.85)
            FORGE.call("char.gait", rig=rig["armature"], speed=2.0)
            return Path(FORGE.call("export.gltf", out=out)["path"]).read_bytes()

        self.assertEqual(build_once("gait_a.glb"), build_once("gait_b.glb"))

    def test_wrong_rig_type_is_a_helpful_error(self):
        FORGE.call("build.box", name="crate")
        with self.assertRaises(ForgeError) as ctx:
            FORGE.call("char.gait", rig="crate")
        self.assertIn("not an armature", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
