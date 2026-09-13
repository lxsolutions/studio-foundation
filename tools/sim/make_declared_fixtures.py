#!/usr/bin/env python3
"""Regenerate the declared-semantics conformance fixtures from World IR.

    uv run --project tools python tools/sim/make_declared_fixtures.py

Nothing in the declared-semantics corpus is hand-written. Non-door entities
are authored as World IR here, compiled by worldc into sim contracts, replayed
by the canonical Python kernel, and the resulting golden hashes are written
back into the fixtures. So the committed artifacts are reproducible, and the
entities they prove are the ones the compiler actually produces rather than
contracts typed by hand. The invalid fixtures are the same contracts with one
deliberate defect each; their expected code is whatever the Python kernel says,
and this script fails if that is not the code the defect was meant to trigger.

The entities are chosen to exercise what the door never could (ADR 0021): a
`toggle`, a guard that makes an event a no-op instead of an error, an `add`
clamped by a parameter, a `requires` check, an integrator moving a variable
that is not `openness` toward a control that is not `openness_target` at a
rate that is not `open_rate_milli` — and arithmetic at the edge of i64, where
the Python kernel must saturate exactly as the Rust kernel does.
"""

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "worldc"))
sys.path.insert(0, str(REPO / "tools" / "sim"))

import kernel  # noqa: E402

import worldc  # noqa: E402

EXAMPLES = REPO / "tools" / "worldc" / "examples"
CORPUS = REPO / "tools" / "sim" / "conformance" / "v0.1"

LIFT = {
    "world_ir": "0.1",
    "entity": "cargo_lift",
    "brief": "a powered cargo lift: charges, then travels between two decks",
    "parts": {"shaft": {"role": "static"}, "platform": {"parent": "shaft"}},
    "joints": {
        "rail": {"parent": "shaft", "child": "platform", "axis": [0, 1, 0], "range_degrees": [0, 0]}
    },
    "state": {"height": "float", "power": "int"},
    "affordances": ["call_top", "call_bottom", "charge"],
    "sim": {"lift_rate_milli": 200, "max_power": 60},
    "semantics": {
        "affordances": {
            # A lift with no power ignores a call: a guard that does not hold is
            # a no-op, exactly as a locked gate absorbs `open`.
            "call_top": {
                "arg": "none",
                "guards": [{"var": "power", "gt": 0}],
                "effects": [
                    {"op": "set_control", "control": "height_target", "value": {"const": 1000}}
                ],
            },
            "call_bottom": {
                "arg": "none",
                "guards": [{"var": "power", "gt": 0}],
                "effects": [
                    {"op": "set_control", "control": "height_target", "value": {"const": 0}}
                ],
            },
            "charge": {
                "arg": "count",
                "requires": ["power"],
                "effects": [
                    {
                        "op": "add",
                        "var": "power",
                        "value": {"arg": True},
                        "sign": 1,
                        "clamp": {"max": {"param": "max_power", "default": 60}},
                    }
                ],
            },
        },
        # The integrator moves a variable that is not `openness`, toward a control
        # that is not `openness_target`, at a rate that is not `open_rate_milli`.
        "integrators": [
            {
                "var": "height",
                "toward": "height_target",
                "rate": {"param": "lift_rate_milli", "default": 200},
            }
        ],
    },
    "navigation": {"never_blocks_when_destroyed": False},
    "network": {"authority": "server", "replicated": ["height", "power"]},
    "requirements": {
        "max_triangles": 4000,
        "require_collision": "shaft",
        "payload_kb_max": 900,
        "platform": "browser_webgpu",
        "asset_class": "prop",
    },
    "recipe": {
        "recipe_version": 1,
        "asset_id": "cargo_lift",
        "brief": "a cargo lift: a shaft with a travelling platform and collision",
        "steps": [
            {"op": "build.box", "args": {"name": "shaft", "size": [2.4, 2.4, 4.0]}},
            {
                "op": "build.box",
                "args": {"name": "platform", "size": [2.0, 0.2, 2.0], "location": [0, 0, -1.8]},
            },
            {"op": "object.parent", "args": {"name": "platform", "parent": "shaft"}},
            {"op": "gameready.collision", "args": {"name": "shaft", "mode": "convex"}},
        ],
        "requirements": {
            "max_triangles": 4000,
            "require_collision": True,
            "platform": "browser_webgpu",
            "asset_class": "prop",
        },
        "export": {"engine": "playcanvas", "category": "architecture"},
    },
}

