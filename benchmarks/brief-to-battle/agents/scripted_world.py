#!/usr/bin/env python3
"""The scripted reference agent for brief-to-battle (the control group).

Receives a workspace dir containing brief.json and the staged entity docs;
writes world.json + battle.json (contracts compiled from the staged World
IR documents) + metrics.json.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "worldc"))
sys.path.insert(0, str(REPO / "tools" / "bforge"))

import worldc  # noqa: E402
from bforge import recipe as recipe_mod  # noqa: E402

SCENARIOS = {
    "fortress_battle": {
        "world": "fortress",
        "initial": {
            "gate_main": {"health": 100, "locked": True},
            "gate_side": {"health": 100, "locked": True},
        },
        "events": [
            [0, "gate_side", "open", None],
            [1, "gate_main", "unlock", None],
            [2, "gate_main", "open", None],
            [5, "gate_main", "attack", 40],
            [8, "gate_main", "attack", 40],
            [11, "gate_main", "attack", 40],
        ],
    },
    "hold_the_gate": {
        "world": "fortress",
        "initial": {
            "gate_main": {"health": 100, "locked": True},
            "gate_side": {"health": 100, "locked": True},
        },
        "events": [
            [2, "gate_main", "attack", 30],
            [5, "gate_main", "attack", 30],
            [8, "gate_main", "attack", 30],
            [9, "gate_main", "repair", 50],
            [10, "gate_side", "unlock", None],
            [11, "gate_side", "open", None],
        ],
    },
}


def main() -> int:
    workspace = Path(sys.argv[1])
    brief = json.loads((workspace / "brief.json").read_text())
    scenario = SCENARIOS.get(brief["id"])
    if scenario is None:
        print(f"no scripted answer for {brief['id']}", file=sys.stderr)
        return 1

    doc_path = workspace / "fortress_gate.json"
    if not doc_path.is_file():
        print("no staged fortress_gate.json", file=sys.stderr)
        return 1
    contract = worldc.sim_contract(worldc.load_entity(doc_path))
    contract_sha = hashlib.sha256(recipe_mod.canonicalize(contract)).hexdigest()

    names = sorted(brief["scenario"]["entities"])
    world = {
        "world_ir": "0.1",
        "world": scenario["world"],
        "entities": {name: {"doc": "fortress_gate.json"} for name in names},
        "scenario": "battle.json",
        "expect_navigation": brief["scenario"]["expect_navigation"],
    }
    (workspace / "world.json").write_text(json.dumps(world, indent=2) + "\n")

    battle = {
        "sim_replay": "0.1",
        "seed": 0,
        "ticks": 20,
        "entities": {
            name: {"contract": contract, "contract_sha256": contract_sha}
            for name in names
        },
        "initial": scenario["initial"],
        "events": scenario["events"],
    }
    (workspace / "battle.json").write_text(json.dumps(battle, indent=2) + "\n")
    (workspace / "metrics.json").write_text(json.dumps({"attempts": 1}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
