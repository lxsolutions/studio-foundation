"""Declared affordance semantics (ADR 0021) — the kernel past the door.

The kernel used to hardcode one entity: six verbs, four state vars, one
integrator, `E_NO_SEMANTICS` for everything else. These tests cover the closed
vocabulary that replaced it, and the first one is the load-bearing one — a v0.1
contract and a v0.2 contract that spells the door out longhand must produce the
same hash, because the built-in door IS the profile now rather than a second
code path that happens to agree.
"""

from __future__ import annotations

import copy
import hashlib
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
GATE_ENTITY = REPO / "tools" / "worldc" / "examples" / "fortress_gate.json"


def run(replay: dict) -> dict:
    """Run a replay dict, re-pinning contract hashes so the test is about semantics."""
    for entry in replay["entities"].values():
        entry["contract_sha256"] = hashlib.sha256(kernel.canonical(entry["contract"])).hexdigest()
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


def contract(state: dict, affordances: list, semantics: dict | None, **params) -> dict:
    doc = {
        "sim_contract": "0.1" if semantics is None else "0.2",
        "source_world_ir_sha256": "0" * 64,
        "entity": "thing",
        "state": state,
        "affordances": affordances,
        "parameters": {
            **params,
            "navigation": {"blocks_below": [], "never_blocks_when_destroyed": False},
        },
    }
    if semantics is not None:
        doc["semantics"] = semantics
    return doc


def replay_of(
    contract_doc: dict, events: list, ticks: int = 6, initial: dict | None = None
) -> dict:
    return {
        "sim_replay": "0.1",
        "seed": 0,
        "ticks": ticks,
        "entities": {"thing": {"contract": contract_doc, "contract_sha256": "0" * 64}},
        "initial": {"thing": initial} if initial else {},
        "events": events,
    }


class TheDoorIsNowData(unittest.TestCase):
    def test_a_v01_gate_and_a_longhand_v02_gate_agree_exactly(self):
        """If the vocabulary could not express the door, this hash would move."""
        gate = worldc.sim_contract(worldc.load_entity(GATE_ENTITY))
        events = [
            [0, "thing", "unlock", None],
            [1, "thing", "open", None],
            [3, "thing", "attack", 60],
        ]

        builtin = copy.deepcopy(gate)
        builtin["entity"] = "thing"
        longhand = copy.deepcopy(builtin)
        longhand["sim_contract"] = "0.2"
        longhand["semantics"] = copy.deepcopy(kernel.DOOR_PROFILE)

        a = run(replay_of(builtin, events, ticks=8, initial={"health": 100, "locked": True}))
        b = run(replay_of(longhand, events, ticks=8, initial={"health": 100, "locked": True}))
        self.assertEqual(a["state_hash"], b["state_hash"])
        self.assertEqual(a["hash_log"], b["hash_log"])

    def test_a_v01_contract_cannot_reach_a_verb_it_did_not_list(self):
        gate = worldc.sim_contract(worldc.load_entity(GATE_ENTITY))
        gate["entity"] = "thing"
        gate["affordances"] = ["open"]  # lock is no longer declared
        self.assertEqual(
            error_code(replay_of(gate, [[0, "thing", "lock", None]])), "E_UNDECLARED_AFFORDANCE"
        )


