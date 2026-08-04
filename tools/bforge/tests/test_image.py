"""Live tests for image.analyze / image.to_mesh — concept image -> 3D mesh."""

from __future__ import annotations

import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge.client import DaemonError, Forge, ForgeError, find_blender  # noqa: E402

FORGE: Forge | None = None
TEMP: tempfile.TemporaryDirectory | None = None


def _png_rgba(path: Path, w: int, h: int, pixel_fn) -> None:
    """Minimal RGBA PNG writer (no PIL on the host side)."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(pixel_fn(x, y))

    def chunk(tag, data):
        body = struct.pack(">I", len(data)) + tag + data
        return body + struct.pack(">I", zlib.crc32(tag + data))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw)))
        + chunk(b"IEND", b"")
    )


def setUpModule():
    global FORGE, TEMP
    if os.environ.get("BFORGE_SKIP_LIVE"):
        raise unittest.SkipTest("BFORGE_SKIP_LIVE is set")
    try:
        find_blender()
    except DaemonError as exc:
        raise unittest.SkipTest(f"Blender not available: {exc}") from exc
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_image_test_")
    FORGE = Forge(workdir=TEMP.name, out_dir=str(Path(TEMP.name) / "out"))
    FORGE.start()
    # A red disc with alpha (clean segmentation), and a green triangle with no
    # alpha on a uniform backdrop (backdrop-distance segmentation).
    _png_rgba(Path(TEMP.name) / "disc.png", 128, 128,
              lambda x, y: (200, 30, 30, 255) if (x - 64) ** 2 + (y - 64) ** 2 < 40 ** 2
              else (12, 12, 16, 255))
    _png_rgba(Path(TEMP.name) / "tri.png", 128, 128,
              lambda x, y: (30, 180, 60, 255) if y > 30 and abs(x - 64) < (y - 30) * 0.6
              else (240, 240, 240, 255))


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


class Analyze(ForgeCase):
    def test_disc_measurements(self):
        result = FORGE.call("image.analyze", path=str(Path(TEMP.name) / "disc.png"))
        self.assertAlmostEqual(result["aspect_h_over_w"], 1.0, delta=0.15)
        self.assertGreater(result["symmetry"], 0.9)
        self.assertGreater(result["fill_ratio"], 0.7)
        self.assertIn("extrude", result["approach"])
        self.assertEqual(result["palette"][0]["hex"], "#c81e1e")

    def test_backdrop_segmentation_without_alpha(self):
        result = FORGE.call("image.analyze", path=str(Path(TEMP.name) / "tri.png"))
        self.assertGreater(result["fill_ratio"], 0.4)
        self.assertTrue(result["palette"][0]["hex"].startswith("#"))


class ToMesh(ForgeCase):
    def test_disc_extrudes_with_high_fidelity(self):
        result = FORGE.call("image.to_mesh", path=str(Path(TEMP.name) / "disc.png"),
                            name="medallion", target_height=1.0, depth=0.2,
                            texture="project")
        self.assertGreater(result["silhouette_iou"], 0.9,
                           "the mesh silhouette must BE the picture's")
        self.assertGreater(result["triangles"], 50)
        self.assertLess(result["triangles"], 3000)
        self.assertAlmostEqual(result["bounds"]["size"][2], 1.0, delta=0.05)
        self.assertAlmostEqual(result["bounds"]["size"][1], 0.2, delta=0.1)

    def test_texture_variants_and_gate(self):
        FORGE.call("image.to_mesh", path=str(Path(TEMP.name) / "disc.png"),
                   name="flat", texture="none")
        review = FORGE.call("gameready.review", objects=["flat"])
        self.assertTrue(review["passed"], f"findings: {review['findings']}")

    def test_exports_cleanly(self):
        import json
        import struct as st
        FORGE.call("image.to_mesh", path=str(Path(TEMP.name) / "disc.png"),
                   name="medallion", texture="project")
        glb = FORGE.call("export.gltf", out="medallion.glb", objects=["medallion"])
        data = Path(glb["path"]).read_bytes()
        chunk_len, chunk_type = st.unpack_from("<I4s", data, 12)
        parsed = json.loads(data[20:20 + chunk_len])
        self.assertGreaterEqual(len(parsed["meshes"]), 1)
        self.assertGreaterEqual(len(parsed.get("images", [])), 1,
                                "projected texture must ship in the GLB")

    def test_determinism(self):
        def build_once(out):
            FORGE.call("session.reset")
            FORGE.call("image.to_mesh", path=str(Path(TEMP.name) / "disc.png"),
                       name="medallion", texture="none")
            return Path(FORGE.call("export.gltf", out=out)["path"]).read_bytes()

        self.assertEqual(build_once("img_a.glb"), build_once("img_b.glb"))

    def test_empty_subject_is_a_helpful_error(self):
        blank = Path(TEMP.name) / "blank.png"
        _png_rgba(blank, 64, 64, lambda x, y: (20, 20, 24, 255))
        with self.assertRaises(ForgeError) as ctx:
            FORGE.call("image.analyze", path=str(blank))
        self.assertIn("no subject", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
