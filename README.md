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
> fundamental WGSL feature gaps, not crashes.
>
> **In-browser render now verified on real hardware (2026-07-24, NVIDIA Tesla P40).**
> Running the rebuilt WebGPU build in headless Chrome on an actual GPU exposed two
> more shader-translation defects that the offline corpus missed (only the
> runtime-*specialized* scene shader triggers them): patch 0011 stops
> `flatten_binding_arrays` from corrupting struct-offset decoration literals, and
> patch 0012 fixes Tint's SPIR-V reader so textures passed by *function parameter*
> (Godot's lightmap/shadow helpers) are converted to core texture types instead of
> crashing its texture lowering. With 0009–0012 the engine **no longer crashes** on
> 3D shader translation on the GPU. **3D is still not yet visible**, now blocked by a
> *different, non-crash* issue: Godot's Forward Mobile scene shader binds 18 samplers
> to the vertex stage, exceeding WebGPU's hard limit of 16 per stage, so the scene
> pipeline is rejected. That is a driver/shader-structure problem (tracked separately),
> not shader translation. WebGL 2 remains the maintained fallback. Details:
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
| 3D shader translation (WebGPU) | No longer crashes — verified in-browser on an NVIDIA Tesla P40. Patches 0009–0012 fix four distinct translation crashes (`Volatile` decoration, transitive combined-sampler split, flatten decoration-literal corruption, and Tint's texture-function-parameter conversion). The rebuilt engine boots the WebGPU device and translates the specialized 3D scene shader without SIGILL |
| WebGPU shader coverage | 177 of 182 engine shaders translate to valid WGSL offline; the runtime-specialized scene shader (which the offline corpus did not cover) also translates after 0011/0012. The 5 offline gaps are fundamental WGSL limits (subpass `input_attachment`, storage-texture format inference, vertex-stage `read_write` storage), not crashes |
| 3D render (visible frame) | **Not yet.** With the crash chain fixed, the scene pipeline is now *rejected* (not crashed): Godot Forward Mobile binds 18 samplers to the vertex stage, over WebGPU's hard 16-per-stage limit. A driver/shader-structure issue, separate from translation, tracked for follow-up |
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