class Vocabulary(unittest.TestCase):
    def test_toggle_flips_a_bool(self):
        doc = contract(
            {"on": {"storage": "bool"}},
            ["pull"],
            {"affordances": {"pull": {"arg": "none", "effects": [{"op": "toggle", "var": "on"}]}}},
        )
        out = run(
            replay_of(
                doc,
                [
                    [0, "thing", "pull", None],
                    [1, "thing", "pull", None],
                    [2, "thing", "pull", None],
                ],
            )
        )
        self.assertTrue(out["final_state"]["thing"]["state"]["on"], "three pulls leave it on")

    def test_a_guard_that_does_not_hold_is_a_no_op_not_an_error(self):
        """A locked gate absorbing `open` generalizes: guards gate, they do not fail."""
        doc = contract(
            {"on": {"storage": "bool"}, "jammed": {"storage": "bool"}},
            ["pull"],
            {
                "affordances": {
                    "pull": {
                        "arg": "none",
                        "guards": [{"var": "jammed", "equals": False}],
                        "effects": [{"op": "toggle", "var": "on"}],
                    }
                }
            },
        )
        out = run(replay_of(doc, [[0, "thing", "pull", None]], initial={"jammed": True}))
        self.assertFalse(out["final_state"]["thing"]["state"]["on"], "the guard should block it")

    def test_add_clamps_against_a_parameter(self):
        doc = contract(
            {"power": {"storage": "i64"}},
            ["charge"],
            {
                "affordances": {
                    "charge": {
                        "arg": "count",
                        "effects": [
                            {
                                "op": "add",
                                "var": "power",
                                "value": {"arg": True},
                                "sign": 1,
                                "clamp": {"max": {"param": "max_power", "default": 10}},
                            }
                        ],
                    }
                }
            },
            max_power=60,
        )
        out = run(replay_of(doc, [[0, "thing", "charge", 999]]))
        self.assertEqual(out["final_state"]["thing"]["state"]["power"], 60)

    def test_add_clamps_at_a_floor(self):
        doc = contract(
            {"hp": {"storage": "i64"}},
            ["hit"],
            {
                "affordances": {
                    "hit": {
                        "arg": "count",
                        "effects": [
                            {
                                "op": "add",
                                "var": "hp",
                                "value": {"arg": True},
                                "sign": -1,
                                "clamp": {"min": 0},
                            }
                        ],
                    }
                }
            },
        )
        out = run(replay_of(doc, [[0, "thing", "hit", 500]], initial={"hp": 10}))
        self.assertEqual(out["final_state"]["thing"]["state"]["hp"], 0)

    def test_an_integrator_moves_any_var_toward_any_control(self):
        """Nothing here is named openness, openness_target, or open_rate_milli."""
        doc = contract(
            {"height": {"storage": "milli_i64"}},
            ["call_top"],
            {
                "affordances": {
                    "call_top": {
                        "arg": "none",
                        "effects": [
                            {"op": "set_control", "control": "height_target", "value": 1000}
                        ],
                    }
                },
                "integrators": [
                    {
                        "var": "height",
                        "toward": "height_target",
                        "rate": {"param": "lift_rate_milli", "default": 200},
                    }
                ],
            },
            lift_rate_milli=250,
        )
        # A replay of N ticks produces N+1 snapshots, so ticks=2 is three steps
        # at 250 — partway, which is the point: it integrates, it does not snap.
        partway = run(replay_of(doc, [[0, "thing", "call_top", None]], ticks=2))
        self.assertEqual(partway["final_state"]["thing"]["state"]["height"], 750)
        arrived = run(replay_of(doc, [[0, "thing", "call_top", None]], ticks=8))
        self.assertEqual(arrived["final_state"]["thing"]["state"]["height"], 1000, "and it stops")

    def test_a_v01_gate_without_health_still_reports_no_semantics(self):
        """Backward compatibility for the one case `requires` still catches.

        A v0.2 contract cannot reach this: validation refuses a `requires` on an
        undeclared var at load. But a v0.1 contract declares affordance NAMES
        only, so it can list `attack` with no `health` var — and the door
        profile's `requires` is what turns that into an error rather than a
        silent no-op, exactly as the hardcoded kernel did.
        """
        gate = worldc.sim_contract(worldc.load_entity(GATE_ENTITY))
        gate["entity"] = "thing"
        del gate["state"]["health"]
        self.assertEqual(
            error_code(replay_of(gate, [[0, "thing", "attack", 10]])), "E_NO_SEMANTICS"
        )

    def test_argument_shape_is_per_affordance(self):
        doc = contract(
            {"on": {"storage": "bool"}},
            ["pull", "charge"],
            {
                "affordances": {
                    "pull": {"arg": "none", "effects": [{"op": "toggle", "var": "on"}]},
                    "charge": {"arg": "count", "effects": [{"op": "toggle", "var": "on"}]},
                }
            },
        )
        self.assertEqual(error_code(replay_of(doc, [[0, "thing", "pull", 5]])), "E_ARGUMENT_DOMAIN")
        self.assertEqual(
            error_code(replay_of(doc, [[0, "thing", "charge", None]])), "E_ARGUMENT_TYPE"
        )
        self.assertEqual(
            error_code(replay_of(doc, [[0, "thing", "charge", 999999]])), "E_ARGUMENT_RANGE"
        )

    def test_a_guard_cannot_compare_a_bool_to_a_number(self):
        """Python says True == 1 and serde_json does not. Rather than let two
        kernels disagree about a guard that can never hold, the comparison is
        refused at load — and the runtime equality stays type-strict underneath."""
        doc = contract(
            {"flag": {"storage": "bool"}, "hits": {"storage": "i64"}},
            ["poke"],
            {
                "affordances": {
                    "poke": {
                        "arg": "none",
                        "guards": [{"var": "flag", "equals": 0}],  # a bool is never the number 0
                        "effects": [{"op": "add", "var": "hits", "value": 1, "sign": 1}],
                    }
                }
            },
        )
        self.assertEqual(
            error_code(replay_of(doc, [[0, "thing", "poke", None]], initial={"flag": False})),
            "E_SEMANTICS_SHAPE",
        )
        self.assertFalse(kernel._json_eq(True, 1))
        self.assertFalse(kernel._json_eq(0, False))
        self.assertTrue(kernel._json_eq(1, 1))


