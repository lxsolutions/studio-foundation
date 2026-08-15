"""Live regression tests for render.sprite game icons and directional sheets."""

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
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_sprite_test_")
    FORGE = Forge(workdir=TEMP.name, out_dir=str(Path(TEMP.name) / "out"))
    FORGE.start()


def tearDownModule():
    if FORGE is not None:
        FORGE.stop()
    if TEMP is not None:
        TEMP.cleanup()


def png_size(path) -> tuple[int, int]:
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"{path} is not a PNG file")
    _length, kind = struct.unpack_from(">I4s", data, 8)
    if kind != b"IHDR":
        raise AssertionError(f"{path}: first chunk is {kind!r}, not IHDR")
    return struct.unpack_from(">II", data, 16)


class ForgeCase(unittest.TestCase):
    def setUp(self):
        FORGE.call("session.reset")

    @property
    def forge(self) -> Forge:
        return FORGE

    def out_file(self, rel_path: str) -> Path:
        return Path(TEMP.name) / rel_path


class Sprite(ForgeCase):
    def test_alpha_icon_is_clean_and_byte_deterministic(self):
        self.forge.call(
            "build.box",
            name="subject",
            size=[0.4, 0.8, 1.6],
            bevel=0.02,
        )
        args = {
            "name": "subject",
            "size": 48,
            "background": "alpha",
            "shadow": False,
            "bloom": 0.0,
            "samples": 1,
            "_timeout": 900,
        }
        first = self.forge.call("render.sprite", out="alpha_a.png", **args)
        second = self.forge.call("render.sprite", out="alpha_b.png", **args)

        self.assertNotIn("sidecar", first)
        self.assertEqual(png_size(first["path"]), (48, 48))
        self.assertEqual(first["supersample"], 2)
        self.assertEqual(first["render_px"], 96)
        metric = first["frame_metrics"][0]
        self.assertEqual(metric["alpha_min"], 0.0)
        self.assertEqual(metric["alpha_max"], 1.0)
        self.assertGreater(metric["alpha_coverage"], 0.05)
        self.assertLess(metric["alpha_coverage"], 0.9)
        self.assertEqual(metric["edge_alpha_max"], 0.0)
        self.assertEqual(
            Path(first["path"]).read_bytes(),
            Path(second["path"]).read_bytes(),
            "the same scene and sprite parameters must produce byte-identical PNGs",
        )

    def test_gradient_icon_is_opaque_and_reports_effective_controls(self):
        self.forge.call("build.box", name="subject", bevel=0.0)
        result = self.forge.call(
            "render.sprite",
            name="subject",
            out="gradient.png",
            size=8,
            supersample=99,
            fill=2.0,
            lens=2.0,
            elevation=100.0,
            exposure=99.0,
            background="gradient",
            shadow=False,
            bloom=0.0,
            samples=1,
            _timeout=900,
        )

        self.assertEqual(result["frame_px"], 32)
        self.assertEqual(result["render_px"], 128)
        self.assertEqual(result["supersample"], 4)
        self.assertEqual(result["samples"], 8)
        self.assertEqual(result["exposure"], 16.0)
        self.assertEqual(png_size(result["path"]), (32, 32))
        self.assertEqual(result["fill_target"], 0.98)
        self.assertEqual(result["camera"]["lens_mm"], 8.0)
        self.assertEqual(result["camera"]["elevation"], 85.0)
        metric = result["frame_metrics"][0]
        self.assertEqual(metric["alpha_min"], 1.0)
        self.assertEqual(metric["alpha_max"], 1.0)
        self.assertEqual(metric["alpha_coverage"], 1.0)

    def test_exposure_changes_linear_subject_luminance(self):
        self.forge.call("build.box", name="subject", bevel=0.0)
        common = {
            "name": "subject",
            "size": 32,
            "supersample": 1,
            "background": "solid",
            "bg_inner": "#000000",
            "shadow": False,
            "bloom": 0.0,
            "look": "linear",
            "contrast": 1.0,
            "saturation": 1.0,
            "vignette": 0.0,
            "samples": 1,
            "_timeout": 900,
        }
        low = self.forge.call("render.sprite", out="exposure_low.png", exposure=-2.0, **common)
        high = self.forge.call("render.sprite", out="exposure_high.png", exposure=2.0, **common)

        self.assertGreater(
            high["analysis"]["luma_linear"]["mean"],
            low["analysis"]["luma_linear"]["mean"],
        )

    def test_directional_sheet_refits_each_view_and_writes_sidecar(self):
        self.forge.call(
            "build.box",
            name="long_subject",
            size=[3.0, 0.25, 1.0],
            bevel=0.0,
        )
        result = self.forge.call(
            "render.sprite",
            name="long_subject",
            out="directions.png",
            size=32,
            views=4,
            azimuth=0.0,
            background="alpha",
            shadow=False,
            bloom=0.0,
            samples=1,
            _timeout=900,
        )

        self.assertEqual((result["cols"], result["rows"]), (2, 2))
        self.assertEqual(png_size(result["path"]), (64, 64))
        metrics = result["frame_metrics"]
        self.assertEqual([row["yaw_degrees"] for row in metrics], [0.0, 90.0, 180.0, 270.0])
        self.assertGreater(
            len({row["distance_m"] for row in metrics}),
            1,
            "an asymmetric subject must be fitted independently at each yaw",
        )
        self.assertTrue(all(row["edge_alpha_max"] == 0.0 for row in metrics))

        sidecar_path = self.out_file(result["sidecar"])
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        self.assertEqual(sidecar["frames"], 4)
        self.assertEqual(sidecar["camera_frames"], metrics)
        self.assertEqual(sidecar["object"], "long_subject")

    def test_missing_subject_names_the_listing_op(self):
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call(
                "render.sprite",
                name="ghost",
                size=32,
                samples=1,
            )
        self.assertIn("object.list", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
