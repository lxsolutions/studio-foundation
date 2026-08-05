"""worldc world-compilation tests — validation, scenario binding, world proof.

The live test compiles the fortress_world example end to end: two gate
entities through bforge (entity proofs), the battle scenario through the
deterministic kernel, and one world proof capsule binding both by hash.
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

from bforge.client import DaemonError, Forge, find_blender  # noqa: E402

import worldc  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "tools" / "worldc" / "examples"
WORLD = EXAMPLES / "fortress_world.json"


def base_world() -> dict:
    return {
        "world_ir": "0.1",
        "world": "arena_test",
        "entities": {
            "gate_a": {"doc": "fortress_gate.json"},
            "gate_b": {"doc": "fortress_gate.json"},
        },
        "scenario": "fortress_battle.json",
    }


class WorldValidation(unittest.TestCase):
    def _load(self, doc: dict):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(doc, fh)
            return fh.name

    def check_error(self, doc: dict):
        with self.assertRaises(worldc.WorldIRError):
            worldc.load_world(self._load(doc))

    def test_valid_document_passes(self):
        doc = worldc.load_world(self._load(base_world()))
        self.assertEqual(doc["world"], "arena_test")

    def test_unknown_top_level_field(self):
        doc = base_world()
        doc["mood"] = "grim"
        self.check_error(doc)

    def test_entities_must_be_nonempty(self):
        doc = base_world()
        doc["entities"] = {}
        self.check_error(doc)

    def test_entity_entry_needs_a_doc_path(self):
        doc = base_world()
        doc["entities"]["gate_a"] = "fortress_gate.json"
        self.check_error(doc)

    def test_scenario_required(self):
        doc = base_world()
        del doc["scenario"]
        self.check_error(doc)

    def test_expect_navigation_must_reference_known_entities(self):
        doc = base_world()
        doc["expect_navigation"] = {"gate_ghost": False}
        self.check_error(doc)

    def test_version_gate(self):
        doc = base_world()
        doc["world_ir"] = "9.9"
        self.check_error(doc)


BLENDER = None
try:
    if not os.environ.get("BFORGE_SKIP_LIVE"):
        BLENDER = find_blender()
except DaemonError:
    BLENDER = None


@unittest.skipIf(BLENDER is None, "Blender not available")
class WorldLive(unittest.TestCase):
    def test_fortress_world_compiles_to_a_passing_world_proof(self):
        tmp = Path(tempfile.mkdtemp(prefix="worldc_world_"))
        self.addCleanup(shutil.rmtree, tmp, True)

        def factory() -> Forge:
            return Forge(workdir=str(tmp), out_dir=str(tmp / "out"))

        proof = worldc.compile_world(WORLD, cache_dir=tmp / "cache", forge_factory=factory)
        self.assertEqual(proof["status"], "pass")

        # both gate instances compiled (same doc -> one shared entity proof)
        self.assertEqual(
            proof["entities"]["gate_main"]["entity_cache_key"],
            proof["entities"]["gate_side"]["entity_cache_key"],
        )
        # the scenario ran and the battle came out as ordered
        self.assertFalse(proof["scenario"]["navigation"]["gate_main"])
        self.assertTrue(proof["scenario"]["navigation"]["gate_side"])
        self.assertEqual(len(proof["scenario"]["state_hash"]), 64)

        # every reference in the proof resolves from its own directory
        world_dir = Path(proof["cache"]["dir"])
        self.assertTrue((world_dir / "world_proof.json").is_file())
        for ref in proof["entities"].values():
            resolved = (world_dir / ref["entity_proof_uri"]).resolve()
            self.assertTrue(resolved.is_file(), f"entity proof URI resolves: {resolved}")
            self.assertEqual(
                ref["entity_proof_sha256"],
                hashlib.sha256(resolved.read_bytes()).hexdigest(),
            )

        # a second compile reuses everything (still pass, same key)
        again = worldc.compile_world(WORLD, cache_dir=tmp / "cache", forge_factory=factory)
        self.assertEqual(again["world_cache_key"], proof["world_cache_key"])


if __name__ == "__main__":
    unittest.main()
