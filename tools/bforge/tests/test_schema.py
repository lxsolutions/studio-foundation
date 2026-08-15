"""Catalog and schema-export tests. No Blender required — these run in CI."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import schema as schema_mod  # noqa: E402


class Catalog(unittest.TestCase):
    def setUp(self):
        self.ops = schema_mod.load_catalog()

    def test_catalog_is_committed_and_populated(self):
        self.assertTrue(schema_mod.CATALOG_PATH.is_file())
        self.assertGreaterEqual(len(self.ops), 80)

    def test_every_op_is_well_formed(self):
        for op in self.ops:
            with self.subTest(op=op["name"]):
                self.assertRegex(op["name"], r"^[a-z_]+\.[a-z_]+$")
                self.assertTrue(op["summary"], "every op needs a summary")
                self.assertEqual(op["inputSchema"]["type"], "object")
                self.assertIn("properties", op["inputSchema"])

    def test_every_parameter_is_documented(self):
        """An undocumented parameter is invisible to a model. None are allowed."""
        undocumented = []
        for op in self.ops:
            for key, spec in op["inputSchema"]["properties"].items():
                if not spec.get("description"):
                    undocumented.append(f"{op['name']}.{key}")
        self.assertEqual(undocumented, [], "parameters missing descriptions")

    def test_core_namespaces_present(self):
        namespaces = {op["name"].split(".")[0] for op in self.ops}
        for expected in (
            "session",
            "build",
            "prop",
            "kit",
            "env",
            "char",
            "material",
            "uv",
            "gameready",
            "render",
            "check",
            "export",
            "meta",
        ):
            self.assertIn(expected, namespaces)

    def test_names_are_unique(self):
        names = [op["name"] for op in self.ops]
        self.assertEqual(len(names), len(set(names)))

    def test_explicit_camera_position_is_required(self):
        camera = next(op for op in self.ops if op["name"] == "render.camera")
        self.assertIn("position", camera["inputSchema"].get("required", []))

    def test_cinematic_camera_position_and_target_are_optional(self):
        cinematic = next(op for op in self.ops if op["name"] == "render.cinematic")
        required = cinematic["inputSchema"].get("required", [])
        self.assertNotIn("position", required)
        self.assertNotIn("target", required)
        self.assertNotIn("default", cinematic["inputSchema"]["properties"]["position"])
        self.assertNotIn("default", cinematic["inputSchema"]["properties"]["target"])

    def test_sprite_supersampling_is_explicit(self):
        sprite = next(op for op in self.ops if op["name"] == "render.sprite")
        self.assertEqual(sprite["inputSchema"]["properties"]["supersample"]["default"], 2)

    def test_paint_operations_declare_their_real_required_inputs(self):
        expected = {
            "paint.fill": {"name", "color"},
            "paint.height": {"name", "low", "high"},
            "paint.cavity": {"name", "color"},
            "paint.noise": {"name", "color_a", "color_b"},
        }
        for name, required in expected.items():
            operation = next(op for op in self.ops if op["name"] == name)
            self.assertEqual(set(operation["inputSchema"].get("required", [])), required)


class Filters(unittest.TestCase):
    def setUp(self):
        self.ops = schema_mod.load_catalog()

    def test_compact_drops_schemas(self):
        rows = schema_mod.compact(self.ops)
        self.assertEqual(len(rows), len(self.ops))
        self.assertNotIn("inputSchema", rows[0])

    def test_tag_filter(self):
        rows = schema_mod.compact(self.ops, tag="prop")
        self.assertTrue(rows)
        self.assertTrue(all("prop" in r["tags"] for r in rows))

    def test_search_filter_matches_name_or_summary(self):
        rows = schema_mod.compact(self.ops, search="barrel")
        self.assertTrue(any(r["name"] == "prop.barrel" for r in rows))

    def test_filters_that_match_nothing_return_empty(self):
        self.assertEqual(schema_mod.compact(self.ops, tag="nope"), [])


class Dialects(unittest.TestCase):
    def setUp(self):
        self.ops = schema_mod.load_catalog()

    def test_openai_names_are_legal_and_reversible(self):
        tools = schema_mod.to_openai(self.ops)
        self.assertEqual(len(tools), len(self.ops))
        for tool, op in zip(tools, self.ops, strict=True):
            name = tool["function"]["name"]
            self.assertRegex(name, r"^[A-Za-z0-9_-]{1,64}$", "OpenAI forbids dots in names")
            self.assertEqual(schema_mod.from_openai_name(name), op["name"])

    def test_anthropic_shape(self):
        tools = schema_mod.to_anthropic(self.ops)
        self.assertIn("input_schema", tools[0])
        self.assertIn("description", tools[0])

    def test_mcp_shape(self):
        tools = schema_mod.to_mcp_tools(self.ops)
        self.assertIn("inputSchema", tools[0])

    def test_everything_is_json_serialisable(self):
        for payload in (
            schema_mod.to_openai(self.ops),
            schema_mod.to_anthropic(self.ops),
            schema_mod.to_mcp_tools(self.ops),
        ):
            json.dumps(payload)

    def test_markdown_reference_covers_every_op(self):
        text = schema_mod.markdown_reference(self.ops)
        for op in self.ops:
            self.assertIn(f"`{op['name']}`", text)

    def test_committed_ops_reference_matches_the_catalog(self):
        """docs/bforge/OPS.md is generated; fail when it drifts from the catalog."""
        reference = Path(__file__).resolve().parents[3] / "docs" / "bforge" / "OPS.md"
        self.assertTrue(reference.is_file(), f"missing {reference}")
        self.assertEqual(
            reference.read_text(encoding="utf-8"),
            schema_mod.markdown_reference(self.ops),
            "OPS.md is stale — run `just bforge-catalog`",
        )


if __name__ == "__main__":
    unittest.main()
