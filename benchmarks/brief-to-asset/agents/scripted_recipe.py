#!/usr/bin/env python3
"""The scripted reference agent for brief-to-asset.

Not a benchmark contestant — the control group. It maps each frozen brief to
a known-good recipe, proving the harness itself is green end to end before
any model is invited. A model's score means something only because this one
is already 6/6.

Receives a workspace dir containing brief.json; writes recipe.json and
metrics.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RECIPES = {
    "crate": {
        "steps": [
            {
                "op": "prop.crate",
                "args": {"name": "crate", "size": [1, 1, 1], "seed": 7},
            },
            {"op": "gameready.collision", "args": {"name": "crate", "mode": "convex"}},
        ],
    },
    "barrel": {
        "steps": [
            {"op": "prop.barrel", "args": {"name": "barrel", "seed": 11}},
        ],
    },
    "gladius": {
        "steps": [
            {
                "op": "prop.weapon",
                "args": {"name": "gladius", "kind": "sword", "seed": 3},
            },
        ],
    },
    "wolf": {
        "steps": [
            {
                "op": "char.creature",
                "args": {
                    "name": "wolf",
                    "plan": "canine",
                    "length": 1.3,
                    "shoulder": 0.85,
                    "bulk": 1.15,
                    "skin": "#4a3c30",
                    "seed": 13,
                },
            },
            {
                "op": "char.creature_rig",
                "args": {
                    "name": "wolf",
                    "plan": "canine",
                    "length": 1.3,
                    "shoulder": 0.85,
                },
            },
            {"op": "char.gait", "args": {"rig": "wolf_rig", "speed": 2.0}},
            {
                "op": "char.gait",
                "args": {
                    "rig": "wolf_rig",
                    "style": "trot",
                    "speed": 4.0,
                    "action_name": "trot",
                },
            },
        ],
    },
    "warden": {
        "steps": [
            {
                "op": "char.humanoid",
                "args": {
                    "name": "warden",
                    "height": 1.82,
                    "build": "heroic",
                    "skin": "#b08a68",
                    "seed": 3,
                },
            },
            {"op": "char.face", "args": {"name": "warden", "height": 1.82}},
            {"op": "char.hands", "args": {"name": "warden", "height": 1.82}},
            {
                "op": "char.outfit",
                "args": {
                    "name": "warden",
                    "piece": "cuirass",
                    "height": 1.82,
                    "material": "bronze",
                },
            },
            {
                "op": "char.outfit",
                "args": {
                    "name": "warden",
                    "piece": "pteruges",
                    "height": 1.82,
                    "material": "leather",
                },
            },
            {
                "op": "char.outfit",
                "args": {
                    "name": "warden",
                    "piece": "greaves",
                    "height": 1.82,
                    "material": "bronze",
                },
            },
            {
                "op": "char.outfit",
                "args": {
                    "name": "warden",
                    "piece": "helmet",
                    "height": 1.82,
                    "material": "bronze",
                },
            },
            {
                "op": "char.rig",
                "args": {"name": "warden", "height": 1.82, "build": "heroic"},
            },
            {"op": "char.gait", "args": {"rig": "warden_rig", "speed": 1.4}},
        ],
    },
    "camp": {
        "steps": [
            {
                "op": "env.camp",
                "args": {"name": "camp", "radius": 8.0, "shelters": 3, "seed": 42},
            },
        ],
    },
}


def main() -> int:
    workspace = Path(sys.argv[1])
    brief = json.loads((workspace / "brief.json").read_text())
    if brief["id"] not in RECIPES:
        print(f"no scripted answer for {brief['id']}", file=sys.stderr)
        return 1

    req = brief.get("requirements", {})
    recipe = {
        "recipe_version": 1,
        "asset_id": brief["id"],
        "brief": brief["text"],
        "steps": RECIPES[brief["id"]]["steps"],
        "requirements": {
            k: v
            for k, v in req.items()
            if k
            in ("max_triangles", "max_materials", "require_collision", "require_lods")
        },
        "export": {
            "engine": "godot",
            "category": {
                "weapon": "prop",
                "environment": "environment",
                "character": "character",
                "creature": "character",
            }.get(brief["category"], "prop"),
        },
    }
    (workspace / "recipe.json").write_text(json.dumps(recipe, indent=2) + "\n")
    (workspace / "metrics.json").write_text(json.dumps({"attempts": 1}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
