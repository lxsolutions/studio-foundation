import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hud_layout import audit_hud  # noqa: E402


class HudLayout(unittest.TestCase):
    def test_compact_bottom_dock_passes(self):
        report = audit_hud(
            {
                "viewport": {"width": 1280, "height": 720},
                "regions": [
                    {
                        "id": "build",
                        "x": 14,
                        "y": 525,
                        "width": 430,
                        "height": 181,
                        "edge": "bottom",
                    },
                    {
                        "id": "selection",
                        "x": 456,
                        "y": 540,
                        "width": 560,
                        "height": 166,
                        "edge": "bottom",
                    },
                    {
                        "id": "map",
                        "x": 1050,
                        "y": 490,
                        "width": 212,
                        "height": 212,
                        "edge": "bottom",
                    },
                ],
                "controls": [{"id": "build_0", "x": 20, "y": 570, "width": 80, "height": 64}],
            }
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["metrics"]["bottom_band_share"], 0.3194)

    def test_giant_overlapping_build_overlay_fails(self):
        report = audit_hud(
            {
                "viewport": {"width": 1280, "height": 720},
                "regions": [
                    {
                        "id": "build",
                        "x": 14,
                        "y": 270,
                        "width": 620,
                        "height": 436,
                        "edge": "bottom",
                    },
                    {
                        "id": "selection",
                        "x": 600,
                        "y": 540,
                        "width": 380,
                        "height": 166,
                        "edge": "bottom",
                    },
                ],
                "controls": [{"id": "tiny", "x": 20, "y": 300, "width": 28, "height": 28}],
            }
        )
        kinds = {finding["kind"] for finding in report["findings"]}
        self.assertFalse(report["ok"])
        self.assertEqual(kinds, {"panel_overlap", "bottom_band_too_tall", "control_too_small"})


if __name__ == "__main__":
    unittest.main()
