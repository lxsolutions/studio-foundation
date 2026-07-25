# Studio Foundation

**An AI-native, open-source game-development toolkit with a maintained Godot
4.7.1 WebGPU distribution path.**

Attribution and maintenance are separate: the initial backend lineage is David
Walter's MIT-licensed [`dwalter/godotwebgpu`](https://github.com/dwalter/godotwebgpu)
work; Studio Foundation maintains the Godot 4.7.1 port, scoped patch curation,
renderer and shader fixes, build/export pipeline, browser validation, release
evidence, MCP tooling, and AI-native distribution layer. Official
[Godot](https://github.com/godotengine/godot) remains the sole active upstream.

## Published release vs current main

<!-- public-evidence-current-status:start -->

| State | Source / base | Patch range | Renderer | Artifact availability | Hardware verification | Current limitation |
|---|---|---|---|---|---|---|
| Official upstream | Godot 4.7.1 stable, commit `a13da4feb8d8aefc283c3763d33a2f170a18d541` | None | Official native renderers; WebGL 2 uses Compatibility | Official Godot downloads | Studio Foundation makes no WebGPU claim for this unpatched row | Does not contain the Studio Foundation WebGPU integration |
| Published `godot-4.7.1-webgpu-p0014` | Official commit above plus the locked Studio Foundation series | `0001–0014` (14 patches) | WebGPU **Forward Mobile** | [Release/debug templates](https://github.com/lxsolutions/studio-foundation/releases/tag/godot-4.7.1-webgpu-p0014) are downloadable; hashes are locked below | NVIDIA Tesla P40 through Chrome/WebGPU: minimal lit + shadowed 3D and three game scenes, with 0 `GPUValidationError` | Forward Mobile lacks several Forward+ effects; these archives do **not** contain patches `0015–0022` |
| Current `main` development state | Same official commit plus the current locked series | `0001–0022` (22 patches) | Forward Mobile still renders; WebGPU Forward+ is an unfinished investigation path | Source patches only; **no p0022 templates are published** | Forward+ was run on the same P40; pipeline warm-up completes, but 18 `GPUValidationError` entries remain and no frame renders | Forward+ WebGPU is not release-ready; current `main` is not the p0014 artifact |

<!-- public-evidence-current-status:end -->

The canonical claim-to-proof map is
[WebGPU evidence](docs/architecture/webgpu-evidence.md). Complete pins and legal
details remain in [NOTICE.md](NOTICE.md) and
[WebGPU integration provenance](docs/architecture/webgpu-integration.md).

### ▶ [Play the published p0014 Chariot demo](https://lxsolutions.github.io/studio-foundation/)

The landing page feature-detects WebGPU before launch. Initial load takes roughly
15–30 seconds depending on the connection; the p0014 measurement attributes most
of that time to downloading the ~46 MB wasm, with pipeline construction taking
about 2 seconds. See
[payload and startup](docs/architecture/webgpu-payload-and-startup.md).

[![The Chariot Club: a Roman colosseum with crowded stands and chariots, rendered in Godot through WebGPU](docs/images/webgpu-chariot.png)](https://lxsolutions.github.io/studio-foundation/)

***The Chariot Club*** *— a Roman colosseum scene with crowded stands, chariot
teams, and real-time shadows, rendered by the published p0014 Forward Mobile
templates. On the P40 verification run it held 60 fps at ~490–630 draw calls and
~23M primitives per frame, with 0 `GPUValidationError`. The public URL was
re-run on that GPU.*

> **What you can rebuild:** the engine integration, minimal showcase, and Chariot
> demo source are all in this repository. Chariot is public for reproducibility,
> not relicensed: under [`games/LICENSE`](games/LICENSE), a game directory
> without its own license remains all rights reserved. Foundation code remains
> under the root [LICENSE](LICENSE).

<details>
<summary>Minimal lit and shadowed 3D reproduction scene</summary>

[![Six PBR meshes with a directional light and real-time shadows](docs/images/webgpu-3d-lit-shadows.png)](https://lxsolutions.github.io/studio-foundation/showcase/index.html)

[`webgpu_showcase.gd`](templates/godot-game/project/scenes/webgpu_showcase.gd)
builds six PBR meshes, a directional light, and real-time shadow mapping in code
with no external assets. The p0014 P40 run measured 59–60 fps, 36 draws/frame,
and 0 `GPUValidationError`.
[Run the showcase](https://lxsolutions.github.io/studio-foundation/showcase/index.html).

</details>

Useful public links:
[live demo](https://lxsolutions.github.io/studio-foundation/) ·
[minimal showcase](https://lxsolutions.github.io/studio-foundation/showcase/index.html) ·
[p0014 release](https://github.com/lxsolutions/studio-foundation/releases/tag/godot-4.7.1-webgpu-p0014) ·
[evidence matrix](docs/architecture/webgpu-evidence.md) ·
[repository](https://github.com/lxsolutions/studio-foundation)

## AI-native positioning

“AI-native” is the project's declared operating model, not a verification claim.
Measured renderer and release claims are kept in the evidence matrix. The
AI-facing surface includes:

- An MCP server under [`tools/studio-mcp`](tools/studio-mcp), with its security
  boundary in [`studio_tools/mcp`](tools/pylib/studio_tools/mcp).
- Agent operating agreements in [`AGENTS.md`](AGENTS.md),
  [`CLAUDE.md`](CLAUDE.md), and [`docs/agents`](docs/agents).
- An AI-driven Blender asset pipeline documented by
  [ADR 0006](docs/adr/0006-blender-master-asset-pipeline.md).
- Checksum-locked patches, artifacts, and public validation commands.

Official Godot stays upstream. Studio Foundation owns the distribution, not the
engine ([ADR 0008](docs/adr/0008-own-the-distribution-not-the-engine.md)).

## Quick start

Prerequisites are reported by `just doctor`. Fast repository checks require
Python 3.11; Godot and the engine toolchain are needed only for their suites.

```sh
git clone https://github.com/lxsolutions/studio-foundation.git
cd studio-foundation
just doctor
just bootstrap
just test
```

Without `just`, run `powershell scripts/bootstrap.ps1` on Windows or
`sh scripts/bootstrap.sh` on Linux, macOS, or WSL2.

### Use the published WebGPU templates

The current download is
[`godot-4.7.1-webgpu-p0014`](https://github.com/lxsolutions/studio-foundation/releases/tag/godot-4.7.1-webgpu-p0014):
official Godot 4.7.1 plus patches `0001–0014`, using Forward Mobile and
`threads=no`. It does not contain current-main patches `0015–0022`.

Point a web preset's `custom_template/release` and `custom_template/debug` at
the downloaded archives, then export with:

```sh
just export-browser-webgpu
```

That command applies the WebGPU handoff the official editor cannot emit. A bare
editor export lacks the WebGPU `renderingDriver` and CLI arguments and will not
start with these templates. The published hashes are:

| p0014 asset | Bytes | SHA-256 |
|---|---:|---|
| `godot.web.template_release.webgpu.zip` | 11,910,848 | `9f137f0b58c9e7c56d3430feb8fd00b1223d68d3b07b0fb5fcf2cadad8edea9b` |
| `godot.web.template_debug.webgpu.zip` | 11,729,626 | `659ad2ee4af91835a92aec8d8e1213c9ab4e91a2bc99083c69d352ce134fe539` |

These are the GitHub release bytes, independently downloadable from the
locally accepted build pair recorded under
`[artifacts.export_templates]`. Both identities are retained in
[engine-lock.toml](engine/engine-lock.toml).

### Build current main yourself

```sh
just engine-versions
just engine-fetch
just engine-build
just engine-validate
just export-browser-webgpu
```

This applies all 22 current patches. It produces a local development build, not
the published p0014 release. The exact Emscripten version and Emdawn backport are
pinned in [engine-lock.toml](engine/engine-lock.toml); the full process is in
[the WebGPU update runbook](docs/runbooks/godot-webgpu-update.md).

## Verified capabilities and limits

| Capability | Current evidence boundary |
|---|---|
| Official base and lineage | Full Godot and David Walter lineage commits are locked in [engine-lock.toml](engine/engine-lock.toml), [NOTICE.md](NOTICE.md), and the [provenance document](docs/architecture/webgpu-integration.md) |
| Patch reproducibility | `just engine-verify-patches` verifies all 22 checksums and ordering; `verify_patch_apply.py` applies them to a pristine official checkout |
| Published templates | Only p0014 is published; its two release hashes are in the lock and the [evidence matrix](docs/architecture/webgpu-evidence.md) |
| WebGPU-only browser context | The browser probe requires adapter, device, and WebGPU canvas requests and rejects WebGL/WebGL 2 requests |
| Forward Mobile 3D | Minimal lit + shadowed 3D, Chariot, Riftline, and The Deep were verified on an NVIDIA Tesla P40 with 0 `GPUValidationError` using p0014 |
| WebGPU vs WebGL 2 A/B | The p0014 test used the same game, scene, machine, browser, and harness; renderer and engine build changed together, so it is not a single-variable benchmark |
| Forward+ WebGPU | Current main has been hardware-run through patch 0022; 18 validation errors remain and no rendered frame was produced |
| Known regression | The p0014 web build failed one Jolt concave terrain collider that the stock WebGL 2 build accepted; rendering was unaffected, physics was not |

Detailed commands, exact evidence, applicable releases, and caveats are in
[webgpu-evidence.md](docs/architecture/webgpu-evidence.md).

WebGPU support remains **beta**. The published p0014 templates use Forward
Mobile, which does not provide the Forward+ SSAO, SSIL, SSR, SDFGI, VoxelGI, or
volumetric-fog paths. The current Forward+ work is hardware-tested investigation,
not a rendering or release claim.

Not yet claimed: Safari/iOS validation, native Android/iOS device runs, non-NVIDIA
GPU validation, or automated GPU coverage in public CI. See
[BOOTSTRAP_REPORT.md](BOOTSTRAP_REPORT.md) and the dated
[runtime investigation log](docs/architecture/webgpu-runtime-status.md).

Performance and startup measurements remain explicitly tied to p0014:

- [WebGPU vs WebGL 2 and game verification](docs/architecture/webgpu-performance.md)
- [Payload size and startup](docs/architecture/webgpu-payload-and-startup.md)

## Included components

- A neutral Godot 4.7.1 project template and reusable `studio_core` addon.
- WebGPU export tooling with an official WebGL 2 fallback.
- Browser smoke, screenshot, visual-regression, benchmark, and release checks.
- An MCP server and agent workflow documentation.
- Blender-to-glTF validation and export tools.
- Optional Rust API/session scaffolding and PostgreSQL development setup.
- An optional Nakama adapter that forwards opaque application payloads.

The optional backend is scaffolding, not a required architecture. A consuming
game owns its content, rules, schemas, identity policy, persistence semantics,
and deployment.

## Repository layout

| Path | Purpose |
|---|---|
| `engine/` | Official Godot pin, WebGPU patches, build commands, and artifact records |
| `templates/godot-game/` | Mechanics-neutral Godot client and optional server template |
| `shared/godot-addons/studio_core/` | Reusable Godot services and platform interfaces |
| `services/` | Optional Rust protocol, session, API, and persistence scaffolding |
| `infra/` | Optional local PostgreSQL, Nakama, and tracing services |
| `tools/` | Engine, asset, export, browser, release, MCP, and repository tooling |
| `tests/` | Cross-language, browser, integration, performance, and visual checks |
| `docs/` | Decisions, architecture notes, evidence, and runbooks |

## Common commands

| Command | Purpose |
|---|---|
| `just test` / `just lint` | Run the fast test and lint suites |
| `just test-godot` / `test-rust` / `test-python` | Run one implementation suite |
| `just public-evidence-validate` | Verify public current-state claims against the lock |
| `just NAME=my_game DISPLAY_NAME="My Game" new-game` | Generate a neutral Godot project |
| `just export-browser-webgl [GAME]` | Export with official WebGL 2 templates |
| `just export-browser-webgpu [GAME]` | Export with locally selected WebGPU templates |
| `just run-browser-smoke` | Check browser boot, console output, canvas, and renderer |
| `just ci-local` | Run the local pull-request acceptance suite |

Run `just` to list every supported command.

## Contributing and license

Material engine changes require tests, updated evidence, and the relevant ADR.
Contributor workflow is in
[WORKING_AGREEMENTS.md](docs/agents/WORKING_AGREEMENTS.md). Security scope and
private reporting instructions are in [SECURITY.md](SECURITY.md).

Foundation code, tooling, templates, documentation, and infrastructure are
dual-licensed under MIT and CC BY 4.0; see [LICENSE](LICENSE). Third-party
attribution is in [NOTICE.md](NOTICE.md) and
[dependency-licenses.md](docs/architecture/dependency-licenses.md).