class FailClosed(unittest.TestCase):
    def check(self, semantics: dict, state: dict | None = None, affordances=("act",)):
        doc = contract(state or {"on": {"storage": "bool"}}, list(affordances), semantics)
        self.assertEqual(error_code(replay_of(doc, [])), "E_SEMANTICS_SHAPE")

    def test_an_effect_writing_an_undeclared_var_is_refused(self):
        self.check(
            {"affordances": {"act": {"effects": [{"op": "set", "var": "nope", "value": 1}]}}}
        )

    def test_an_unknown_effect_op_is_refused(self):
        self.check({"affordances": {"act": {"effects": [{"op": "launch", "var": "on"}]}}})

    def test_a_guard_on_an_undeclared_var_is_refused(self):
        self.check({"affordances": {"act": {"guards": [{"var": "nope", "equals": True}]}}})

    def test_a_guard_with_two_tests_is_refused(self):
        self.check({"affordances": {"act": {"guards": [{"var": "on", "equals": True, "gt": 1}]}}})

    def test_an_integrator_on_an_undeclared_var_is_refused(self):
        self.check(
            {"affordances": {}, "integrators": [{"var": "nope", "toward": "t", "rate": 1}]},
            affordances=(),
        )

    def test_semantics_for_an_unlisted_affordance_are_refused(self):
        """Declaring behaviour for a verb the contract does not offer is a trap."""
        self.check({"affordances": {"ghost": {"effects": []}}}, affordances=("act",))

    def test_an_unsupported_contract_version_is_refused(self):
        doc = contract({"on": {"storage": "bool"}}, ["act"], {"affordances": {}})
        doc["sim_contract"] = "0.3"
        self.assertEqual(error_code(replay_of(doc, [])), "E_CONTRACT_VERSION")


