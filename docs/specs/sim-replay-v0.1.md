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
- The argument shape is per affordance (`arg: none | count`); a `count` is a
  nonnegative integer ≤ 65535. The door's `open`/`close`/`lock`/`unlock` take
  none; `attack`/`repair` take a count.
- Every integer the kernel holds is an **i64**: initial values, parameters and
  literals outside that range are refused, and the two places arithmetic
  happens (`add`, integrators) saturate rather than wrap or grow.
- Unknown replay fields, non-finite constants (NaN/Infinity), mistyped
  initial values, and undeclared state vars are all hard errors.

### Standard verb semantics (contract v0.1 — the door)

A `sim_contract` of `"0.1"` lists affordance *names* and inherits the built-in
door profile:

| verb | contract |
| --- | --- |
| `open` | sets the openness target to 1000; absorbed when `locked` or `destroyed` |
| `close` | sets the openness target to 0; absorbed when `destroyed` |
| `lock` / `unlock` | sets `locked` |
| `attack n` | `health -= n` (floor 0); at 0, sets `destroyed` (if declared) and the gate hangs open |
| `repair n` | `health += n` (ceiling `sim.max_health`, default 100); revives `destroyed` above 0 |

Integration: `openness` tracks its target at `sim.open_rate` milli per tick
(default 250), clamped.

### Declared semantics (contract v0.2)

A `sim_contract` of `"0.2"` carries a `semantics` block and says what its own
affordances do, so the kernel is not limited to doors ([ADR 0021](../adr/0021-declared-affordance-semantics.md)).
The door above is itself written in this vocabulary and v0.1 desugars into it —
there is one interpreter, and the frozen golden hashes are what proves the
desugaring exact. A `0.1` contract must not carry `semantics`; a `0.2` contract
must (`E_CONTRACT_SHAPE` otherwise).

| kind | forms |
| --- | --- |
| argument | `none`, `count` (integer `0..65535`) |
| guard | `equals`, `exists`, `gt`, `lt` — against a literal, `param` or `var` |
| effect | `set`, `set_control`, `add` (with `sign` and `min`/`max` clamp), `toggle` |
| value | a bare literal, or `{const}`, `{arg: true}`, `{param, default}`, `{var}` |
| integrator | `{var, toward, rate}` |

```json
"semantics": {
  "affordances": {
    "call_top": {
      "arg": "none",
      "guards": [{"var": "power", "gt": 0}],
      "effects": [{"op": "set_control", "control": "height_target", "value": 1000}]
    }
  },
  "integrators": [
    {"var": "height", "toward": "height_target", "rate": {"param": "lift_rate_milli"}}
  ]
}
```

Rules that hold everywhere:

- **A guard that does not hold is a no-op, not an error** — a locked gate
  absorbing `open`, generalized.
- **Effects apply in order** and each reads the state the previous one left.
- **Equality is type-strict**: a boolean is never the number 0, because Python
  and `serde_json` must agree.
- **An absent state var** compares as the zero of the type it is compared to
  (only the desugared door can reach this; a 0.2 contract declares every var
  it names and every declared var is seeded).

The block is validated **at load, fail-closed, with `E_SEMANTICS_SHAPE`** —
never mid-replay, because a replay that fails halfway leaves a hash nobody can
reproduce. Everything the interpreter will read is checked, and it is checked
in both kernels in the same order:

- **Typed against the state schema.** `milli_i64`/`i64` vars are `int`,
  `bool` is `bool`, `string` is `string`. `set` writes a value of its var's
  type; `add`, `gt`/`lt` and integrators need `int`; `toggle` needs `bool`;
  a control carries an `int` because integrators read it; `equals` compares
  like with like. A `{var}` source has its var's type, `{arg}`/`{param}` are
  `int`, a literal has its own type, and floats are not a type the kernel has.
- **A value has exactly one source** (`const` | `arg` | `param` | `var`);
  `arg` is literally `true` and only legal in a `count` affordance; a `param`
  must be set by the contract or carry an integer `default`; a `var` must be
  declared.
- **Unknown keys are refused everywhere** — in the block, an affordance, an
  effect, a clamp, a guard, a value source and an integrator — because a
  `guard` where `guards` was meant would otherwise vanish silently.
- **Every listed affordance has semantics** and no semantics name an unlisted
  one; `requires` lists declared vars; control names are snake_case.
- **The contract itself is shaped first** (`E_CONTRACT_SHAPE`): state vars
  carry a known storage, affordances are identifiers, every parameter but
  `navigation` is an i64 integer, and navigation rules are well-formed.

`worldc` asks the kernel these same questions when it compiles a document, so
a malformed block fails at compile time in the compiler's own error.

### Wires (the world's couplings)

A replay may carry `wires` ([ADR 0024](../adr/0024-wires-the-worlds-couplings.md)):

```json
"wires": [
  {"name": "lever_opens_gate",
   "when": [{"entity": "signal_lever", "var": "on", "equals": true}],
   "then": [{"entity": "gate", "verb": "open", "arg": null}]}
]
```

- Each tick: scheduled events, then every wire in declared order, then
  integration. A wire whose `when` clauses all hold *now* delivers each
  `then` as an ordinary event (the target's guards still apply); later wires
  see what earlier ones did; nothing is remembered between ticks.
- A clause names one entity, one state `var` or `control`, and exactly one
  of `equals` / `gt` / `lt` / `exists` against a literal, typed like a guard.
- A wire **holds**, so its targets may only be affordances whose effects are
  all `set` / `set_control`; `arg` must fit the verb (`null` for `none`, an
  integer 0..65535 for `count`). Names are unique snake_case; unknown keys
  are refused. Everything is checked at load with `E_WIRE_SHAPE`, in both
  kernels, in the same order.

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

`services/sim-kernel` is the native + Wasm kernel. `tools/sim/tests/test_parity.py`
proves, over every fixture in `tools/sim/conformance/v0.1/`:

```text
canonical Python kernel  ─┐   valid:   identical final state, hash log, navigation
native Rust kernel       ─┼─→
wasm32 Rust kernel (node)─┘   invalid: identical stable error code
```

The wasm build exports a raw ABI (`sim_alloc`/`sim_run`/`sim_free`), so
parity needs no wasm-bindgen layer and no new JavaScript dependencies. The
declared-semantics fixtures are generated from World IR by
`tools/sim/make_declared_fixtures.py`, never typed by hand.

## Snapshots and observers

Every run also produces `snapshots`: the complete world state after each
tick, in the same canonical form the hash covers. A runtime adapter may
OBSERVE snapshots — map them to animation, UI, sound — but it has no path to
write simulation state. `tools/sim-viewer/` is the reference adapter: the
wasm kernel in a browser tab, the forged gate GLB as geometry, and
`adapter.js` mapping openness to hinge rotation. Its node test
(`adapter_test.mjs`, run in CI) proves every rendered frame is derived from
a kernel snapshot, never invented.
