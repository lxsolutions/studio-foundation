# ADR 0021: Declared affordance semantics — the kernel past the door

- Status: Accepted
- Date: 2026-09-04
- Extends: [ADR 0018](0018-brief-to-battle-world-compiler.md) (World IR and the
  deterministic kernel are milestones M2/M3; this makes M3 general)
- Relates: [ADR 0019](0019-compiled-gameplay-on-the-web.md) (the kernel is the
  compiled-gameplay answer for the browser — it needed to simulate more than a
  door for that answer to be worth much), [ADR 0020](0020-engine-neutral-presentation.md)

## Context

The deterministic simulation kernel is the piece this repository leans on
hardest. ADR 0018 calls it the substrate. ADR 0019 makes it the answer to "how
does compiled gameplay logic reach a browser". ADR 0020 puts three renderers
downstream of it. Every one of those arguments assumed it simulates *worlds*.

It simulated a door.

Concretely, before this ADR the kernel knew six verbs — `open`, `close`, `lock`,
`unlock`, `attack`, `repair` — four state variables, one integrator moving
`openness` toward `openness_target`, and one error code for everything else:

```
E_NO_SEMANTICS: no semantics for affordance "pull" in kernel v0.1
```

World IR meanwhile lets an author declare any state schema and any affordance
list, and `worldc` compiled all of it faithfully into a contract the kernel
would then refuse to act on. `SIM_PARAM_KEYS` in the compiler was literally
`{"open_rate_milli", "max_health"}`. So BRIEF→BATTLE could compile any world you
liked, as long as it was made of doors.

This is the gap between a demo and a substrate, and it was invisible because the
one thing the corpus tested *was* a door.

## Decision

**Affordance semantics are declared in the contract, in a closed vocabulary the
kernel interprets. The built-in door becomes data in that vocabulary.**

An affordance is guards plus an ordered list of effects. An integrator is one
variable moving toward one control target at one rate. That is the whole
language:

| Kind | Forms |
|---|---|
| Argument | `none`, `count` (integer `0..65535`) |
| Guard | `equals`, `exists`, `gt`, `lt` — against a literal, `param` or `var` |
| Effect | `set`, `set_control`, `add` (with `sign` and `min`/`max` clamp), `toggle` |
| Value | a bare literal, or `{const}`, `{arg}`, `{param, default}`, `{var}` |
| Integrator | `{var, toward, rate}` |

Deliberately absent: loops, expressions, arithmetic beyond a clamped add, and
any form of indirection that could not be bounded. [ADR 0018](0018-brief-to-battle-world-compiler.md)
rules out model-emitted executable code reaching production state, so this is
*data an agent may write*, not a scripting surface. Everything expressible in it
terminates in a fixed number of integer operations.

**A guard that does not hold is a no-op, not an error.** That generalizes what
the door already did — a locked gate absorbed `open` — and it is the difference
between a world that behaves and a replay that dies mid-tick.

### One execution path

`sim_contract` `"0.1"` lists affordance *names* and desugars into `DOOR_PROFILE`,
the door written out in the vocabulary above. `"0.2"` declares its own. Both run
through the same interpreter — there is no second code path that "happens to
agree", because a second code path is exactly how the old binding in ADR 0020
stayed broken for two months.

### Fail closed, at load

A malformed semantics block is rejected before the first tick, with
`E_SEMANTICS_SHAPE`. Effects that write undeclared state, guards that read it,
integrators on variables that do not exist, unknown ops, a guard carrying two
tests, semantics for an affordance the contract never offered — all refused up
front. A replay that fails halfway leaves a partial world and a hash nobody can
reproduce, which is the one outcome a deterministic kernel must never produce.

### Typed, closed, and exact at the edge

A closed vocabulary two kernels interpret is only as safe as the shapes it
admits, so the block is **typed against the state schema** at load: `set`
writes its var's type, `add`/`gt`/`lt` and integrators work on integers,
`toggle` on bools, controls carry integers because integrators read them, and
`equals` compares like with like. A value has exactly one source; `{arg: true}`
is literally `true` and only legal in a `count` affordance; a `param` must be
set or carry a default; every listed affordance has semantics; unknown keys are
refused everywhere. Each of those closes a place the two kernels could
otherwise disagree on malformed input — `{"exists": 1}` was truthy in Python
and no test at all in Rust; `{"arg": 1}` read the argument in one kernel and
nothing in the other; a bool `const` added as `1` in Python and `0` in Rust.