class TypedAtLoad(unittest.TestCase):
    """The vocabulary is typed against the state schema at load, so `true + 1`
    is never a question either kernel has to answer — and a value has exactly
    one source, `arg` is literally `true`, and unknown keys are refused
    everywhere, because a `guard` where `guards` was meant would otherwise
    vanish without a sound."""

    STATE = {"on": {"storage": "bool"}, "hp": {"storage": "i64"}, "name": {"storage": "string"}}

    def refuse(self, semantics: dict, affordances=("act",)):
        doc = contract(self.STATE, list(affordances), semantics)
        self.assertEqual(error_code(replay_of(doc, [])), "E_SEMANTICS_SHAPE")

    @staticmethod
    def act(*effects, arg="none", guards=None):
        spec = {"arg": arg, "effects": list(effects)}
        if guards is not None:
            spec["guards"] = guards
        return {"affordances": {"act": spec}}

    def test_set_must_match_the_vars_type(self):
        self.refuse(self.act({"op": "set", "var": "on", "value": 1}))
        self.refuse(self.act({"op": "set", "var": "hp", "value": True}))
        self.refuse(self.act({"op": "set", "var": "name", "value": {"var": "hp"}}))

    def test_add_and_ordering_need_integers(self):
        self.refuse(self.act({"op": "add", "var": "on", "value": 1}))
        self.refuse(self.act({"op": "add", "var": "hp", "value": True}))
        self.refuse(self.act({"op": "add", "var": "hp", "value": 1, "clamp": {"max": False}}))
        self.refuse(self.act({"op": "toggle", "var": "on"}, guards=[{"var": "on", "gt": 0}]))

    def test_toggle_needs_a_bool(self):
        self.refuse(self.act({"op": "toggle", "var": "hp"}))

    def test_a_control_carries_an_integer_and_has_a_snake_case_name(self):
        self.refuse(self.act({"op": "set_control", "control": "target", "value": True}))
        self.refuse(self.act({"op": "set_control", "control": "Target", "value": 1}))

    def test_floats_are_not_a_thing_the_kernel_holds(self):
        self.refuse(self.act({"op": "set", "var": "hp", "value": 1.5}))
        self.refuse(self.act({"op": "add", "var": "hp", "value": {"const": 2.0}}))

    def test_a_value_has_exactly_one_source(self):
        self.refuse(self.act({"op": "set", "var": "hp", "value": {"const": 1, "var": "hp"}}))
        self.refuse(self.act({"op": "set", "var": "hp", "value": {}}))
        self.refuse(self.act({"op": "set", "var": "hp", "value": {"const": 1, "default": 0}}))

    def test_the_argument_source_is_literally_true_and_needs_a_count(self):
        self.refuse(self.act({"op": "add", "var": "hp", "value": {"arg": 1}}, arg="count"))
        self.refuse(self.act({"op": "add", "var": "hp", "value": {"arg": True}}))  # arg: none

    def test_a_parameter_must_be_set_or_defaulted(self):
        self.refuse(self.act({"op": "add", "var": "hp", "value": {"param": "ghost"}}))
        doc = contract(
            self.STATE,
            ["act"],
            self.act({"op": "add", "var": "hp", "value": {"param": "ghost", "default": 3}}),
        )
        out = run(replay_of(doc, [[0, "thing", "act", None]]))
        self.assertEqual(out["final_state"]["thing"]["state"]["hp"], 3)

    def test_exists_is_a_bool(self):
        """`exists: 1` would be truthy in Python and no test at all in Rust."""
        self.refuse(self.act({"op": "toggle", "var": "on"}, guards=[{"var": "on", "exists": 1}]))

    def test_unknown_keys_are_refused_everywhere(self):
        self.refuse(self.act({"op": "toggle", "var": "on", "guard": []}))  # `guard` for `when`
        self.refuse({"affordances": {"act": {"effects": [], "guard": []}}})
        self.refuse({"affordances": {"act": {"effects": []}}, "integrator": []})
        self.refuse(self.act({"op": "add", "var": "hp", "value": 1, "clamp": {"minimum": 0}}))
        self.refuse(
            self.act(
                {"op": "toggle", "var": "on"}, guards=[{"var": "on", "equals": True, "note": 1}]
            )
        )

    def test_every_listed_affordance_needs_semantics(self):
        self.refuse({"affordances": {"act": {"effects": []}}}, affordances=("act", "other"))

    def test_requires_is_a_list_of_declared_vars(self):
        self.refuse({"affordances": {"act": {"requires": "hp", "effects": []}}})
        self.refuse({"affordances": {"act": {"requires": ["ghost"], "effects": []}}})

    def test_an_integrator_needs_an_integer_var_and_a_snake_case_control(self):
        for bad in (
            {"var": "on", "toward": "t", "rate": 1},
            {"var": "hp", "toward": "t", "rate": True},
            {"var": "hp", "toward": "Target", "rate": 1},
        ):
            self.refuse({"affordances": {}, "integrators": [bad]}, affordances=())


