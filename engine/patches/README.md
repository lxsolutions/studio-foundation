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

The series currently compiles and reaches the WebGPU Mobile renderer, but the
browser runtime is not accepted: startup stops in Tint texture lowering at
`texture.cc:606`. No template artifact is locked until that gate passes.