#!/usr/bin/env python3
"""sim — the deterministic simulation kernel (ADR 0018 milestone M3).

The contract:

    initial world state + seed + fixed-step event stream = final state hash

Kernels consume a COMPILED simulation contract (worldc.sim_contract), never
raw World IR: the contract is integer-only (floats are milli-units), carries
its source document's canonical hash, and is pinned by the replay via
contract_sha256. Replays are self-contained — the contract is inline — so
native, Wasm, and hosted runs need no document I/O at all.

Authoritative state is INTEGER fixed-point, and control intent is part of the
hashed state: identical visible state with different drive targets hashes
differently, because the next tick differs. Navigation is derived, never
stored. Validation is fail-closed with stable error codes.

Replay file (JSON, v0.1):

    {
      "sim_replay": "0.1",
      "seed": 0,
      "ticks": 40,
      "entities": {"fortress_gate": {"contract": {...}, "contract_sha256": "..."}},
      "initial": {"fortress_gate": {"health": 100, "locked": true}},
      "events": [[tick, "fortress_gate", "unlock", null], ...],
      "expect_state_hash": "..."   # optional golden assertion
    }

Initial values for float state vars are INTEGER MILLI-UNITS (1.0 == 1000).
Usage: python tools/sim/kernel.py replay FILE [--update-golden] [--full]
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

REPLAY_VERSION = "0.1"
QUANTUM = 1000  # float state vars are integer milli-units: 1.0 == 1000
# 0.1 lists affordance names and relies on the built-in door; 0.2 declares
# its own semantics. Both run through the same interpreter (ADR 0021).
SUPPORTED_CONTRACTS = ("0.1", "0.2")
MAX_TICKS = 1_000_000
MAX_EVENT_ARG = 65_535

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
REPLAY_KEYS = {
    "sim_replay",
    "seed",
    "ticks",
    "comment",
    "entities",
    "initial",
    "events",
    "expect_state_hash",
    # conformance-corpus metadata (not simulation semantics)
    "expect",
    "expect_error",
}


class SimError(Exception):
    """A replay or contract is invalid, or an event broke the contract.

    Carries a stable machine-readable `code` (E_...) so different kernel
    implementations can be checked for identical rejection behavior, not
    merely similar error prose.
    """

    def __init__(self, message: str, code: str = "E_SIM"):
        super().__init__(f"{code}: {message}")
        self.code = code


def canonical(state: dict) -> bytes:
    return json.dumps(state, sort_keys=True, separators=(",", ":")).encode()


def state_hash(world: dict) -> str:
    """Hash the COMPLETE deterministic state: declared state vars plus control
    intent. Anything the next tick depends on is inside this hash."""
    return hashlib.sha256(canonical(world)).hexdigest()


def initial_state(contract: dict) -> dict:
    """Typed defaults from the contract's state schema."""
    state: dict = {}
    for var, spec in contract.get("state", {}).items():
        state[var] = {
            "milli_i64": 0,
            "i64": 0,
            "bool": False,
            "string": "",
        }[spec["storage"]]
    return state


def _coerce_initial(entity: str, contract: dict, var: str, value) -> object:
    spec = contract.get("state", {}).get(var)
    if spec is None:
        raise SimError(
            f"{entity}: initial sets undeclared state var {var!r}", code="E_INITIAL_UNKNOWN_VAR"
        )
    storage = spec["storage"]
    if storage in ("milli_i64", "i64"):
        # float state vars take INTEGER MILLI-UNITS; no float conversion ever
        # happens inside the kernel
        if not _is_int(value):
            raise SimError(
                f"{entity}: initial {var} must be an i64 integer"
                + (" (milli-units)" if storage == "milli_i64" else ""),
                code="E_INITIAL_TYPE",
            )
        return value
    if storage == "bool":
        if not isinstance(value, bool):
            raise SimError(f"{entity}: initial {var} must be a boolean", code="E_INITIAL_TYPE")
        return value
    if storage == "string":
        if not isinstance(value, str):
            raise SimError(f"{entity}: initial {var} must be a string", code="E_INITIAL_TYPE")
        return value
    raise SimError(f"{entity}: unknown storage {storage!r}", code="E_CONTRACT_SHAPE")


