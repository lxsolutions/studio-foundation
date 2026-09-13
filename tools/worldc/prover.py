#!/usr/bin/env python3
"""prover — bounded model checking over World IR worlds (ADR 0022).

A world proof used to say one thing: *this scripted replay produced this
hash*. That is reproducibility, not design. A designer's questions are about
the possibility space — can the main gate be opened at all, can a broken gate
ever be shut again, is there a state from which the level can no longer be
finished — and today those are answered by playtesting, which is sampling.

The declared-semantics kernel (ADR 0021) makes them answerable exactly. An
entity is a small integer state machine in a closed vocabulary: no loops, no
expressions, bounded effects. Its reachable state space is finite and small,
so the prover can walk it. It does so with the canonical kernel itself —
`apply_event` and `step_entity` from tools/sim/kernel.py — never a model of
the kernel, so what it explores is exactly what the game will run.

Three property kinds, all over the same explored graph:

    reachable  ∃ a schedule from the initial state reaching a state where
               `when` holds                                  → witness replay
    never      no reachable state satisfies `when`           → counterexample
    live       from every reachable state, a `when` state is still reachable
               (no soft-lock)                                → path to the lock

Every verdict is bounded and says so: the search is over one event per tick,
the argument amounts the semantics themselves name (plus the maximum), a tick
horizon and a state budget. A witness is a plain sim replay; the prover runs
it back through the kernel before it reports it, so a witness is proof by
execution rather than by the prover's say-so. `inconclusive` (budget hit) is
a third verdict, never rounded to a pass.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))

import kernel  # noqa: E402

KINDS = ("reachable", "never", "live")
TESTS = ("equals", "gt", "lt", "exists")
DEFAULT_HORIZON = 32
DEFAULT_BUDGET = 100_000
MAX_HORIZON = 1_000
MAX_BUDGET = 5_000_000
STORAGE_TYPE = kernel.STORAGE_TYPE
SLUG = re.compile(r"[^a-z0-9]+")


class ProofError(Exception):
    """A malformed properties block. Raised before any exploration."""


# ------------------------------------------------------------- validation


def validate_properties(props, contracts: dict, source: str = "<world>") -> dict:
    """Shape and type the properties block against the compiled contracts.

    Clauses are typed the way the kernel types guards: `equals` compares like
    with like, `gt`/`lt` need an integer var, `exists` is a bool. A clause may
    read a state var or a control (drive targets are part of the hashed world
    and often the thing a designer means by "was told to open").
    """
    where = f"{source}: properties"

    def reject(message: str) -> None:
        raise ProofError(f"{where} {message}")

    if not isinstance(props, dict):
        reject("must be an object")
    unknown = sorted(set(props) - {"horizon", "budget", "amounts", "assert"})
    if unknown:
        reject(f"has unknown keys {unknown}")
    horizon = props.get("horizon", DEFAULT_HORIZON)
    if not kernel._is_int(horizon) or not 1 <= horizon <= MAX_HORIZON:
        reject(f"horizon must be an integer 1..{MAX_HORIZON}")
    budget = props.get("budget", DEFAULT_BUDGET)
    if not kernel._is_int(budget) or not 1 <= budget <= MAX_BUDGET:
        reject(f"budget must be an integer 1..{MAX_BUDGET}")
    amounts = props.get("amounts", [])
    if not isinstance(amounts, list) or not all(
        kernel._is_int(a) and 0 <= a <= kernel.MAX_EVENT_ARG for a in amounts
    ):
        reject(f"amounts must be a list of integers 0..{kernel.MAX_EVENT_ARG}")
    claims = props.get("assert")
    if not isinstance(claims, list) or not claims:
        reject("assert must be a non-empty list of properties")

    names = set()
    for i, claim in enumerate(claims):
        label = f"assert[{i}]"
        if not isinstance(claim, dict):
            reject(f"{label} must be an object")
        unknown = sorted(set(claim) - {"name", "kind", "when"})
        if unknown:
            reject(f"{label} has unknown keys {unknown}")
        name = claim.get("name")
        if not isinstance(name, str) or not name.strip():
            reject(f"{label} needs a name")
        if name in names:
            reject(f"{label} repeats the name {name!r}")
        names.add(name)
        if claim.get("kind") not in KINDS:
            reject(f"{label}.kind must be one of {KINDS}")
        when = claim.get("when")
        if not isinstance(when, list) or not when:
            reject(f"{label}.when must be a non-empty list of clauses")
        for j, clause in enumerate(when):
            _validate_clause(clause, f"{label}.when[{j}]", contracts, reject)
    return {"horizon": horizon, "budget": budget, "amounts": sorted(set(amounts)), "assert": claims}


def _validate_clause(clause, label: str, contracts: dict, reject) -> None:
    if not isinstance(clause, dict):
        reject(f"{label} must be an object")
    entity = clause.get("entity")
    if entity not in contracts:
        reject(f"{label} names unknown entity {entity!r}")
    tests = [t for t in TESTS if t in clause]
    if len(tests) != 1:
        reject(f"{label} needs exactly one of {TESTS}")
    test = tests[0]
    if "var" in clause and "control" in clause:
        reject(f"{label} reads either a var or a control, not both")
    if "var" in clause:
        allowed = {"entity", "var", test}
        var = clause["var"]
        state = contracts[entity].get("state", {})
        if not isinstance(var, str) or var not in state:
            reject(f"{label} reads undeclared state var {var!r} of {entity}")
        var_type = STORAGE_TYPE[state[var]["storage"]]
    elif "control" in clause:
        allowed = {"entity", "control", test}
        if not isinstance(clause["control"], str) or not kernel.IDENTIFIER.match(clause["control"]):
            reject(f"{label} control must be a snake_case name")
        var_type = "int"  # controls carry integers because integrators read them
    else:
        reject(f"{label} needs a var or a control")
    unknown = sorted(set(clause) - allowed)
    if unknown:
        reject(f"{label} has unknown keys {unknown}")
    literal = clause[test]
    if test == "exists":
        if not isinstance(literal, bool):
            reject(f"{label}.exists must be a bool")
        return
    literal_type = kernel._literal_type(literal)
    if literal_type is None:
        reject(f"{label}.{test} must be a bool, i64 integer or string literal")
    if test in ("gt", "lt") and (var_type != "int" or literal_type != "int"):
        reject(f"{label}.{test} orders integers only")
    if test == "equals" and literal_type != var_type:
        reject(f"{label}.equals compares a {var_type} with a {literal_type}")


# ------------------------------------------------------------ exploration


def _holds(when: list, world: dict) -> bool:
    """A conjunction of clauses against one world, with the kernel's own guard
    semantics (type-strict equality, typed zero for an absent name)."""
    for clause in when:
        entry = world[clause["entity"]]
        if "control" in clause:
            guard = {"var": clause["control"], **{k: v for k, v in clause.items() if k in TESTS}}
            table = entry["control"]
        else:
            guard = {k: v for k, v in clause.items() if k != "entity"}
            table = entry["state"]
        if not kernel._guard_holds(guard, table, {}):
            return False
    return True


def _amount_ints(spec: dict, params: dict) -> set:
    """The integers a count verb's semantics compare or clamp against, and the
    parameters it reads: the magnitudes at which its behaviour changes. Not
    `sign`, not `set` targets, not integrator rates — those are not amounts."""
    found: set = set()

    def source(node) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, int):
            found.add(node)
        elif isinstance(node, dict):
            if "const" in node and kernel._is_int(node["const"]):
                found.add(node["const"])
            if "param" in node and isinstance(node["param"], str):
                value = params.get(node["param"], node.get("default"))
                if kernel._is_int(value):
                    found.add(value)

    def guards(items) -> None:
        for guard in items or []:
            for test in ("equals", "gt", "lt"):
                if test in guard:
                    source(guard[test])

    guards(spec.get("guards"))
    for effect in spec.get("effects", []):
        guards(effect.get("when"))
        for bound in ("min", "max"):
            if bound in effect.get("clamp", {}):
                source(effect["clamp"][bound])
    return found


def candidate_amounts(contract: dict, spec: dict, extra: list) -> list:
    """The amounts tried for a `count` verb: what its own semantics compare or
    clamp against, the world's extra amounts, and the maximum. Bounded on
    purpose and reported with every verdict — the prover never claims to have
    tried every integer, and a designer widens the set with `amounts`."""
    params = {k: v for k, v in contract.get("parameters", {}).items() if k != "navigation"}
    found = _amount_ints(spec, params)
    found.update(extra)
    found.add(kernel.MAX_EVENT_ARG)
    return sorted(a for a in found if 0 < a <= kernel.MAX_EVENT_ARG)


def _moves(contracts: dict, declared: dict, extra_amounts: list) -> list:
    """Every (entity, verb, arg) the prover may schedule, plus a bare wait."""
    moves: list = [None]
    amounts: dict = {}
    for entity in sorted(contracts):
        contract = contracts[entity]
        for verb in contract.get("affordances", []):
            spec = declared[entity].get("affordances", {}).get(verb)
            if spec is None:
                continue  # a v0.1 verb the door profile does not define
            if spec.get("arg", "none") == "count":
                tried = candidate_amounts(contract, spec, extra_amounts)
                amounts[f"{entity}.{verb}"] = tried
                moves.extend((entity, verb, a) for a in tried)
            else:
                moves.append((entity, verb, None))
    return moves, amounts


def _step(world: dict, contracts: dict, declared: dict, move) -> dict | None:
    """One tick: at most one event, then every entity integrates — exactly the
    kernel's own order, so a path here is a replay there."""
    if move is not None:
        entity, verb, arg = move
        try:
            kernel.apply_event(contracts[entity], entity, world, verb, arg, declared[entity])
        except kernel.SimError:
            return None  # a verb this contract cannot take (e.g. a v0.1 `requires`)
    for name, contract in contracts.items():
        kernel.step_entity(contract, name, world, declared[name])
    return world


