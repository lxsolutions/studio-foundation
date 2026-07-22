# ADR 0002: Official Godot + isolated WebGPU fork for browser builds

- Status: Accepted
- Date: 2026-07-19
- Last amended: 2026-07-21

## Context

Official Godot's browser export is WebGL 2 (Compatibility renderer). The
community `dwalter/godotwebgpu` fork (MIT, self-described beta, and largely
AI-generated per its README) adds a WebGPU backend for the Mobile renderer and
compute-capable browser workloads.

The upstream fork originally lagged at Godot 4.6.2 while the editor of record
was 4.7.1. The studio completed and validated a 4.7.1 port in its maintained
`lxsolutions/godot-webgpu` fork. Persistent risks remain: beta quality, a small
maintainer surface, AI-generated code provenance, recurring version lag, and
the possibility that official Godot ships its own WebGPU backend.

## Decision

1. The fork is an **unofficial browser export backend only**. Games are authored,
   tested, and natively exported with official Godot (ADR 0001).
2. Exact fork commit, base version, Emscripten version, SCons version, build
   flags, and patch checksums are pinned in `engine/engine-lock.toml`. Production
   builds never track a moving branch.
3. Studio engine changes live in the maintained backend fork or an explicit
   `engine/patches/` series. Official Godot remains an unmodified upstream.
4. Game code must not call fork-only APIs directly. Fork behavior stays behind
   `studio_core` platform interfaces and runtime quality profiles.
5. WebGL 2 is the maintained, always-green fallback. WebGPU may be red without
   blocking a release; WebGL may not.
6. The maintained fork line must match the editor-of-record minor before WebGPU
   can be claimed as green. Future updates use an isolated `engine-rebase`
   worktree, conflict classification, candidate build, browser smoke, visual
   comparison, and benchmark gate.

## Rebase procedure

Fetch both pins → prepare an isolated candidate worktree → classify and resolve
conflicts → build candidate templates without replacing pinned artifacts → run
headless tests, WebGPU smoke, visual regression, and benchmarks → update exact
pins and checksums → land as a reviewed PR.

The authoritative procedure is `docs/runbooks/godot-fork-rebase.md`.

## Switch / abandon triggers

- **Adopt official WebGPU** when godotengine/godot ships a WebGPU web backend
  that passes the studio smoke, visual, and performance suites.
- **Abandon the fork** if rebases fall more than two minor releases behind,
  upstream-breaking regressions remain unfixed for more than 90 days, or
  maintenance stops. WebGL remains the shipping fallback.

## Consequences

- Browser WebGPU is a quality tier, not a platform requirement.
- Engine sources and rebase worktrees remain disposable cache state; exact pins,
  patches, build flags, and evidence remain the source of truth.
- Candidate templates are installed under
  `engine/artifacts/candidates/<workspace>/templates`; they do not replace
  pinned artifacts during evaluation.
- WebGPU production-readiness is never claimed without recorded browser and
  visual evidence in `BOOTSTRAP_REPORT.md`.