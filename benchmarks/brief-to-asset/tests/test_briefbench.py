"""brief-to-asset static checks: the frozen set is well-formed and the
reference agent only uses ops that actually exist (no Blender required)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
REPO = BENCH.parents[1]


class FrozenSet(unittest.TestCase):
    def setUp(self):
        self.briefs = sorted(BENCH.glob("briefs/*.json"))
        self.catalog = {
            op["name"]
            for op in json.loads(
                (REPO / "tools" / "bforge" / "catalog.json").read_text()
            )["ops"]
        }

    def test_briefs_are_well_formed(self):
        self.assertGreaterEqual(
            len(self.briefs), 5, "the frozen set must not silently shrink"
        )
        ids = []
        for path in self.briefs:
            with self.subTest(brief=path.name):
                brief = json.loads(path.read_text())
                self.assertEqual(brief["id"], path.stem)
                self.assertTrue(brief["text"])
                self.assertIn(
                    brief["category"],
                    {"prop", "weapon", "creature", "character", "environment"},
                )
                self.assertIsInstance(brief.get("requirements", {}), dict)
                ids.append(brief["id"])
        self.assertEqual(len(ids), len(set(ids)), "brief ids must be unique")

    def test_reference_agent_ops_exist_in_the_catalog(self):
        agent = (BENCH / "agents" / "scripted_recipe.py").read_text()
        self.assertIn("RECIPES", agent)
        import ast

        ops_used = set()
        for node in ast.walk(ast.parse(agent)):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "." in node.value
            ):
                if node.value.split(".")[0] in (
                    "prop",
                    "char",
                    "env",
                    "gameready",
                    "image",
                    "mesh",
                    "uv",
                    "material",
                    "kit",
                    "arch",
                    "check",
                    "render",
                    "rig",
                    "morph",
                    "paint",
                    "build",
                    "object",
                    "bake",
                    "meta",
                    "session",
                    "export",
                ):
                    ops_used.add(node.value)
        self.assertGreater(len(ops_used), 5)
        missing = ops_used - self.catalog
        self.assertEqual(
            missing, set(), f"agent uses ops not in the catalog: {missing}"
        )

    def test_summary_is_committed_and_current_format(self):
        summary = (BENCH / "SUMMARY.md").read_text()
        self.assertIn("verdict:", summary)
        for path in self.briefs:
            self.assertIn(f"| {path.stem} |", summary)


if __name__ == "__main__":
    unittest.main()
