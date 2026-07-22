# Studio Foundation

A Godot-first, open-source foundation for building and operating games across
web, mobile, desktop, and dedicated servers from one shared project per game.

Client: pinned official **Godot 4.7.1** and **GDScript**. Browser: official
**WebGL 2** fallback plus the repository's beta **WebGPU integration**. Assets:
**Blender to glTF/GLB**. Backend: **Rust** (Tokio/Axum/SQLx) and
**PostgreSQL**. Infrastructure: **Docker Compose**. Task runner: **just**.

![Godot 4.7.1 rendering through the Studio Foundation WebGPU integration](templates/godot-game/project/captures/web-webgpu.png)

The WebGPU source is self-contained and reproducible:
`engine-fetch` checks out official Godot at the locked commit, verifies the
committed patch checksums, and applies the patches into a disposable local
worktree. Studio Foundation completed the 4.7.1 forward port from earlier
MIT-licensed WebGPU work and owns its maintenance, patch curation, build,
fallback, and validation system. Historical source attribution is documented in
[NOTICE.md](NOTICE.md); the detailed engineering boundary is in
[WebGPU integration provenance](docs/architecture/webgpu-integration.md).
This public repository deliberately has one client runtime: Godot. Alternative
JavaScript engines used by individual products are outside Studio Foundation's
architecture and dependency graph.

Read [GOAL.md](GOAL.md) first. Decisions live in [docs/adr/](docs/adr/).
Evidence for current platform claims lives in
[BOOTSTRAP_REPORT.md](BOOTSTRAP_REPORT.md).

## Quickstart

```sh
git clone <this-repo> && cd studio-foundation
just doctor
just bootstrap
just services-up
just test
# Optional live authority proof: run `just asha-server`, then `just nakama-probe`
```

No `just`? Bootstrap directly with `powershell scripts/bootstrap.ps1` on
Windows or `sh scripts/bootstrap.sh` on Linux, macOS, or WSL2.

## Everyday commands

| Command | Purpose |
|---|---|
| `just doctor` | Report required, optional, and platform-specific tooling |
| `just test` / `just lint` | Run the fast test and lint suites |
| `just test-rust` / `just test-godot` / `just test-python` | Run a narrow suite |
| `just services-up` / `services-down` / `db-reset` / `db-seed` / `db-backup` | Operate local infrastructure |
| `just nakama-build` / `nakama-test` / `nakama-up` | Build and run the optional Nakama boundary |
| `just asha-server` / `nakama-probe` | Run and probe the private Rust authority |
| `just asset-validate FILE` / `asset-export FILE` / `asset-cook PROFILE` | Operate the Blender asset pipeline |
| `just godot-sync-addons` | Copy the shared addon into game projects |
| `just export-browser-webgl [GAME]` | Export the WebGL 2 fallback with official templates |
| `just export-browser-webgpu [GAME]` | Export WebGPU using locally built patched templates |
| `just run-browser-smoke` | Serve an export and run the browser console/canvas smoke test |
| `just NAME=my_game DISPLAY_NAME="My Game" new-game` | Generate a Godot game from the template |
| `just engine-fetch` / `engine-build` | Prepare and build the locked in-repository WebGPU integration |
| `just engine-rebase --dry-run --json` | Test the patch series against another official Godot ref |
| `just benchmark-scene` | Run the finite Godot scene benchmark |
| `just visual-baseline` / `visual-compare` | Capture and compare browser-rendered baselines |
| `just release-validate --allow-dirty` / `sbom` / `audit` | Validate release inputs and dependency policy |
| `just demo-connectivity` | Prove Godot to API/PostgreSQL and game-server connectivity |
| `just ci-local` | Run the same checks used by CI |

## Repository map

| Path | Contents |
|---|---|
| `engine/` | Official Godot pin, checksummed WebGPU patches, source preparation, build tooling, and artifact metadata |
| `shared/godot-addons/studio_core/` | Reusable Godot services, platform interfaces, settings, networking, accessibility, and diagnostics |
| `shared/protocol/`, `shared/schemas/`, `shared/test-fixtures/` | Cross-language contracts, schemas, and golden fixtures |
| `templates/godot-game/` | Godot game template, server crate, asset layout, docs, and tests |
| `services/` | Rust services and shared simulation/protocol crates |
| `tools/` | Asset, Godot, release, infrastructure, benchmark, screenshot, and MCP tooling |
| `infra/` | Docker Compose, PostgreSQL, Nakama, observability, and environment models |
| `tests/` | Browser, integration, performance, protocol, and visual regression tests |
| `docs/` | Architecture, ADRs, workflows, platform guidance, security, and runbooks |
| `games/` | Generated game projects and living examples |
| `.github/` | CI workflows and contribution templates |

## Platform status

Godot is the editor and client runtime of record. WebGL 2 is the release-safe
browser fallback. The WebGPU integration is beta and is considered green only
when its build, browser smoke, and visual comparison evidence is current.
See [BOOTSTRAP_REPORT.md](BOOTSTRAP_REPORT.md) for the evidence-backed matrix;
Safari/iOS and other hardware-specific claims require real-device verification.

## For AI agents

Start with [AGENTS.md](AGENTS.md) or [CLAUDE.md](CLAUDE.md), then follow
[docs/agents/WORKING_AGREEMENTS.md](docs/agents/WORKING_AGREEMENTS.md).
Reusable skills and MCP setup live under [docs/agents/](docs/agents/).

## License

Platform code, tooling, and infrastructure are dual-licensed under MIT and
CC BY 4.0; see [LICENSE](LICENSE). Content under [games/](games/) is
proprietary and is not covered by that platform license; see
[games/LICENSE](games/LICENSE).

Dependency attribution and review:
[docs/architecture/dependency-licenses.md](docs/architecture/dependency-licenses.md).