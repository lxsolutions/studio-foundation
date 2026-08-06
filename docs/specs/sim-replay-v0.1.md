# Simulation & replay v0.1 — the deterministic contract

Status: prototype (ADR 0018, milestone M3 precursor)
Schema id: `"sim_replay": "0.1"`

The renderer never feeds the simulation. The contract is:

```text
initial world state + seed + fixed-step event stream = final state hash
```

`tools/sim/kernel.py` is the canonical v0.1 kernel: pure Python, stdlib-only,
no wall clock, no engine objects, no randomness (the `seed` field is reserved
for v0.2 verbs that sample). Any other kernel — Rust, Wasm, a future runtime
— must reproduce these hashes bit-for-bit; this document freezes what
"conforming" means.

## State

- Entities are World IR v0.1 documents; the state schema comes from their
  `state` block with typed defaults (`float` 0, `int` 0, `bool` false,
  `string` ""). `initial` may override declared vars only, with types checked.
- **Authoritative state is integer fixed-point.** A World IR `float` var is
  held as integer milli-units (1.0 == 1000). No float ever enters simulation
  arithmetic or the hashed state — no IEEE parsing, rounding, or formatting
  decisions can make two conforming kernels disagree.
- **Control intent is state.** The hashed world is
  `{entity: {"state": {...}, "control": {...}}}` — drive targets included.
  Two simulations with identical visible state but different intent hash
  differently, because their next tick differs (there is an adversarial
  fixture proving exactly this).
- Navigation is a pure function of `state` — derived, never stored, never
  hashed.
- The state hash is `sha256` over canonical JSON (sorted keys, tight
  separators) of the complete world.

## Events

`[tick, entity, verb, arg]`, applied in stable `(tick, file-order)` order
before that tick's integration step. Everything is validated fail-closed:

- `ticks` is an integer 0..1,000,000; every event tick must be inside it.
- `entity` must be declared in `entities`; `verb` a snake_case identifier that
  is a declared affordance of the target.
- `open`/`close`/`lock`/`unlock` take no argument; `attack`/`repair` take a
  nonnegative integer ≤ 65535.
- Unknown replay fields, non-finite constants (NaN/Infinity), mistyped
  initial values, and undeclared state vars are all hard errors.

### Standard verb semantics (v0.1)

| verb | contract |
| --- | --- |
| `open` | sets the openness target to 1000; absorbed when `locked` or `destroyed` |
| `close` | sets the openness target to 0; absorbed when `destroyed` |
| `lock` / `unlock` | sets `locked` |
| `attack n` | `health -= n` (floor 0); at 0, sets `destroyed` (if declared) and the gate hangs open |
| `repair n` | `health += n` (ceiling `sim.max_health`, default 100); revives `destroyed` above 0 |

Integration: `openness` tracks its target at `sim.open_rate` milli per tick
(default 250), clamped.

## Navigation derivation

`blocks_navigation` evaluates the World IR `navigation` block from state:
`never_blocks_when_destroyed`, and any `blocks_below_<var>` threshold
(converted to milli) against the named float var.

## Golden replays and fingerprints

A replay file may carry `expect_state_hash`. `kernel.py replay FILE` exits
non-zero when the recomputed hash differs; `--update-golden` rewrites the
expectation deliberately. Every run also reports fingerprints: the kernel
source hash, the per-entity World IR document hashes, and the replay's own
canonical SHA-256 — a result names exactly what produced it.

The committed example (`tools/sim/replays/gate_open_destroy.json`) is the
fortress gate's first battle: a locked open attempt absorbed, unlock, open,
three attacks to destruction, navigation unblocked.

## Parity

`services/sim-kernel` is the native + Wasm kernel for the single-entity gate
reducer. `tools/sim/tests/test_parity.py` proves:

```text
canonical Python kernel  ─┐
native Rust kernel       ─┼─→ gate_open_destroy.json → identical hash
wasm32 Rust kernel (node)─┘
```

The wasm build exports a raw ABI (`sim_alloc`/`sim_run`), so parity needs no
wasm-bindgen layer and no new JavaScript dependencies. Generic multi-entity
worlds remain deferred to the M3 proper milestones.
