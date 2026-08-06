"""brief-to-battle static checks (no Blender required)."""

from __future__ import annotations

import importlib.util
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

    def test_every_brief_has_a_control_answer(self):
        """A brief with no scripted answer has no control group: the reference
        run fails on it, so any model score for that brief is unanchored."""
        spec = importlib.util.spec_from_file_location(
            "scripted_world", BENCH / "agents" / "scripted_world.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for path in sorted(BENCH.glob("briefs/*.json")):
            brief = json.loads(path.read_text())
            with self.subTest(brief=path.stem):
                scenario = module.SCENARIOS.get(path.stem)
                self.assertIsNotNone(scenario, "brief needs a reference answer")
                self.assertEqual(
                    sorted(scenario["initial"]),
                    sorted(brief["scenario"]["entities"]),
                    "reference initial state must cover exactly the brief's entities",
                )
                known = set(brief["scenario"]["entities"])
                for _tick, entity, _verb, _arg in scenario["events"]:
                    self.assertIn(entity, known, "event names an unknown entity")


class WrapperIsBriefNeutral(unittest.TestCase):
    """The wrapper must never tell the model the objective.

    A wrapper that states one brief's goal states the INVERSE of another's, and
    the harness then scores obedience as a reasoning failure. That is exactly
    what happened to hold_the_gate in the 2026-08-06 runs: the prompt ended
    with the fortress_battle objective for every brief.
    """

    def _wrapper(self):
        spec = importlib.util.spec_from_file_location(
            "claude_battle", BENCH / "agents" / "claude_battle.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_prompt_template_states_no_outcome(self):
        prompt = self._wrapper().PROMPT
        for leak in ("destroyed or open", "intact and closed"):
            self.assertNotIn(
                leak,
                prompt,
                "the goal sentence must come from the brief, not the template",
            )

    def test_goal_line_matches_every_brief(self):
        wrapper = self._wrapper()
        for path in sorted(BENCH.glob("briefs/*.json")):
            brief = json.loads(path.read_text())
            expect = brief["scenario"]["expect_navigation"]
            with self.subTest(brief=path.stem):
                for name, blocks in expect.items():
                    clause = wrapper.goal_clause(name, blocks)
                    other = wrapper.goal_clause(name, not blocks)
                    self.assertIn("blocking", clause)
                    self.assertNotEqual(clause, other)
                    # blocking == intact and shut; not-blocking == open/destroyed
                    self.assertEqual(
                        "intact and closed" in clause,
                        blocks,
                        f"{path.stem}/{name}: goal contradicts expect_navigation",
                    )


if __name__ == "__main__":
    unittest.main()
