# Asha Platform Strategy: Godot Distribution, Not a New Engine

Source: external technical review (ChatGPT synthesis, 2026-07-20). Ratified here as
studio strategy. Related: ADR 0002 (WebGPU fork isolation), ADR 0007 (one world).

## Verdict

**Do not build a new engine by combining Godot, Bevy, PlayCanvas, Babylon.js, and
Three.js.** They are alternative architectures — each has its own scene graph,
renderer, material system, asset pipeline, and platform layer — not composable
modules. Combining them yields duplicated subsystems and permanent integration
debugging.

Instead we build an **Asha Godot Distribution**: official Godot as the upstream
foundation, plus the layers that differentiate the studio.

## What we own (the differentiating layers)

```
Official Godot (pinned, ADR 0002)
├── Small maintained WebGPU patch set (engine/patches, engine-lock.toml)
├── Asha editor plugins + studio_core addon (shared/godot-addons/)
├── GDScript game framework (quality profiles, not forks)
├── Rust simulation + authoritative servers (services/)
├── Blender asset cooker (tools/blender, tools/asset-pipeline)
├── Nakama + PostgreSQL authority (backend/, infra/)
├── Automated, agent-readable testing (just recipes, tests/)
└── Cross-platform build/export system (tools/godot)
```

## What we borrow from other engines (designs, not runtimes)

- **Bevy**: data-oriented ECS concepts, batched simulation, parallel scheduling,
  render-extraction and GPU-driven rendering ideas → implemented in **Rust
  beneath Godot**, never by embedding Bevy.
- **PlayCanvas**: browser startup optimization, WebGPU/WebGL capability profiles,
  asset streaming/compression, browser profiling, glTF pipeline discipline.
- **Babylon.js**: WebGPU compatibility testing matrices, material abstraction,
  capability detection, shader portability, WebXR patterns.
- **Three.js**: a *reference renderer* only — small browser experiments, WebGPU
  control cases, asset previews, internal visualization. Never spliced into Godot.

## Where AI agents spend effort

1. Production-grade Godot WebGPU support (browser builds, shader translation,
   pipeline caching, startup time, cross-browser + cross-OS testing, WebGL
   fallback, resource-lifetime validation, visual regression, GPU benchmarks).
2. Rust simulation framework (entity storage, spatial indexing, pathfinding,
   interest management, snapshot interpolation, procedural generation, replays,
   authoritative servers) exposed to Godot through narrow APIs.
3. Studio-wide Godot framework addons (accounts/sessions, settings, saves,
   graphics profiles, input, telemetry, asset manifests, streaming, i18n, a11y,
   debugging, automated captures).
4. Blender production pipeline (validators, LOD/collision generation, GLB export,
   skeleton/animation checks, texture compression, budget reports, provenance).
5. Agent-readable testing infrastructure (`just test`, `just export-webgpu`,
   `just export-webgl`, `just benchmark`, `just capture-scene`,
   `just compare-screenshots`, `just simulate-clients COUNT=100`,
   `just validate-assets`).

## When a truly custom engine would make sense

Only after: (1) one or two serious shipped games, (2) the same Godot limitation
repeatedly blocks multiple products, (3) a dedicated human engine architect is on
staff, (4) the limitation cannot be fixed via module, Rust library, editor plugin,
or renderer patch, and (5) we accept maintaining browser/mobile/desktop/console
backends for years (console SDKs are private/NDA — Godot already has licensed
third-party console paths). None of these hold today.
