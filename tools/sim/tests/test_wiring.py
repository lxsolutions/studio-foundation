"""Wires (ADR 0024): the world's couplings between entities.

A wire is `when` (clauses over the world) and `then` (verbs delivered to
entities). It HOLDS: every tick its condition is true, its verbs are applied
after the tick's events and before integration, in declared order. It carries
no hidden state, and it may only target affordances that merely set."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kernel  # noqa: E402


def contract(entity: str, state: dict, affordances: list, semantics: dict) -> dict:
    return {
        "sim_contract": "0.2",
        "source_world_ir_sha256": "0" * 64,
        "entity": entity,
        "state": {var: {"storage": storage} for var, storage in state.items()},
        "affordances": affordances,
        "parameters": {"navigation": {"blocks_below": [], "never_blocks_when_destroyed": False}},
        "semantics": semantics,
    }


LEVER = contract(
    "lever",
    {"on": "bool", "jammed": "bool"},
    ["pull", "jam"],
    {
        "affordances": {
            "pull": {
                "arg": "none",
                "guards": [{"var": "jammed", "equals": False}],
                "effects": [{"op": "toggle", "var": "on"}],
            },
            "jam": {"arg": "none", "effects": [{"op": "set", "var": "jammed", "value": True}]},
        },
        "integrators": [],
    },
)
LAMP = contract(
    "lamp",
    {"lit": "bool", "brightness": "milli_i64"},
    ["light", "dark"],
    {
        "affordances": {
            "light": {
                "arg": "none",
                "effects": [
                    {"op": "set", "var": "lit", "value": True},
                    {"op": "set_control", "control": "brightness_target", "value": 1000},
                ],
            },
            "dark": {
                "arg": "none",
                "effects": [
                    {"op": "set", "var": "lit", "value": False},
                    {"op": "set_control", "control": "brightness_target", "value": 0},
                ],
            },
        },
        "integrators": [{"var": "brightness", "toward": "brightness_target", "rate": 500}],
    },
)
ON_LIGHTS = {
    "name": "on_lights",
    "when": [{"entity": "lever", "var": "on", "equals": True}],
    "then": [{"entity": "lamp", "verb": "light", "arg": None}],
}
OFF_DARKENS = {
    "name": "off_darkens",
    "when": [{"entity": "lever", "var": "on", "equals": False}],
    "then": [{"entity": "lamp", "verb": "dark", "arg": None}],
}


def replay_of(events: list, wires=None, ticks: int = 4) -> dict:
    doc = {
        "sim_replay": "0.1",
        "seed": 0,
        "ticks": ticks,
        "entities": {
            name: {
                "contract": c,
                "contract_sha256": hashlib.sha256(kernel.canonical(c)).hexdigest(),
            }
            for name, c in (("lever", LEVER), ("lamp", LAMP))
        },
        "initial": {},
        "events": events,
    }
    if wires is not None:
        doc["wires"] = wires
    return doc


def run(replay: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "replay.json"
        path.write_text(json.dumps(replay), encoding="utf-8")
        return kernel.run_replay(path)


def error_code(replay: dict) -> str:
    try:
        run(replay)
    except kernel.SimError as exc:
        return exc.code
    raise AssertionError("expected the kernel to refuse this replay")


def lamp_at(result: dict, tick: int) -> tuple:
    snap = result["snapshots"][tick]["lamp"]
    return (
        snap["state"]["lit"],
        snap["state"]["brightness"],
        snap["control"].get("brightness_target"),
    )


class Holding(unittest.TestCase):
    def test_a_wire_delivers_its_verb_every_tick_its_condition_holds(self):
        out = run(
            replay_of(
                [[0, "lever", "pull", None], [2, "lever", "pull", None]], [ON_LIGHTS, OFF_DARKENS]
            )
        )
        # tick 0: pull -> on; the wire lights the lamp in the same tick, before integration
        self.assertEqual(lamp_at(out, 0), (True, 500, 1000))
        self.assertEqual(lamp_at(out, 1), (True, 1000, 1000))
        # tick 2: pull -> off; the other wire darkens it, same tick
        self.assertEqual(lamp_at(out, 2), (False, 500, 0))
        self.assertEqual(lamp_at(out, 3), (False, 0, 0))

    def test_a_wire_overrules_a_direct_command_in_the_same_tick(self):
        """Events first, then wires: a `light` given while the lever is off is
        undone by the wire before the tick integrates."""
        out = run(replay_of([[1, "lamp", "light", None]], [OFF_DARKENS]))
        self.assertEqual(lamp_at(out, 1), (False, 0, 0))
        unwired = run(replay_of([[1, "lamp", "light", None]]))
        self.assertEqual(lamp_at(unwired, 1), (True, 500, 1000))

    def test_wires_fire_in_declared_order_and_later_ones_see_earlier_ones(self):
        lit_darkens = {
            "name": "lit_darkens",
            "when": [{"entity": "lamp", "var": "lit", "equals": True}],
            "then": [{"entity": "lamp", "verb": "dark", "arg": None}],
        }
        pull = [[0, "lever", "pull", None]]
        first_light = run(replay_of(pull, [ON_LIGHTS, lit_darkens], ticks=0))
        first_dark = run(replay_of(pull, [lit_darkens, ON_LIGHTS], ticks=0))
        self.assertEqual(lamp_at(first_light, 0)[0], False, "lit, then darkened by the later wire")
        self.assertEqual(
            lamp_at(first_dark, 0)[0], True, "not yet lit when the darkening wire looked"
        )
        self.assertNotEqual(first_light["state_hash"], first_dark["state_hash"])

    def test_a_guard_on_the_target_still_applies(self):
        """A wire delivers a verb; the verb's own guards decide. A jammed lever
        cannot be pulled by anyone, and a wire is no exception."""
        jam_pulls = {
            "name": "lit_pulls",
            "when": [{"entity": "lamp", "var": "lit", "equals": True}],
            "then": [{"entity": "lamp", "verb": "dark", "arg": None}],
        }
        out = run(replay_of([[0, "lamp", "light", None]], [jam_pulls], ticks=0))
        self.assertEqual(lamp_at(out, 0)[0], False)

    def test_a_control_clause_reads_drive_intent(self):
        wire = {
            "name": "bright_lever",
            "when": [{"entity": "lamp", "control": "brightness_target", "equals": 1000}],
            "then": [{"entity": "lamp", "verb": "dark", "arg": None}],
        }
        out = run(replay_of([[0, "lamp", "light", None]], [wire], ticks=0))
        self.assertEqual(lamp_at(out, 0), (False, 0, 0))

    def test_no_wires_and_an_empty_wire_list_agree(self):
        events = [[0, "lever", "pull", None], [1, "lamp", "light", None]]
        self.assertEqual(
            run(replay_of(events))["state_hash"], run(replay_of(events, []))["state_hash"]
        )


class FailClosed(unittest.TestCase):
    def refuse(self, wires) -> None:
        self.assertEqual(error_code(replay_of([], wires)), "E_WIRE_SHAPE")

    def wire(self, **changes) -> dict:
        return {**ON_LIGHTS, **changes}

    def test_a_wire_may_not_pulse(self):
        """`pull` toggles: delivered every tick it would flap. Refused at load."""
        self.refuse([self.wire(then=[{"entity": "lever", "verb": "pull", "arg": None}])])

    def test_targets_and_sources_must_exist(self):
        self.refuse([self.wire(then=[{"entity": "ghost", "verb": "light", "arg": None}])])
        self.refuse([self.wire(then=[{"entity": "lamp", "verb": "explode", "arg": None}])])
        self.refuse([self.wire(when=[{"entity": "ghost", "var": "on", "equals": True}])])
        self.refuse([self.wire(when=[{"entity": "lever", "var": "power", "gt": 0}])])

    def test_clauses_are_typed_like_guards(self):
        self.refuse([self.wire(when=[{"entity": "lever", "var": "on", "equals": 1}])])
        self.refuse([self.wire(when=[{"entity": "lever", "var": "on", "gt": 0}])])
        self.refuse(
            [self.wire(when=[{"entity": "lamp", "control": "brightness_target", "equals": True}])]
        )
        self.refuse(
            [self.wire(when=[{"entity": "lever", "var": "on", "control": "x", "equals": True}])]
        )
        self.refuse([self.wire(when=[{"entity": "lever", "var": "on", "equals": True, "gt": 1}])])

    def test_arguments_fit_the_verb(self):
        self.refuse([self.wire(then=[{"entity": "lamp", "verb": "light", "arg": 5}])])
        self.refuse([self.wire(then=[{"entity": "lamp", "verb": "light"}])])

    def test_shape_is_strict(self):
        self.refuse([self.wire(note="x")])
        self.refuse([self.wire(name="Bad Name")])
        self.refuse([ON_LIGHTS, ON_LIGHTS])
        self.refuse([self.wire(when=[])])
        self.refuse([self.wire(then=[])])
        self.refuse({"on_lights": ON_LIGHTS})
        self.refuse([self.wire(when=[{"entity": "lever", "var": "on", "equals": True, "note": 1}])])


if __name__ == "__main__":
    unittest.main()
