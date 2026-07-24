# WebGPU integration provenance

This document separates upstream Godot, historical backend lineage, third-party
source, and Studio Foundation maintenance.

## Source model

Studio Foundation builds from one active engine upstream:

- Repository: [godotengine/godot](https://github.com/godotengine/godot)
- Version: Godot 4.7.1 stable
- Commit: `a13da4feb8d8aefc283c3763d33a2f170a18d541`

`engine-fetch` clones that repository and applies the ordered patches recorded
in [engine-lock.toml](../../engine/engine-lock.toml). The patched tree is
disposable build state. No LX Solutions engine fork, Git submodule, or secondary
upstream is used.

## Historical lineage

The initial Godot WebGPU backend code came from the MIT-licensed
[dwalter/godotwebgpu](https://github.com/dwalter/godotwebgpu) project at commit
`f329e39ce8db7acaa5c9d6628a530fb769969228`. That commit is retained for
attribution and engineering traceability only; it is not fetched by the build.

The available backend line targeted Godot 4.6.2. Studio Foundation's current
series adapts the selected backend code to the pinned Godot 4.7.1 source. The
port included resolution of the conflicts recorded in
[rebase-4.7.1-conflicts.txt](../../engine/rebase-4.7.1-conflicts.txt), support
for the 4.7.1 pack format, and subsequent API and renderer build fixes.

## Maintained patch series

| Patch | Scope | Files | Added | Deleted |
|---|---|---:|---:|---:|
| `0001-studio-webgpu-engine.patch` | Godot renderer, WebGPU driver, web platform, resource, and build integration | 72 | 18,888 | 188 |
| `0002-studio-webgpu-spirv.patch` | Required vendored SPIR-V headers and tools | 397 | 155,766 | 10 |
| `0003-studio-webgpu-tint.patch` | Required vendored Tint source and license | 824 | 202,514 | 0 |
| `0004-godot-4.7.1-webgpu-interfaces.patch` | 4.7.1 API adaptation and Windows shader build reproducibility | 6 | 189 | 17 |
| `0005-webgpu-shell-capability-gate.patch` | Fail-closed browser WebGPU capability gate | 1 | 13 | 8 |
| `0006-webgpu-single-thread-stdio.patch` | No-threads web build compatibility | 1 | 1 | 0 |
| `0007-tint-storage-buffer-access.patch` | SPIR-V/Tint storage-buffer access compatibility | 1 | 1 | 1 |
| `0008-tint-image-ordering.patch` | SPIR-V/Tint image-value lowering order | 1 | 10 | 3 |

The large third-party source patches are listed separately so their line counts
are not presented as Studio Foundation-authored implementation. Copyright and
license notices remain with their respective projects.

Studio Foundation maintains the 4.7.1 integration delta, patch packaging,
source-preparation commands, template build, WebGL fallback, browser runtime
checks, visual comparison, and release evidence. Godot itself remains upstream
work maintained by the Godot contributors.

The locked template build explicitly enables `webgpu=yes`, disables `opengl3`,
and uses `threads=no`; an archive name is never treated as proof of its
renderer. On Windows, the optional host-generated WGSL lookup table defaults to
an empty table and the compiled runtime Tint path converts cache misses.

## Current runtime status

The no-threads build reaches a browser WebGPU adapter, device, canvas context,
and Godot's Mobile renderer without requesting WebGL. Startup then fails in the
vendored Tint SPIR-V reader at `texture.cc:606` while lowering a texture
operation. Patch 0007 removed the preceding illegal write-only storage-buffer
errors, but the texture assertion remains. Consequently, there are no accepted
WebGPU template artifacts or public game proof at this checkpoint.

## Reproduce and inspect

```sh
just engine-versions
just engine-fetch
git -C engine/.cache/studio-webgpu status --short
git apply --numstat engine/patches/0001-studio-webgpu-engine.patch
just engine-build
just engine-validate
just engine-record-artifacts
```

Before preparing source, `engine-fetch` rejects missing patches, path traversal,
and any patch whose SHA-256 differs from the lock. `engine-record-artifacts`
accepts only a complete release/debug pair and records exact filenames, byte
counts, and SHA-256 values.

Current verification results are in
[BOOTSTRAP_REPORT.md](../../BOOTSTRAP_REPORT.md). Attribution is also summarized
in [NOTICE.md](../../NOTICE.md).