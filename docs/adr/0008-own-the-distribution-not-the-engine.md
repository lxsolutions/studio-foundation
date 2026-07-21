# ADR 0008: Own the Distribution, Not the Engine

Status: Accepted (2026-07-20)
Constrains: engine strategy, `engine/engine-lock.toml`, ADR 0002, ADR 0007.
Related: `docs/architecture/asha-platform-strategy.md`, `NOTICE.md`.

## Context

After evaluating the WebGPU export path (ADR 0002), the studio hit the structural
limits of consuming the `dwalter/godotwebgpu` backend as a raw clone: it is
beta, largely AI-generated, has no release line, and lags official Godot by a
minor (4.6.2 vs our 4.7.1 editor), producing a runtime pack-format mismatch.
We were already maintaining an un-upstreamable `webgpu-4.7.1` merge — a de-facto
fork. The question arose: fork `dwalter/godotwebgpu`, fork `godotengine/godot`,
or take a different strategic direction entirely.

## Decision

Three commitments, made together:

1. **Fork the WebGPU backend — `dwalter/godotwebgpu` → `lxsolutions/godot-webgpu`.**
   This is vendoring a scoped beta component, not forking an engine. We own the
   `webgpu-4.7.1` line; upstream stays fetch-only; every change passes the ADR
   0002 gate. If upstream Godot ships native WebGPU, this component is deleted
   with no structural loss.

2. **Never fork `godotengine/godot`.** Official Godot remains a clean upstream
   and the editor of record. Forking it would put the studio on the treadmill of
   maintaining the editor, scene/animation/UI systems, importer, physics, and
   platform/console export surface — precisely the surface a small team must not
   own. Official Godot is only replaced if all five custom-engine conditions in
   `asha-platform-strategy.md` are met (they are not).

3. **Own the distribution, not the engine.** The strategic asset is the layer
   above Godot: the pinned patch set, editor plugins, `studio_core` addon, Rust
   simulation/authoritative servers, Blender asset cooker, Nakama+PostgreSQL
   authority, and the agent-readable test/export/benchmark/capture/compare
   commands. That distribution is the moat. The engine stays borrowed.

## Consequences

- `engine-lock.toml`'s `godot.webgpu_fork.repo` points at our fork; `upstream`
  records the origin. `NOTICE.md` carries the MIT + AI-generated attribution.
- One-line rule for contributors and agents: **fork the backend because we must;
  never fork Godot because we'd drown; own the distribution, not the engine.**
- Future Godot version bumps follow `docs/runbooks/godot-fork-rebase.md`.

## Alternatives rejected

- Keep consuming the upstream clone: no 4.7 line exists; the pack-format gap
  recurs every release.
- Fork official Godot: converts borrowed leverage into permanent maintenance
  debt across the entire engine surface.