LEVER = {
    "world_ir": "0.1",
    "entity": "signal_lever",
    "brief": "a signal lever that can jam: pulling flips it and counts the pull",
    "parts": {"post": {"role": "static"}, "handle": {"parent": "post"}},
    "joints": {
        "pivot": {
            "parent": "post",
            "child": "handle",
            "axis": [1, 0, 0],
            "range_degrees": [-40, 40],
        }
    },
    "state": {"on": "bool", "pulls": "int", "jammed": "bool"},
    "affordances": ["pull", "jam", "free"],
    "sim": {},
    "semantics": {
        "affordances": {
            "pull": {
                "arg": "none",
                "guards": [{"var": "jammed", "equals": False}],
                "effects": [
                    {"op": "toggle", "var": "on"},
                    {"op": "add", "var": "pulls", "value": 1, "sign": 1},
                ],
            },
            "jam": {"arg": "none", "effects": [{"op": "set", "var": "jammed", "value": True}]},
            "free": {"arg": "none", "effects": [{"op": "set", "var": "jammed", "value": False}]},
        },
        "integrators": [],
    },
    "navigation": {},
    "network": {"authority": "server", "replicated": ["on", "pulls", "jammed"]},
    "requirements": {
        "max_triangles": 2000,
        "require_collision": "post",
        "payload_kb_max": 400,
        "platform": "browser_webgpu",
        "asset_class": "prop",
    },
    "recipe": {
        "recipe_version": 1,
        "asset_id": "signal_lever",
        "brief": "a signal lever: a post with a pivoting handle and collision",
        "steps": [
            {"op": "build.box", "args": {"name": "post", "size": [0.3, 0.3, 1.2]}},
            {
                "op": "build.box",
                "args": {"name": "handle", "size": [0.12, 0.12, 0.8], "location": [0, 0, 0.6]},
            },
            {"op": "object.parent", "args": {"name": "handle", "parent": "post"}},
            {"op": "gameready.collision", "args": {"name": "post", "mode": "convex"}},
        ],
        "requirements": {
            "max_triangles": 2000,
            "require_collision": True,
            "platform": "browser_webgpu",
            "asset_class": "prop",
        },
        "export": {"engine": "babylon", "category": "prop"},
    },
}

# A tally counter whose single verb adds 2^62. Two bumps from 2^62 would carry a
# Python integer past i64; the kernel must saturate instead, because that is
# what the Rust kernel does and the two must never disagree.
COUNTER = {
    "world_ir": "0.1",
    "entity": "tally_counter",
    "brief": "a tally counter that only ever counts up, by a very large step",
    "parts": {"housing": {"role": "static"}},
    "joints": {},
    "state": {"count": "int"},
    "affordances": ["bump"],
    "sim": {},
    "semantics": {
        "affordances": {
            "bump": {"arg": "none", "effects": [{"op": "add", "var": "count", "value": 2**62}]}
        },
        "integrators": [],
    },
    "navigation": {},
    "network": {"authority": "server", "replicated": ["count"]},
    "requirements": {"max_triangles": 500, "require_collision": True, "payload_kb_max": 200},
    "recipe": {
        "recipe_version": 1,
        "asset_id": "tally_counter",
        "brief": "a tally counter housing",
        "steps": [
            {"op": "build.box", "args": {"name": "housing", "size": [0.4, 0.2, 0.3]}},
            {"op": "gameready.collision", "args": {"name": "housing", "mode": "convex"}},
        ],
        "requirements": {"max_triangles": 500, "require_collision": True},
    },
}


def pinned(contract: dict) -> dict:
    return {
        "contract": contract,
        "contract_sha256": hashlib.sha256(kernel.canonical(contract)).hexdigest(),
    }


def write_valid(name: str, replay: dict) -> None:
    """Run the replay through the canonical kernel and freeze its results."""
    path = CORPUS / "valid" / f"{name}.json"
    replay.pop("expect", None)
    path.write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    result = kernel.run_replay(path)
    replay["expect"] = {
        k: result[k] for k in ("final_state", "state_hash", "hash_log", "navigation")
    }
    path.write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(REPO)}\n  state_hash {result['state_hash']}")


def write_invalid(name: str, replay: dict, expected: str) -> None:
    """Freeze a deliberately defective replay with the code the kernel gives it."""
    path = CORPUS / "invalid" / f"{name}.json"
    replay.pop("expect_error", None)
    path.write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    try:
        kernel.run_replay(path)
    except kernel.SimError as exc:
        code = exc.code
    else:
        raise SystemExit(f"{name}: the kernel accepted a fixture meant to be invalid")
    if code != expected:
        raise SystemExit(f"{name}: expected {expected}, the kernel said {code}")
    replay["expect_error"] = code
    path.write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(REPO)}\n  expect_error {code}")


