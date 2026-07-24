# Studio Foundation verification report

Last updated: 2026-07-22

This report separates verified repository behavior from work still in progress.
It is not a product roadmap.

## Public scope

Studio Foundation contains reusable Godot integration, a neutral project
template, asset/export/release tooling, mechanics-neutral transport and service
scaffolding, optional provider adapters, and their tests.

It does not define a game's content, entities, mechanics, domain schema,
identity policy, persistence semantics, or production deployment. The optional
server and Nakama adapter carry opaque application payloads supplied by a
consumer.

## Verified in this change

| Area | Evidence |
|---|---|
| Official engine source | Godot 4.7.1 stable commit `a13da4feb8d8aefc283c3763d33a2f170a18d541` is the sole active upstream pin |
| WebGPU source preparation | Eight checksum-pinned patches pass path-containment, reusable-source preparation, candidate-isolation, dry-run, resume, and conflict-handling tests |
| Build configuration | WebGPU templates explicitly use `webgpu=yes`, `opengl3=no`, and `threads=no` |
| Template installation | The installer selects only the archive matching the lock's thread mode and rejects archives missing the WebGPU loader bridge or compiled backend marker |
| Browser evidence | The smoke test instruments engine-owned adapter, device, and canvas-context requests and rejects any WebGL/WebGL 2 request |
| Artifact acceptance | The recorder requires a complete release/debug pair; on 2026-07-24 the release and debug WebGPU templates were recorded by byte count and SHA-256 in `engine-lock.toml` after passing the runtime gate |
| Current engine result | A no-threads build reaches a WebGPU adapter, device, and active canvas context under the Forward Mobile renderer without requesting WebGL, and **renders 2D/Control UI**: it passes the browser probe and a visual comparison of the neutral template's 2D menu against the WebGL baseline (1.2% diff). **The 3D-black bug is root-caused and fixed (patch 0009).** 3D was black because Tint's SPIR-V reader aborts (`TINT_UNIMPLEMENTED` decoration 21 = `Volatile`) on Godot's coherent compute shaders (`volumetric_fog.glsl`, compiled during 3D init) — a wasm trap that freezes the page. Patch 0009 strips that decoration. Verified offline (native reproducer over all 182 engine shaders: 0 crash, was 1); in-browser render verification pending a GPU-capable machine (this box has no hardware GPU). Earlier `texture.cc:606` + Emdawn `RefCounted` issues also fixed. **Lit, shadowed 3D now renders in-browser on a Tesla P40 (patches 0013 + 0014):** 0013 gives sampler/texture bind-group entries precise per-stage visibility (Forward Mobile over-declared 18 samplers per stage vs WebGPU's hard 16-per-stage limit), which made an unshaded mesh draw; 0014 then fixes the two defects that still blacked out real scenes — bindings reached only through helper-function parameters were wrongly demoted to no visibility, and depth textures were paired with Filtering samplers, which WebGPU forbids. A scene with six PBR meshes, a directional light, and real-time shadow mapping now renders at 59–60 fps, 36 draws/frame, with 0 `GPUValidationError` (was 2283) |
| WebGPU shader translation coverage | 177 of 182 engine shaders translate to valid WGSL under the offline native reproducer (was 174). Patch 0010 makes the combined image-sampler split transitive across function call chains, so a `sampler2D` forwarded from a wrapper into a deeper helper (tonemap bicubic glow, `taa_resolve`) no longer emits invalid SPIR-V that silently fails Tint. Each fixed shader is confirmed by SPIRV-Tools validation plus a correct-WGSL spot check (separate `texture_2d` + `sampler`, `textureSampleLevel` wired to the split pair). The 5 remaining failures are fundamental WGSL feature gaps (subpass `input_attachment` ×2, storage-texture format inference, vertex-stage `read_write` storage, vertex `@builtin(position)`), not crashes |
| Optional Nakama bridge | The bridge carries opaque consumer-owned payloads and remains optional |

## Engine lineage

Official Godot is upstream. Studio Foundation has no active dependency on a
separate LX Solutions engine fork. Historical MIT-licensed WebGPU lineage is
retained in [NOTICE.md](NOTICE.md); the maintained 4.7.1 delta, patch curation,
build commands, fallback, and validation live in this repository.

## External game status

OSWT is an external demo candidate, not accepted WebGPU proof. Independent live
inspection found that the current Asha Arena OSWT route requests WebGL 2. It has
not been overwritten or relabeled. A future proof release must use a clean
locked template, pass the engine-owned context instrumentation, and publish
matching source and artifact provenance.

## Not yet claimed

- A published OSWT (or other real-game) WebGPU capture and deployment produced from the accepted templates
- Safari/iOS WebGPU behavior
- Native Android and iOS device runs
- Database-backed integration tests against a live disposable PostgreSQL stack
- Console support beyond the documented licensed-provider path

## Reproduce the fast evidence

```sh
just test
just lint
just test-generated
just release-validate --allow-dirty
```

The longer engine sequence is:

```sh
just engine-fetch
just engine-build
just engine-validate
just engine-record-artifacts
just release-validate --allow-dirty
```

A WebGPU screenshot is accepted only when the runtime probe confirms engine-owned
adapter, device, and WebGPU canvas-context requests with no WebGL request.