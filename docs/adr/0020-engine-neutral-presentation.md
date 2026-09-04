# ADR 0020: Engine-neutral presentation — one binding, three renderers, proven

- Status: Accepted
- Date: 2026-09-04
- Extends: [ADR 0018](0018-brief-to-battle-world-compiler.md) (World IR, deterministic
  kernel — this is milestone M2, "World IR compiled to two runtimes", made checkable),
  [ADR 0019](0019-compiled-gameplay-on-the-web.md) (the kernel is host-independent)
- Relates: [ADR 0006](0006-blender-master-asset-pipeline.md) (glTF is the asset boundary),
  [ADR 0001](0001-godot-as-primary-engine.md) (Godot remains the reference client)

## Context

A fair reading of this repository is that most of its engineering is not about
Godot: bforge exports glTF that Unity, Unreal, three.js, Babylon and PlayCanvas
all read; the simulation kernel is renderer-independent by construction; World IR
describes what an entity *is* rather than what any one engine calls it. Only the
WebGPU patch series is truly engine-specific.

That reading is correct, and it was also **unproven** — which turns out to have
mattered. The repository had exactly one renderer binding, in an untested HTML
file, and it was broken:

- The viewer looked joints up by **instance** name (`gate_main`) in a table keyed
  by **part** name (`leaf_l`). Every lookup missed, so the derived `angleDeg` was
  always exactly `0` and the gate leaves never moved, through 21 ticks of a
  replay in which the kernel opens a gate from 0 to fully open.
- The test that covered it kept its only angle assertion inside `if (joint)` —
  the branch that never held. It passed for two months.
- The binding also rotated about **Y**, while World IR declares the hinge axis as
  **Z**. A renderer picking its own axis is a second, unverified source of truth,
  which is precisely what the "renderer observes only" contract exists to forbid.

None of that is an argument against engine neutrality. It is an argument that
"engine-neutral" has to be a property something *checks*, because the failure
mode is silence: a scene that renders beautifully and shows the wrong world.

## Decision

**Presentation is a data translation, and it lives in `shared/runtime/`, holding
no engine types. Renderers apply instructions; they never derive them.**

The contract is deliberately narrow:

```js
{ node: "gate_main/leaf_l", rotate: { axis: [0,0,1], radians: -1.91 }, hidden: false }
```

- **Axis-angle**, because it is the one rotation form three.js, Babylon and
  PlayCanvas all accept without an argument about Euler order or handedness.
- **The axis is read from World IR**, never chosen by a renderer.
- **Instance-qualified node names** (`instance/part`), because the bug above was
  exactly a part name standing in for an instance name.
- **Swing sign is layout data.** A double door's leaves mirror because of how the
  door was hung — that is placement, not simulation and not semantics, so it is
  declared once in a layout file instead of invented per frame in renderer code.

Engine adapters take the engine module as an argument rather than importing it:
`shared/` carries no npm dependencies, and a consuming game already has its
engine loaded.

### What is proven, and how

| Claim | Evidence | Command |
|---|---|---|
| The contract itself is correct | 9 assertions with no engine installed — axis provenance, clamping, mirroring, purity, loud failure on bad World IR | `just runtime-contract` |
| three.js, Babylon.js and PlayCanvas agree | the real kernel replay drives all three; every joint's world-space probe point matches on every tick, and hinges must swing exactly when the kernel says their gate opened | `just runtime-conformance` |
| The binding is not inert | both suites fail if the rotation is forced to zero (verified by mutation, not by inspection) | both |
| glTF reaches every named runtime | the committed op catalog must offer all six engine presets to both export ops | `just test-python` |

All three engines run **headless with no GPU**: three.js needs no renderer for
scene-graph maths, Babylon has `NullEngine`, and PlayCanvas's `GraphNode` works
without an Application. This is a normal test, not a hardware ritual.

### Measured engine differences, recorded so they are not rediscovered

- **Precision.** three.js keeps `Matrix4` in a float64 JS array; Babylon and
  PlayCanvas use `Float32Array`. Agreement is exact only to single precision —
  ~4e-7 at coordinates near 3.2 — so the conformance tolerance is 1e-6. That is a
  property of the engines, not a fudge factor.
- **PlayCanvas visibility.** The public `enabled` getter resolves through the
  hierarchy, and that propagation is maintained by an `Application`; on a
  detached graph it answers `false` whatever was set.
- **Babylon packaging.** The `babylonjs` UMD package hangs every symbol off the
  ESM default export, so a named import of `NullEngine` silently yields
  `undefined`.
- **Rotation maths agrees exactly.** All three produce identical transforms for
  the same axis-angle, and Babylon's `useRightHandedSystem` does *not* change
  node transform maths — it governs projection and glTF import. A conformance
  test comparing only quaternions would therefore pass without proving anything;
  this one transforms an off-axis point and compares world-space positions.

## What this does not claim

- **Not that a whole game runs on three renderers.** What is proven is the
  presentation binding: state to transforms. Cameras, materials, input, audio,
  physics and asset loading are untouched by this contract.
- **Not that the same GLB imports identically everywhere.** glTF is the declared
  boundary (ADR 0006) and the export presets exist, but no test yet loads one
  asset into three engines and compares the result. That is the next honest gate.
- **Not Unity or Unreal.** They have export presets and no adapter and no test.
- **Not Godot.** The reference client binds kernel state in GDScript through
  `StudioSimKernel` (ADR 0019) and does not yet implement this contract. Godot
  being the one engine outside the engine-neutral layer is a real gap, and
  naming it is better than a table with a tick in every column.
- **Not a change of primary engine.** ADR 0001 stands. Godot is the reference
  runtime; this ADR makes the layer *beneath* it portable, which is a different
  claim from replacing it.

## Consequences

- The description that fits the repository is no longer "an AI Godot toolkit" but
  "an engine-independent production compiler whose reference runtime is Godot" —
  and that sentence is now backed by a suite rather than by a diagram.
- The sim-viewer is no longer demo code that quietly disagreed with the
  simulation: it drives the same adapter the conformance suite holds three
  engines to.
- `angleDeg` is gone from the presentation frame. Frames carry simulation state;
  geometry is derived where the axis is known. This is a deliberate, breaking
  change to an internal format, and the removed field was always `0`.
- A new cost: three engine packages as dev dependencies of `tests/runtime`
  (~230 MB, MIT/Apache-2.0, dev-only). The suite skips cleanly when they are not
  installed, and is mandatory under `RUNTIME_REQUIRE_ENGINES=1`.