The integer domain is pinned too. Every integer the kernel holds is an i64:
literals, parameters and initial values outside it are refused, and the two
places arithmetic happens saturate in both kernels, because Python's integers
are unbounded and Rust's are not. A fixture drives a counter past 2^63 and all
three kernels stop at `i64::MAX`.

## Evidence

| Claim | How it is checked |
|---|---|
| The vocabulary expresses the door **exactly** | The 7 pre-existing conformance replays reproduce their committed golden `state_hash`, `hash_log`, `final_state` and `navigation` byte-for-byte through the general interpreter. If the desugaring were even slightly off, those hashes would move |
| The desugaring *is* the profile | A v0.1 gate and a v0.2 gate that spells `DOOR_PROFILE` out longhand produce the same hash and the same per-tick hash log |
| It simulates things that are not doors | `declared_semantics_lift_and_lever` runs a **cargo lift** (integrator on `height` toward `height_target` at `lift_rate_milli`, `add` clamped by a `max_power` parameter, a call absorbed while unpowered) and a **signal lever** (`toggle`, a jam guard that makes a pull a no-op) — agreeing across Python, native Rust and Wasm, and in a real browser through the Godot host script |
| Arithmetic is exact at the edge | `declared_semantics_saturates_at_i64` pushes a counter past 2^63; all three kernels saturate to the same value |
| Both kernels agree on every new refusal | 8 invalid fixtures — undeclared var, type mismatch, unknown key, uncovered affordance, non-bool `exists`, a 0.2 contract without semantics, a float parameter, an initial value outside i64 — return the same stable code from all three |
| The compiler refuses what the kernel would | `worldc.sim_contract` asks the kernel to validate every contract it emits; a malformed block fails at compile time as a `WorldIRError` carrying the kernel's code |
| The vocabulary itself | 39 unit tests: clamping, per-affordance argument shape, integrator generality, saturation, and every fail-closed refusal — typing, sources, unknown keys, coverage, contract shape |

The first row is the one that matters. Rewriting a kernel that three
implementations must agree on is the kind of change that quietly alters
behaviour; a frozen corpus of golden hashes is the only reason it can be made at
all. Notably the Python side was generalized first and passed three-way parity
against the *unchanged* Rust door — an independent implementation confirming the
interpreter reproduces the hardcoded semantics bit for bit.

### Cross-language hazards, recorded

- **Type-strict equality.** Python says `True == 1`; `serde_json` does not. Both
  kernels compare with the stricter rule, or `{"equals": 0}` would match a
  boolean in one kernel and not the other.
- **Absent state variables** compare as the zero *of the type they are compared
  against* — the old kernel read them through `state.get(var)` (falsy) in Python
  and `unwrap_or(false)`/`unwrap_or(0)` in Rust, and those only agree if the
  missing value takes its type from the literal.

## What this does not claim

- **Not a physics or behaviour engine.** There is no continuous simulation, no
  collision, no scheduling. An entity is a small integer state machine with one
  linear integrator, which is what World IR describes and no more.
- **Not enough for every entity.** No timers, no cross-entity effects, no
  randomness (the seed is still unused by any declared effect). Each of those is
  a deliberate next increment, not an oversight — and each needs its own frozen
  fixtures before it can be believed.
- **Not a change to the replay format.** `sim_replay` stays `"0.1"`; only the
  contract inside it gained a version.

## Consequences

- `worldc` no longer restricts simulation parameters to the door's two. A
  document with declared semantics may name any parameter its effects read; the
  kernel validates that every reference resolves.
- The claim that the kernel is "the substrate" is now true rather than
  aspirational, which matters most for [ADR 0019](0019-compiled-gameplay-on-the-web.md):
  a team told to move compiled gameplay rules into it can now express rules that
  are not about opening a gate.
- Conformance fixtures are generated from World IR by
  `tools/sim/make_declared_fixtures.py`, not typed by hand, so the entities the
  corpus proves are the ones the compiler actually emits — and the invalid
  fixtures are those same contracts with one deliberate defect each, frozen
  with the code the canonical kernel gives them.
- `worldc` validates every contract it compiles through the kernel, so a
  document with malformed semantics never reaches a proof capsule.
- New surface to keep in lockstep: every vocabulary addition must land in the
  Python kernel, the Rust kernel, both validators, and a fixture — or three-way
  parity fails, which is the intended cost.