class ContractShape(unittest.TestCase):
    """Shapes both kernels must agree on before either reads a value: a float
    parameter Python would truncate and Rust would ignore, a storage type one
    kernel knows and the other does not."""

    def refuse(self, doc: dict, code: str = "E_CONTRACT_SHAPE"):
        self.assertEqual(error_code(replay_of(doc, [])), code)

    def test_a_v01_contract_cannot_carry_semantics(self):
        doc = contract(
            {"on": {"storage": "bool"}}, ["act"], {"affordances": {"act": {"effects": []}}}
        )
        doc["sim_contract"] = "0.1"
        self.refuse(doc)

    def test_a_v02_contract_must_declare_semantics(self):
        doc = contract({"on": {"storage": "bool"}}, [], None)
        doc["sim_contract"] = "0.2"
        self.refuse(doc)

    def test_parameters_are_i64_integers(self):
        for bad in (300.0, True, "300", 2**63):
            self.refuse(contract({"on": {"storage": "bool"}}, [], None, open_rate_milli=bad))

    def test_state_vars_need_a_known_storage(self):
        self.refuse(contract({"on": {"storage": "boolean"}}, [], None))
        self.refuse(contract({"on": "bool"}, [], None))

    def test_affordances_are_snake_case_identifiers(self):
        self.refuse(contract({"on": {"storage": "bool"}}, ["Pull"], None))
        self.refuse(contract({"on": {"storage": "bool"}}, "pull", None))

    def test_navigation_rules_are_shaped(self):
        doc = contract({"on": {"storage": "bool"}}, [], None)
        doc["parameters"]["navigation"]["blocks_below"] = [{"var": "on"}]
        self.refuse(doc)

    def test_initial_values_are_i64(self):
        doc = contract({"hp": {"storage": "i64"}}, [], None)
        self.assertEqual(error_code(replay_of(doc, [], initial={"hp": 2**70})), "E_INITIAL_TYPE")


class Saturation(unittest.TestCase):
    """Python integers are unbounded; the Rust kernel's are i64. The Python
    kernel saturates exactly where Rust does, so the two cannot drift apart at
    the edge — and a conformance fixture holds all three kernels to it."""

    def test_add_saturates_at_i64_max(self):
        doc = contract(
            {"x": {"storage": "i64"}},
            ["bump"],
            {
                "affordances": {
                    "bump": {"arg": "none", "effects": [{"op": "add", "var": "x", "value": 2**62}]}
                }
            },
        )
        bumps = [[tick, "thing", "bump", None] for tick in range(3)]
        out = run(replay_of(doc, bumps, initial={"x": 2**62}))
        self.assertEqual(out["final_state"]["thing"]["state"]["x"], kernel.I64_MAX)

    def test_an_integrator_saturates_too(self):
        doc = contract(
            {"x": {"storage": "i64"}},
            ["go"],
            {
                "affordances": {
                    "go": {
                        "arg": "none",
                        "effects": [
                            {"op": "set_control", "control": "x_target", "value": kernel.I64_MAX}
                        ],
                    }
                },
                "integrators": [{"var": "x", "toward": "x_target", "rate": kernel.I64_MAX}],
            },
        )
        out = run(replay_of(doc, [[0, "thing", "go", None]], initial={"x": 5}, ticks=1))
        self.assertEqual(out["final_state"]["thing"]["state"]["x"], kernel.I64_MAX)


if __name__ == "__main__":
    unittest.main()
