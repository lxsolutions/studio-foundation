"""Live Blender integration tests for morph.* — shape keys must reach glTF as
morph targets (extras.targetNames + primitives[].targets), and morph.animate
must produce a weights animation channel.

Same pattern as test_forge.py: one shared daemon per module, clean skips when
Blender is absent or BFORGE_SKIP_LIVE is set.
"""

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
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_test_morph_")
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
    """Parse a GLB container's JSON chunk — same stdlib-only proof as test_forge."""
    data = path.read_bytes()
    magic, _version, _length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, f"not a GLB file: magic={magic:#x}"
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    assert chunk_type == 0x4E4F534A, "first GLB chunk is not JSON"
    return json.loads(data[20 : 20 + chunk_length].decode("utf-8"))


class Add(ForgeCase):
    def test_add_exports_a_morph_target_with_the_key_name(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        self.forge.call("morph.add", name="b", key="dented", rule="dent", amount=0.2, radius=2.0)
        exported = self.forge.call("export.gltf", out="morphed.glb")
        gltf = read_glb_json(Path(exported["path"]))
        mesh = gltf["meshes"][0]
        targets = mesh["primitives"][0].get("targets", [])
        self.assertEqual(len(targets), 1, "one shape key -> one morph target")
        self.assertIn("POSITION", targets[0])
        self.assertEqual(mesh.get("extras", {}).get("targetNames"), ["dented"])

    def test_add_reports_moved_vertices_and_keys(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        result = self.forge.call(
            "morph.add", name="b", key="inflate", rule="inflate", amount=0.1, radius=5.0
        )
        self.assertGreater(result["vertices_moved"], 0)
        self.assertEqual(result["keys"], ["Basis", "inflate"])

    def test_add_with_a_tiny_radius_warns_instead_of_silently_no_op(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        result = self.forge.call(
            "morph.add", name="b", key="poke", rule="dent", center=[9, 9, 9], radius=0.1
        )
        self.assertEqual(result["vertices_moved"], 0)
        self.assertIn("note", result)

    def test_add_a_duplicate_key_is_a_helpful_error(self):
        self.forge.call("build.box", name="b")
        self.forge.call("morph.add", name="b", key="dent", rule="dent")
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("morph.add", name="b", key="dent", rule="bulge")
        self.assertIn("already exists", str(ctx.exception))

    def test_rules_actually_displace_different_verts(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        dent = self.forge.call(
            "morph.add", name="b", key="dent", rule="dent", amount=0.2, radius=2.0
        )
        self.forge.call("session.reset")
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        taper = self.forge.call(
            "morph.add", name="b", key="taper", rule="taper", amount=0.5, radius=2.0
        )
        self.assertGreater(dent["vertices_moved"], 0)
        self.assertGreater(taper["vertices_moved"], 0)


class SetAndList(ForgeCase):
    def test_set_updates_the_slider_and_list_reports_it(self):
        self.forge.call("build.box", name="b")
        self.forge.call("morph.add", name="b", key="dent", rule="dent")
        result = self.forge.call("morph.set", name="b", key="dent", value=0.6)
        self.assertAlmostEqual(result["value"], 0.6, places=4)
        listing = self.forge.call("morph.list", name="b")
        dent = [k for k in listing["keys"] if k["key"] == "dent"]
        self.assertEqual(len(dent), 1)
        self.assertAlmostEqual(dent[0]["value"], 0.6, places=4)
        self.assertEqual(dent[0]["slider_min"], 0.0)
        self.assertEqual(dent[0]["slider_max"], 1.0)

    def test_set_clamps_out_of_range_values(self):
        self.forge.call("build.box", name="b")
        self.forge.call("morph.add", name="b", key="dent", rule="dent")
        result = self.forge.call("morph.set", name="b", key="dent", value=4.0)
        self.assertEqual(result["value"], 1.0)

    def test_list_without_keys_reports_empty(self):
        self.forge.call("build.box", name="b")
        listing = self.forge.call("morph.list", name="b")
        self.assertEqual(listing["keys"], [])
        self.assertEqual(listing["count"], 0)

    def test_set_an_unknown_key_lists_what_exists(self):
        self.forge.call("build.box", name="b")
        self.forge.call("morph.add", name="b", key="dent", rule="dent")
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("morph.set", name="b", key="nope", value=1.0)
        self.assertIn("dent", str(ctx.exception))


class Animate(ForgeCase):
    def test_animate_exports_a_weights_channel(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        self.forge.call("morph.add", name="b", key="dented", rule="dent", amount=0.2, radius=2.0)
        result = self.forge.call(
            "morph.animate",
            name="b",
            key="dented",
            frames=[1, 12, 24],
            values=[0.0, 1.0, 0.0],
        )
        self.assertEqual(result["keyframes"], 3)
        exported = self.forge.call("export.gltf", out="morph_anim.glb")
        gltf = read_glb_json(Path(exported["path"]))
        paths = [
            channel["target"]["path"]
            for animation in gltf.get("animations", [])
            for channel in animation["channels"]
        ]
        self.assertIn("weights", paths, f"no morph-weights channel exported: {paths}")

    def test_animate_rejects_mismatched_frame_and_value_lists(self):
        self.forge.call("build.box", name="b")
        self.forge.call("morph.add", name="b", key="dent", rule="dent")
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("morph.animate", name="b", key="dent", frames=[1, 12], values=[0.0])
        self.assertIn("same length", str(ctx.exception))

    def test_animate_requires_an_existing_key(self):
        self.forge.call("build.box", name="b")
        with self.assertRaises(ForgeError):
            self.forge.call(
                "morph.animate", name="b", key="ghost", frames=[1, 12], values=[0.0, 1.0]
            )


if __name__ == "__main__":
    unittest.main()
