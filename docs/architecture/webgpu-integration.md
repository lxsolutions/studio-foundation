# WebGPU integration provenance

Last reconciled: 2026-07-25

This document separates official upstream, historical backend lineage,
third-party source, and current Studio Foundation maintenance. Runtime claims
and reproduction commands are indexed in
[webgpu-evidence.md](webgpu-evidence.md).

## Source model

Studio Foundation builds from one active engine upstream:

- Repository: [godotengine/godot](https://github.com/godotengine/godot)
- Version: Godot 4.7.1 stable
- Commit: `a13da4feb8d8aefc283c3763d33a2f170a18d541`

`engine-fetch` clones that repository and applies the ordered patches in
[`engine-lock.toml`](../../engine/engine-lock.toml). The patched tree is
disposable build state. No LX Solutions engine fork, Git submodule, or secondary
upstream is used.

## Historical backend lineage

The initial Godot WebGPU backend code came from David Walter's MIT-licensed
[`dwalter/godotwebgpu`](https://github.com/dwalter/godotwebgpu) project at commit
`f329e39ce8db7acaa5c9d6628a530fb769969228`. The selected historical backend
targeted Godot 4.6.2.

That commit is retained for attribution and engineering traceability only. It is
not fetched by the build, and this repository does not claim that Studio
Foundation originated all backend code.

## Studio Foundation maintenance boundary

Studio Foundation owns and maintains:

- the port to official Godot 4.7.1, including the conflict resolution recorded
  in [`rebase-4.7.1-conflicts.txt`](../../engine/rebase-4.7.1-conflicts.txt);
- the scoped, ordered, checksum-locked patch series;
- later SPIR-V/Tint, shader, sampler, texture, bind-group-layout, and Forward+
  investigation fixes;
- the pinned Emdawn namespace backport and engine build pipeline;
- browser export handoff tooling and official WebGL 2 fallback;
- browser context probes, visual gates, render counters, benchmarks, and release
  evidence;
- MCP tooling, agent workflows, and the AI-native distribution layer.

Godot itself remains work maintained by the Godot contributors. Copyright and
license notices remain with their respective authors and projects.

## Patch scope and release boundary

| Range | Scope | Public status |
|---|---|---|
| `0001–0003` | Initial WebGPU integration plus required vendored SPIR-V and Tint sources/licenses | Historical backend-derived source, carried under its original licenses |
| `0004–0008` | Godot 4.7.1 API/build adaptation, browser gate, no-threads support, and early translation/toolchain fixes | Included in p0014 |
| `0009–0014` | Forward Mobile translation and bind-group fixes that produced lit, shadowed 3D | Included in p0014 and hardware-verified |
| `0015–0017` | Forward+ shader variants and corrected offline harness | Current-main source only; not in p0014 |
| `0018–0022` | Forward+ hardware investigation, abort/device-limit fixes, and bind-group-layout corrections | Current-main source only; 18 validation errors remain and no frame renders |

The published
[`godot-4.7.1-webgpu-p0014`](https://github.com/lxsolutions/studio-foundation/releases/tag/godot-4.7.1-webgpu-p0014)
archives contain only patches `0001–0014` and use Forward Mobile. Current
`main` contains patches `0001–0022`, but no p0022 templates are published.

The large third-party source patches are listed separately so their line counts
are not presented as Studio Foundation-authored implementation.
[`engine/patches/README.md`](../../engine/patches/README.md) documents every
patch's defect and evidence.

## Build and artifact identity

The template build explicitly enables `webgpu=yes`, disables `opengl3`, and uses
`threads=no`. An archive name or HTML setting is never treated as proof of its
renderer.

The lock retains two artifact identities:

- `[releases.godot_4_7_1_webgpu_p0014]` records the byte counts and hashes of the
  downloadable GitHub release.
- `[artifacts.export_templates]` records a separate locally accepted build pair
  written by `engine-record-artifacts`.

The hashes differ and are not interchangeable. Current-main patch count does not
flow into either p0014 identity.

## Current runtime status

- Published p0014 Forward Mobile renders the minimal lit/shadowed scene,
  Chariot, Riftline, and The Deep on an NVIDIA Tesla P40 with 0
  `GPUValidationError`.
- Current-main Forward+ has been run on the P40. Patch 0022 leaves 18
  `GPUValidationError` entries, and no frame renders.
- Forward+ hardware execution is investigation evidence, not a rendering or
  release claim.

See [webgpu-runtime-status.md](webgpu-runtime-status.md) for the dated
investigation log and [webgpu-performance.md](webgpu-performance.md) for p0014
measurements.

## Historical provenance checkpoint

The following state is retained as a dated checkpoint rather than presented as
current:

> On 2026-07-22, after patches `0001–0008`, startup still failed in Tint texture
> lowering and there were no accepted WebGPU templates or public game proof at
> that checkpoint. Later patches and hardware work superseded that status:
> p0014 was published on 2026-07-24, and the patch series reached 0022 on
> 2026-07-25.

## Reproduce and inspect

```sh
just engine-versions
just engine-verify-patches
just engine-fetch
git -C engine/.cache/studio-webgpu status --short
just engine-build
just engine-validate
just public-evidence-validate
```

`engine-fetch` rejects missing patches, path traversal, and checksum drift before
preparing source. `verify_patch_apply.py` separately checks that the full series
applies to a clean official tree.
