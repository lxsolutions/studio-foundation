"""Live tests for render.impostor — billboard sprite-sheet baking.

Same pattern as test_forge.py: one shared daemon for the whole module
(booting Blender costs ~5 s), skipping cleanly when Blender is absent or
BFORGE_SKIP_LIVE is set. PNG dimensions are read from the IHDR chunk with
struct — stdlib only, no PIL.
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
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_impostor_test_")
    FORGE = Forge(workdir=TEMP.name, out_dir=str(Path(TEMP.name) / "out"))
    FORGE.start()


def tearDownModule():
    if FORGE is not None:
        FORGE.stop()
    if TEMP is not None:
        TEMP.cleanup()


def png_size(path) -> tuple[int, int]:
    """(width, height) from the PNG IHDR chunk, stdlib only."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"{path} is not a PNG file")
    length, kind = struct.unpack_from(">I4s", data, 8)
    if kind != b"IHDR":
        raise AssertionError(f"{path}: first chunk is {kind!r}, not IHDR")
    width, height = struct.unpack_from(">II", data, 16)
    return width, height


class ForgeCase(unittest.TestCase):
    def setUp(self):
        FORGE.call("session.reset")

    @property
    def forge(self) -> Forge:
        return FORGE

    def out_file(self, rel: str) -> Path:
        return Path(TEMP.name) / rel


class Impostor(ForgeCase):
    def test_sheet_layout_sidecar_and_pixel_dimensions(self):
        self.forge.call("build.box", name="crateish", size=[0.8, 0.6, 1.2], bevel=0.0)
        result = self.forge.call(
            "render.impostor",
            name="crateish",
            out="imp.png",
            views=4,
            size=64,
            samples=8,
            _timeout=900,
        )
        self.assertEqual(result["frames"], 4)
        self.assertEqual(result["cols"], 2)
        self.assertEqual(result["rows"], 2)

        sheet = self.out_file(result["sheet"])
        self.assertTrue(sheet.is_file(), f"sheet missing: {sheet}")
        self.assertEqual(png_size(sheet), (2 * 64, 2 * 64))
        self.assertEqual(result["bytes"], sheet.stat().st_size)

        sidecar_path = self.out_file(result["sidecar"])
        self.assertTrue(sidecar_path.is_file(), f"sidecar missing: {sidecar_path}")
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        self.assertEqual(sidecar["frames"], 4)
        self.assertEqual(sidecar["cols"], 2)
        self.assertEqual(sidecar["rows"], 2)
        self.assertEqual(sidecar["frame_px"], 64)
        self.assertEqual(sidecar["yaw_degrees"], [0.0, 90.0, 180.0, 270.0])
        self.assertEqual(sidecar["elevation"], 0.0)
        self.assertEqual(sidecar["object"], "crateish")
        for axis, want in enumerate((0.8, 0.6, 1.2)):
            self.assertAlmostEqual(sidecar["bounds_m"][axis], want, places=3)

    def test_normals_true_writes_the_normal_sheet(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1], bevel=0.0)
        result = self.forge.call(
            "render.impostor",
            name="b",
            out="lit.png",
            views=4,
            size=64,
            samples=8,
            normals=True,
            _timeout=900,
        )
        self.assertIn("normal_sheet", result)
        normal = self.out_file(result["normal_sheet"])
        self.assertEqual(normal.name, "lit_normal.png")
        self.assertTrue(normal.is_file(), f"normal sheet missing: {normal}")
        self.assertEqual(png_size(normal), (result["cols"] * 64, result["rows"] * 64))

    def test_identical_calls_produce_identical_output(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1], bevel=0.0)
        first = self.forge.call(
            "render.impostor", name="b", out="a.png", views=4, size=64, samples=8,
            _timeout=900,
        )
        second = self.forge.call(
            "render.impostor", name="b", out="b.png", views=4, size=64, samples=8,
            _timeout=900,
        )
        self.assertEqual(
            self.out_file(first["sidecar"]).read_bytes(),
            self.out_file(second["sidecar"]).read_bytes(),
            "sidecar JSON must be byte-identical run to run",
        )
        # This pipeline (Cycles CPU, fixed seed, Blender's PNG writer) embeds no
        # timestamps, so the whole PNG compares byte-identical. If a future
        # Blender adds a tIME chunk, compare IHDR+IDAT chunks only.
        self.assertEqual(
            self.out_file(first["sheet"]).read_bytes(),
            self.out_file(second["sheet"]).read_bytes(),
            "sheet PNG must be byte-identical run to run",
        )

    def test_missing_object_names_the_listing_op(self):
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("render.impostor", name="ghost", views=1, size=8, samples=1)
        self.assertIn("object.list", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
