# ADR 0017: TypeScript/Three.js as a peer runtime, and an engine-neutral quality layer

- Status: Proposed
- Date: 2026-07-28
- Constrains: repository scope, templates, tooling
- Amends: ADR 0016 decision 2 (scope wording), ADR 0001 (primary-engine framing)
- Related: ADR 0008, ADR 0014, `tools/gauntlet/`

## Context

Studio Foundation's stated purpose is to own the distribution and tooling layer
rather than an engine (ADR 0008), and to stay product-neutral (ADR 0016). In
practice the repository's runtime scope has been Godot-only: ADR 0016 decision 2
scopes the repository to "reusable Godot integration", and ADR 0001 names Godot
the primary engine.

Two things have changed.

**The editor is not being used.** The working mode this repository actually
serves is an agent editing source files headlessly and validating through
automated capture. Godot's integrated editor — its single largest advantage — is
not part of that loop. The repository is paying an engine's costs without
drawing its principal benefit.

**Iteration latency is the binding constraint on quality.** In a
build → capture → critique loop, output quality is a function of completed
rounds. Measured on this hardware: a capture round costs ~4 minutes on the remote
GPU host, while `tsc --noEmit` costs ~2 seconds. A statically-checked source
language converts a whole class of failures from round-cost to seconds-cost. A
Godot web export additionally interposes an export step between edit and
observation.

Separately, the browser-first bar this studio is measured against is built in
TypeScript and Three.js. The reference builds surveyed in `tools/gauntlet/BLUEPRINT.md`
are without exception browser/Three.js projects, which matters because an
agent-authored codebase is limited by how reliably the model writes the target
framework, not only by the framework's capability.

## Decision

1. **TypeScript/Three.js becomes the default runtime for new browser-first
   work.** `templates/three-game/` is a peer of `templates/godot-game/`.
2. **Godot remains a fully supported runtime**, not a deprecated one. Existing
   Godot products continue to be built, exported, validated and shipped from
   this repository. ADR 0002's WebGPU patch series is retained.
3. **ADR 0016 decision 2 is amended**: the repository's scope is reusable
   *runtime* integration — currently Godot and TypeScript/Three.js — rather than
   Godot integration specifically. Everything else in ADR 0016 stands.
4. **The quality layer is engine-neutral and shared.** `tools/gauntlet/` drives a
   URL and reads pixels, so it validates any runtime that renders in a browser.
   It is not permitted to acquire runtime-specific branching in its core; runtime
   differences belong in shot definitions and the optional runtime contract.
5. **The asset layer stays runtime-neutral.** bforge (ADR 0014) already exports
   glTF and serves both runtimes unchanged. No fork, no per-runtime variant.
6. **Runtime selection principle:** choose the runtime that reaches a verified
   result with the least agent and maintenance friction. Default to
   TypeScript/Three.js for new browser-first work; choose Godot when its built-in
   systems (animation state machines, navigation, physics, native export targets)
   save substantial work, or when a product already lives there.

## Evidence

The engine-neutrality of the quality layer is measured, not asserted. The same
harness, with no code changes, produced full reports for:

- `templates/three-game/` (TypeScript/Three.js) — 60 fps p50 on a Tesla P40
- a third-party Three.js reference build
- `games/chariot/project/exports/web-webgl/` (Godot web export) — 60 fps p50 on
  the same host

Capability and application backend are reported separately, because conflating
them overstates the claim: every run above had a hardware WebGPU adapter
*available*, while the Three.js template and the `web-webgl` export both render
through `webgl2`.

An earlier revision of this ADR claimed the `web-webgpu` export was the first
evidence that ADR 0002's patch series renders through WebGPU on hardware. **That
claim was wrong and is withdrawn.** It came from a destructive probe that created
a WebGPU context on a canvas which had none, and then reported it. With passive
detection the same export reports `no-context-requested` and renders a black
screen — see `tools/gauntlet/VERIFICATION.md` §3. This does not affect the
engine-neutrality argument, which rests on the `web-webgl` export.

## Consequences

- New browser-first projects start from `templates/three-game/`, typechecked,
  with the runtime contract wired from the first increment.
- Both templates are validated by one harness, so quality claims are comparable
  across runtimes for the first time.
- ADR 0001's "primary engine" framing narrows to "primary *Godot* engine and
  editor of record for Godot projects"; it no longer implies the only runtime.
- Godot's WebGPU patch series becomes *testable* on real hardware through
  `tools/gauntlet/harness/remote.mjs --gpu-profile webgpu`, which previously had
  no hardware path on the development host. The first such test found the
  `web-webgpu` export rendering black on a Tint shader-translation failure.
- Two runtimes mean two sets of template maintenance. This is accepted
  deliberately; the shared asset and quality layers absorb most of the
  duplication, and the alternative is worse (see below).

## Alternatives rejected

- **Replace Godot with a JavaScript engine.** Rejected in ADR 0008 and still
  rejected here. Shipped Godot products exist; the editor, physics, animation and
  native export paths have no browser equivalent; and nothing about adopting a
  second runtime requires abandoning the first.
- **Keep Godot as the sole runtime.** It taxes the actual working mode (headless,
  agent-driven, browser-first) with an export step and a weaker static-analysis
  loop, for an editor benefit that is not being consumed.
- **Adopt Babylon.js as the default instead of Three.js.** Babylon is
  TypeScript-native, which is a real advantage. But for an agent-authored
  codebase the dominant variable is how reliably the model produces working code
  in the target framework, and the evidence base is overwhelmingly Three.js.
  Babylon remains a candidate adapter, not the default.
- **Keep the quality layer outside the repository.** It is precisely the
  "distribution and validation" surface ADR 0008 says this repository should own.
