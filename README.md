# Studio Foundation

Reproducible Godot 4.7.1 browser builds, a mechanics-neutral project template,
and the tests needed to verify both.

Studio Foundation is an open-source toolkit built around
[official Godot](https://github.com/godotengine/godot). Its distinctive
component is a beta WebGPU export path maintained as checksum-pinned patches
against Godot 4.7.1. WebGL 2 remains the fallback. No separate LX Solutions
engine fork is fetched or required.

> **Status:** WebGPU support is beta and **2D-only today.** The locked source
> build boots the WebGPU backend (Forward Mobile renderer) and renders 2D/Control
> UI in-browser — verified 2026-07-24 against the engine-owned WebGPU probe
> (active canvas context, no runtime error) and a visual comparison of the neutral
> template's 2D menu against the WebGL baseline (1.2% diff). Both templates are
> recorded by byte count and SHA-256 in [engine-lock.toml](engine/engine-lock.toml).
>
> **3D-black bug — root-caused and fixed (2026-07-24, patch 0009).** A lit *or
> even unshaded* 3D mesh rendered black under WebGPU while rendering fine under
> WebGL. Cause: Tint's SPIR-V reader aborts (`TINT_UNIMPLEMENTED`, decoration 21 =
> `Volatile`) when translating Godot's coherent compute shaders — concretely
> `volumetric_fog.glsl`, which the Forward Mobile renderer compiles during 3D
> init. In the browser that abort is a WebAssembly trap that freezes the page, so
> every 3D scene went black (2D/UI was unaffected). Patch 0009 strips the
> `Volatile` decoration in SPIR-V preprocessing (same approach as `Restrict`).
> **Verified offline** with a native reproducer over all 182 engine shaders:
> `volumetric_fog` now translates and 0 crash (was 1). A follow-up (patch 0010)
> also fixes a class of *silent* shader-translation failures — combined
> image-samplers forwarded through function call chains (bicubic glow,
> `taa_resolve`) — raising offline coverage to 177/182; the remaining 5 are
> fundamental WGSL feature gaps, not crashes. **In-browser render verification is
> still pending** a GPU-capable machine (this dev box has no hardware GPU). WebGL 2
> remains the maintained fallback. Details:
> [BOOTSTRAP_REPORT.md](BOOTSTRAP_REPORT.md).

## What is verifiable

| Capability | Evidence in this repository |
|---|---|
| Official engine base | Godot 4.7.1 stable is pinned by full commit in [engine-lock.toml](engine/engine-lock.toml) |
| WebGPU source | Eight ordered patches are stored in [engine/patches/](engine/patches/) and checked by SHA-256 before application |
| WebGPU toolchain | The exact Emdawn source and Dawn namespace backport are independently versioned and checksum-locked under [engine/toolchain/](engine/toolchain/) |
| Source preparation | `engine-fetch` clones official Godot only and creates a disposable patched worktree |
| Export templates | Accepted archives are recorded by filename, byte count, and SHA-256 in [engine-lock.toml](engine/engine-lock.toml); the release and debug WebGPU templates are locked (they passed the **2D** browser + visual gate on 2026-07-24) |
| Runtime verification | Browser smoke tests observe the engine's adapter, device, and WebGPU canvas requests and reject any WebGL context request |
| 3D rendering (WebGPU) | Root-caused + fixed (patch 0009 strips the `Volatile` decoration Tint's SPIR-V reader aborts on, from Godot's coherent compute shaders). Verified offline (native reproducer, 0/182 shaders crash, was 1). In-browser render verification pending a GPU-capable machine |
| WebGPU shader coverage | 177 of 182 engine shaders translate to valid WGSL offline (was 174). Patch 0010 fixes combined image-samplers forwarded through function call chains (tonemap bicubic glow, `taa_resolve`). The 5 remaining are fundamental WGSL feature gaps (subpass `input_attachment`, storage-texture format inference, vertex-stage `read_write` storage), not crashes — the effect degrades, 3D still renders |
| Fallback | The same template project has an official WebGL 2 export preset |
| Template behavior | Headless GDScript tests cover the shared addon and neutral starter project |
| Optional services | Rust and Nakama components are independently tested and are not required for client-only use |

Exact test counts, artifact state, and unverified areas are listed in the
[verification report](BOOTSTRAP_REPORT.md).

## Demo status

OSWT is being evaluated as an external consumer, but it is not currently
accepted as WebGPU proof. The existing Asha Arena route uses WebGL 2 and will
remain labeled and deployed accordingly until a clean, locked build passes the
engine-owned WebGPU context probe and produces matching provenance.

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
Security scope and private reporting instructions are in [SECURITY.md](SECURITY.md).


Foundation code, tooling, templates, documentation, and infrastructure are
dual-licensed under MIT and CC BY 4.0; see [LICENSE](LICENSE). Third-party
attribution is in [NOTICE.md](NOTICE.md) and
[dependency-licenses.md](docs/architecture/dependency-licenses.md).
