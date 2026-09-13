# ADR 0023: Declared joint drives — the presentation binding past the door

- Status: Accepted
- Date: 2026-09-13
- Extends: [ADR 0020](0020-engine-neutral-presentation.md) (the neutral binding
  — this is what it binds *from*), [ADR 0021](0021-declared-affordance-semantics.md)
  (the kernel past the door; this takes the renderer there too)
- Relates: [ADR 0022](0022-design-properties-are-proven.md) (a witness replay
  drives exactly these bindings, so a proven schedule can be watched)

## Context

ADR 0021 let the kernel simulate a cargo lift and a signal lever. ADR 0022
proved properties about them. Neither could be *shown*: the engine-neutral
binding in `shared/runtime/scene_binding.mjs` computed every joint's rotation
from `entity.openness` mapped onto `range_degrees`. A lift's `height` and a
lever's `on` never reached a renderer. The depot world would have drawn a
platform welded to its shaft and a handle frozen at minus forty degrees, and
every conformance test would have passed, because every test was about a door.

That is the same class of silence ADR 0020 records — a scene that renders
beautifully and shows the wrong world — one layer up: the axis was read from
World IR, but *which state var moves the joint* was still a renderer's
assumption.

## Decision

**A joint declares what moves it, and how far. The binding reads the
declaration; it never assumes a variable.**

```json
"joints": {
  "rail":  { "parent": "shaft", "child": "platform", "axis": [0, 1, 0],
             "type": "slider", "range_units": [0, 3.6],
             "drive": { "var": "height", "from": 0, "to": 1 } },
  "pivot": { "parent": "post", "child": "handle", "axis": [1, 0, 0],
             "range_degrees": [-40, 40],
             "drive": { "var": "on" } }
}
```

- **`type`** is `hinge` (the default) or `slider`. A hinge sweeps
  `range_degrees` about its axis; a slider travels `range_units` along it.
  Each type has exactly one range, named for what it measures, so a number
  never has to be guessed at.
- **`drive`** names the state var and the span of it that maps onto the
  joint's range. A float var's span is in World IR units and the binding
  scales it to the kernel's milli-units; an int var is what it says; a bool
  var has no span — `false` is the joint's minimum, `true` its maximum.
- **The door convention becomes explicit.** A joint that declares no drive
  inherits `openness` over its whole travel — and only if the entity actually
  declares a float `openness`. Otherwise `worldc` refuses the document and the
  binding throws, instead of silently drawing a joint that never moves.
- **The instruction gains one form.** Beside
  `{ node, rotate: { axis, radians }, hidden }` there is now
  `{ node, translate: { axis, units }, hidden }`. Adapters apply whichever is
  present, from the node's placed position. Nothing else about the contract
  changes; the layout still owns the swing sign, which applies to sliders too.

### What is proven, and how

| Claim | Evidence | Command |
|---|---|---|
| The contract maps drives correctly | A slider translates across `range_units` scaled from milli and clamps at both ends; a bool drive snaps a hinge to the ends of its range; the door's default is `openness` and nothing else; a missing drive, an undeclared var, an unknown type and a missing range all fail loudly | `just runtime-contract` |
| Three engines agree on both worlds | The depot replay (a slider driven by a float, a hinge driven by a bool) now runs beside the fortress through three.js, Babylon.js and PlayCanvas; every joint's world-space probe agrees on every tick | `just runtime-conformance` |
| The binding is not inert, per drive | The anti-vacuity gate generalizes: a joint must move exactly when the var that *drives* it changed over the replay, and must not otherwise — `openness` is no longer special-cased | same |
| The compiler refuses what the binding would | `worldc` validates joint type, the matching range, unknown joint fields, and the drive's var, type and span | `just test-python` |

The conformance line now reads `agree to within 1e-6 on 2 worlds (fortress:
21 ticks x 4 joints; depot: 15 ticks x 2 joints, mean travel 3.362)`. The
lift's travel is the slider's 3.6 units; the lever's is the probe swept
through eighty degrees.

## What this does not claim

- **Still transforms only.** Cameras, materials, audio, input, physics and
  asset import remain outside the neutral layer (ADR 0020's boundary).
- **One var per joint.** A joint blends nothing; a part that should move on
  two variables is two joints.
- **Straight sliders.** A slider translates along one axis; curved rails are
  not a joint type.
- **Not Godot.** The reference client still binds kernel state in GDScript
  through `StudioSimKernel` and does not implement this contract.

## Consequences

- The three ADRs now compose end to end for an entity that is not a door: it
  is declared (World IR), simulated (ADR 0021), proven (ADR 0022) and shown
  (this) with no renderer-side assumption in the chain.
- World IR documents gain optional joint fields; existing documents are
  unchanged because the door convention is the default — but a new entity
  without `openness` must say what drives its joints, which is the point.
- The generated fixtures were regenerated: the lift's and lever's document
  hashes changed (`source_world_ir_sha256`, hence `contract_sha256`), their
  golden state hashes did not.