def initial_world(contracts: dict, initial: dict) -> dict:
    world = {}
    for name, contract in contracts.items():
        state = kernel.initial_state(contract)
        for var, value in initial.get(name, {}).items():
            state[var] = kernel._coerce_initial(name, contract, var, value)
        world[name] = {"state": state, "control": {}}
    return world


class Graph:
    """The explored reachable graph. Nodes are canonical world bytes; edges
    carry the move that produced them. `open` nodes sit at the horizon with
    unexplored successors, which is what keeps `live` honest."""

    def __init__(self):
        self.keys: list[bytes] = []
        self.index: dict[bytes, int] = {}
        self.parent: list[int] = []
        self.move: list = []
        self.depth: list[int] = []
        self.successors: list[list[int]] = []
        self.open: set[int] = set()
        self.exhaustive = False
        self.budget_hit = False

    def add(self, key: bytes, parent: int, move, depth: int) -> int:
        node = len(self.keys)
        self.keys.append(key)
        self.index[key] = node
        self.parent.append(parent)
        self.move.append(move)
        self.depth.append(depth)
        self.successors.append([])
        return node

    def world(self, node: int) -> dict:
        return json.loads(self.keys[node])

    def path(self, node: int) -> list:
        """The moves from the root to `node`, as replay events [tick, e, v, a]."""
        moves = []
        while node != 0:
            moves.append(self.move[node])
            node = self.parent[node]
        moves.reverse()
        return [[tick, *move] for tick, move in enumerate(moves) if move is not None]


