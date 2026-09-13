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


class Properties(unittest.TestCase):
    """Design properties are checked without geometry (`worldc prove`), and a
    violated one is a failed check like any other (ADR 0022)."""

    def test_the_example_worlds_prove_their_properties(self):
        for world in ("fortress_world.json", "depot_world.json"):
            report = worldc.prove_world(EXAMPLES / world)
            statuses = {r["name"]: r["status"] for r in report["results"]}
            self.assertTrue(all(s == "holds" for s in statuses.values()), (world, statuses))
            self.assertGreater(report["explored"]["states"], 10)

    def test_every_witness_is_a_replay_the_kernel_reproduced(self):
        tmp = Path(tempfile.mkdtemp(prefix="worldc_prove_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        report = worldc.prove_world(EXAMPLES / "depot_world.json", out_dir=tmp)
        witnessed = [r for r in report["results"] if r["witness"] and r["witness"]["replay"]]
        self.assertTrue(witnessed)
        for verdict in witnessed:
            path = tmp / verdict["witness"]["replay"]
            self.assertTrue(path.is_file())
            self.assertTrue(verdict["witness"]["verified"])
            self.assertEqual(
                verdict["witness"]["replay_sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
            )

    def test_a_violated_property_is_reported_with_its_counterexample(self):
        """The prover's first real find: a destroyed gate repaired by one point
        stands ajar while still locked. Nobody had written that down."""
        tmp = Path(tempfile.mkdtemp(prefix="worldc_prove_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in ("fortress_gate.json", "fortress_battle.json"):
            shutil.copy(EXAMPLES / name, tmp / name)
        doc = json.loads((WORLD).read_text())
        doc["properties"] = {
            "horizon": 8,
            "assert": [
                {
                    "name": "a locked intact gate is never ajar",
                    "kind": "never",
                    "when": [
                        {"entity": "gate_side", "var": "locked", "equals": True},
                        {"entity": "gate_side", "var": "destroyed", "equals": False},
                        {"entity": "gate_side", "var": "openness", "gt": 0},
                    ],
                }
            ],
        }
        (tmp / "world.json").write_text(json.dumps(doc))
        verdict = worldc.prove_world(tmp / "world.json")["results"][0]
        self.assertEqual(verdict["status"], "violated")
        self.assertEqual([e[2] for e in verdict["witness"]["events"]], ["attack", "repair"])
        self.assertTrue(verdict["witness"]["verified"])

    def test_malformed_properties_are_a_world_error(self):
        tmp = Path(tempfile.mkdtemp(prefix="worldc_prove_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in ("fortress_gate.json", "fortress_battle.json"):
            shutil.copy(EXAMPLES / name, tmp / name)
        doc = json.loads((WORLD).read_text())
        for bad in (
            [],  # not an object
            {"assert": []},  # nothing to prove
            {
                "assert": [
                    {
                        "name": "x",
                        "kind": "never",
                        "when": [{"entity": "ghost", "var": "openness", "gt": 0}],
                    }
                ]
            },
            {
                "assert": [
                    {
                        "name": "x",
                        "kind": "never",
                        "when": [{"entity": "gate_main", "var": "locked", "gt": 0}],
                    }
                ]
            },
        ):
            doc["properties"] = bad
            (tmp / "world.json").write_text(json.dumps(doc))
            with self.assertRaises(worldc.WorldIRError):
                worldc.prove_world(tmp / "world.json")

    def test_a_world_without_properties_has_nothing_to_prove(self):
        tmp = Path(tempfile.mkdtemp(prefix="worldc_prove_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in ("fortress_gate.json", "fortress_battle.json"):
            shutil.copy(EXAMPLES / name, tmp / name)
        doc = json.loads((WORLD).read_text())
        doc.pop("properties", None)
        (tmp / "world.json").write_text(json.dumps(doc))
        with self.assertRaises(worldc.WorldIRError):
            worldc.prove_world(tmp / "world.json")


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

        # the design properties were proven and their witnesses sit beside the
        # proof, each re-run through the kernel (ADR 0022)
        results = proof["properties"]["results"]
        self.assertEqual({r["status"] for r in results}, {"holds"})
        self.assertTrue(any(c["check"].startswith("property (") for c in proof["checks"]))
        world_dir = Path(proof["cache"]["dir"])
        for verdict in results:
            if verdict["witness"] and verdict["witness"]["replay"]:
                self.assertTrue((world_dir / verdict["witness"]["replay"]).is_file())
                self.assertTrue(verdict["witness"]["verified"])

        # every reference in the proof resolves from its own directory
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
