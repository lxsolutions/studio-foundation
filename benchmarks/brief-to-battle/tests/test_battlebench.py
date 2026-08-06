"""brief-to-battle static checks (no Blender required)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
REPO = BENCH.parents[1]


class FrozenSet(unittest.TestCase):
    def test_brief_is_well_formed(self):
        briefs = sorted(BENCH.glob("briefs/*.json"))
        self.assertGreaterEqual(len(briefs), 1, "at least the fortress battle")
        for path in briefs:
            with self.subTest(brief=path.name):
                brief = json.loads(path.read_text())
                self.assertEqual(brief["id"], path.stem)
                self.assertTrue(brief["text"])
                self.assertIn("expect_navigation", brief.get("scenario", {}))
                for _name, rel in brief.get("available_entities", {}).items():
                    self.assertTrue(
                        (REPO / rel).is_file(), f"available entity doc exists: {rel}"
                    )

    def test_summary_is_committed_and_current_format(self):
        summary = (BENCH / "SUMMARY.md").read_text()
        self.assertIn("verdict:", summary)
        for path in BENCH.glob("briefs/*.json"):
            self.assertIn(f"| {path.stem} |", summary)

    def test_reference_agent_produces_required_outputs(self):
        agent = (BENCH / "agents" / "scripted_world.py").read_text()
        for required in ("world.json", "battle.json", "metrics.json", "sim_contract"):
            self.assertIn(required, agent)


if __name__ == "__main__":
    unittest.main()
