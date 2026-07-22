# Studio Foundation: a Godot distribution, not a new engine

Related: ADR 0002 (WebGPU patch series), ADR 0007 (authoritative world), and
ADR 0008 (distribution boundary).

## Decision

Studio Foundation builds around official Godot instead of combining several
client engines into a custom runtime. Scene graphs, renderers, material systems,
asset pipelines, and platform layers do not become simpler when multiple engines
are embedded together.

## What the repository owns

```text
Official Godot (pinned)
  + scoped WebGPU patch series and WebGL fallback
  + studio_core shared addon and Godot project template
  + GDScript platform services and quality profiles
  + Rust simulation and authoritative servers
  + Blender-to-GLB validation and cooking
  + PostgreSQL and optional Nakama infrastructure
  + agent-readable tests, exports, benchmarks, and release checks
```

The repository borrows engineering ideas from the broader game-development
ecosystem, but it does not add another client runtime merely to adopt those
ideas.

## Where agents should spend effort

1. Browser build, shader, startup, resource-lifetime, compatibility, and visual
   validation work for the Godot WebGPU integration
2. Rust simulation, spatial, interest-management, replay, and authority systems
3. Reusable Godot services for sessions, settings, input, networking,
   accessibility, diagnostics, and content loading
4. Deterministic Blender and Godot asset validation
5. Small commands that build, test, export, capture, compare, and report evidence

## Custom-engine threshold

Reconsider the boundary only after shipped games demonstrate the same blocking
Godot limitation repeatedly, narrower extensions cannot solve it, experienced
engine maintainers are available, and the team accepts years of responsibility
for browser, mobile, desktop, and console integration. Those conditions do not
hold today.