"""Live tests for check.style / check.conformance — the art-director layer.

A set of same-style assets must score coherent; a palette- or texel-drifting
asset must be caught with the right axis named.
"""

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
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_style_test_")
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


def _styled_box(name, color="#777777", uv_scale=1.0):
    FORGE.call(
        "build.box",
        name=name,
        size=[1.0, 1.0, 1.0],
        material="metal",
        color=color,
        uv="box",
        uv_scale=uv_scale,
    )
    return name


class Style(ForgeCase):
    def test_fingerprint_reports_the_style_axes(self):
        _styled_box("crate_a")
        result = FORGE.call("check.style")
        fp = result["objects"][0]
        for key in (
            "palette",
            "texel_density",
            "hard_edge_ratio",
            "materials",
            "tris_per_m3",
            "uv_coverage",
        ):
            self.assertIn(key, fp)
        self.assertEqual(fp["materials"], 1)
        self.assertGreater(fp["texel_density"], 0)
        self.assertTrue(fp["palette"][0]["hex"].startswith("#"))
        self.assertIn("median_texel_density", result["set"])


class Conformance(ForgeCase):
    def test_same_style_set_is_coherent(self):
        _styled_box("a")
        _styled_box("b")
        result = FORGE.call("check.conformance")
        self.assertEqual(result["outliers"], [])
        for row in result["objects"]:
            self.assertEqual(
                row["verdict"], "coherent", f"{row['object']} should be coherent: {row}"
            )

    def test_palette_and_texel_drift_are_caught_and_named(self):
        _styled_box("a")
        _styled_box("b")
        _styled_box("drifter", color="#b020e0", uv_scale=20.0)
        result = FORGE.call("check.conformance")
        worst = result["objects"][0]  # sorted by score ascending
        self.assertEqual(worst["object"], "drifter")
        self.assertIn(worst["verdict"], ("drifting", "outlier"))
        self.assertIn(worst["worst_axis"], ("palette", "texel_density"))
        self.assertTrue(worst["fix"], "a finding must name the fixing op")
        good = {r["object"]: r for r in result["objects"][1:]}
        self.assertEqual(good["a"]["verdict"], "coherent")
        self.assertEqual(good["b"]["verdict"], "coherent")

    def test_reference_mode(self):
        _styled_box("hero")
        _styled_box("same_as_hero")
        _styled_box("off", color="#1010c0")
        result = FORGE.call("check.conformance", reference="hero")
        rows = {r["object"]: r for r in result["objects"]}
        self.assertEqual(rows["same_as_hero"]["verdict"], "coherent")
        self.assertLess(rows["off"]["score"], rows["same_as_hero"]["score"])

    def test_real_pack_conforms(self):
        """The props a real recipe produces must not trip the gate."""
        FORGE.call("prop.crate", name="crate", seed=3)
        FORGE.call("prop.barrel", name="barrel", height=1.1, bands=3, seed=7)
        result = FORGE.call("check.conformance")
        self.assertEqual(
            result["outliers"], [], f"stock props should look like one game: {result['objects']}"
        )


if __name__ == "__main__":
    unittest.main()
