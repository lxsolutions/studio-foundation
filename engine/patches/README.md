# Studio Foundation WebGPU patch series

These ordered patches are the additional source inputs used to prepare the
browser WebGPU template build. They apply to the official Godot commit in
`../engine-lock.toml` and are verified by SHA-256 before use.

1. `0001-studio-webgpu-engine.patch` - WebGPU engine, renderer, browser platform,
   resource, and build integration.
2. `0002-studio-webgpu-spirv.patch` - required vendored SPIR-V headers and tools.
3. `0003-studio-webgpu-tint.patch` - required vendored Tint source and license.
4. `0004-godot-4.7.1-webgpu-interfaces.patch` - Godot 4.7.1 interface adaptation
   and reproducible WebGPU shader-generation fixes.
5. `0005-webgpu-shell-capability-gate.patch` - fail closed when the browser does
   not expose WebGPU instead of silently selecting WebGL.
6. `0006-webgpu-single-thread-stdio.patch` - support the required no-threads web
   build configuration.
7. `0007-tint-storage-buffer-access.patch` - translate write-only SPIR-V storage
   buffers to Tint's supported read-write access mode.
8. `0008-tint-image-ordering.patch` - lower SPIR-V `OpImage` values before
   texture operations that can reference them earlier in module order.
9. `0009-tint-volatile-decoration.patch` - strip the SPIR-V `Volatile` decoration
   (21) that Tint's reader aborts on; without it, coherent compute shaders (e.g.
   `volumetric_fog`) crash shader translation and every 3D scene renders black.
10. `0010-webgpu-transitive-sampler-split.patch` - propagate the combined
    image-sampler split through function call chains, so a `sampler2D` forwarded
    from a wrapper into a deeper helper (e.g. tonemap's `texture2D_bicubic`, and
    `taa_resolve`) no longer produces invalid SPIR-V (`OpFunctionCall` argument
    type mismatch) that silently fails Tint translation.
11. `0011-webgpu-flatten-decoration-literals.patch` - stop `flatten_binding_arrays`
    from rewriting `OpDecorate`/`OpMemberDecorate` literal arguments (Offset,
    ArrayStride, ...). A struct-member Offset literal that collided with an array
    type id was being remapped, corrupting the struct layout into invalid SPIR-V.
12. `0012-tint-texture-function-params.patch` - Tint spirv-reader fix: convert
    texture types on function PARAMETERS, not only global vars. Godot forward-mobile
    passes lightmap/shadow textures by parameter; those kept `spirv::type::Image`
    and crashed Tint's texture lowering (`ProcessCoords` assert) on any 3D scene.

13. `0013-webgpu-sampler-texture-stage-visibility.patch` - give sampler/texture
    bind-group-layout entries precise per-stage visibility from a WGSL reachability
    scan instead of the `u.stages` union. Godot forward-mobile declares up to 22
    samplers visible to every stage, but the vertex stage samples none and the
    fragment stage at most 7; the over-approximation tripped WebGPU's hard
    16-samplers-per-stage limit so every 3D pipeline failed to create (verified on a
    Tesla P40: an unshaded 3D mesh renders at 60 fps with 0 GPUValidationError;
    lit/shadowed scenes needed `0014` as well).

14. `0014-webgpu-lit-shadow-sampler-types.patch` - make lit and shadowed 3D render.
    Fixes two sampler-description defects remaining after `0013`: bindings reached
    only through helper-function parameters (Godot's lighting/PCF helpers) were
    wrongly demoted to no visibility, and depth textures were paired with Filtering
    samplers, which WebGPU forbids. Adds a driver-owned non-filtering sampler for
    depth slots. Verified on a Tesla P40: six PBR meshes with real-time shadows at
    59-60 fps, 36 draws/frame, 0 GPUValidationError.

The WebGPU implementation originated in `dwalter/godotwebgpu`. Studio
Foundation owns the 4.7.1 port, scoped patch curation, preparation/build tooling,
and validation. See `../../docs/architecture/webgpu-integration.md` for the
authorship and maintenance boundary.

## Rules

- Apply patches only in the order locked in `engine-lock.toml`.
- Do not add unrelated files from a historical engine branch.
- Preserve all applicable third-party license files.
- Regenerate a patch from a reviewed candidate tree; do not silently hand-edit
  a locked patch.
- Recalculate SHA-256 values and run release validation after regeneration.
- A checksum change requires review even when the filename is unchanged.

`engine/.cache/studio-webgpu` is disposable output. This directory and
`engine-lock.toml` are source of truth.

The pinned Emdawn port also needs a toolchain-level namespace backport, stored
separately under `engine/toolchain/patches/`. It isolates Dawn's private
`RefCounted` type from Godot's type of the same name and is independently
checksum-locked in `engine-lock.toml`.

As of 2026-07-24 the release/debug rebuild and the engine-owned browser WebGPU
probe (active canvas context + 1.2% visual diff vs the WebGL baseline) both pass;
the accepted templates are checksum-locked in
`engine-lock.toml [artifacts.export_templates]`.