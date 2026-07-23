# Studio Foundation - Goal

Studio Foundation is a public, reusable Godot toolkit for teams shipping games
across:

- Web browsers, with WebGPU preferred and WebGL 2 as the maintained fallback
- iOS and Android
- Windows, Linux, and macOS
- Optional dedicated multiplayer servers

This repository contains universal capabilities rather than any one game's
content or mechanics: Godot integration, shared addons, asset processing,
mechanics-neutral transport and service scaffolding, tooling, tests, CI
guidance, documentation, and agent operating agreements.

## Scope boundary

Official Godot is the only client runtime standardized here. Product code,
gameplay schemas, product-specific identity policy, and production deployments
live in consuming repositories. Babylon.js, Capacitor, or any other runtime
selected by a product does not become a Studio Foundation dependency unless a
future public ADR explicitly changes that decision.

The optional Rust server establishes sessions and can forward opaque
application payloads to a handler supplied by a game. Foundation does not define
the payload schema or gameplay semantics.

## Non-negotiable principles

1. Prefer free and open-source, commercial-use-compatible dependencies.
2. Require no proprietary cloud or paid backend platform.
3. Keep local development usable offline after dependencies are cached.
4. Maintain one shared Godot project per game, not separate browser/mobile clients.
5. Share only genuinely reusable systems, data formats, protocols, and backend seams.
6. Absorb platform differences through runtime quality profiles and interfaces.
7. Keep generated files and build outputs out of the source-of-truth role.
8. Give humans and agents documented commands, acceptance criteria, and tests.
9. Optimize for small teams working with coding agents.
10. Add infrastructure only after a demonstrated, product-independent requirement and an ADR.
11. Keep product content, mechanics, business rules, and deployment credentials outside this repository.

## Architecture in one paragraph

Official Godot 4.7.1 is the pinned editor and engine; projects use GDScript,
with native extensions reserved for measured hotspots. Browser WebGPU templates
are built from official Godot plus a checksum-pinned patch series committed in
`engine/patches/`; official WebGL 2 templates remain the fallback. Blender is
the master asset source and exports deterministic glTF/GLB. Generic Rust
services provide API, WebSocket session, protocol, and persistence scaffolding;
games opt into and extend those seams. Docker Compose runs optional local
PostgreSQL, a mechanics-neutral Nakama bridge, and observability
infrastructure, and `just` is the command front door for humans, agents, and
CI.

## Where to go next

- [README.md](README.md) - quickstart and repository map
- [docs/adr/](docs/adr/) - material decisions and rationale
- [docs/agents/WORKING_AGREEMENTS.md](docs/agents/WORKING_AGREEMENTS.md) - contribution workflow
- [engine/engine-lock.toml](engine/engine-lock.toml) - exact source and toolchain pins
- [BOOTSTRAP_REPORT.md](BOOTSTRAP_REPORT.md) - current verified evidence
