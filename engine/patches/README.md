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