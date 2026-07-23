# An agent-operable Godot foundation

Studio Foundation is designed so coding agents can make bounded changes and
produce the same evidence expected from human contributors. That is a workflow
property, not a claim that agents replace design judgment or release ownership.

## The contract

- `just` recipes define supported development and validation entry points.
- `studio-mcp` exposes narrow, audited operations.
- ADRs and working agreements establish scope and safety constraints.
- Protocol fixtures and visual comparisons catch cross-language and rendering
  regressions.
- `BOOTSTRAP_REPORT.md` separates measured results from plans.
- Repository-local engine patches make browser integration reviewable and
  reproducible without another LX Solutions repository.

## Foundation layers

```text
Official Godot 4.7.1
  + Studio Foundation WebGPU patches and WebGL fallback
  + shared Godot addons and mechanics-neutral templates
  + Blender asset validation and export
  + optional Rust API, session, protocol, and persistence scaffolding
  + optional PostgreSQL, Nakama identity bridge, and tracing infrastructure
  + tests, benchmarks, captures, and release checks
```

## Engineering priorities

1. Keep the Godot client and browser export paths reproducible.
2. Maintain a release-safe WebGL fallback while WebGPU remains beta.
3. Keep shared protocols and services mechanics-neutral and replaceable.
4. Make asset and export workflows deterministic and observable.
5. Give agents small commands with explicit inputs, outputs, and failure modes.
6. Record evidence before expanding platform claims.

## Success measures

Useful measurements include time from clean clone to passing tests, percentage
of commands runnable without editor interaction, patch-update effort across
Godot releases, browser smoke/visual reliability, real-device coverage, and the
ratio of agent-authored changes that pass review without rework.

Studio Foundation succeeds when it reduces the cost and uncertainty of shipping
Godot games for its adopters. It does not dictate the gameplay or product
architecture of consuming repositories.
