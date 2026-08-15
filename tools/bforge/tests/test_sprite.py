"""Live regression tests for render.sprite game icons and directional sheets."""

from __future__ import annotations

import json
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


def png_rgba(path) -> tuple[int, int, list[bytes]]:
    """Decode an 8-bit non-interlaced RGBA PNG with the standard library."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"{path} is not a PNG file")
    offset, compressed = 8, bytearray()
    width = height = depth = colour = interlace = 0
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour, _compression, _filter, interlace = struct.unpack(
                ">IIBBBBB", body
            )
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            break
        offset += 12 + length
    if (depth, colour, interlace) != (8, 6, 0):
        raise AssertionError(
            f"{path}: expected 8-bit non-interlaced RGBA, got "
            f"depth={depth}, colour={colour}, interlace={interlace}"
        )
    raw = zlib.decompress(bytes(compressed))
    stride, source, previous, rows = width * 4, 0, bytearray(width * 4), []
    for _ in range(height):
        filter_kind = raw[source]
        row = bytearray(raw[source + 1 : source + 1 + stride])
        source += stride + 1
        for index in range(stride):
            left = row[index - 4] if index >= 4 else 0
            above = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            if filter_kind == 1:
                row[index] = (row[index] + left) & 0xFF
            elif filter_kind == 2:
                row[index] = (row[index] + above) & 0xFF
            elif filter_kind == 3:
                row[index] = (row[index] + (left + above) // 2) & 0xFF
            elif filter_kind == 4:
                predictor = left + above - upper_left
                distances = (
                    abs(predictor - left),
                    abs(predictor - above),
                    abs(predictor - upper_left),
                )
                chosen = (left, above, upper_left)[distances.index(min(distances))]
                row[index] = (row[index] + chosen) & 0xFF
            elif filter_kind != 0:
                raise AssertionError(f"{path}: unsupported PNG filter {filter_kind}")
        rows.append(bytes(row))
        previous = row
    return width, height, rows


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
            color="#c43b2f",
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
        self.assertFalse(metric["clipped"])
        self.assertIsNotNone(metric["content_bounds_px"])
        self.assertIsNotNone(metric["bottom_center_px"])
        self.assertEqual(
            Path(first["path"]).read_bytes(),
            Path(second["path"]).read_bytes(),
            "the same scene and sprite parameters must produce byte-identical PNGs",
        )
        width, height, rows = png_rgba(first["path"])
        transparent_rgb = [
            row[x * 4 : x * 4 + 3] for row in rows for x in range(width) if row[x * 4 + 3] == 0
        ]
        self.assertTrue(transparent_rgb, "fixture must contain fully transparent pixels")
        self.assertTrue(
            all(any(channel > 0 for channel in rgb) for rgb in transparent_rgb),
            "saved alpha PNG must carry dilated hidden RGB for filtering/mipmaps",
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
        self.assertEqual(metric["alpha_min"], 0.0)
        self.assertEqual(metric["alpha_max"], 1.0)
        self.assertGreater(metric["alpha_coverage"], 0.05)
        self.assertLess(metric["alpha_coverage"], 0.9)
        self.assertEqual(metric["edge_alpha_max"], 0.0)
        self.assertFalse(metric["clipped"])
        self.assertIsNotNone(metric["content_bounds_px"])
        self.assertEqual(result["budget"]["sheet_px"], [32, 32])

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

    def test_directional_sheet_uses_shared_scale_anchor_and_writes_sidecar(self):
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
        self.assertEqual(
            len({row["distance_m"] for row in metrics}),
            1,
            "every yaw must preserve one world scale instead of popping",
        )
        self.assertEqual(len({tuple(row["target_m"]) for row in metrics}), 1)
        self.assertEqual(len({tuple(row["ground_anchor_m"]) for row in metrics}), 1)
        self.assertEqual(len({tuple(row["ground_anchor_px"]) for row in metrics}), 1)
        self.assertEqual(len({row["scale_px_per_m"] for row in metrics}), 1)
        content_widths = {
            row["content_bounds_px"][2] - row["content_bounds_px"][0] for row in metrics
        }
        self.assertGreater(
            len(content_widths),
            1,
            "an asymmetric subject should change silhouette width, not camera scale",
        )
        self.assertTrue(all(row["edge_alpha_max"] == 0.0 for row in metrics))
        self.assertTrue(all(not row["clipped"] for row in metrics))

        sidecar_path = self.out_file(result["sidecar"])
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        self.assertEqual(sidecar["frames"], 4)
        self.assertEqual(sidecar["camera_frames"], metrics)
        self.assertEqual(sidecar["object"], "long_subject")
        self.assertEqual(sidecar["framing"], result["framing"])
        self.assertEqual(sidecar["budget"], result["budget"])

    def test_directional_sidecar_is_removed_by_single_view_replacement(self):
        self.forge.call("build.box", name="subject", bevel=0.0)
        common = {
            "name": "subject",
            "out": "replace.png",
            "size": 32,
            "supersample": 1,
            "background": "alpha",
            "shadow": False,
            "bloom": 0.0,
            "samples": 1,
            "_timeout": 900,
        }
        directional = self.forge.call("render.sprite", views=2, **common)
        sidecar = self.out_file(directional["sidecar"])
        self.assertTrue(sidecar.is_file())
        self.assertEqual(json.loads(sidecar.read_text(encoding="utf-8"))["frames"], 2)

        single = self.forge.call("render.sprite", views=1, **common)
        self.assertNotIn("sidecar", single)
        self.assertFalse(sidecar.exists(), "single-view replacement must remove stale JSON")
        self.assertEqual(
            list(sidecar.parent.glob(f".{sidecar.name}.*.tmp")),
            [],
            "atomic sidecar writes must not leave temporary files",
        )

    def test_exr_scratch_is_cleaned_after_success_and_partial_failure(self):
        self.forge.call("build.box", name="subject", bevel=0.0)
        common = {
            "name": "subject",
            "size": 32,
            "supersample": 1,
            "background": "alpha",
            "shadow": False,
            "bloom": 0.0,
            "samples": 1,
            "_timeout": 900,
        }
        scratch = Path(TEMP.name) / "out" / "_sprite"

        self.forge.call("render.sprite", out="scratch_ok.png", **common)
        self.assertFalse(scratch.exists(), "successful render must remove EXR scratch")

        blocked_output = Path(TEMP.name) / "out" / "partial.png"
        blocked_output.mkdir(parents=True)
        with self.assertRaises(ForgeError):
            self.forge.call("render.sprite", out="partial.png", **common)
        self.assertFalse(scratch.exists(), "partial failure must remove EXR scratch")

    def test_over_budget_is_rejected_before_scene_lookup_or_scratch(self):
        scratch = Path(TEMP.name) / "out" / "_sprite"
        with self.assertRaises(ForgeError) as raised:
            self.forge.call(
                "render.sprite",
                name="ghost",
                size=512,
                supersample=2,
                views=16,
                samples=97,
            )
        message = str(raised.exception)
        self.assertIn("resource budget rejected", message)
        self.assertIn("aggregate work", message)
        self.assertNotIn("ghost", message, "budget preflight must win before scene lookup")
        self.assertFalse(scratch.exists(), "rejected request must not create scratch storage")

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