# ------------------------------------------------------- declared semantics
#
# The kernel used to hardcode a door. It knew six verbs — open, close, lock,
# unlock, attack, repair — four state vars, and one integrator, and it answered
# E_NO_SEMANTICS to everything else. World IR meanwhile lets an author declare
# any state schema and any affordance, so the substrate could compile a world
# made of anything and simulate only worlds made of doors.
#
# Semantics are therefore DECLARED, in a closed vocabulary the kernel
# interprets. Not scripting: ADR 0018 rules out model-emitted executable code
# reaching production state, so there are no loops, no expressions, and no
# escape hatch — an affordance is guards plus an ordered list of effects drawn
# from a fixed set, and an integrator is one variable moving toward one control
# target at one rate. Everything an author can say is bounded and terminates.
#
# The door itself is now written in that vocabulary (DOOR_PROFILE below) and a
# v0.1 contract desugars into it. That is the point: there is ONE execution
# path, and the frozen conformance corpus — 7 replays pinned by golden state
# hashes — re-derives byte-identical results through the general interpreter.
# If the vocabulary could not express the door exactly, those hashes would move.

DOOR_PROFILE: dict = {
    "affordances": {
        "open": {
            "arg": "none",
            # A destroyed gate hangs open; a locked one absorbs the command.
            # Failing a guard is a no-op, never an error.
            "guards": [
                {"var": "destroyed", "equals": False},
                {"var": "locked", "equals": False},
            ],
            "effects": [
                {"op": "set_control", "control": "openness_target", "value": {"const": QUANTUM}}
            ],
        },
        "close": {
            "arg": "none",
            "guards": [{"var": "destroyed", "equals": False}],
            "effects": [{"op": "set_control", "control": "openness_target", "value": {"const": 0}}],
        },
        "lock": {
            "arg": "none",
            "effects": [{"op": "set", "var": "locked", "value": {"const": True}}],
        },
        "unlock": {
            "arg": "none",
            "effects": [{"op": "set", "var": "locked", "value": {"const": False}}],
        },
        "attack": {
            "arg": "count",
            "requires": ["health"],
            "effects": [
                {
                    "op": "add",
                    "var": "health",
                    "value": {"arg": True},
                    "sign": -1,
                    "clamp": {"min": {"const": 0}},
                },
                # Effects apply in order and read the state the previous one
                # left, so these see the health just written.
                {
                    "op": "set",
                    "var": "destroyed",
                    "value": {"const": True},
                    "when": [{"var": "health", "equals": 0}, {"var": "destroyed", "exists": True}],
                },
                {
                    "op": "set_control",
                    "control": "openness_target",
                    "value": {"const": QUANTUM},
                    "when": [{"var": "health", "equals": 0}, {"var": "destroyed", "exists": True}],
                },
            ],
        },
        "repair": {
            "arg": "count",
            "requires": ["health"],
            "effects": [
                {
                    "op": "add",
                    "var": "health",
                    "value": {"arg": True},
                    "sign": 1,
                    "clamp": {"max": {"param": "max_health", "default": 100}},
                },
                {
                    "op": "set",
                    "var": "destroyed",
                    "value": {"const": False},
                    "when": [
                        {"var": "health", "gt": {"const": 0}},
                        {"var": "destroyed", "exists": True},
                    ],
                },
            ],
        },
    },
    "integrators": [
        {
            "var": "openness",
            "toward": "openness_target",
            "rate": {"param": "open_rate_milli", "default": 250},
        }
    ],
}

EFFECT_OPS = ("set", "set_control", "add", "toggle")
ARG_KINDS = ("none", "count")
GUARD_TESTS = ("equals", "exists", "gt", "lt")
VALUE_SOURCES = ("const", "arg", "param", "var")
EFFECT_KEYS = {
    "set": ("op", "var", "value", "when"),
    "set_control": ("op", "control", "value", "when"),
    "add": ("op", "var", "value", "sign", "clamp", "when"),
    "toggle": ("op", "var", "when"),
}
# Every integer the kernel holds is an i64, because that is what the Rust twin
# holds. Python's integers are unbounded, so the bound is enforced here: at
# load for literals, parameters and initial values, and by saturation in the
# two places arithmetic happens (`add` and the integrators).
I64_MIN = -(2**63)
I64_MAX = 2**63 - 1
# Storage says how a value is held; the TYPE says what may be written to it and
# compared against it. The vocabulary is typed against the state schema at load
# so neither kernel ever has to decide what `true + 1` means.
STORAGE_TYPE = {"milli_i64": "int", "i64": "int", "bool": "bool", "string": "string"}


def _sat(value: int) -> int:
    """Saturate to i64 — the Rust kernel's saturating arithmetic, spelled out."""
    return I64_MIN if value < I64_MIN else I64_MAX if value > I64_MAX else value