def main() -> None:
    for doc, name in ((LIFT, "cargo_lift"), (LEVER, "signal_lever")):
        (EXAMPLES / f"{name}.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    lift = worldc.sim_contract(LIFT, source="cargo_lift.json")
    lever = worldc.sim_contract(LEVER, source="signal_lever.json")
    counter = worldc.sim_contract(COUNTER, source="tally_counter.json")
    gate = worldc.sim_contract(worldc.load_entity(EXAMPLES / "fortress_gate.json"))

    write_valid(
        "declared_semantics_lift_and_lever",
        {
            "sim_replay": "0.1",
            "seed": 0,
            "ticks": 14,
            "entities": {"cargo_lift": pinned(lift), "signal_lever": pinned(lever)},
            "initial": {"cargo_lift": {"power": 0}, "signal_lever": {"on": False}},
            "events": [
                [0, "cargo_lift", "call_top", None],  # no power: absorbed, lift stays down
                [1, "cargo_lift", "charge", 25],
                [2, "cargo_lift", "call_top", None],  # now it travels, arriving at tick 7
                [3, "signal_lever", "pull", None],  # toggles on, pulls -> 1
                [4, "signal_lever", "pull", None],  # toggles off, pulls -> 2
                [5, "signal_lever", "jam", None],
                [6, "signal_lever", "pull", None],  # jammed: no-op, pulls stays 2
                [7, "signal_lever", "free", None],
                [8, "signal_lever", "pull", None],  # pulls -> 3
                [9, "cargo_lift", "charge", 999],  # clamped at max_power 60
                [12, "cargo_lift", "call_bottom", None],  # three steps down: ends mid-travel at 400
            ],
        },
    )
    write_valid(
        "declared_semantics_saturates_at_i64",
        {
            "sim_replay": "0.1",
            "seed": 0,
            "ticks": 3,
            "entities": {"tally_counter": pinned(counter)},
            "initial": {"tally_counter": {"count": 2**62}},
            "events": [[tick, "tally_counter", "bump", None] for tick in range(3)],
        },
    )

    def lever_replay(mutate) -> dict:
        contract = json.loads(json.dumps(lever))
        mutate(contract)
        return {
            "sim_replay": "0.1",
            "seed": 0,
            "ticks": 3,
            "entities": {"signal_lever": pinned(contract)},
            "initial": {},
            "events": [[0, "signal_lever", "pull", None]],
        }

    def gate_replay(mutate=None, initial=None) -> dict:
        contract = json.loads(json.dumps(gate))
        if mutate:
            mutate(contract)
        return {
            "sim_replay": "0.1",
            "seed": 0,
            "ticks": 3,
            "entities": {"fortress_gate": pinned(contract)},
            "initial": {"fortress_gate": initial or {}},
            "events": [],
        }

    def writes_undeclared(c):
        del c["state"]["pulls"]  # `pull` still adds to it

    def type_mismatch(c):
        c["semantics"]["affordances"]["jam"]["effects"][0]["value"] = 1  # int into a bool

    def unknown_key(c):
        spec = c["semantics"]["affordances"]["pull"]
        spec["guard"] = spec.pop("guards")  # the typo that would silently drop a guard

    def uncovered(c):
        del c["semantics"]["affordances"]["free"]  # still listed, no longer defined

    def exists_not_bool(c):
        c["semantics"]["affordances"]["pull"]["guards"] = [{"var": "jammed", "exists": 1}]

    def no_semantics(c):
        del c["semantics"]  # while still claiming sim_contract 0.2

    def float_parameter(c):
        c["parameters"]["open_rate_milli"] = 300.0  # Python would truncate, Rust would ignore

    write_invalid(
        "semantics_writes_undeclared_var", lever_replay(writes_undeclared), "E_SEMANTICS_SHAPE"
    )
    write_invalid("semantics_type_mismatch", lever_replay(type_mismatch), "E_SEMANTICS_SHAPE")
    write_invalid("semantics_unknown_key", lever_replay(unknown_key), "E_SEMANTICS_SHAPE")
    write_invalid("semantics_uncovered_affordance", lever_replay(uncovered), "E_SEMANTICS_SHAPE")
    write_invalid("semantics_exists_not_bool", lever_replay(exists_not_bool), "E_SEMANTICS_SHAPE")
    write_invalid("contract_v02_without_semantics", lever_replay(no_semantics), "E_CONTRACT_SHAPE")
    write_invalid("parameter_not_integer", gate_replay(float_parameter), "E_CONTRACT_SHAPE")
    write_invalid("initial_outside_i64", gate_replay(initial={"health": 2**70}), "E_INITIAL_TYPE")


if __name__ == "__main__":
    main()
