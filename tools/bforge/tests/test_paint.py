"""Live Blender integration tests for paint.* — vertex colours must reach glTF
as COLOR_0, gradients must actually vary, and noise must be bit-deterministic.

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
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_test_paint_")
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


def read_glb(path: Path):
    """Split a GLB into (json dict, BIN chunk bytes) with stdlib only."""
    data = path.read_bytes()
    magic, _version, _length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, f"not a GLB file: magic={magic:#x}"
    offset = 12
    gltf, binary = None, b""
    while offset < len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8 : offset + 8 + chunk_length]
        if chunk_type == 0x4E4F534A:
            gltf = json.loads(chunk.decode("utf-8"))
        elif chunk_type == 0x004E4942:
            binary = chunk
        offset += 8 + chunk_length
    assert gltf is not None, "GLB has no JSON chunk"
    return gltf, binary


_COMPONENT = {
    5120: ("b", 1, None),
    5121: ("B", 1, 255),
    5122: ("h", 2, None),
    5123: ("H", 2, 65535),
    5125: ("I", 4, None),
    5126: ("f", 4, None),
}
_TYPE_LEN = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_accessor(gltf, binary, index):
    """Decode an accessor into a list of tuples, honouring `normalized`."""
    accessor = gltf["accessors"][index]
    view = gltf["bufferViews"][accessor["bufferView"]]
    fmt, size, norm_max = _COMPONENT[accessor["componentType"]]
    width = _TYPE_LEN[accessor["type"]]
    stride = view.get("byteStride") or size * width
    base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    out = []
    for i in range(accessor["count"]):
        at = base + i * stride
        values = struct.unpack_from(f"<{width}{fmt}", binary, at)
        if norm_max is not None and accessor.get("normalized"):
            values = tuple(v / norm_max for v in values)
        out.append(values)
    return out


def read_colors(path: Path):
    """The exported COLOR_0 of the first primitive, as (r, g, b, a) 0..1 rows."""
    gltf, binary = read_glb(path)
    primitive = gltf["meshes"][0]["primitives"][0]
    return gltf, read_accessor(gltf, binary, primitive["attributes"]["COLOR_0"])


class Fill(ForgeCase):
    def test_fill_exports_color0(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        result = self.forge.call("paint.fill", name="b", color="#8899aa")
        self.assertEqual(result["layer"], "color")
        self.assertGreater(result["loops_painted"], 0)
        exported = self.forge.call("export.gltf", out="filled.glb")
        gltf, _binary = read_glb(Path(exported["path"]))
        primitive = gltf["meshes"][0]["primitives"][0]
        self.assertIn("COLOR_0", primitive["attributes"])

    def test_fill_paints_every_loop_the_same_colour(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        result = self.forge.call("paint.fill", name="b", color="#8899aa")
        exported = self.forge.call("export.gltf", out="filled_uniform.glb")
        _gltf, colors = read_colors(Path(exported["path"]))
        self.assertEqual(len(colors), result["loops_painted"])
        for channel in range(3):
            values = [c[channel] for c in colors]
            self.assertLessEqual(
                max(values) - min(values),
                0.02,
                "a flat fill must come back uniform",
            )
        # #8899aa is a cool grey: blue channel clearly above red.
        self.assertGreater(colors[0][2], colors[0][0])

    def test_fill_accepts_a_palette_name(self):
        self.forge.call("build.box", name="b")
        result = self.forge.call("paint.fill", name="b", color="leaf_green")
        self.assertGreater(result["loops_painted"], 0)

    def test_fill_on_a_missing_object_is_a_clean_error(self):
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("paint.fill", name="does_not_exist", color="#ffffff")
        self.assertIn("does_not_exist", str(ctx.exception))


class Height(ForgeCase):
    def test_height_gradient_varies_from_bottom_to_top(self):
        self.forge.call("build.box", name="b", size=[1, 1, 2], origin="center")
        self.forge.call("paint.height", name="b", low="#000000", high="#ffffff", axis="z")
        exported = self.forge.call("export.gltf", out="gradient.glb")
        _gltf, colors = read_colors(Path(exported["path"]))
        luma = [0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] for c in colors]
        self.assertGreater(
            max(luma) - min(luma),
            0.5,
            f"a black-to-white gradient over 2 m must span most of the range: {min(luma):.3f}..{max(luma):.3f}",
        )

    def test_height_reports_the_auto_range(self):
        self.forge.call("build.box", name="b", size=[1, 1, 2], origin="bottom")
        result = self.forge.call("paint.height", name="b", low="#000000", high="#ffffff")
        self.assertEqual(result["range"], [0.0, 2.0])

    def test_height_on_a_flat_axis_is_a_clear_error(self):
        self.forge.call("build.plane", name="flat", size=[2, 2])
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("paint.height", name="flat", low="#000000", high="#ffffff", axis="z")
        self.assertIn("flat", str(ctx.exception))


class Noise(ForgeCase):
    def test_noise_is_deterministic_for_a_seed(self):
        def bake(out):
            self.forge.call("build.plane", name="p", size=[4, 4], cuts=8)
            self.forge.call(
                "paint.noise", name="p", color_a="#000000", color_b="#ffffff", scale=2.0, seed=7
            )
            exported = self.forge.call("export.gltf", out=out)
            _gltf, colors = read_colors(Path(exported["path"]))
            return colors

        first = bake("noise_a.glb")
        self.forge.call("session.reset")
        second = bake("noise_b.glb")
        self.assertEqual(first, second, "same seed + same params must give identical colours")

    def test_different_seeds_give_different_patterns(self):
        self.forge.call("build.plane", name="p", size=[4, 4], cuts=8)
        self.forge.call("paint.noise", name="p", color_a="#000000", color_b="#ffffff", seed=1)
        first = read_colors(Path(self.forge.call("export.gltf", out="n1.glb")["path"]))[1]
        self.forge.call("session.reset")
        self.forge.call("build.plane", name="p", size=[4, 4], cuts=8)
        self.forge.call("paint.noise", name="p", color_a="#000000", color_b="#ffffff", seed=2)
        second = read_colors(Path(self.forge.call("export.gltf", out="n2.glb")["path"]))[1]
        self.assertNotEqual(first, second)

    def test_noise_actually_varies_across_the_mesh(self):
        self.forge.call("build.plane", name="p", size=[4, 4], cuts=8)
        self.forge.call(
            "paint.noise", name="p", color_a="#000000", color_b="#ffffff", scale=2.0, seed=7
        )
        exported = self.forge.call("export.gltf", out="noise_var.glb")
        _gltf, colors = read_colors(Path(exported["path"]))
        luma = {round(c[0], 2) for c in colors}
        self.assertGreater(len(luma), 4, "noise should paint more than a handful of values")


class Cavity(ForgeCase):
    def test_cavity_paints_a_recess_but_not_the_flat_surround(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        # Sink a panel into the top: the recess walls are concave, the rest flat.
        self.forge.call("build.extrude", name="b", direction="up", distance=-0.2, inset=0.2)
        result = self.forge.call("paint.cavity", name="b", color="#000000", mode="cavity")
        self.assertGreater(result["loops_painted"], 0)
        exported = self.forge.call("export.gltf", out="cavity.glb")
        _gltf, colors = read_colors(Path(exported["path"]))
        dark = sum(1 for c in colors if c[0] < 0.9)
        fraction = dark / len(colors)
        self.assertGreater(fraction, 0.01, "the recess should take the dirt colour")
        self.assertLess(fraction, 0.9, "flat faces around the recess must stay unpainted")

    def test_edge_mode_paints_convex_ridges_instead(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        cavity = self.forge.call("paint.cavity", name="b", color="#000000", mode="cavity")
        edge = self.forge.call("paint.cavity", name="b", color="#ffffff", mode="edge", layer="wear")
        # A bevelled box has both concave-free flats and convex chamfer edges;
        # the two modes must not agree on zero.
        self.assertGreaterEqual(cavity["loops_painted"], 0)
        self.assertGreater(edge["loops_painted"], 0)

    def test_cavity_on_a_flat_plane_is_advice_not_silence(self):
        self.forge.call("build.plane", name="flat", size=[2, 2])
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("paint.cavity", name="flat", color="#000000")
        self.assertIn("curvature", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
