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

The large third-party source patches are listed separately so their line counts
are not presented as Studio Foundation-authored implementation. Copyright and
license notices remain with their respective projects.

Studio Foundation maintains the 4.7.1 integration delta, patch packaging,
source-preparation commands, template build, WebGL fallback, browser runtime
checks, visual comparison, and release evidence. Godot itself remains upstream
work maintained by the Godot contributors.

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