def explore(contracts: dict, initial: dict, horizon: int, budget: int, extra_amounts: list):
    """Breadth-first over one-event-per-tick schedules, deduplicated by the
    kernel's canonical world. BFS order means the first node satisfying a
    predicate is a shortest witness."""
    declared = {name: kernel.semantics(c) for name, c in contracts.items()}
    moves, amounts = _moves(contracts, declared, extra_amounts)
    graph = Graph()
    root = initial_world(contracts, initial)
    graph.add(kernel.canonical(root), -1, None, 0)
    queue = deque([0])
    while queue:
        node = queue.popleft()
        depth = graph.depth[node]
        if depth >= horizon:
            graph.open.add(node)
            continue
        for move in moves:
            world = _step(graph.world(node), contracts, declared, move)
            if world is None:
                continue
            key = kernel.canonical(world)
            child = graph.index.get(key)
            if child is None:
                if len(graph.keys) >= budget:
                    graph.budget_hit = True
                    graph.open.add(node)
                    queue.clear()
                    break
                child = graph.add(key, node, move, depth + 1)
                queue.append(child)
            graph.successors[node].append(child)
    graph.exhaustive = not graph.open and not graph.budget_hit
    return graph, amounts


def _backward_closure(graph: Graph, seeds: set) -> set:
    predecessors: dict[int, list[int]] = {}
    for node, children in enumerate(graph.successors):
        for child in children:
            predecessors.setdefault(child, []).append(node)
    seen = set(seeds)
    stack = list(seeds)
    while stack:
        node = stack.pop()
        for pred in predecessors.get(node, []):
            if pred not in seen:
                seen.add(pred)
                stack.append(pred)
    return seen


