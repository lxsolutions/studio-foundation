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
import hashlib
import json
import re
import sys
from pathlib import Path

REPLAY_VERSION = "0.1"
QUANTUM = 1000  # float state vars are integer milli-units: 1.0 == 1000
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
NULL_ARG_VERBS = {"open", "close", "lock", "unlock"}
AMOUNT_VERBS = {"attack", "repair"}


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
        if isinstance(value, bool) or not isinstance(value, int):
            raise SimError(
                f"{entity}: initial {var} must be an integer"
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


def apply_event(contract: dict, entity: str, world: dict, verb: str, arg) -> None:
    """One event against one entity, checked against its contract."""
    if verb not in contract.get("affordances", []):
        raise SimError(
            f"{entity}: event verb {verb!r} is not a declared affordance",
            code="E_UNDECLARED_AFFORDANCE",
        )
    if verb in NULL_ARG_VERBS and arg is not None:
        raise SimError(f"{entity}: {verb} takes no argument", code="E_ARGUMENT_DOMAIN")
    if verb in AMOUNT_VERBS:
        if isinstance(arg, bool) or not isinstance(arg, int):
            raise SimError(
                f"{entity}: {verb} needs a nonnegative integer amount", code="E_ARGUMENT_TYPE"
            )
        if arg < 0 or arg > MAX_EVENT_ARG:
            raise SimError(
                f"{entity}: {verb} amount out of range 0..{MAX_EVENT_ARG}",
                code="E_ARGUMENT_RANGE",
            )

    state = world[entity]["state"]
    control = world[entity]["control"]
    params = contract.get("parameters", {})
    max_health = int(params.get("max_health", 100))

    if verb == "open":
        if state.get("destroyed"):
            return  # a destroyed gate hangs open; nothing to drive
        if state.get("locked"):
            return  # a locked gate absorbs the command
        control["openness_target"] = QUANTUM
    elif verb == "close":
        if state.get("destroyed"):
            return
        control["openness_target"] = 0
    elif verb == "lock":
        state["locked"] = True
    elif verb == "unlock":
        state["locked"] = False
    elif verb == "attack":
        if "health" not in state:
            raise SimError(f"{entity}: attack needs a 'health' state var", code="E_NO_SEMANTICS")
        state["health"] = max(0, int(state["health"]) - arg)
        if state["health"] == 0 and "destroyed" in state:
            state["destroyed"] = True
            control["openness_target"] = QUANTUM  # broken gates hang open
    elif verb == "repair":
        if "health" not in state:
            raise SimError(f"{entity}: repair needs a 'health' state var", code="E_NO_SEMANTICS")
        state["health"] = min(max_health, int(state["health"]) + arg)
        if state["health"] > 0 and "destroyed" in state:
            state["destroyed"] = False
    else:
        raise SimError(
            f"{entity}: no semantics for affordance {verb!r} in kernel v0.1",
            code="E_NO_SEMANTICS",
        )


def step_entity(contract: dict, entity: str, world: dict) -> None:
    """Fixed-step integration over integer milli-units."""
    state = world[entity]["state"]
    control = world[entity]["control"]
    if "openness" not in state:
        return
    target = control.get("openness_target", state["openness"])
    rate = int(contract.get("parameters", {}).get("open_rate_milli", 250))
    if state["openness"] < target:
        state["openness"] = min(target, state["openness"] + rate)
    elif state["openness"] > target:
        state["openness"] = max(target, state["openness"] - rate)


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
    if not isinstance(contract, dict):
        raise SimError(
            f"{source}: entity {entity!r} needs an inline contract object",
            code="E_ENTITY_ENTRY",
        )
    if contract.get("sim_contract") != "0.1":
        raise SimError(
            f"{source}: entity {entity!r} contract has unsupported sim_contract "
            f"{contract.get('sim_contract')!r}",
            code="E_CONTRACT_VERSION",
        )
    for field in ("state", "affordances", "parameters"):
        if field not in contract:
            raise SimError(
                f"{source}: entity {entity!r} contract is missing {field}",
                code="E_CONTRACT_SHAPE",
            )
    return contract


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

    events = replay.get("events", [])
    order = sorted(range(len(events)), key=lambda i: (events[i][0], i))
    by_tick: dict[int, list[int]] = {}
    for i in order:
        by_tick.setdefault(events[i][0], []).append(i)

    ticks = replay["ticks"]
    hash_log = []
    for tick in range(ticks + 1):
        for i in by_tick.get(tick, []):
            _, entity, verb, arg = events[i]
            apply_event(contracts[entity], entity, world, verb, arg)
        for name, contract in contracts.items():
            step_entity(contract, name, world)
        hash_log.append(state_hash(world))

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
    args = parser.parse_args(argv)

    try:
        result = run_replay(args.file)
    except SimError as exc:
        print(json.dumps({"error": str(exc), "code": exc.code}), file=sys.stderr)
        return 1

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
