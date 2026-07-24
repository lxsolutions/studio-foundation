# ADR 0002: Official Godot plus an in-repository WebGPU patch series

- Status: Accepted
- Date: 2026-07-19
- Last amended: 2026-07-23

## Context

Official Godot 4.7.1 provides WebGL 2 browser export through the Compatibility
renderer. The MIT-licensed `dwalter/godotwebgpu` project demonstrated a WebGPU
backend for the Mobile renderer, but its available line lagged behind Studio
Foundation's Godot version.

A validated 4.7.1 integration was produced historically in
`lxsolutions/godot-webgpu`. Making that separate repository an active
dependency created avoidable failure and communication risk: deleting it broke
`engine-fetch`, while its default branch could misrepresent the maintained
version. Studio Foundation already owned the port, build tooling, validation,
and release evidence.

## Decision

1. Official Godot 4.7.1 is the editor, engine of record, and sole engine upstream.
2. Browser WebGPU support is maintained in this repository as an ordered patch
   series under `engine/patches/`, applied to the exact official commit in
   `engine-lock.toml`.
3. `engine-fetch` fetches official Godot only. It verifies patch paths and
   SHA-256 values before preparing a disposable patched worktree.
4. The patch series is scoped to the WebGPU implementation and required
   SPIR-V/Tint sources. Unrelated changes from historical branches are excluded.
5. WebGPU templates explicitly build with `webgpu=yes` and `opengl3=no`.
   Filenames or HTML configuration alone never establish renderer capability.
6. `dwalter/godotwebgpu` remains technical source lineage and attribution, not
   a runtime, build, or availability dependency.
7. Game code cannot call integration-only APIs directly. Renderer differences
   stay behind `studio_core` interfaces and quality profiles.
8. Official WebGL 2 is the maintained release fallback. WebGPU may be red
   without blocking a release; WebGL may not.
9. A Godot update is accepted only after the patches apply, templates build,
   browser smoke passes, visual comparison passes, and evidence is recorded.
10. Accepted release/debug templates have byte counts and SHA-256 values in
   `engine-lock.toml`; proof consumers must verify both before export.
11. Template installation must find the compiled WebGPU bridge and backend.
    Browser proof observes the engine's adapter, device, and canvas requests
    and fails if the alleged WebGPU runtime requests WebGL or WebGL 2.
12. The browser build uses `threads=no` because the current backend does not
    support Godot's threaded web runtime. Installers may not relabel an archive
    built for a different thread mode.
13. Toolchain backports are separate checksum-locked inputs under
    `engine/toolchain/`. The build copies and patches the exact Emdawn package
    in a disposable cache; it never mutates the installed Emscripten SDK.

Tint storage-buffer lowering is fixed in the Godot patch series. An ASAN
regression test also reproduced the later Emdawn/Godot global `RefCounted`
collision and passed with the locked Dawn namespace backport. On 2026-07-24 the
release and debug templates were rebuilt from those locked inputs and passed the
engine-owned browser WebGPU probe (active WebGPU canvas context, no runtime
error) and the visual comparison against the WebGL baseline (1.2% diff, 3%
threshold). Both templates are now recorded with byte counts and SHA-256 values
in `engine-lock.toml [artifacts.export_templates]`; the artifact lock is no
longer blocked. See `docs/architecture/webgpu-runtime-status.md`.

## Update procedure

Fetch the proposed official ref, run `engine-rebase` to apply the locked patches
in an isolated candidate worktree, resolve any conflicts by review, build
candidate templates without replacing pinned artifacts, then run headless,
browser, visual, and benchmark gates.

The authoritative procedure is
`docs/runbooks/godot-webgpu-update.md`.

## Switch or abandon triggers

- Adopt official WebGPU when Godot ships a backend that passes the Studio
  Foundation smoke, visual, and performance suites.
- Suspend the local WebGPU tier if it falls more than two minor releases behind,
  unresolved regressions persist for more than 90 days, or maintenance stops.
  WebGL remains the shipping browser path.

## Consequences

- Studio Foundation is standalone: the repository contains every additional
  source input required to reconstruct its WebGPU tree.
- Patches, locks, checksums, and evidence are source of truth; source worktrees
  and compiled templates are disposable outputs.
- The historical upstream and integration commits remain documented so credit
  and engineering ancestry are not lost.
- WebGPU remains a beta quality tier and is never described as supported without
  current browser evidence.