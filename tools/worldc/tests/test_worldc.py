"""worldc tests — World IR validation, artifact verification, entity cache.

Unit tests run anywhere; the live test compiles the fortress_gate example
through a real Blender daemon and verifies the entity proof against the GLB.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bforge"))

import glb as glb_mod  # noqa: E402
from bforge.client import DaemonError, Forge, find_blender  # noqa: E402

import worldc  # noqa: E402
from bforge import recipe as recipe_mod  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = REPO / "tools" / "worldc" / "examples" / "fortress_gate.json"


def base_entity() -> dict:
    return {
        "world_ir": "0.1",
        "entity": "widget_door",
        "parts": {
            "frame": {"role": "static"},
            "leaf": {"parent": "frame"},
        },
        "joints": {
            "hinge": {
                "parent": "frame",
                "child": "leaf",
                "axis": [0, 0, 1],
                "range_degrees": [0, 90],
            }
        },
        "state": {"openness": "float", "locked": "bool"},
        "affordances": ["open", "close", "lock"],
        "navigation": {"blocks_below_openness": 0.5},
        "network": {"authority": "server", "replicated": ["openness", "locked"]},
        "requirements": {"require_collision": "frame"},
        "recipe": {
            "recipe_version": 1,
            "asset_id": "widget_door",
            "steps": [{"op": "build.box", "args": {"name": "frame", "size": [1, 1, 2]}}],
        },
    }


class Validation(unittest.TestCase):
    def test_valid_document_passes(self):
        self.assertEqual(worldc.validate_entity(base_entity())["entity"], "widget_door")

    def test_unknown_top_level_field_rejected(self):
        doc = base_entity()
        doc["vibes"] = {"mood": "good"}
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_extensions_field_is_the_escape_hatch(self):
        doc = base_entity()
        doc["extensions"] = {"vendor": {"anything": "goes"}}
        self.assertEqual(worldc.validate_entity(doc)["entity"], "widget_door")

    def test_part_spec_must_be_an_object(self):
        doc = base_entity()
        doc["parts"]["leaf"] = "frame"  # malformed shorthand
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_unknown_parent_reference_rejected(self):
        doc = base_entity()
        doc["parts"]["leaf"]["parent"] = "ghost"
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_parent_cycle_rejected(self):
        doc = base_entity()
        doc["parts"]["frame"]["parent"] = "leaf"
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_joint_must_link_two_real_parts(self):
        doc = base_entity()
        doc["joints"]["bad"] = {
            "parent": "frame",
            "child": "frame",
            "axis": [0, 0, 1],
            "range_degrees": [0, 90],
        }
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_joint_axis_must_be_three_finite_nonzero_numbers(self):
        for bad in ([0, 0], [0, 0, 0], [0, 0, float("inf")], "z"):
            doc = base_entity()
            doc["joints"]["hinge"]["axis"] = bad
            with self.subTest(axis=bad), self.assertRaises(worldc.WorldIRError):
                worldc.validate_entity(doc)

    def test_joint_range_must_be_ordered_pair(self):
        doc = base_entity()
        doc["joints"]["hinge"]["range_degrees"] = [90, 0]
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_duplicate_affordances_rejected(self):
        doc = base_entity()
        doc["affordances"] = ["open", "open", "close"]
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_state_keys_are_identifiers(self):
        doc = base_entity()
        doc["state"]["Open-ness!"] = "float"
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_replicated_state_must_be_declared_and_unique(self):
        doc = base_entity()
        doc["network"]["replicated"] = ["openness", "openness"]
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)
        doc["network"]["replicated"] = ["mana"]
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_navigation_rule_needs_a_float_state_var(self):
        doc = base_entity()
        doc["state"]["openness"] = "int"
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_collision_owner_must_be_a_part(self):
        doc = base_entity()
        doc["requirements"]["require_collision"] = "ghost"
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_recipe_asset_id_must_match_entity(self):
        doc = base_entity()
        doc["recipe"]["asset_id"] = "something_else"
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)

    def test_version_gate(self):
        doc = base_entity()
        doc["world_ir"] = "9.9"
        with self.assertRaises(worldc.WorldIRError):
            worldc.validate_entity(doc)


def write_glb(path: Path, nodes: list[dict]) -> Path:
    gltf = {"asset": {"version": "2.0"}, "nodes": nodes, "scenes": [{"nodes": [0]}]}
    payload = json.dumps(gltf).encode()
    payload += b" " * (-len(payload) % 4)
    total = 12 + 8 + len(payload)
    blob = (
        b"glTF"
        + (2).to_bytes(4, "little")
        + total.to_bytes(4, "little")
        + len(payload).to_bytes(4, "little")
        + b"JSON"
        + payload
    )
    path.write_bytes(blob)
    return path


class ArtifactVerification(unittest.TestCase):
    def good_nodes(self):
        return [
            {"name": "frame", "children": [1]},
            {"name": "leaf"},
            {"name": "frame-convcol"},
        ]

    def test_parts_hierarchy_collision_and_payload_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_glb(Path(tmp) / "w.glb", self.good_nodes())
            checks = worldc.verify_artifact(base_entity(), path)
            self.assertEqual([c["ok"] for c in checks], [True] * len(checks))

    def test_missing_part_and_missing_collision_owner_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            # leaf missing; only a proxy for the WRONG part exists
            path = write_glb(Path(tmp) / "w.glb", [{"name": "frame"}, {"name": "leaf-convcol"}])
            checks = worldc.verify_artifact(base_entity(), path)
            failed = [c["check"] for c in checks if not c["ok"]]
            self.assertIn("part present: leaf", failed)
            self.assertIn("collision proxy present", failed)

    def test_malformed_node_trees_are_structure_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            dup = write_glb(Path(tmp) / "a.glb", [{"name": "x"}, {"name": "x"}])
            with self.assertRaises(glb_mod.GLBStructureError):  # duplicate names
                glb_mod.node_index(glb_mod.read_glb_json(dup))
            oor = write_glb(Path(tmp) / "b.glb", [{"name": "x", "children": [7]}])
            with self.assertRaises(glb_mod.GLBStructureError):  # child index out of range
                glb_mod.node_index(glb_mod.read_glb_json(oor))
            multi = write_glb(
                Path(tmp) / "c.glb",
                [{"name": "a", "children": [2]}, {"name": "b", "children": [2]}, {"name": "c"}],
            )
            with self.assertRaises(glb_mod.GLBStructureError):  # multiple parents
                glb_mod.node_index(glb_mod.read_glb_json(multi))


class FakeForge:
    """Worker double for entity-cache tests; export fabricates a valid GLB."""

    instances: list[FakeForge] = []
    glb_nodes: list[dict] = []

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        FakeForge.instances.append(self)

    def start(self) -> dict:
        return {
            "blender": recipe_mod.pinned_blender_version() or "unknown",
            "python": "fake",
            "ops": 137,
        }

    def stop(self):
        pass

    def call(self, op, _timeout=None, **args):
        self.calls.append((op, args))
        if op == "check.asset":
            return {"ok": True, "errors": 0}
        if op == "gameready.budget":
            return {"within_budget": True}
        if op == "export.asset":
            out = Path(args["out_dir"]) / f"{args['asset_id']}.glb"
            write_glb(out, FakeForge.glb_nodes)
            return {"ok": True, "glb": str(out)}
        return {"ok": True}


class EntityCache(unittest.TestCase):
    def setUp(self):
        FakeForge.instances = []
        FakeForge.glb_nodes = [
            {"name": "frame", "children": [1]},
            {"name": "leaf"},
            {"name": "frame-convcol"},
        ]

    def compile(self, tmp: str, doc: dict, name: str = "entity.json") -> dict:
        path = Path(tmp) / name
        path.write_text(json.dumps(doc))
        return worldc.compile_entity(path, cache_dir=Path(tmp) / "cache", forge_factory=FakeForge)

    def test_entity_cache_is_separate_from_the_asset_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            proof = self.compile(tmp, base_entity())
            self.assertEqual(proof["status"], "pass")
            entity_dir = Path(proof["cache"]["dir"])
            self.assertIn("entity-cache", str(entity_dir))
            # the proof URI resolves, for real, to the asset proof
            resolved = (entity_dir / proof["asset"]["proof_uri"]).resolve()
            self.assertTrue(resolved.is_file(), f"proof_uri must resolve: {resolved}")
            self.assertIn("asset-cache", resolved.as_posix())
            self.assertEqual(resolved.name, "proof.json")
            # the asset store contains NO entity-level files
            self.assertFalse(list(resolved.parent.glob("entity*")))
            # the proof chain is cryptographic, not a path
            self.assertEqual(len(proof["asset"]["proof_sha256"]), 64)
            self.assertEqual(len(proof["world_ir_sha256"]), 64)

    def test_two_entities_sharing_one_recipe_do_not_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = base_entity()
            b = base_entity()
            b["state"]["health"] = "int"  # different semantics, same geometry recipe
            b["affordances"] = ["open", "close", "lock", "attack"]
            pa = self.compile(tmp, a, "a.json")
            pb = self.compile(tmp, b, "b.json")
            self.assertNotEqual(pa["entity_cache_key"], pb["entity_cache_key"])
            self.assertEqual(
                pa["asset"]["cache_key"], pb["asset"]["cache_key"], "same recipe, same asset"
            )
            self.assertNotEqual(pa["cache"]["dir"], pb["cache"]["dir"])
            self.assertTrue((Path(pa["cache"]["dir"]) / "entity_proof.json").is_file())
            self.assertTrue((Path(pb["cache"]["dir"]) / "entity_proof.json").is_file())

    def test_second_compile_is_a_hit_without_a_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.compile(tmp, base_entity())
            self.assertEqual(len(FakeForge.instances), 1)
            proof = self.compile(tmp, base_entity())
            self.assertTrue(proof["cache"]["hit"])
            self.assertEqual(len(FakeForge.instances), 1)

    def test_tampered_asset_proof_forces_asset_rebuild(self):
        """Editing asset-proof metadata invalidates the asset entry; the entity
        proof must reference the REBUILT proof, never the tampered one."""
        with tempfile.TemporaryDirectory() as tmp:
            first = self.compile(tmp, base_entity())
            entity_dir = Path(first["cache"]["dir"])
            asset_proof = (entity_dir / first["asset"]["proof_uri"]).resolve()
            doc = json.loads(asset_proof.read_text())
            doc["toolchain"]["blender"] = "tampered-9.9.9"
            asset_proof.write_text(json.dumps(doc, indent=2) + "\n")
            second = self.compile(tmp, base_entity())
            self.assertEqual(
                len(FakeForge.instances), 2, "the asset layer must rebuild after tampering"
            )
            current = json.loads(asset_proof.read_text())
            pinned = recipe_mod.pinned_blender_version() or "unknown"
            self.assertEqual(current["toolchain"]["blender"], pinned)
            self.assertEqual(
                second["asset"]["proof_sha256"],
                hashlib.sha256(asset_proof.read_bytes()).hexdigest(),
            )
            self.assertNotEqual(second["asset"]["proof_sha256"], first["asset"]["proof_sha256"])

    def test_world_requirements_override_the_embedded_recipe(self):
        """World IR requirements are authoritative — a recipe that undercuts
        the entity contract must not stand."""
        with tempfile.TemporaryDirectory() as tmp:
            doc = base_entity()
            doc["requirements"]["max_triangles"] = 4000
            doc["recipe"]["requirements"] = {"max_triangles": 100000}
            self.compile(tmp, doc)
            check_calls = [args for op, args in FakeForge.instances[0].calls if op == "check.asset"]
            self.assertTrue(check_calls, "check.asset must run")
            self.assertEqual(check_calls[0]["triangle_budget"], 4000)

    def test_tampered_entity_proof_check_detail_invalidates_the_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.compile(tmp, base_entity())
            self.assertEqual(len(FakeForge.instances), 1)
            entity_proof_path = Path(first["cache"]["dir"]) / "entity_proof.json"
            tampered = json.loads(entity_proof_path.read_text())
            tampered["checks"][0]["ok"] = False  # edit a verdict
            entity_proof_path.write_text(json.dumps(tampered, indent=2) + "\n")
            second = self.compile(tmp, base_entity())
            self.assertFalse(second["cache"]["hit"], "a tampered check must not be served")
            self.assertEqual([c["ok"] for c in second["checks"]], [True] * len(second["checks"]))


BLENDER = None
try:
    if not os.environ.get("BFORGE_SKIP_LIVE"):
        BLENDER = find_blender()
except DaemonError:
    BLENDER = None


@unittest.skipIf(BLENDER is None, "Blender not available")
class CompileLive(unittest.TestCase):
    def test_fortress_gate_compiles_to_a_passing_entity_proof(self):
        tmp = Path(tempfile.mkdtemp(prefix="worldc_test_"))
        self.addCleanup(shutil.rmtree, tmp, True)

        def factory() -> Forge:
            return Forge(workdir=str(tmp), out_dir=str(tmp / "out"))

        proof = worldc.compile_entity(EXAMPLE, cache_dir=tmp / "cache", forge_factory=factory)
        self.assertEqual(proof["status"], "pass")
        check_names = [c["check"] for c in proof["checks"]]
        self.assertIn("part present: frame", check_names)
        self.assertIn("hierarchy: leaf_l under frame", check_names)
        self.assertIn("collision proxy present", check_names)
        self.assertEqual(len(proof["asset"]["proof_sha256"]), 64)
        self.assertTrue(proof["world_ir_sha256"])
        entity_proof = Path(proof["cache"]["dir"]) / "entity_proof.json"
        self.assertTrue(entity_proof.is_file())


if __name__ == "__main__":
    unittest.main()
