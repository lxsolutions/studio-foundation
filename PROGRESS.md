# PROGRESS — gauntlet quality layer

Terse per-round record. Newest last.

## R1 — port into studio-foundation (owner: single, sequential)

- Ported `tools/gauntlet/` + `templates/three-game/` onto a clean worktree off
  `origin/main`; ADR 0017; `just gauntlet-*`. PR #50 (draft), 4/4 CI green.
- Objective: fatal 0 · warn 0 · pageErrors 0 · fps p50 60 · instability 0.
  `edgeEnergy 9.17` = procedural fallback (bforge GLB is gitignored).
- Judge: not run — no reference set committed, by design.
- Vendoring surfaced 3 portability bugs, all fixed: path resolution against the
  harness dir rather than the caller's; hardcoded `node_modules` candidates;
  swallowed ssh tunnel stderr that made a stale reverse-forward look like a
  browser failure.

## R2 — composition metrics (owner: single, sequential)

The measured gap is content density, and the harness could not see it. Added a
block-grid pass and validated it against labelled frames from this session
(`harness/discriminate.mjs`), because a metric that cannot separate known cases
is worse than none.

| set | edgeEnergy | emptyBlk% | repeatBlk% | blkEdgeP10 |
|---|---|---|---|---|
| good (reference) | 21.67 | 16.32 | 51.33 | **2.47** |
| tiled (looked worse) | 38.02 | 23.10 | 33.10 | 0.23 |
| empty (looked bare) | 12.01 | **42.00** | 28.23 | 0.23 |
| forged | 35.05 | 24.63 | 22.93 | 0.23 |

- **Kept:** `emptyBlockPct`, and `blockEdgeP10` — the strongest discriminator
  found. The bar never drops below 2.47; every one of our builds bottoms out at
  0.23. It measures dead space, which whole-frame edge energy cannot see. Wired
  as calibrated findings `sparse-frame` and `dead-space`.
- **Rejected:** `repeatBlockPct` came out INVERTED (good 51.3 > tiled 33.1). A
  uniformly dense authored frame produces many statistically similar detailed
  blocks; mean/std/edge cannot separate that from tiling. Left in the output as
  diagnostic-only with a comment; detecting repetition needs autocorrelation or
  a frequency-domain test. Not gated on.
- Verified the new gate fires where the old one passed: r009 and r008 now warn
  `dead-space`; the reference produces no findings.

## R3 — review fixes (owner: single, sequential)

Three correctness issues raised in review, all real:

1. **Stale-JS capture.** Preflight ran `tsc --noEmit` while the browser loads
   `main.js`, so an edited `.ts` could pass preflight and be measured against the
   previous compile. Preflight now emits (`npx tsc`) and tsconfig sets
   `noEmitOnError`.
2. **Overclaimed WebGPU.** `probeGpu()` created its own canvases, so
   `webgpu=nvidia` proved browser capability, not that the application used it —
   and the Three.js template uses `WebGLRenderer` while the documented Godot test
   targeted `web-webgl`. Split into `availableWebGL`/`availableWebGPU` plus a real
   `applicationRenderer` detected from the page's own canvas.
   - **New result:** the `web-webgpu` export reports
     `Application rendered through: webgpu` at 60 fps p50 on the P40. First
     evidence ADR 0002's patch series actually renders through WebGPU on
     hardware. Controls (`web-webgl`, Three.js template) report `webgl2`, so the
     detector discriminates.
3. **Stale README paths** (`three-starter`, bare `node harness/...`) corrected to
   the repo-root layout, with the `just` front door shown first.

**Next, highest leverage:** content density is still the measured gap. Fill the
frame with authored geometry (`arch.colonnade`, `env.scatter`, `prop.debris`,
`build.greeble`) rather than tuning one hero asset — round 9 proved a single
authored prop cannot carry a frame that is 70% empty ground.

## R4 — content density via bforge dressing (owner: single, sequential)

The measured gap for nine rounds. Attacked it with authored geometry rather than
another material pass.

- Forged `arch.colonnade` (circle, 40 columns + entablature, 2560 tris) and
  `prop.debris` (48 pieces), both through `material.pbr` + `material.bake_pbr`,
  replacing 12 hand-placed columns.
- `check.critique` flagged 80 n-gons with the exact fix (`gameready.optimize
  triangulate=true`); applied rather than shipping unpredictable shading.

| round | change | warn | edgeEnergy | dynRange | blkEdgeP10 (hero) |
|---|---|---|---|---|---|
| R2 | ring r15 + debris | 6 | 16.56 | 160 | **0.06** |
| R3 | ring r15 -> r22 | 4 | 18.83 | 186.25 | 0.23 |

- **R2 flagged REGRESSED, and the comparison was invalid**: R1 ran with no
  `--references`, so no calibrated findings existed at all. Warn 0 -> 6 was a
  gate change, not a regression. Same class of error as comparing across a
  threshold change — check what moved, the build or the ruler.
- **R2's real defect was found by looking**: the hero camera sits at radius 15
  and the ring was radius 15, so the shot was a column 20cm from the lens.
  Re-forged at r22 (outside every camera) rather than moving cameras, because
  the shot set is the measurement contract.
- R3 is the best frame produced so far. dynamicRange 186.25 against a bar median
  of 195; fps p50 60; instability 0.
- `dead-space` still fires on all four shots (0.23–0.36 vs bar 0.44–3.8). The
  metric is doing its job: the ground plane is still a large low-detail expanse.

**Next, highest leverage:** still coverage, now specifically the ground. Options
in descending order: `env.terrain` with real relief instead of a flat plane,
`env.scatter` for denser mid-ground props, and an enclosed space rather than an
open plaza — the bar is an interior, where every pixel lands on something.
