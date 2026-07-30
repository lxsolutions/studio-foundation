"""Selector-parameter normalisation. No Blender required — these run in CI.

Across the catalog, "which object do I act on" is spelled five different ways:
``name``, ``object``, ``objects``, ``target``, ``mesh``. An agent composing a
recipe has to remember which spelling each op wants, and a wrong guess costs a
round-trip. This was measured, not assumed: writing one real eight-step recipe
cost four separate failed runs, one per spelling mismatch.

These tests are built from the COMMITTED CATALOG rather than from hand-copied
declarations, so they keep tracking the real ops as those change.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import schema as schema_mod  # noqa: E402
from runtime.registry import Op, OpError  # noqa: E402

SELECTORS = ("object", "objects", "name", "target", "mesh")


def op_from_catalog(entry: dict) -> Op:
    """Rebuild a runtime Op from its catalog schema, without importing bpy."""
    params = {}
    for key, prop in (entry.get("inputSchema") or {}).get("properties", {}).items():
        kind = "str[]" if prop.get("type") == "array" else "str"
        params[key] = (kind, prop.get("default"), prop.get("description", ""))
    return Op(entry["name"], lambda **k: None, entry.get("summary", ""), params, "object", (), True)


class SelectorNormalisation(unittest.TestCase):
    def setUp(self):
        self.ops = {e["name"]: op_from_catalog(e) for e in schema_mod.load_catalog()}

    def op(self, name) -> Op:
        if name not in self.ops:
            self.skipTest(f"{name} not in catalog")
        return self.ops[name]

    # -- the four spellings that actually cost a round-trip each -------------

    def test_name_maps_onto_objects_list(self):
        got = self.op("gameready.optimize").coerce({"name": "hold"})
        self.assertEqual(got["objects"], ["hold"])

    def test_name_maps_onto_object_scalar(self):
        got = self.op("uv.unwrap").coerce({"object": None, "name": "hold", "style": "box"})
        self.assertEqual(got["object"], "hold")

    def test_object_maps_onto_objects_list(self):
        got = self.op("check.critique").coerce({"object": "hold"})
        self.assertEqual(got["objects"], ["hold"])

    def test_single_item_list_unwraps_to_scalar(self):
        got = self.op("uv.unwrap").coerce({"objects": ["hold"], "style": "box"})
        self.assertEqual(got["object"], "hold")

    # -- the case aliasing must NOT paper over ------------------------------

    def test_material_set_name_is_the_material_not_the_object(self):
        """`material.set` declares both `object` and `name`, and `name` is the
        MATERIAL's name. Passing name='hold' used to be silently accepted and
        then fail deeper with "object name must be a non-empty string, got
        None". It must fail here, naming the real fix."""
        with self.assertRaises(OpError) as ctx:
            self.op("material.set").coerce({"name": "hold", "preset": "iron"})
        msg = str(ctx.exception)
        self.assertIn("object", msg)
        self.assertIn("hold", msg)

    def test_correct_call_is_untouched(self):
        got = self.op("material.set").coerce({"object": "hold", "name": "m_custom", "preset": "iron"})
        self.assertEqual(got["object"], "hold")
        self.assertEqual(got["name"], "m_custom")

    def test_genuinely_unknown_parameter_still_errors(self):
        with self.assertRaises(OpError) as ctx:
            self.op("uv.unwrap").coerce({"object": "hold", "nonsense": 1})
        self.assertIn("nonsense", str(ctx.exception))

    # -- output-path spellings: same defect, second group -------------------

    def test_path_maps_onto_out(self):
        """`export.gltf` wants `objects` + `out`; `export.blend` wants `path`.
        Writing one recipe against both cost a failed run."""
        got = self.op("export.gltf").coerce({"object": "hold", "path": "x.glb"})
        self.assertEqual(got["objects"], ["hold"])
        self.assertEqual(got["out"], "x.glb")

    def test_no_op_declares_two_output_spellings(self):
        """Aliasing outputs is only safe while no op means two different things
        by two members of the group. If this ever fails, that op needs the
        material.set treatment instead."""
        OUTPUTS = ("out", "path", "file", "filepath", "dest", "output")
        for name, op in self.ops.items():
            with self.subTest(op=name):
                self.assertLessEqual(len([k for k in OUTPUTS if k in op.params]), 1)

    # -- coverage over the whole catalog ------------------------------------

    def test_every_selector_op_accepts_the_common_spelling(self):
        """For each op with exactly one selector parameter, the four other
        spellings must all resolve to it. This is the property that lets an
        agent write a recipe without consulting the schema per op."""
        checked = 0
        for name, op in self.ops.items():
            declared = [s for s in SELECTORS if s in op.params]
            if len(declared) != 1:
                continue  # multi-selector ops are the ambiguous case, tested above
            canonical = declared[0]
            for spelling in SELECTORS:
                if spelling == canonical:
                    continue
                with self.subTest(op=name, spelling=spelling):
                    try:
                        got = op.coerce({spelling: "thing"})
                    except OpError as e:
                        if "missing required parameter" in str(e):
                            continue  # some other required arg; not a selector failure
                        raise
                    self.assertIn(got[canonical], ("thing", ["thing"]))
            checked += 1
        self.assertGreater(checked, 40, "expected many single-selector ops in the catalog")


if __name__ == "__main__":
    unittest.main()