def _is_int(value) -> bool:
    """A JSON integer in i64 range: not a bool (Python's bool IS an int), not a float."""
    return isinstance(value, int) and not isinstance(value, bool) and I64_MIN <= value <= I64_MAX


def _literal_type(value) -> str | None:
    """The type of a bare literal, or None when it is not one the kernel holds."""
    if isinstance(value, bool):
        return "bool"
    if _is_int(value):
        return "int"
    if isinstance(value, str):
        return "string"
    return None


def semantics(contract: dict) -> dict:
    """The contract's declared semantics, or the door profile it desugars to.

    A v0.1 contract lists affordance NAMES and relies on built-in meaning. It
    resolves to the subset of DOOR_PROFILE it actually declared, so a v0.1
    contract cannot reach a verb it never listed.
    """
    declared = contract.get("semantics")
    if declared is not None:
        return declared
    names = contract.get("affordances", [])
    return {
        "affordances": {
            verb: spec for verb, spec in DOOR_PROFILE["affordances"].items() if verb in names
        },
        "integrators": DOOR_PROFILE["integrators"],
    }


def _typed_zero(like) -> object:
    """What an absent state var compares as: the zero of the literal's type.

    Only the v0.1 door can reach this — a v0.2 contract declares every var it
    names and `initial_state` seeds them all — but the old kernel read absent
    vars through `state.get(var)` (falsy) and the Rust twin through
    `unwrap_or(false)` / `unwrap_or(0)`, and those only agree if the missing
    value takes its type from what it is compared against.
    """
    if isinstance(like, bool):
        return False
    if isinstance(like, int):
        return 0
    if isinstance(like, str):
        return ""
    return None


