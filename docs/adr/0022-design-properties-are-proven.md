# ADR 0022: Design properties are proven, not playtested — bounded model checking over World IR

- Status: Accepted
- Date: 2026-09-13
- Extends: [ADR 0018](0018-brief-to-battle-world-compiler.md) ("every world
  ships with proof" — this is what the proof can now be *about*),
  [ADR 0021](0021-declared-affordance-semantics.md) (the closed vocabulary is
  what makes a world's state space finite and walkable)
- Relates: [ADR 0020](0020-engine-neutral-presentation.md) (a witness is a
  replay, so it drives the same renderers the conformance suite holds to it)

## Context

A world proof said one thing: *this scripted replay produced this hash*. That
is reproducibility. It is not design. The questions a designer actually has
are about the possibility space, not one path through it:

- Can the main gate be opened at all, from where the player starts?
- Can a broken gate ever be shut again?
- Is there any state the player can reach from which the level can no longer
  be finished?

Today those are answered by playtesting, which is sampling: a tester walks
some paths and reports what they saw. The soft-lock that ships is the one
nobody walked. Studios put people on it because there was no alternative for
a game whose rules live in engine scripts, where the state space is whatever
the scripts happen to do.

[ADR 0021](0021-declared-affordance-semantics.md) changed that premise here.
An entity is a small integer state machine in a closed vocabulary — guards,
ordered effects, one linear integrator per variable, no loops, no expressions,
bounded arithmetic. Its reachable state space is finite and, for the entities
World IR describes, small: the fortress with two gates has 576 reachable
states; the depot with a lift and a lever, 538 within 24 ticks. A machine can
walk that in a fraction of a second. So the question is no longer "did anyone
try it" but "is it so".

## Decision

**A world declares design properties, and `worldc` proves them over the
kernel's own state space. A world proof carries the verdicts; a verdict
carries a witness; a witness is a replay the kernel has already reproduced.**

```json
"properties": {
  "horizon": 24,
  "assert": [
    {"name": "the main gate can be opened fully", "kind": "reachable",
     "when": [{"entity": "gate_main", "var": "openness", "equals": 1000}]},
    {"name": "a broken gate is never told to shut", "kind": "never",
     "when": [{"entity": "gate_side", "var": "destroyed", "equals": true},
              {"entity": "gate_side", "control": "openness_target", "equals": 0}]},
    {"name": "the main gate can always still be opened fully", "kind": "live",
     "when": [{"entity": "gate_main", "var": "openness", "equals": 1000}]}
  ]
}
```

Three kinds, all over one explored graph:

| kind | claim | on failure |
|---|---|---|
| `reachable` | some schedule from the initial state reaches a `when` state | "no schedule reaches it", with the bound named |
| `never` | no reachable state satisfies `when` | a counterexample replay |
| `live` | from every reachable state a `when` state is still reachable — no soft-lock | a replay to the state the goal can no longer be reached from |

A `when` is a conjunction of clauses in the kernel's own guard vocabulary
(`equals`, `gt`, `lt`, `exists`; type-strict; typed against the entity's
state schema at load), over state vars or controls — drive targets are part of
the hashed world, and "was told to open" is often the thing a designer means.

### The prover is the kernel, exploring itself

`tools/worldc/prover.py` does not model the kernel. It calls
`kernel.apply_event` and `kernel.step_entity` — the canonical Python kernel
that the Rust and wasm kernels are held to by parity — breadth-first over
one-event-per-tick schedules, deduplicated by the kernel's canonical world.
What it explores is exactly what the game will run, and BFS order makes the
first hit a shortest witness.

A witness is written as an ordinary `sim_replay` (contracts inline, pinned by
hash, `expect_state_hash` set) and **run back through the kernel before it is
reported**. `verified: true` in a proof means the kernel landed on the witness
state, not that the prover said so. Because it is an ordinary replay, the
native Rust and wasm kernels reproduce it too — checked by hand for every
witness of both example worlds, and by a test when the native kernel is built.

### Bounded, and it says so

The search is bounded in four ways, and every verdict names which one it hit:

- **One event per tick.** The replay format allows several; the prover
  schedules at most one, then integrates. A witness is therefore always a
  legal replay.
- **Amounts.** A `count` verb is tried with the integers its own semantics
  compare or clamp against, the parameters it reads, and the maximum
  (65535) — `attack` with `[65535]`, `repair` with `[100, 65535]` for the
  door — plus anything the world lists under `amounts`. Not every integer,
  and the verdict lists what was tried.
- **Horizon** (ticks, default 32) and **budget** (states, default 100,000).

The bound is reported as `exhaustive` (the frontier emptied: the reachable
graph is complete for these amounts), `horizon`, or `budget`. A spent budget
yields `inconclusive`, a third verdict that is never rounded to a pass — the
same discipline the WebGPU render probe holds to.

`live` is the property most easily faked by a bounded search, so it is kept
honest explicitly: nodes at the horizon are marked *open* (unexplored
successors), and a soft-lock is reported only for a state whose entire
explored future is goal-free and contains no open node. States that merely
*might* lock beyond the horizon are counted and named in the verdict rather
than silently passed.

### Fail closed, in the compiler

`worldc prove WORLD` answers in seconds with no geometry compile — the
designer's loop. `worldc compile-world` runs the same prover into the proof
directory: each property is a check like any other, a `violated` or
`inconclusive` property breaks the world contract, and the capsule records the
exploration (states, depth, bound, amounts tried) beside the verdicts. The
prover's own source hash is part of the compiler fingerprint, so a changed
prover is a changed world proof.

## Evidence

| Claim | How it is checked |
|---|---|
| The example worlds keep their properties | `just worldc-prove` on `fortress_world.json` (5 properties, 576 states, exhaustive, 0.24 s) and `depot_world.json` (5 properties, 538 states, 0.17 s); both are tests |
| A witness is proof by execution | Every witness is re-run through the Python kernel before it is reported; each of both worlds' witnesses also reproduces through the native Rust and wasm kernels |
| A soft-lock is found and named | A lever with no `free`: one `jam` and "can always be switched on" is gone forever; the prover reports it in one tick with the replay |
| A violation is a counterexample, not an opinion | The prover's first real find — see below — is a test |
| The three verdicts stay distinct | A budget of three states is `inconclusive`, never `holds`; an unbounded counter is `holds` to the `horizon`, a finite world `exhaustive` |
| Properties are typed and closed | 17 prover unit tests and 5 world tests: guard typing, unknown entities/vars/keys, duplicate names, bad kinds, out-of-range bounds |

### The first find

While writing the fortress properties, the obvious one — *a locked, intact
gate is never ajar* — was expected to hold. The prover refuted it in two ticks:

```text
FAIL  never  a locked intact gate is never ajar — reached in 2 tick(s)
        witness: [[0, "gate_side", "attack", 65535], [1, "gate_side", "repair", 100]]
```

Destroy the gate (it hangs open and starts swinging), repair it while it is
still locked: it is now intact, locked, and ajar. Nothing in the door's
semantics closes a revived gate. Nobody had written that down, and a playtest
would have had to try exactly that order to see it. That is the point of the
mechanism, and the case is now a test.

## What this does not claim

- **Not that a world is fun.** Reachability, safety and liveness are structure.
  The prover cannot say whether the puzzle is satisfying, only whether it can
  be solved and whether it can be broken.
- **Not unbounded proof.** Every verdict is relative to its amounts, horizon
  and budget, and says so. Widen `amounts` or `horizon` when a property is
  about a magnitude or a length the defaults do not reach.
- **Not multi-event ticks.** A schedule with two events in one tick is a legal
  replay the prover does not try.
- **Not cross-entity behaviour.** Entities still cannot affect each other
  (ADR 0021 defers wiring), so a property over several entities is a
  conjunction over independent machines. The interesting cases — a lever that
  opens a gate — arrive with wiring, and this prover is ready for them: it
  walks whatever the kernel does.
- **Not temporal logic.** Three kinds cover what designers ask first; "always
  eventually" beyond `live`, or ordering constraints, are later increments.

## Consequences

- A world proof now says what a world *can* and *cannot* do, with replays
  anyone can run, not only that one script ran. "Every world ships with
  proof" (ADR 0018) means design properties from here on.
- A generated world has a new gate to pass before it becomes state: the
  properties its brief implies. BRIEF→BATTLE scoring can ask "is the objective
  reachable, is it un-soft-lockable" mechanically instead of by inspection.
- Every future kernel feature (wiring, timers, randomness) inherits the prover
  for free, and inherits the obligation to keep its state space walkable — a
  feature that makes worlds unprovable is a feature to think twice about.
- New surface: `properties` in world documents (spec updated), `worldc prove`,
  `just worldc-prove`, `prover_sha256` in the compiler fingerprint.