def _bound(graph: Graph) -> str:
    if graph.budget_hit:
        return "budget"
    return "exhaustive" if graph.exhaustive else "horizon"


def check(claim: dict, graph: Graph) -> dict:
    """One property against the explored graph."""
    when, kind = claim["when"], claim["kind"]
    hits = [node for node in range(len(graph.keys)) if _holds(when, graph.world(node))]
    bound = _bound(graph)
    verdict = {"name": claim["name"], "kind": kind, "bound": bound, "witness": None}

    if kind == "reachable":
        if hits:
            node = hits[0]  # BFS order: shortest
            verdict.update(status="holds", detail=f"reached in {graph.depth[node]} tick(s)")
            verdict["witness"] = _witness(graph, node)
        elif bound == "budget":
            verdict.update(
                status="inconclusive", detail="state budget exhausted before a witness was found"
            )
        else:
            verdict.update(
                status="violated",
                detail=f"no schedule reaches it ({bound}: {len(graph.keys)} states explored)",
            )
    elif kind == "never":
        if hits:
            node = hits[0]
            verdict.update(status="violated", detail=f"reached in {graph.depth[node]} tick(s)")
            verdict["witness"] = _witness(graph, node)
        elif bound == "budget":
            verdict.update(
                status="inconclusive", detail="state budget exhausted with no violation found"
            )
        else:
            verdict.update(
                status="holds",
                detail=f"no reachable state satisfies it ({bound}: {len(graph.keys)} states)",
            )
    else:  # live: from every reachable state a goal state is still reachable
        goal = set(hits)
        can_reach_goal = _backward_closure(graph, goal)
        # A node from which neither a goal nor an unexplored (open) node is
        # reachable has a fully explored, goal-free future: a definite lock.
        maybe = _backward_closure(graph, goal | graph.open)
        locks = [node for node in range(len(graph.keys)) if node not in maybe]
        unknown = [
            node for node in range(len(graph.keys)) if node in maybe and node not in can_reach_goal
        ]
        if locks:
            node = min(locks, key=lambda n: graph.depth[n])
            verdict.update(
                status="violated",
                detail=f"a state {graph.depth[node]} tick(s) in has no schedule back to the goal (soft-lock)",
            )
            verdict["witness"] = _witness(graph, node)
        elif bound == "budget":
            verdict.update(
                status="inconclusive",
                detail="state budget exhausted before every future was explored",
            )
        elif not goal:
            verdict.update(
                status="violated", detail="the goal is not reachable at all, so nothing is live"
            )
        else:
            note = f" ({len(unknown)} state(s) at the horizon undecided)" if unknown else ""
            verdict.update(
                status="holds", detail=f"every explored state keeps the goal reachable{note}"
            )
    return verdict


