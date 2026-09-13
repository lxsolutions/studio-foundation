"""The prover (ADR 0022): design properties are proven over the kernel's own
state space, and every witness is a replay the kernel reproduces.

Contracts here are built directly (contract 0.2), not through World IR, so
each test says exactly what world it is about."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sim"))

import kernel  # noqa: E402
import prover  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
NATIVE_KERNEL = REPO / "services" / "target" / "release" / "sim-kernel"


def contract(entity: str, state: dict, affordances: list, semantics: dict, **params) -> dict:
    return {
        "sim_contract": "0.2",
        "source_world_ir_sha256": "0" * 64,
        "entity": entity,
        "state": {var: {"storage": storage} for var, storage in state.items()},
        "affordances": affordances,
        "parameters": {
            **params,
            "navigation": {"blocks_below": [], "never_blocks_when_destroyed": False},
        },
        "semantics": semantics,
    }


def lever(with_free: bool = True, counted: bool = True) -> dict:
    state = {"on": "bool", "jammed": "bool"}
    if counted:
        state["pulls"] = "i64"
    pull_effects = [{"op": "toggle", "var": "on"}]
    if counted:
        pull_effects.append({"op": "add", "var": "pulls", "value": 1})
    affordances = {
        "pull": {
            "arg": "none",
            "guards": [{"var": "jammed", "equals": False}],
            "effects": pull_effects,
        },
        "jam": {"arg": "none", "effects": [{"op": "set", "var": "jammed", "value": True}]},
    }
    if with_free:
        affordances["free"] = {
            "arg": "none",
            "effects": [{"op": "set", "var": "jammed", "value": False}],
        }
    return contract(
        "lever", state, list(affordances), {"affordances": affordances, "integrators": []}
    )


def lift() -> dict:
    semantics = {
        "affordances": {
            "call_top": {
                "arg": "none",
                "guards": [{"var": "power", "gt": 0}],
                "effects": [{"op": "set_control", "control": "height_target", "value": 1000}],
            },
            "charge": {
                "arg": "count",
                "effects": [
                    {
                        "op": "add",
                        "var": "power",
                        "value": {"arg": True},
                        "clamp": {"max": {"param": "max_power", "default": 60}},
                    }
                ],
            },
        },
        "integrators": [
            {
                "var": "height",
                "toward": "height_target",
                "rate": {"param": "lift_rate_milli", "default": 200},
            }
        ],
    }
    return contract(
        "lift",
        {"height": "milli_i64", "power": "i64"},
        ["call_top", "charge"],
        semantics,
        lift_rate_milli=250,
        max_power=60,
    )


def clause(entity: str, **test) -> dict:
    return {"entity": entity, **test}


def prove(contracts: dict, claims: list, initial: dict | None = None, **options) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        return prover.prove(
            {**options, "assert": claims}, contracts, initial or {}, witness_dir=Path(tmp)
        )


def only(report: dict) -> dict:
    return report["results"][0]


class Reachable(unittest.TestCase):
    def test_a_witness_is_the_shortest_schedule_and_the_kernel_reproduces_it(self):
        report = prove(
            {"lever": lever()},
            [
                {
                    "name": "pulled twice",
                    "kind": "reachable",
                    "when": [clause("lever", var="pulls", gt=1)],
                }
            ],
        )
        verdict = only(report)
        self.assertEqual(verdict["status"], "holds")
        witness = verdict["witness"]
        self.assertEqual(
            witness["events"], [[0, "lever", "pull", None], [1, "lever", "pull", None]]
        )
        self.assertEqual(
            witness["ticks"], 1, "a node two ticks in replays as ticks=1 (0..1 inclusive)"
        )
        self.assertTrue(witness["verified"], "the kernel must land on the witness hash")
        # And independently: run the written replay shape through the kernel ourselves.
        replay = prover.witness_replay(
            {
                "events": witness["events"],
                "ticks": witness["ticks"],
                "state_hash": witness["state_hash"],
            },
            {"lever": lever()},
            {},
            "test",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.json"
            path.write_text(json.dumps(replay))
            self.assertEqual(kernel.run_replay(path)["state_hash"], witness["state_hash"])

    @unittest.skipUnless(NATIVE_KERNEL.is_file(), "native kernel not built (just sim-parity)")
    def test_a_witness_is_an_ordinary_replay_any_kernel_reproduces(self):
        """The prover explores with the Python kernel; the witness it writes is a
        plain replay, so the native Rust kernel must land on the same hash."""
        import subprocess

        verdict = only(
            prove(
                {"lever": lever()},
                [
                    {
                        "name": "pulled twice",
                        "kind": "reachable",
                        "when": [clause("lever", var="pulls", gt=1)],
                    }
                ],
            )
        )
        witness = verdict["witness"]
        replay = prover.witness_replay(witness, {"lever": lever()}, {}, "test")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.json"
            path.write_text(json.dumps(replay))
            out = subprocess.run(
                [str(NATIVE_KERNEL), str(path)], capture_output=True, text=True, check=True
            )
        self.assertEqual(json.loads(out.stdout)["state_hash"], witness["state_hash"])

    def test_a_property_true_in_the_initial_state_needs_no_replay(self):
        verdict = only(
            prove(
                {"lever": lever()},
                [
                    {
                        "name": "starts off",
                        "kind": "reachable",
                        "when": [clause("lever", var="on", equals=False)],
                    }
                ],
            )
        )
        self.assertEqual(verdict["status"], "holds")
        self.assertEqual(verdict["witness"]["events"], [])
        self.assertIsNone(verdict["witness"]["ticks"])
        self.assertTrue(verdict["witness"]["verified"])

    def test_an_unreachable_goal_is_violated_with_the_bound_named(self):
        # Without `free`, a jammed lever stays jammed; but jamming is only ever
        # done by us, so `jammed == True` IS reachable. Ask for the impossible.
        verdict = only(
            prove(
                {"lever": lever(counted=False)},
                [
                    {
                        "name": "on and off",
                        "kind": "reachable",
                        "when": [
                            clause("lever", var="on", equals=True),
                            clause("lever", var="on", equals=False),
                        ],
                    }
                ],
            )
        )
        self.assertEqual(verdict["status"], "violated")
        self.assertEqual(verdict["bound"], "exhaustive", "a finite world is explored to closure")

    def test_a_control_clause_reads_drive_intent(self):
        verdict = only(
            prove(
                {"lift": lift()},
                [
                    {
                        "name": "summoned",
                        "kind": "reachable",
                        "when": [clause("lift", control="height_target", equals=1000)],
                    }
                ],
            )
        )
        self.assertEqual(verdict["status"], "holds")
        # charge first (a call with no power is absorbed), then call
        self.assertEqual([e[2] for e in verdict["witness"]["events"]], ["charge", "call_top"])


class Never(unittest.TestCase):
    def test_a_violation_comes_with_a_counterexample(self):
        verdict = only(
            prove(
                {"lever": lever()},
                [
                    {
                        "name": "never on while jammed",
                        "kind": "never",
                        "when": [
                            clause("lever", var="on", equals=True),
                            clause("lever", var="jammed", equals=True),
                        ],
                    }
                ],
            )
        )
        self.assertEqual(verdict["status"], "violated")
        self.assertEqual([e[2] for e in verdict["witness"]["events"]], ["pull", "jam"])
        self.assertTrue(verdict["witness"]["verified"])

    def test_holds_exhaustively_on_a_finite_world(self):
        verdict = only(
            prove(
                {"lever": lever(counted=False)},
                [
                    {
                        "name": "never both",
                        "kind": "never",
                        "when": [
                            clause("lever", var="on", equals=True),
                            clause("lever", var="on", equals=False),
                        ],
                    }
                ],
            )
        )
        self.assertEqual((verdict["status"], verdict["bound"]), ("holds", "exhaustive"))

    def test_holds_only_to_the_horizon_on_an_unbounded_counter(self):
        verdict = only(
            prove(
                {"lever": lever()},
                [
                    {
                        "name": "never negative",
                        "kind": "never",
                        "when": [clause("lever", var="pulls", lt=0)],
                    }
                ],
                horizon=6,
            )
        )
        self.assertEqual((verdict["status"], verdict["bound"]), ("holds", "horizon"))

    def test_the_lift_never_moves_unpowered(self):
        verdict = only(
            prove(
                {"lift": lift()},
                [
                    {
                        "name": "no power no motion",
                        "kind": "never",
                        "when": [
                            clause("lift", var="height", gt=0),
                            clause("lift", var="power", equals=0),
                        ],
                    }
                ],
            )
        )
        self.assertEqual(verdict["status"], "holds")


class Live(unittest.TestCase):
    def test_a_soft_lock_is_found_and_witnessed(self):
        """A lever with no `free`: one jam and the goal is gone forever."""
        verdict = only(
            prove(
                {"lever": lever(with_free=False, counted=False)},
                [
                    {
                        "name": "can always be switched on",
                        "kind": "live",
                        "when": [clause("lever", var="on", equals=True)],
                    }
                ],
            )
        )
        self.assertEqual(verdict["status"], "violated")
        self.assertIn("soft-lock", verdict["detail"])
        self.assertEqual(verdict["witness"]["events"], [[0, "lever", "jam", None]])
        self.assertTrue(verdict["witness"]["verified"])

    def test_holds_when_every_state_keeps_the_goal_reachable(self):
        verdict = only(
            prove(
                {"lever": lever(counted=False)},
                [
                    {
                        "name": "can always be switched on",
                        "kind": "live",
                        "when": [clause("lever", var="on", equals=True)],
                    }
                ],
            )
        )
        self.assertEqual((verdict["status"], verdict["bound"]), ("holds", "exhaustive"))

    def test_an_unreachable_goal_is_not_live(self):
        verdict = only(
            prove(
                {"lever": lever(counted=False)},
                [
                    {
                        "name": "impossible",
                        "kind": "live",
                        "when": [
                            clause("lever", var="on", equals=True),
                            clause("lever", var="on", equals=False),
                        ],
                    }
                ],
            )
        )
        self.assertEqual(verdict["status"], "violated")


class Bounds(unittest.TestCase):
    def test_a_spent_budget_is_inconclusive_not_a_pass(self):
        verdict = only(
            prove(
                {"lever": lever()},
                [
                    {
                        "name": "never negative",
                        "kind": "never",
                        "when": [clause("lever", var="pulls", lt=0)],
                    }
                ],
                budget=3,
            )
        )
        self.assertEqual((verdict["status"], verdict["bound"]), ("inconclusive", "budget"))

    def test_amounts_tried_are_the_ones_the_semantics_name_plus_the_maximum(self):
        report = prove(
            {"lift": lift()},
            [
                {
                    "name": "top",
                    "kind": "reachable",
                    "when": [clause("lift", var="height", equals=1000)],
                }
            ],
            amounts=[7],
        )
        self.assertEqual(report["explored"]["amounts"], {"lift.charge": [7, 60, 65535]})
        self.assertEqual(only(report)["status"], "holds")

    def test_the_whole_graph_is_explored_once_for_every_property(self):
        report = prove(
            {"lever": lever(counted=False)},
            [
                {
                    "name": "a",
                    "kind": "reachable",
                    "when": [clause("lever", var="on", equals=True)],
                },
                {"name": "b", "kind": "never", "when": [clause("lever", var="pulls", lt=0)]}
                if False
                else {
                    "name": "b",
                    "kind": "live",
                    "when": [clause("lever", var="on", equals=True)],
                },
            ],
        )
        self.assertEqual([r["status"] for r in report["results"]], ["holds", "holds"])
        self.assertEqual(report["explored"]["states"], 4, "on x jammed")


class Wired(unittest.TestCase):
    """Wires (ADR 0024) are applied where the kernel applies them, so the
    prover reasons about couplings and its witnesses replay through them."""

    LAMP = contract(
        "lamp",
        {"lit": "bool"},
        ["light", "dark"],
        {
            "affordances": {
                "light": {"arg": "none", "effects": [{"op": "set", "var": "lit", "value": True}]},
                "dark": {"arg": "none", "effects": [{"op": "set", "var": "lit", "value": False}]},
            },
            "integrators": [],
        },
    )
    WIRES = [
        {
            "name": "on_lights",
            "when": [clause("lever", var="on", equals=True)],
            "then": [{"entity": "lamp", "verb": "light", "arg": None}],
        },
        {
            "name": "off_darkens",
            "when": [clause("lever", var="on", equals=False)],
            "then": [{"entity": "lamp", "verb": "dark", "arg": None}],
        },
    ]

    def prove(self, claims):
        with tempfile.TemporaryDirectory() as tmp:
            return prover.prove(
                {"assert": claims},
                {"lever": lever(counted=False), "lamp": self.LAMP},
                {},
                witness_dir=Path(tmp),
                wires=self.WIRES,
            )

    def test_a_coupling_is_reachable_through_the_wire_and_the_witness_carries_it(self):
        verdict = only(
            self.prove(
                [
                    {
                        "name": "lit by the lever",
                        "kind": "reachable",
                        "when": [
                            clause("lamp", var="lit", equals=True),
                            clause("lever", var="on", equals=True),
                        ],
                    }
                ]
            )
        )
        self.assertEqual(verdict["status"], "holds")
        self.assertEqual(verdict["witness"]["events"], [[0, "lever", "pull", None]])
        self.assertTrue(verdict["witness"]["verified"], "the kernel replayed the wire too")

    def test_a_wire_that_dominates_makes_a_never_property_hold(self):
        """`light` is a direct affordance, but the off wire darkens the lamp in
        the same tick, so a lit lamp under an off lever is unreachable."""
        verdict = only(
            self.prove(
                [
                    {
                        "name": "never lit while off",
                        "kind": "never",
                        "when": [
                            clause("lamp", var="lit", equals=True),
                            clause("lever", var="on", equals=False),
                        ],
                    }
                ]
            )
        )
        self.assertEqual((verdict["status"], verdict["bound"]), ("holds", "exhaustive"))

    def test_without_the_wire_the_same_property_is_violated(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = prover.prove(
                {
                    "assert": [
                        {
                            "name": "never lit while off",
                            "kind": "never",
                            "when": [
                                clause("lamp", var="lit", equals=True),
                                clause("lever", var="on", equals=False),
                            ],
                        }
                    ]
                },
                {"lever": lever(counted=False), "lamp": self.LAMP},
                {},
                witness_dir=Path(tmp),
            )
        self.assertEqual(only(report)["status"], "violated")
        self.assertEqual(only(report)["witness"]["events"], [[0, "lamp", "light", None]])


class Validation(unittest.TestCase):
    def refuse(self, claims, contracts=None, **options):
        with self.assertRaises(prover.ProofError):
            prover.validate_properties(
                {**options, "assert": claims}, contracts or {"lever": lever()}
            )

    def test_clauses_are_typed_like_guards(self):
        self.refuse([{"name": "x", "kind": "never", "when": [clause("lever", var="on", equals=1)]}])
        self.refuse([{"name": "x", "kind": "never", "when": [clause("lever", var="on", gt=0)]}])
        self.refuse(
            [{"name": "x", "kind": "never", "when": [clause("lever", var="pulls", equals=True)]}]
        )
        self.refuse([{"name": "x", "kind": "never", "when": [clause("lever", var="on", exists=1)]}])

    def test_clauses_name_real_entities_and_vars(self):
        self.refuse(
            [{"name": "x", "kind": "never", "when": [clause("ghost", var="on", equals=True)]}]
        )
        self.refuse(
            [{"name": "x", "kind": "never", "when": [clause("lever", var="nope", equals=True)]}]
        )
        self.refuse(
            [{"name": "x", "kind": "never", "when": [clause("lever", control="Bad", equals=1)]}]
        )

    def test_shape_is_strict(self):
        self.refuse(
            [{"name": "x", "kind": "maybe", "when": [clause("lever", var="on", equals=True)]}]
        )
        self.refuse(
            [{"name": "x", "kind": "never", "when": [clause("lever", var="on", equals=True, gt=0)]}]
        )
        self.refuse(
            [{"name": "x", "kind": "never", "when": [clause("lever", var="on", equals=True), 5]}]
        )
        self.refuse([{"name": "x", "kind": "never", "when": [], "note": 1}])
        self.refuse(
            [
                {"name": "x", "kind": "never", "when": [clause("lever", var="on", equals=True)]},
                {"name": "x", "kind": "never", "when": [clause("lever", var="on", equals=True)]},
            ]
        )
        self.refuse(
            [{"name": "x", "kind": "never", "when": [clause("lever", var="on", equals=True)]}],
            horizon=0,
        )
        self.refuse(
            [{"name": "x", "kind": "never", "when": [clause("lever", var="on", equals=True)]}],
            amounts=[-1],
        )


if __name__ == "__main__":
    unittest.main()
