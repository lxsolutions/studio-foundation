# Studio Foundation - Goal

Studio Foundation is the shared, public Godot platform for a small game studio
shipping multiple first-class games from one shared project per game across:

- Web browsers, with WebGPU preferred and WebGL 2 as the maintained fallback
- iOS and Android
- Windows, Linux, and macOS
- Dedicated multiplayer servers

This repository contains platform capabilities rather than a single game's
mechanics: Godot integration, shared addons, asset processing, backend services,
tooling, tests, CI, documentation, and agent operating agreements.

## Scope boundary

Godot is the only client runtime standardized by this public repository.
Babylon.js, Capacitor, or other runtimes chosen by individual private products
do not become Studio Foundation dependencies unless a future public ADR
explicitly changes that decision.

## Non-negotiable principles

1. Prefer free and open-source, commercial-use-compatible dependencies.
2. Require no proprietary cloud or paid backend platform.
3. Keep local development usable offline after dependencies are cached.
4. Maintain one shared Godot project per game, not separate browser/mobile clients.
5. Share source assets, systems, data formats, protocols, and backend services.
6. Absorb platform differences through runtime quality profiles and interfaces.
7. Keep generated files and build outputs out of the source-of-truth role.
8. Give humans and agents documented commands, acceptance criteria, and tests.
9. Optimize for a small human team working with coding agents.
10. Add infrastructure only after a demonstrated requirement and an ADR.

## Architecture in one paragraph

Official Godot 4.7.1 is the pinned editor and engine; gameplay uses GDScript,
with native extensions reserved for measured hotspots. Browser WebGPU templates
are built from official Godot plus a checksum-pinned patch series committed in
`engine/patches/`; official WebGL 2 templates remain the fallback. Blender is
the master asset source and exports deterministic glTF/GLB. Rust services provide
authoritative simulation and networking with PostgreSQL as durable state.
Docker Compose runs local infrastructure, and `just` is the command front door
for humans, agents, and CI.

## Where to go next

- [README.md](README.md) - quickstart and repository map
- [docs/adr/](docs/adr/) - material decisions and rationale
- [docs/agents/WORKING_AGREEMENTS.md](docs/agents/WORKING_AGREEMENTS.md) - contribution workflow
- [engine/engine-lock.toml](engine/engine-lock.toml) - exact source and toolchain pins
- [BOOTSTRAP_REPORT.md](BOOTSTRAP_REPORT.md) - current verified evidence