def _json_eq(a, b) -> bool:
    """Type-strict equality. Python says True == 1; serde_json does not, and a
    kernel that disagrees with its own twin is worse than one that is wrong.
    Load-time typing makes a mismatched comparison unreachable in v0.2; this is
    the belt under those braces."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _resolve(source, arg, state: dict, params: dict) -> object:
    """A declared value: a bare literal, or one of {const, arg, param, var}.

    Bare literals are allowed because `{"equals": false}` reads better than
    `{"equals": {"const": false}}` and an author will write the short form
    anyway. The Rust twin makes the same allowance on the same rule: a
    non-object is a literal. Shapes are validated at load, so nothing here
    has to guess.
    """
    if not isinstance(source, dict):
        return source
    if "const" in source:
        return source["const"]
    if "arg" in source:
        return 0 if arg is None else int(arg)
    if "param" in source:
        return int(params.get(source["param"], source.get("default", 0)))
    return state.get(source["var"], 0)


def _guard_holds(guard: dict, state: dict, params: dict) -> bool:
    var = guard["var"]
    if "exists" in guard:
        return (var in state) is guard["exists"]
    for test in ("equals", "gt", "lt"):
        if test not in guard:
            continue
        wanted = _resolve(guard[test], None, state, params)
        actual = state.get(var, _typed_zero(wanted))
        if test == "equals":
            return _json_eq(actual, wanted)
        if isinstance(actual, bool) or isinstance(wanted, bool):
            return False  # ordering on booleans is not a question with an answer
        return actual > wanted if test == "gt" else actual < wanted
    return True


def _guards_hold(guards, state: dict, params: dict) -> bool:
    return all(_guard_holds(g, state, params) for g in guards or [])


def _apply_effect(effect: dict, arg, state: dict, control: dict, params: dict) -> None:
    if not _guards_hold(effect.get("when"), state, params):
        return
    op = effect["op"]
    if op == "set":
        state[effect["var"]] = _resolve(effect["value"], arg, state, params)
    elif op == "set_control":
        control[effect["control"]] = _resolve(effect["value"], arg, state, params)
    elif op == "toggle":
        state[effect["var"]] = not bool(state.get(effect["var"], False))
    elif op == "add":
        var = effect["var"]
        delta = _sat(
            int(_resolve(effect["value"], arg, state, params)) * int(effect.get("sign", 1))
        )
        value = _sat(int(state.get(var, 0)) + delta)
        clamp = effect.get("clamp", {})
        if "min" in clamp:
            value = max(int(_resolve(clamp["min"], arg, state, params)), value)
        if "max" in clamp:
            value = min(int(_resolve(clamp["max"], arg, state, params)), value)
        state[var] = value


def apply_event(contract: dict, entity: str, world: dict, verb: str, arg, declared=None) -> None:
    """One event against one entity, checked against its contract.

    `declared` is `semantics(contract)`, resolved once per run by the caller;
    it is optional so the function stays usable on its own.
    """
    if verb not in contract.get("affordances", []):
        raise SimError(
            f"{entity}: event verb {verb!r} is not a declared affordance",
            code="E_UNDECLARED_AFFORDANCE",
        )
    if declared is None:
        declared = semantics(contract)
    spec = declared.get("affordances", {}).get(verb)
    if spec is None:
        raise SimError(
            f"{entity}: affordance {verb!r} is declared but has no semantics",
            code="E_NO_SEMANTICS",
        )

    kind = spec.get("arg", "none")
    if kind == "none" and arg is not None:
        raise SimError(f"{entity}: {verb} takes no argument", code="E_ARGUMENT_DOMAIN")
    if kind == "count":
        if isinstance(arg, bool) or not isinstance(arg, int):
            raise SimError(
                f"{entity}: {verb} needs a nonnegative integer amount", code="E_ARGUMENT_TYPE"
            )
        if arg < 0 or arg > MAX_EVENT_ARG:
            raise SimError(
                f"{entity}: {verb} amount {arg} outside 0..{MAX_EVENT_ARG}",
                code="E_ARGUMENT_RANGE",
            )

    state = world[entity]["state"]
    control = world[entity]["control"]
    params = contract.get("parameters", {})

    for required in spec.get("requires", []):
        if required not in state:
            raise SimError(
                f"{entity}: {verb} needs a {required!r} state var", code="E_NO_SEMANTICS"
            )
    if not _guards_hold(spec.get("guards"), state, params):
        return  # a guard that does not hold is a no-op, not a failure
    for effect in spec.get("effects", []):
        _apply_effect(effect, arg, state, control, params)


def step_entity(contract: dict, entity: str, world: dict, declared=None) -> None:
    """Fixed-step integration over integer milli-units, per declared integrator."""
    state = world[entity]["state"]
    control = world[entity]["control"]
    params = contract.get("parameters", {})
    if declared is None:
        declared = semantics(contract)
    for integrator in declared.get("integrators", []):
        var = integrator["var"]
        if var not in state:
            continue  # an entity without the variable simply has nothing to integrate
        current = int(state[var])
        target = int(control.get(integrator["toward"], current))
        rate = int(_resolve(integrator["rate"], None, state, params))
        if current < target:
            state[var] = min(target, _sat(current + rate))
        elif current > target:
            state[var] = max(target, _sat(current - rate))


def blocks_navigation(contract: dict, state: dict) -> bool:
    """The navigation contract, evaluated from state (milli-units). Every
    blocks_below rule is evaluated; any unsatisfied rule blocks."""
    nav = contract.get("parameters", {}).get("navigation", {})
    if nav.get("never_blocks_when_destroyed") and state.get("destroyed"):
        return False
    for rule in nav.get("blocks_below", []):
        if state.get(rule["var"], QUANTUM) < rule["threshold_milli"]:
            return True
    return False


def _validate_contract(entity: str, contract, source: str) -> dict:
    """Shape the contract before either kernel reads a value from it.

    Everything below is a place where the two kernels used to be able to
    disagree on malformed input — a float parameter Python truncates and Rust
    ignores, a storage type one kernel knows and the other does not. Each is
    now refused up front with a stable code, so parity holds for rejections
    too.
    """
    if not isinstance(contract, dict):
        raise SimError(
            f"{source}: entity {entity!r} needs an inline contract object",
            code="E_ENTITY_ENTRY",
        )
    if contract.get("sim_contract") not in SUPPORTED_CONTRACTS:
        raise SimError(
            f"{source}: entity {entity!r} contract has unsupported sim_contract "
            f"{contract.get('sim_contract')!r}",
            code="E_CONTRACT_VERSION",
        )
    where = f"{source}: entity {entity!r}"

    def reject(message: str) -> None:
        raise SimError(f"{where} {message}", code="E_CONTRACT_SHAPE")

    for field in ("state", "affordances", "parameters"):
        if field not in contract:
            reject(f"contract is missing {field}")

    state = contract["state"]
    if not isinstance(state, dict):
        reject("state must be an object")
    for var, spec in state.items():
        if not isinstance(spec, dict) or spec.get("storage") not in STORAGE_TYPE:
            reject(f"state var {var!r} needs a storage of {tuple(STORAGE_TYPE)}")

    affordances = contract["affordances"]
    if not isinstance(affordances, list) or not all(
        isinstance(verb, str) and IDENTIFIER.match(verb) for verb in affordances
    ):
        reject("affordances must be a list of snake_case identifiers")

    params = contract["parameters"]
    if not isinstance(params, dict):
        reject("parameters must be an object")
    for name, value in params.items():
        if name != "navigation" and not _is_int(value):
            reject(f"parameter {name!r} must be an i64 integer")
    nav = params.get("navigation", {})
    if not isinstance(nav, dict):
        reject("parameters.navigation must be an object")
    if not isinstance(nav.get("never_blocks_when_destroyed", False), bool):
        reject("parameters.navigation.never_blocks_when_destroyed must be a bool")
    rules = nav.get("blocks_below", [])
    if not isinstance(rules, list):
        reject("parameters.navigation.blocks_below must be a list")
    for rule in rules:
        if (
            not isinstance(rule, dict)
            or not isinstance(rule.get("var"), str)
            or not _is_int(rule.get("threshold_milli"))
        ):
            reject(
                "parameters.navigation.blocks_below entries need a var and an i64 threshold_milli"
            )

    # The version says where meaning comes from: 0.1 inherits the door, 0.2
    # declares its own. A contract that says one and does the other is a
    # contract two readers can interpret differently.
    if contract["sim_contract"] == "0.1" and "semantics" in contract:
        reject(
            "a 0.1 contract inherits the door and cannot carry semantics; declare sim_contract 0.2"
        )
    if contract["sim_contract"] == "0.2" and "semantics" not in contract:
        reject("a 0.2 contract must declare a semantics block")
    _validate_semantics(entity, contract, source)
    return contract


def _validate_semantics(entity: str, contract: dict, source: str) -> None:
    """Reject a malformed semantics block at load, not mid-replay.

    Everything the interpreter reads is checked here, so effect evaluation can
    assume well-formedness and stay branch-free enough to mirror in Rust
    exactly. A replay that fails halfway leaves a partial world and a hash
    nobody can reproduce, which is the one outcome a deterministic kernel must
    never produce — so this is fail-closed and up front.

    The block is TYPED against the state schema: an effect writes a value of
    its var's type, `add`/`gt`/`lt` and integrators work on integers, `toggle`
    on bools, and a control carries an integer because integrators read it.
    Unknown keys are refused everywhere — a `guard` where `guards` was meant
    would otherwise vanish silently, which is exactly the class of failure
    ADR 0020 records.
    """
    declared = contract.get("semantics")
    if declared is None:
        return
    where = f"{source}: entity {entity!r}"

    def reject(message: str) -> None:
        raise SimError(f"{where} {message}", code="E_SEMANTICS_SHAPE")

    def only_keys(obj: dict, allowed: tuple, what: str) -> None:
        unknown = sorted(set(obj) - set(allowed))
        if unknown:
            reject(f"{what} has unknown keys {unknown}")

    if not isinstance(declared, dict):
        reject("semantics must be an object")
    only_keys(declared, ("affordances", "integrators"), "semantics")
    affordances = declared.get("affordances", {})
    if not isinstance(affordances, dict):
        reject("semantics.affordances must be an object")
    integrators = declared.get("integrators", [])
    if not isinstance(integrators, list):
        reject("semantics.integrators must be a list")

    var_types = {var: STORAGE_TYPE[spec["storage"]] for var, spec in contract["state"].items()}
    int_params = {name for name in contract["parameters"] if name != "navigation"}
    listed = contract["affordances"]

    def check_value(value, what: str, expected: str, arg_kind: str) -> None:
        """A value source of the expected type: a bare literal or one of VALUE_SOURCES."""
        if not isinstance(value, dict):
            actual = _literal_type(value)
            if actual is None:
                reject(f"{what} must be a bool, i64 integer or string literal, or a value source")
        else:
            sources = [key for key in VALUE_SOURCES if key in value]
            if len(sources) != 1:
                reject(f"{what} needs exactly one of {VALUE_SOURCES}")
            kind = sources[0]
            only_keys(value, (kind, "default") if kind == "param" else (kind,), what)
            if kind == "const":
                actual = _literal_type(value["const"])
                if actual is None:
                    reject(f"{what}.const must be a bool, an i64 integer or a string")
            elif kind == "arg":
                if value["arg"] is not True:
                    reject(f"{what}.arg must be true")
                if arg_kind != "count":
                    reject(f"{what} reads the event argument, but the affordance takes none")
                actual = "int"
            elif kind == "param":
                name = value["param"]
                if not isinstance(name, str):
                    reject(f"{what}.param must name a parameter")
                if "default" in value and not _is_int(value["default"]):
                    reject(f"{what}.default must be an i64 integer")
                if name not in int_params and "default" not in value:
                    reject(f"{what} reads parameter {name!r}, which is not set and has no default")
                actual = "int"
            else:
                name = value["var"]
                if not isinstance(name, str) or name not in var_types:
                    reject(f"{what} reads undeclared state var {name!r}")
                actual = var_types[name]
        if actual != expected:
            reject(f"{what} must be {expected}, not {actual}")

    def check_guards(guards, what: str, arg_kind: str) -> None:
        if guards is None:
            return
        if not isinstance(guards, list):
            reject(f"{what} must be a list")
        for i, guard in enumerate(guards):
            label = f"{what}[{i}]"
            if not isinstance(guard, dict) or not isinstance(guard.get("var"), str):
                reject(f"{label} needs a var")
            var = guard["var"]
            if var not in var_types:
                reject(f"{label} tests undeclared state var {var!r}")
            tests = [test for test in GUARD_TESTS if test in guard]
            if len(tests) != 1:
                reject(f"{label} needs exactly one of {GUARD_TESTS}")
            test = tests[0]
            only_keys(guard, ("var", test), label)
            if test == "exists":
                if not isinstance(guard["exists"], bool):
                    reject(f"{label}.exists must be a bool")
            elif test == "equals":
                check_value(guard["equals"], f"{label}.equals", var_types[var], arg_kind)
            else:
                if var_types[var] != "int":
                    reject(f"{label}.{test} orders state var {var!r}, which is not an integer")
                check_value(guard[test], f"{label}.{test}", "int", arg_kind)

    def check_effect(effect, label: str, arg_kind: str) -> None:
        if not isinstance(effect, dict) or effect.get("op") not in EFFECT_OPS:
            reject(f"{label}.op must be one of {EFFECT_OPS}")
        op = effect["op"]
        only_keys(effect, EFFECT_KEYS[op], label)
        check_guards(effect.get("when"), f"{label}.when", arg_kind)
        if op == "set_control":
            control = effect.get("control")
            if not isinstance(control, str) or not IDENTIFIER.match(control):
                reject(f"{label} needs a snake_case control name")
            check_value(effect.get("value"), f"{label}.value", "int", arg_kind)
            return
        var = effect.get("var")
        if not isinstance(var, str) or var not in var_types:
            reject(f"{label} writes undeclared state var {var!r}")
        if op == "toggle":
            if var_types[var] != "bool":
                reject(f"{label} toggles state var {var!r}, which is not a bool")
            return
        if op == "set":
            check_value(effect.get("value"), f"{label}.value", var_types[var], arg_kind)
            return
        if var_types[var] != "int":
            reject(f"{label} adds to state var {var!r}, which is not an integer")
        check_value(effect.get("value"), f"{label}.value", "int", arg_kind)
        sign = effect.get("sign", 1)
        if not _is_int(sign) or sign not in (1, -1):
            reject(f"{label}.sign must be 1 or -1")
        clamp = effect.get("clamp", {})
        if not isinstance(clamp, dict):
            reject(f"{label}.clamp must be an object")
        only_keys(clamp, ("min", "max"), f"{label}.clamp")
        for bound in ("min", "max"):
            if bound in clamp:
                check_value(clamp[bound], f"{label}.clamp.{bound}", "int", arg_kind)

    for verb, spec in sorted(affordances.items()):
        what = f"semantics.affordances.{verb}"
        if verb not in listed:
            reject(f"{what} is not in the contract's affordance list")
        if not isinstance(spec, dict):
            reject(f"{what} must be an object")
        only_keys(spec, ("arg", "guards", "requires", "effects"), what)
        arg_kind = spec.get("arg", "none")
        if arg_kind not in ARG_KINDS:
            reject(f"{what}.arg must be one of {ARG_KINDS}")
        requires = spec.get("requires", [])
        if not isinstance(requires, list):
            reject(f"{what}.requires must be a list")
        for required in requires:
            if not isinstance(required, str) or required not in var_types:
                reject(f"{what} requires undeclared state var {required!r}")
        check_guards(spec.get("guards"), f"{what}.guards", arg_kind)
        effects = spec.get("effects", [])
        if not isinstance(effects, list):
            reject(f"{what}.effects must be a list")
        for i, effect in enumerate(effects):
            check_effect(effect, f"{what}.effects[{i}]", arg_kind)
    missing = sorted(set(listed) - set(affordances))
    if missing:
        reject(f"semantics.affordances must cover every listed affordance; missing {missing}")

    for i, integrator in enumerate(integrators):
        label = f"semantics.integrators[{i}]"
        if not isinstance(integrator, dict):
            reject(f"{label} must be an object")
        only_keys(integrator, ("var", "toward", "rate"), label)
        var = integrator.get("var")
        if not isinstance(var, str) or var not in var_types:
            reject(f"{label} integrates undeclared state var {var!r}")
        if var_types[var] != "int":
            reject(f"{label} integrates state var {var!r}, which is not an integer")
        toward = integrator.get("toward")
        if not isinstance(toward, str) or not IDENTIFIER.match(toward):
            reject(f"{label} needs a snake_case control name to move toward")
        check_value(integrator.get("rate"), f"{label}.rate", "int", "none")


def validate_contract(entity: str, contract, source: str = "<contract>") -> dict:
    """Public entry for tools that compile contracts (worldc): the same fail-closed
    checks a replay load performs, so a malformed contract is refused where it is
    produced rather than at the first replay that carries it."""
    return _validate_contract(entity, contract, source)


def load_replay(path: Path) -> dict:
    source = str(path)

    def reject(value):
        raise SimError(
            f"{source}: non-finite constant {value!r} is not valid JSON", code="E_NON_FINITE"
        )

    try:
        replay = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)
    except json.JSONDecodeError as exc:
        raise SimError(f"{source}: not valid JSON: {exc}", code="E_INVALID_JSON") from exc
    if not isinstance(replay, dict):
        raise SimError(f"{source}: a replay is a JSON object", code="E_REPLAY_SHAPE")
    unknown = sorted(set(replay) - REPLAY_KEYS)
    if unknown:
        raise SimError(f"{source}: unknown replay fields {unknown}", code="E_UNKNOWN_FIELD")
    if replay.get("sim_replay") != REPLAY_VERSION:
        raise SimError(
            f"{source}: unsupported sim_replay {replay.get('sim_replay')!r}",
            code="E_REPLAY_VERSION",
        )
    ticks = replay.get("ticks")
    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 0 or ticks > MAX_TICKS:
        raise SimError(f"{source}: ticks must be an integer 0..{MAX_TICKS}", code="E_TICKS_RANGE")
    seed = replay.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SimError(f"{source}: seed must be an integer", code="E_SEED_TYPE")

    entities = replay.get("entities")
    if not isinstance(entities, dict) or not entities:
        raise SimError(f"{source}: entities must be a non-empty object", code="E_ENTITIES_SHAPE")
    for name, entry in entities.items():
        if not IDENTIFIER.match(name):
            raise SimError(f"{source}: bad entity name {name!r}", code="E_ENTITY_ENTRY")
        if not isinstance(entry, dict):
            raise SimError(f"{source}: entity {name!r} needs an object", code="E_ENTITY_ENTRY")
        _validate_contract(name, entry.get("contract"), source)
        pinned = entry.get("contract_sha256")
        if not isinstance(pinned, str) or not HASH_RE.match(pinned):
            raise SimError(
                f"{source}: entity {name!r} must pin its contract by contract_sha256 "
                "(canonical hash, lowercase hex)",
                code="E_ENTITY_ENTRY",
            )

    initial = replay.get("initial", {})
    if not isinstance(initial, dict):
        raise SimError(f"{source}: initial must be an object", code="E_INITIAL_SHAPE")
    for name in initial:
        if name not in entities:
            raise SimError(
                f"{source}: initial references unknown entity {name!r}", code="E_UNKNOWN_ENTITY"
            )

    events = replay.get("events", [])
    if not isinstance(events, list):
        raise SimError(f"{source}: events must be a list", code="E_EVENTS_SHAPE")
    for i, event in enumerate(events):
        if not isinstance(event, list) or len(event) != 4:
            raise SimError(
                f"{source}: event {i} must be [tick, entity, verb, arg]", code="E_EVENT_SHAPE"
            )
        tick, entity, verb, _arg = event
        if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0 or tick > ticks:
            raise SimError(
                f"{source}: event {i} tick {tick!r} outside 0..{ticks}",
                code="E_EVENT_TICK_RANGE",
            )
        if not isinstance(entity, str) or entity not in entities:
            raise SimError(
                f"{source}: event {i} targets unknown entity {entity!r}",
                code="E_UNKNOWN_ENTITY",
            )
        if not isinstance(verb, str) or not IDENTIFIER.match(verb):
            raise SimError(f"{source}: event {i} has a bad verb {verb!r}", code="E_BAD_VERB")
    return replay


def kernel_fingerprint() -> dict:
    return {"kernel_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def run_replay(replay_path, contracts=None) -> dict:
    """Execute a replay deterministically; return the final state and hashes.

    Replays are self-contained (contracts inline). `contracts` exists for
    tests that inject contracts directly.
    """
    replay_path = Path(replay_path).resolve()
    replay = load_replay(replay_path)

    if contracts is None:
        contracts = {}
        for name, entry in replay["entities"].items():
            contract = entry["contract"]
            actual = hashlib.sha256(canonical(contract)).hexdigest()
            if actual != entry["contract_sha256"]:
                raise SimError(
                    f"{name}: contract hash mismatch — the replay pins "
                    f"{entry['contract_sha256'][:12]}… but the inline contract hashes "
                    f"{actual[:12]}…",
                    code="E_CONTRACT_HASH",
                )
            contracts[name] = contract

    world: dict[str, dict] = {}
    for name, contract in contracts.items():
        state = initial_state(contract)
        for var, value in replay.get("initial", {}).get(name, {}).items():
            state[var] = _coerce_initial(name, contract, var, value)
        world[name] = {"state": state, "control": {}}

    # Resolved once per run: the declared block, or the door profile a v0.1
    # contract desugars to. Both kernels do this in the same place.
    declared = {name: semantics(contract) for name, contract in contracts.items()}

    events = replay.get("events", [])
    order = sorted(range(len(events)), key=lambda i: (events[i][0], i))
    by_tick: dict[int, list[int]] = {}
    for i in order:
        by_tick.setdefault(events[i][0], []).append(i)

    ticks = replay["ticks"]
    hash_log = []
    snapshots = []
    for tick in range(ticks + 1):
        for i in by_tick.get(tick, []):
            _, entity, verb, arg = events[i]
            apply_event(contracts[entity], entity, world, verb, arg, declared[entity])
        for name, contract in contracts.items():
            step_entity(contract, name, world, declared[name])
        hash_log.append(state_hash(world))
        snapshots.append(copy.deepcopy(world))

    entity_hashes = {
        name: hashlib.sha256(canonical(contract)).hexdigest()
        for name, contract in contracts.items()
    }
    return {
        "ticks": ticks,
        "entities": sorted(contracts),
        "final_state": world,
        "state_hash": state_hash(world),
        "hash_log": hash_log,
        "snapshots": snapshots,
        "navigation": {
            name: blocks_navigation(contract, world[name]["state"])
            for name, contract in contracts.items()
        },
        "fingerprints": {
            "kernel": kernel_fingerprint(),
            "entities": entity_hashes,
            "replay_sha256": hashlib.sha256(canonical(replay)).hexdigest(),
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sim", description=__doc__.split("\n")[3])
    sub = parser.add_subparsers(dest="command", required=True)
    replay = sub.add_parser("replay", help="Run a deterministic replay")
    replay.add_argument("file")
    replay.add_argument(
        "--update-golden", action="store_true", help="Write the resulting hash back into the file"
    )
    replay.add_argument(
        "--full",
        action="store_true",
        help="Print final_state, hash_log, navigation, state_hash (for parity harnesses)",
    )
    replay.add_argument(
        "--snapshots",
        action="store_true",
        help="Print the per-tick world snapshots a runtime adapter may observe",
    )
    args = parser.parse_args(argv)

    try:
        result = run_replay(args.file)
    except SimError as exc:
        print(json.dumps({"error": str(exc), "code": exc.code}), file=sys.stderr)
        return 1

    if args.snapshots:
        print(json.dumps({"snapshots": result["snapshots"], "state_hash": result["state_hash"]}))
        return 0

    if args.full:
        print(
            json.dumps(
                {
                    "final_state": result["final_state"],
                    "state_hash": result["state_hash"],
                    "hash_log": result["hash_log"],
                    "navigation": result["navigation"],
                }
            )
        )
        return 0

    out = {
        "state_hash": result["state_hash"],
        "navigation": result["navigation"],
        "fingerprints": result["fingerprints"],
    }
    expected = json.loads(Path(args.file).read_text()).get("expect_state_hash")
    if args.update_golden:
        path = Path(args.file)
        doc = json.loads(path.read_text())
        doc["expect_state_hash"] = result["state_hash"]
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        out["golden_updated"] = True
    elif expected and expected != result["state_hash"]:
        out["error"] = f"golden mismatch: expected {expected}, got {result['state_hash']}"
        print(json.dumps(out, indent=2))
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
