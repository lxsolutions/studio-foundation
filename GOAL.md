# Studio Foundation — Goal

This repository is the shared platform for a small open-source game studio that ships
multiple first-class games from **one shared project per game** across:

- Web browsers (WebGPU preferred, WebGL 2 fallback)
- Native iOS and Android
- Windows, Linux, macOS
- Dedicated multiplayer servers

## Intended games (not built here)

1. Diablo-style action RPG
2. Persistent social MMO (WoW / Puzzle Pirates style)
3. Combined-arms multiplayer (Battlefield 1942 / original Battlefront II style)
4. Smaller browser-first and mobile games

This repo contains **no game mechanics**. It contains the engine integration, shared
Godot addon, asset pipeline, backend services, tooling, tests, CI, documentation, and
AI-agent operating system that every game reuses.

## Non-negotiable principles

1. Free and open-source first; commercial-use-compatible licensing (MIT/Apache-2.0/BSD/ISC/Zlib preferred).
2. No required proprietary cloud or paid backend platform. Every hosted service has a local/self-hosted equivalent.
3. Local development works offline once dependencies are cached.
4. One shared game project per game — never separate browser and mobile codebases.
5. Shared source assets, gameplay systems, data formats, network protocol, and backend services.
6. Runtime **quality profiles** (not forks) absorb platform differences; rendering/platform differences stay behind interfaces.
7. Generated files and build outputs are never the source of truth.
8. AI agents work through tests, acceptance criteria, documented commands, and pull requests.
9. Optimize for a small human team multiplied by Codex, Claude Code, and Kimi Code.
10. Simple, maintainable foundations. No Kubernetes, microservices, Redis, or message queues until a demonstrated requirement exists (record the demonstration in an ADR).

## Architecture in one paragraph

Official **Godot 4.x** is the engine; gameplay is **GDScript** (C++/GDExtension only for
measured hotspots; no C# in shared client code because browser support must remain
possible). Browser builds use the pinned, isolated **godotwebgpu fork** as an unofficial
WebGPU export backend with official **WebGL 2 Compatibility** export as the fallback.
**Blender** is the master asset source, driven headlessly into glTF/GLB by a
deterministic pipeline. The backend is a **Rust** workspace (Tokio/Axum/SQLx) with
**PostgreSQL** as the source of truth and a transport abstraction (WebSocket baseline;
WebTransport/QUIC later) for server-authoritative networking. Local infrastructure runs
in **Docker Compose**. `just` is the task-runner front door for humans, agents, and CI.

## Where to go next

- `README.md` — quickstart and repo map
- `docs/adr/` — every material decision and why
- `docs/agents/WORKING_AGREEMENTS.md` — how agents (and humans) work here
- `engine/engine-lock.toml` — exact engine/toolchain pins
- `BOOTSTRAP_REPORT.md` — what verifiably works on which platform today
