# ADR 0024: Wires — the world's couplings, declared, held, and hidden-state-free

- Status: Accepted
- Date: 2026-09-13
- Extends: [ADR 0021](0021-declared-affordance-semantics.md) (entities with
  declared semantics; this lets them affect each other),
  [ADR 0022](0022-design-properties-are-proven.md) (the prover walks wired
  worlds with no change to itself)
- Relates: [ADR 0023](0023-declared-joint-drives.md) (a wired world renders
  through the same three engines), [ADR 0019](0019-compiled-gameplay-on-the-web.md)

## Context

After ADR 0021 an entity could be anything, and after ADR 0022 a world could
be proven — but a world was still a bag of state machines that never touched.
Every event named one entity, every effect wrote that entity, and nothing a
lever did could reach a gate. That is not a world; it is a shelf. The
interesting design questions (*can the player open the gate from the far side
of the moat*) are about couplings, and the prover had nothing to say about
them because the kernel had no way to express them.

The obvious extension — let an effect write another entity — was refused.
Declared semantics stay bounded because an affordance can only touch its own
entity; a `set` that reached across would make every entity's meaning depend
on every other's, and the closed vocabulary would stop being closed. Couplings
belong to the **world**, which is where the entities are bound by name.

## Decision

**A world declares wires. A wire is `when` (clauses over the world) and
`then` (verbs delivered to entities). It holds rather than pulses, it carries
no hidden state, and both kernels apply it in the same place.**

```json
"wires": [
  {"name": "lever_opens_gate",
   "when": [{"entity": "signal_lever", "var": "on", "equals": true}],
   "then": [{"entity": "gate", "verb": "open", "arg": null}]},
  {"name": "lever_closes_gate",
   "when": [{"entity": "signal_lever", "var": "on", "equals": false}],
   "then": [{"entity": "gate", "verb": "close", "arg": null}]}
]
```

- **Where in the tick.** Scheduled events first, then every wire in declared
  order, then integration. A wire whose condition holds *now* — after the
  tick's events and after earlier wires — delivers its verbs as ordinary
  events: the target's own guards still decide, a locked gate still absorbs
  `open`. Later wires see what earlier ones did; a chain propagates one hop
  per tick. Nothing is remembered between ticks, so the hashed world is still
  the whole world.
- **It holds.** While the lever is on, the gate is told to open every tick.
  That is the semantics of a relay, not of a button, and it is what makes
  hidden state unnecessary: a pulse needs to remember whether it already
  fired; a hold does not. It also gives wires a precedence a designer can
  reason about — a direct `open` given while the lever is off is overruled by
  the closing wire in the same tick.
- **So it may only target affordances that merely set.** A wire delivered to
  `toggle` would flap every tick; one delivered to `add` would count ticks.
  `validate_wires` refuses any target whose effects are not all `set` or
  `set_control` (`E_WIRE_SHAPE`). The v0.1 door's `open`/`close`/`lock`/
  `unlock` qualify; `attack`/`repair` do not.
- **Clauses are the kernel's vocabulary.** A clause — one entity, one state
  var or control, one typed test — is now defined once in the kernel
  (`validate_clause`, `clause_holds`) and used by wires and by the prover's
  properties alike. "While the lever is on" and "the gate is never open while
  the lever is off" are the same sentence.
- **Wires travel with the replay.** A replay may carry `wires`; a world
  document declares them; `worldc` compiles a world only if the scenario's
  wires are the world's (by canonical hash), and the world proof records that
  hash. A witness replay through a wired world carries the wires, so any
  kernel reproduces it.

### What is proven, and how

| Claim | How it is checked |
|---|---|
| Both kernels agree on wired worlds | `declared_wiring_lever_and_gate` — the gatehouse: on, off, an overruled direct open, on again, and a close delivered to a locked gate — reproduces byte-for-byte through Python, native Rust and Wasm, and in Chrome through the Godot host script |
| Both kernels agree on every refusal | Two invalid fixtures — a wire that targets `pull` (a toggle) and one that reads an undeclared var — return `E_WIRE_SHAPE` from all three |
| The semantics themselves | 11 unit tests: holding every tick, overruling a direct command in the same tick, declared order with later wires seeing earlier ones, a target's guard still applying, control clauses, an empty wire list equal to none, and seven fail-closed refusals |
| The prover reasons about couplings | A lamp wired to a lever: "lit while the lever is off" is unreachable *with* the wire and violated *without* it, and the witness through the wire replays through the kernel |
| The compiler refuses what the kernel would | `worldc` validates a world's wires through the kernel and refuses a scenario whose wires are not the world's |
| A wired world renders | The gatehouse joins the cross-engine suite: the gate's leaves swing because the lever's handle swung, and three engines agree on every tick |

## What this does not claim

- **Not pulses.** A one-shot coupling ("when the lever *is pulled*, count a
  score") needs an edge, and an edge needs memory. That is a deliberate
  later increment with its own hashed state and its own fixtures.
- **Not same-tick cascades.** A chain of wires resolves one hop per tick, in
  declared order. That is a feature — it is the timing model — but a designer
  who expects instantaneous propagation across three hops should know.
- **Not conditions on events.** A wire reads the world, never the event
  stream; "when anyone attacks the gate" is not expressible.
- **Not physics.** A wire delivers a verb; it does not move anything itself.

## Consequences

- Worlds are now worlds: entities affect each other, through declarations
  the compiler checks and the prover walks. `worldc prove` answers "does pulling the
  lever start the gate opening" and "is an intact gate ever driven open while the
  lever is off" exhaustively for the gatehouse in well under a second.
- New surface to keep in lockstep: `wires` in replays and world documents,
  `validate_wires`/`apply_wires`/`clause_holds` in both kernels, the
  fixtures that hold them to each other, and `wires_sha256` in world proofs.
- The prover changed by one argument. That is the payoff of building it on
  the kernel's own step: a feature the kernel gains, the prover inherits.
