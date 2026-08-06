"""sim kernel tests — determinism is a checked property, not a slogan."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / "worldc"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / "bforge"))

import kernel  # noqa: E402

import worldc  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
GATE_REPLAY = REPO / "tools" / "sim" / "replays" / "gate_open_destroy.json"
GATE_ENTITY = REPO / "tools" / "worldc" / "examples" / "fortress_gate.json"


def gate_contract() -> dict:
    return worldc.sim_contract(worldc.load_entity(GATE_ENTITY))


def base_replay() -> dict:
    contract = gate_contract()
    import hashlib

    return {
        "sim_replay": "0.1",
        "seed": 0,
        "ticks": 10,
        "entities": {
            "gate": {
                "contract": contract,
                "contract_sha256": hashlib.sha256(kernel.canonical(contract)).hexdigest(),
            }
        },
        "initial": {"gate": {"health": 100}},
        "events": [],
    }


def run_with_doc(replay: dict) -> dict:
    """Run a replay dict against the fortress_gate contract under 'gate'."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.json"
        path.write_text(json.dumps(replay))
        return kernel.run_replay(path, contracts={"gate": gate_contract()})


class Determinism(unittest.TestCase):
    def test_same_replay_same_hash(self):
        replay = base_replay()
        replay["events"] = [[0, "gate", "open", None], [4, "gate", "attack", 10]]
        self.assertEqual(run_with_doc(replay)["state_hash"], run_with_doc(replay)["state_hash"])

    def test_tampered_event_changes_the_hash(self):
        replay = base_replay()
        replay["events"] = [[4, "gate", "attack", 10]]
        tampered = copy.deepcopy(replay)
        tampered["events"][0][3] = 11
        self.assertNotEqual(
            run_with_doc(replay)["state_hash"], run_with_doc(tampered)["state_hash"]
        )

    def test_golden_replay_matches_committed_hash(self):
        result = kernel.run_replay(GATE_REPLAY)
        expected = json.loads(GATE_REPLAY.read_text())["expect_state_hash"]
        self.assertEqual(result["state_hash"], expected)

    def test_same_visible_state_different_drive_hashes_differently(self):
        """Adversarial fixture: identical openness, different intent. The hash
        must differ, because the next tick differs."""
        # A: at 750 milli, driving to open. B: at 750 milli, no drive.
        opening = base_replay()
        opening["ticks"] = 0
        opening["initial"]["gate"]["openness"] = 500
        opening["events"] = [[0, "gate", "open", None]]
        holding = base_replay()
        holding["ticks"] = 0
        holding["initial"]["gate"]["openness"] = 750
        a = run_with_doc(opening)
        b = run_with_doc(holding)
        self.assertEqual(
            a["final_state"]["gate"]["state"]["openness"],
            b["final_state"]["gate"]["state"]["openness"],
            "the visible states must be identical for this fixture to mean anything",
        )
        self.assertNotEqual(
            a["state_hash"], b["state_hash"], "control intent is part of the hashed state"
        )


