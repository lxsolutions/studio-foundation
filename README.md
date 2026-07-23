# Studio Foundation

A Godot-first, open-source foundation for building, testing, exporting, and
operating games across web, mobile, desktop, and dedicated servers.

Client: pinned official **Godot 4.7.1** and **GDScript**. Browser: official
**WebGL 2** fallback plus the repository's beta **WebGPU integration**. Assets:
**Blender to glTF/GLB**. Optional backend scaffolding: **Rust**
(Tokio/Axum/SQLx) and **PostgreSQL**. Infrastructure: **Docker Compose**. Task
runner: **just**.

![Godot 4.7.1 rendering through the Studio Foundation WebGPU integration](templates/godot-game/project/captures/web-webgpu.png)

The WebGPU source is self-contained and reproducible:
`engine-fetch` checks out official Godot at the locked commit, verifies the
committed patch checksums, and applies the patches into a disposable local
worktree. Studio Foundation completed the 4.7.1 forward port from earlier
MIT-licensed WebGPU work and owns its maintenance, patch curation, build,
fallback, and validation system. Historical source attribution is documented in
[NOTICE.md](NOTICE.md); the detailed engineering boundary is in
[WebGPU integration provenance](docs/architecture/webgpu-integration.md).

Read [GOAL.md](GOAL.md) first. Decisions live in [docs/adr/](docs/adr/).
Evidence for current platform claims lives in
[BOOTSTRAP_REPORT.md](BOOTSTRAP_REPORT.md).

## Universal scope

Studio Foundation standardizes reusable engine integration, Godot addons,
project generation, asset processing, transport contracts, export pipelines,
browser validation, release evidence, and optional service scaffolding.

It does not contain or prescribe a particular game's content, mechanics,
domain schema, persistent-state semantics, product-specific identity policy, or
production deployment. Those decisions belong in consuming game repositories. The optional dedicated server handles
connection lifecycle and opaque application payloads through a game-supplied
handler; Foundation does not interpret the payload.

Alternative client engines used by individual products are likewise outside
this repository's architecture and dependency graph.

## Independent game proof

[OSWT on Asha Arena](https://ashaarena.com/games/oswt) is a separate, playable
3D game repository consuming Studio Foundation rather than a Foundation starter
scene. Its integration branch adds Studio Core, the locked Godot 4.7.1 WebGPU
export path, 55 headless gameplay checks, browser validation, and an in-game
engine-proof panel. Publication is accepted only with a
[machine-readable build record](https://ashaarena.com/games/oswt/play/build-provenance.json)
covering exact source, patch, template, export, and verification hashes. This is
team-authored use-case evidence, not a claim of unrelated third-party adoption.

## Quickstart

```sh
git clone <this-repo> && cd studio-foundation
just doctor
just bootstrap
just services-up
just test
```

No `just`? Bootstrap directly with `powershell scripts/bootstrap.ps1` on
Windows or `sh scripts/bootstrap.sh` on Linux, macOS, or WSL2.

## Everyday commands

| Command | Purpose |
|---|---|
| `just doctor` | Report required, optional, and platform-specific tooling |
| `just test` / `just lint` | Run the fast test and lint suites |
| `just test-rust` / `test-godot` / `test-python` | Run a narrow suite |
| `just services-up` / `services-down` / `db-reset` / `db-seed` / `db-backup` | Operate the optional local PostgreSQL stack |
| `just nakama-build` / `nakama-test` / `nakama-up` / `nakama-probe` | Build, test, run, and probe the optional neutral Nakama bridge |
| `just asset-validate FILE` / `asset-export FILE` / `asset-cook PROFILE` | Operate the Blender asset pipeline |
| `just godot-sync-addons` | Copy the shared addon into generated game projects |
| `just export-browser-webgl [GAME]` | Export the WebGL 2 fallback with official templates |
| `just export-browser-webgpu [GAME]` | Export WebGPU using locally built patched templates |
| `just run-browser-smoke` | Serve an export and run the browser console/canvas smoke test |
| `just NAME=my_game DISPLAY_NAME="My Game" new-game` | Generate a Godot game from the template |
| `just engine-fetch` / `engine-build` | Prepare and build the locked WebGPU integration |
| `just engine-rebase --dry-run --json` | Test the patch series against another official Godot ref |
| `just benchmark-scene` | Run the finite Godot scene benchmark |
| `just visual-baseline` / `visual-compare` | Capture and compare browser-rendered baselines |
| `just release-validate --allow-dirty` / `sbom` / `audit` | Validate release inputs and dependency policy |
| `just demo-connectivity` | Prove Godot-to-API/PostgreSQL and server connectivity |
| `just ci-local` | Run the same checks used by CI |

## Repository map

| Path | Contents |
|---|---|
| `engine/` | Official Godot pin, checksummed WebGPU patches, source preparation, build tooling, and artifact metadata |
| `shared/godot-addons/studio_core/` | Reusable Godot services, platform interfaces, settings, networking, accessibility, and diagnostics |
| `shared/protocol/`, `shared/schemas/`, `shared/test-fixtures/` | Cross-language contracts, schemas, and golden fixtures |
| `templates/godot-game/` | Mechanics-neutral Godot project and optional server templates |
| `services/` | Generic Rust API, transport, protocol, persistence, and administration scaffolding |
| `tools/` | Asset, Godot, release, infrastructure, benchmark, screenshot, and MCP tooling |
| `infra/` | Optional PostgreSQL, Nakama bridge, and observability development infrastructure |
| `tests/` | Browser, integration, performance, protocol, and visual regression tests |
| `docs/` | Architecture, ADRs, workflows, platform guidance, security, and runbooks |
| `games/` | Local output location for generated or separately licensed game projects |

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

Foundation code, tooling, templates, documentation, and infrastructure are
dual-licensed under MIT and CC BY 4.0; see [LICENSE](LICENSE). Generated or
external game projects choose their own licenses; the default local
`games/` policy is documented in [games/LICENSE](games/LICENSE).

Dependency attribution and review:
[docs/architecture/dependency-licenses.md](docs/architecture/dependency-licenses.md).
