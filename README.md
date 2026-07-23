# Studio Foundation

Reproducible Godot 4.7.1 browser builds, a mechanics-neutral project template,
and the tests needed to verify both.

Studio Foundation is an open-source toolkit built around
[official Godot](https://github.com/godotengine/godot). Its distinctive
component is a beta WebGPU export path maintained as checksum-pinned patches
against Godot 4.7.1. WebGL 2 remains the fallback. No separate LX Solutions
engine fork is fetched or required.

> **Status:** WebGPU support is beta. The repository records verified behavior
> and known gaps in [BOOTSTRAP_REPORT.md](BOOTSTRAP_REPORT.md); it does not claim
> untested browser, device, or production support.

![Godot 4.7.1 template rendered through the WebGPU integration](templates/godot-game/project/captures/web-webgpu.png)

## What is verifiable

| Capability | Evidence in this repository |
|---|---|
| Official engine base | Godot 4.7.1 stable is pinned by full commit in [engine-lock.toml](engine/engine-lock.toml) |
| WebGPU source | Three ordered patches are stored in [engine/patches/](engine/patches/) and checked by SHA-256 before application |
| Source preparation | `engine-fetch` clones official Godot only and creates a disposable patched worktree |
| Export templates | Release and debug archives are recorded by filename, byte count, and SHA-256 in the engine lock |
| Runtime verification | Browser smoke tests require `navigator.gpu`, a usable adapter, and an active WebGPU canvas context |
| Fallback | The same template project has an official WebGL 2 export preset |
| Template behavior | Headless GDScript tests cover the shared addon and neutral starter project |
| Optional services | Rust and Nakama components are independently tested and are not required for client-only use |

Exact test counts, artifact state, and unverified areas are listed in the
[verification report](BOOTSTRAP_REPORT.md).
## Independent game proof

The separate [OSWT integration branch](https://github.com/lxsolutions/OSWT/tree/studio-foundation-webgpu-demo)
is a playable consumer of this repository, rebased onto Devon Rowkowski's
current `f6f8fe9` game update. At OSWT commit `a93d550` and Foundation commit
`61a92fa`, it passes 103/103 headless checks, exports with the locked WebGPU
template, and passes the strict live-browser WebGPU probe. The workflow emits a
machine-readable record containing both source commits, patch and template
hashes, exported artifact hashes, and verification results.

A public deployment is not claimed yet; the source and reproduction path are
published before the hosted URL.


## Quick start

Prerequisites are reported by `just doctor`. The fast repository checks require
Python 3.11; Godot and the engine toolchain are needed only for their respective
suites.

```sh
git clone https://github.com/lxsolutions/studio-foundation.git
cd studio-foundation
just doctor
just bootstrap
just test
```

Without `just`, run `powershell scripts/bootstrap.ps1` on Windows or
`sh scripts/bootstrap.sh` on Linux, macOS, or WSL2.

## Reproduce the WebGPU path

```sh
just engine-versions
just engine-fetch
just engine-build
just engine-validate
just engine-record-artifacts
just release-validate --allow-dirty
```

The pipeline is deliberately split:

```text
official Godot commit
        |
        v
verified local patch series
        |
        v
release + debug WebGPU templates
        |
        v
Godot export -> browser runtime probe -> visual evidence
```

`engine-build` requires the Emscripten version pinned in
[engine-lock.toml](engine/engine-lock.toml). The complete update procedure is in
[the WebGPU runbook](docs/runbooks/godot-webgpu-update.md).

## Included components

- A neutral Godot 4.7.1 project template and reusable `studio_core` addon.
- WebGPU export tooling with an official WebGL 2 fallback.
- Browser smoke, screenshot, visual-regression, benchmark, and release checks.
- Blender-to-glTF validation and export tools.
- Optional Rust API/session scaffolding and PostgreSQL development setup.
- An optional Nakama adapter that forwards opaque application payloads without
  defining game mechanics.

The optional backend is scaffolding, not a required architecture. A consuming
game owns its content, rules, schemas, identity policy, persistence semantics,
and deployment.

## Source and attribution

Official Godot is the sole active engine upstream. The WebGPU backend has
MIT-licensed historical lineage from `dwalter/godotwebgpu`; Studio Foundation
maintains the current Godot 4.7.1 patch series, build tooling, and validation
surface in this repository. The lineage repository is never cloned by the
build.

See [NOTICE.md](NOTICE.md) and
[WebGPU integration provenance](docs/architecture/webgpu-integration.md) for
the exact source boundary and commit pins.

## Repository layout

| Path | Purpose |
|---|---|
| `engine/` | Official Godot pin, WebGPU patches, build commands, and artifact records |
| `templates/godot-game/` | Mechanics-neutral Godot client and optional server template |
| `shared/godot-addons/studio_core/` | Reusable Godot services and platform interfaces |
| `services/` | Optional Rust protocol, session, API, and persistence scaffolding |
| `infra/` | Optional local PostgreSQL, Nakama, and tracing services |
| `tools/` | Engine, asset, export, browser, release, and repository tooling |
| `tests/` | Cross-language, browser, integration, performance, and visual checks |
| `docs/` | Decisions, architecture notes, and runbooks |

## Common commands

| Command | Purpose |
|---|---|
| `just test` / `just lint` | Run the fast test and lint suites |
| `just test-godot` / `test-rust` / `test-python` | Run one implementation suite |
| `just NAME=my_game DISPLAY_NAME="My Game" new-game` | Generate a neutral Godot project |
| `just export-browser-webgl [GAME]` | Export with official WebGL 2 templates |
| `just export-browser-webgpu [GAME]` | Export with the locally built WebGPU templates |
| `just run-browser-smoke` | Check browser boot, console output, canvas, and renderer |
| `just ci-local` | Run the full local acceptance suite |

Run `just` to list every supported command.

## Contributing and license

Material engine changes require tests, updated evidence, and the relevant ADR.
Contributor workflow is documented in
[WORKING_AGREEMENTS.md](docs/agents/WORKING_AGREEMENTS.md).

Foundation code, tooling, templates, documentation, and infrastructure are
dual-licensed under MIT and CC BY 4.0; see [LICENSE](LICENSE). Third-party
attribution is in [NOTICE.md](NOTICE.md) and
[dependency-licenses.md](docs/architecture/dependency-licenses.md).