def _witness(graph: Graph, node: int) -> dict:
    events = graph.path(node)
    depth = graph.depth[node]
    world = graph.world(node)
    return {
        "events": events,
        # A replay of N ticks runs ticks 0..N inclusive; a node `depth` ticks in
        # is the world after ticks 0..depth-1, so the replay says depth-1.
        "ticks": depth - 1 if depth > 0 else None,
        "state_hash": kernel.state_hash(world),
        "final_state": world,
    }


def witness_replay(witness: dict, contracts: dict, initial: dict, comment: str) -> dict | None:
    """A self-contained sim replay any kernel can run to the witness state."""
    if witness["ticks"] is None:
        return None  # the property holds (or fails) in the initial state itself
    return {
        "sim_replay": "0.1",
        "seed": 0,
        "ticks": witness["ticks"],
        "comment": comment,
        "entities": {
            name: {
                "contract": contract,
                "contract_sha256": hashlib.sha256(kernel.canonical(contract)).hexdigest(),
            }
            for name, contract in contracts.items()
        },
        "initial": initial,
        "events": witness["events"],
        "expect_state_hash": witness["state_hash"],
    }


def slug(name: str) -> str:
    return SLUG.sub("-", name.lower()).strip("-")[:48]


def prove(
    props: dict,
    contracts: dict,
    initial: dict,
    source: str = "<world>",
    witness_dir: Path | None = None,
) -> dict:
    """Validate, explore once, check every property, and re-run every witness
    through the kernel. Returns the results block that goes into a world proof."""
    props = validate_properties(props, contracts, source)
    graph, amounts = explore(
        contracts, initial, props["horizon"], props["budget"], props["amounts"]
    )
    results = []
    for i, claim in enumerate(props["assert"]):
        verdict = check(claim, graph)
        witness = verdict.pop("witness")
        if witness is not None:
            replay = witness_replay(
                witness,
                contracts,
                initial,
                f"witness for {claim['kind']} property: {claim['name']}",
            )
            record = {
                "events": witness["events"],
                "ticks": witness["ticks"],
                "state_hash": witness["state_hash"],
                "replay": None,
                "verified": None,
            }
            if replay is not None and witness_dir is not None:
                path = witness_dir / f"witness-{i:02d}-{slug(claim['name'])}.json"
                path.write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
                # Proof by execution: the kernel must land on the same hash.
                result = kernel.run_replay(path)
                record["replay"] = path.name
                record["replay_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                record["verified"] = result["state_hash"] == witness["state_hash"]
                if not record["verified"]:
                    verdict["status"] = "inconclusive"
                    verdict["detail"] += " — but the kernel did not reproduce the witness"
            elif replay is None:
                record["verified"] = _holds(claim["when"], initial_world(contracts, initial)) == (
                    claim["kind"] != "live"
                )
            verdict["witness"] = record
        else:
            verdict["witness"] = None
        results.append(verdict)
    return {
        "explored": {
            "states": len(graph.keys),
            "max_depth": max(graph.depth) if graph.depth else 0,
            "horizon": props["horizon"],
            "budget": props["budget"],
            "bound": _bound(graph),
            "amounts": amounts,
            "one_event_per_tick": True,
        },
        "results": results,
    }


def render(report: dict) -> str:
    """A designer-facing table."""
    lines = []
    ex = report["explored"]
    lines.append(
        f"explored {ex['states']} states to depth {ex['max_depth']} "
        f"(horizon {ex['horizon']}, budget {ex['budget']}, bound: {ex['bound']})"
    )
    for verb, tried in ex["amounts"].items():
        lines.append(f"  amounts tried for {verb}: {tried}")
    for r in report["results"]:
        mark = {"holds": "PASS", "violated": "FAIL", "inconclusive": "????"}[r["status"]]
        lines.append(f"{mark}  {r['kind']:<9} {r['name']} — {r['detail']}")
        w = r.get("witness")
        if w and w["events"]:
            lines.append(f"        witness: {json.dumps(w['events'])}")
            if w.get("replay"):
                lines.append(f"        replay:  {w['replay']} (kernel reproduced: {w['verified']})")
    return "\n".join(lines)
