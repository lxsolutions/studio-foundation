# ADR 0002: Official Godot + isolated WebGPU fork for browser builds

- Status: Accepted
- Date: 2026-07-19

## Context

Official Godot's browser export today is WebGL 2 ("Compatibility" renderer). The
community fork `dwalter/godotwebgpu` (MIT, self-described **beta**, largely
AI-generated per its README) adds a WebGPU backend claiming large FPS gains and support
for the Mobile renderer + compute shaders in browsers. It is based on Godot
**4.6.2-stable** while official stable is **4.7.1** — the fork lags upstream.

Risks: beta quality, single-maintainer bus factor, AI-generated code provenance,
version lag, and the possibility that official Godot ships its own WebGPU backend.

## Decision

1. The fork is an **unofficial browser export backend only**. Games are authored,
   tested, and natively exported with official Godot (ADR 0001).
2. Exact fork commit, base version, Emscripten version, SCons version, build flags, and
   patch checksums are pinned in `engine/engine-lock.toml`. **Never track a branch.**
3. Studio changes to the engine live as an explicit patch series in `engine/patches/`
   applied by `engine/scripts/fetch.py`. No direct pushes to a mutable fork branch.
4. Game code must not call fork-only APIs directly. Anything fork-specific is wrapped
   behind `studio_core` platform interfaces (`StudioPlatform`, render profiles), so a
   WebGL-only or official-WebGPU future needs no game changes.
5. **WebGL 2 Compatibility export is a maintained, always-green fallback.** Browser CI
   runs both exports; WebGPU may be red without blocking releases, WebGL may not.
6. Because the fork is based on 4.6.2: shared code (`studio_core`) and template
   projects avoid 4.7-only APIs until the fork rebases. CI's fork-export job is the
   enforcement point.

## Rebase procedure (summary; full runbook in docs/runbooks/godot-fork-rebase.md)

fetch both pins → apply patch series → build editor + web templates → run headless test
suite + WebGPU smoke scene + visual regression vs WebGL baseline → update lock file
checksums → land as a reviewed PR.

## Switch / abandon triggers

- **Adopt official WebGPU** the moment godotengine/godot ships a WebGPU web backend
  that passes our smoke + visual + performance suites — the fork is then dropped.
- **Abandon the fork** if: rebases fall >2 minors behind official, upstream-breaking
  regressions stay unfixed >90 days, or maintenance stops. Fallback is WebGL 2 export,
  which is why it must stay green.

## Consequences

- Browser WebGPU is a *quality tier*, not a platform requirement; shipping never
  depends on the fork.
- Engine rebuilds are reproducible from `engine-lock.toml` alone (fetch → patch →
  build → checksum), and never require committing the engine tree to this repo.
- We must not claim WebGPU production-readiness without recorded test results
  (BOOTSTRAP_REPORT.md tracks current evidence).