class ReplayValidation(unittest.TestCase):
    def run_bad(self, mutate) -> None:
        replay = base_replay()
        mutate(replay)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text(json.dumps(replay))
            with self.assertRaises(kernel.SimError):
                kernel.run_replay(path, contracts={"gate": gate_contract()})

    def test_negative_tick_rejected(self):
        self.run_bad(lambda r: r["events"].append([-5, "gate", "attack", 100]))

    def test_out_of_range_tick_rejected(self):
        self.run_bad(lambda r: r["events"].append([999999, "gate", "attack", 100]))

    def test_unknown_top_level_field_rejected(self):
        self.run_bad(lambda r: r.update(vibes="good"))

    def test_unknown_entity_rejected(self):
        self.run_bad(lambda r: r["events"].append([1, "ghost", "open", None]))

    def test_non_identifier_verb_rejected(self):
        self.run_bad(lambda r: r["events"].append([1, "gate", "Open!", None]))

    def test_negative_attack_rejected(self):
        self.run_bad(lambda r: r["events"].append([1, "gate", "attack", -30]))

    def test_negative_repair_rejected(self):
        self.run_bad(lambda r: r["events"].append([1, "gate", "repair", -10]))

    def test_null_arg_verbs_reject_arguments(self):
        self.run_bad(lambda r: r["events"].append([1, "gate", "open", 5]))

    def test_initial_types_are_checked(self):
        self.run_bad(lambda r: r["initial"]["gate"].update(locked="yes"))
        self.run_bad(lambda r: r["initial"]["gate"].update(health="lots"))

    def test_initial_cannot_invent_state_vars(self):
        self.run_bad(lambda r: r["initial"]["gate"].update(mana=5))

    def test_non_finite_initial_rejected(self):
        replay = base_replay()
        text = json.dumps(replay).replace('"health": 100', '"health": NaN')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text(text)
            with self.assertRaises(kernel.SimError):
                kernel.run_replay(path, contracts={"gate": gate_contract()})


class VerbSemantics(unittest.TestCase):
    def state(self, replay: dict) -> dict:
        return run_with_doc(replay)["final_state"]["gate"]["state"]

    def test_locked_gate_absorbs_open(self):
        replay = base_replay()
        replay["initial"]["gate"]["locked"] = True
        replay["events"] = [[0, "gate", "open", None]]
        self.assertEqual(self.state(replay)["openness"], 0)

    def test_open_integrates_at_the_fixed_rate(self):
        replay = base_replay()
        replay["events"] = [[0, "gate", "open", None]]
        # 11 ticks (0..10) at 250 milli/tick clamps at 1000
        self.assertEqual(self.state(replay)["openness"], 1000)

    def test_attack_to_zero_destroys_and_unblocks_navigation(self):
        replay = base_replay()
        replay["events"] = [[0, "gate", "attack", 100]]
        result = run_with_doc(replay)
        self.assertTrue(result["final_state"]["gate"]["state"]["destroyed"])
        self.assertFalse(result["navigation"]["gate"])

    def test_intact_closed_gate_blocks_navigation(self):
        replay = base_replay()
        result = run_with_doc(replay)
        self.assertFalse(result["final_state"]["gate"]["state"]["destroyed"])
        self.assertTrue(result["navigation"]["gate"])

    def test_repair_revives(self):
        replay = base_replay()
        replay["events"] = [[0, "gate", "attack", 100], [2, "gate", "repair", 10]]
        state = self.state(replay)
        self.assertEqual(state["health"], 10)
        self.assertFalse(state["destroyed"])

    def test_undeclared_affordance_is_a_hard_error(self):
        replay = base_replay()
        replay["events"] = [[0, "gate", "explode", None]]
        with self.assertRaises(kernel.SimError):
            run_with_doc(replay)

    def test_snapshots_cover_every_tick_and_chain_to_the_final_hash(self):
        replay = base_replay()
        replay["events"] = [[0, "gate", "open", None], [6, "gate", "attack", 25]]
        result = run_with_doc(replay)
        snaps = result["snapshots"]
        self.assertEqual(len(snaps), replay["ticks"] + 1)
        self.assertEqual(snaps[-1], result["final_state"])
        # every snapshot hashes to its hash_log entry — an adapter observing
        # the stream sees exactly the states the kernel hashed
        for snap, logged in zip(snaps, result["hash_log"], strict=True):
            self.assertEqual(kernel.state_hash(snap), logged)

    def test_fingerprints_cover_kernel_entities_and_replay(self):
        result = run_with_doc(base_replay())
        fp = result["fingerprints"]
        self.assertEqual(len(fp["kernel"]["kernel_sha256"]), 64)
        self.assertEqual(len(fp["entities"]["gate"]), 64)
        self.assertEqual(len(fp["replay_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
