# Studio Foundation WebGPU patch series

These ordered patches are the additional source inputs used to prepare the
browser WebGPU template build. They apply to the official Godot commit in
`../engine-lock.toml` and are verified by SHA-256 before use.

1. `0001-studio-webgpu-engine.patch` - WebGPU engine, renderer, browser platform,
   resource, and build integration.
2. `0002-studio-webgpu-spirv.patch` - required vendored SPIR-V headers and tools.
3. `0003-studio-webgpu-tint.patch` - required vendored Tint source and license.

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