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

## R5 — FIRST BLIND JUDGE RUN (owner: single, sequential)

The judge is the component the whole method rests on and it had never actually
been run — only smoke-tested with synthetic verdicts. Ran it for real: fresh
sub-agent, given only the deck directory and JUDGE_BRIEF.md, no build history,
no knowledge of which slot was ours.

**Result: 0W / 4L — 0% — BELOW_REFERENCE.**

Protocol validated: the judge picked the reference in all four pairs across
*randomised* slots (three A, one B), so it tracked content rather than position.
It also declined to speculate about provenance, as the brief requires.

Gaps it named, by frequency — note that three of the four are invisible to every
objective metric in this harness:

| gap | pairs | objective gate |
|---|---|---|
| no contact shadows / AO — "the set floats on its own shadows" | 001,002,003 | **invisible** |
| flat-shaded, one matte response everywhere | 001,004 | partially (`edgeEnergy`) |
| polygonised sphere silhouette | 001,003 | **invisible** |
| ground plane ends in a hard seam against the sky | 004 | **invisible** |

**The two gates disagree, and both are right.** The objective gate says content
density (`dead-space`). The judge says light transport. Neither could have found
the other's problem. This is the argument for keeping both.

Fixes applied (largest gap first, one owner): GTAOPass for contact darkening,
and sphere subdivision 1 -> 4 to kill the polygon silhouette.

| metric | R3 | R4 | note |
|---|---|---|---|
| warn | 4 | 4 | — |
| edgeEnergy | 18.83 | 19.45 | +0.62 |
| dynamicRange | 186.25 | 183.25 | −3 |
| dead-space (hero) | 0.23 | 0.15 | **worse** |

`dead-space` moved the wrong way because AO darkens low-contrast regions — the
fix trades against the metric while addressing what the judge named. Recorded
rather than resolved; do not "fix" it by removing the AO.

Also caught by looking: routing through EffectComposer broke the stats hook
(HUD read `1 draws · 1 tris`) because `renderer.info` resets per render call and
the final fullscreen pass overwrote the scene counts. Now `autoReset = false`
with one reset per frame, so the figure covers the whole frame including post.
Playtest: 4/4 pass, 0 NaN transforms across 65 objects.

**Next, highest leverage:** re-judge. The judge is the only gate that has ever
scored this build, it named four specific gaps, and two are now addressed. A
second run tells us whether the win rate moved — which is half the stop
condition and currently unmeasured.

## R6 — second blind judge, and an UNRESOLVED AO failure (owner: single, sequential)

**Judge round 2: 0W / 4L — 0%. Win rate FLAT (0 -> 0).**
Brief SHA identical to round 1 (`3a476a74f6671ea9`), so the judge was provably
not softened between runs.

A second, independent judge named the *same* dominant gap in nearly the same
words: "only a dithered shadow-map fringe instead of a darkening contact
shadow", "~30 column bases meet the sand with zero occlusion". It said this
**while GTAOPass was enabled**, which means the fix from R5 did not land.

Diagnosis so far, measured not guessed:

1. GTAO's default radius is **0.25 world units**. This scene has 7.5m columns on
   a 200m plane, so it darkened within 25cm of a surface — invisible at every
   framing. Set to 2.0m. Still no visible occlusion.
2. Captured the raw AO buffer (`OUTPUT.AO`): luma p50 **228/255**, dynamic range
   20. White means unoccluded, so the pass computes ~zero occlusion everywhere.
3. Suspected depth precision (camera was near 0.1 / far 400 — a 4000:1 ratio).
   Changed to 0.5/220. AO buffer came back **byte-identical** (227.327 both
   runs), which is itself the finding: the buffer does not respond to scene
   changes at all.

**UNRESOLVED. Stated rather than papered over.** The near/far change is kept
because it is correct regardless. The diagnostic is also confounded: `OutputPass`
sits after GTAO and tone-maps whatever it emits, so `OUTPUT.AO` was not a clean
read of the buffer.

Next, in order: (a) re-run the AO-only capture with OutputPass removed so the
buffer is read raw; (b) drop in `SSAOPass` as a control — if SSAO produces
occlusion on the same scene, the problem is GTAO configuration, and if it does
not, the problem is the depth/normal input both passes share; (c) only then
consider baked AO via a second UV channel.

Objective metrics were flat across all of this (edgeEnergy 19.45 -> 19.65, warn
4, fps 60, instability 0), which is the point: **no metric in this harness can
see the defect two independent judges named twice.**

Stop condition NOT met: win rate is flat, but each round produced new findings.

## R7 — AO RESOLVED via control experiment (owner: lighting/post, sequential)

Closed the blocker from R6 rather than starting new work, because contact
shadows apply to every game in this studio, not just this template.

Diagnostic chain, each step measured:

1. GTAO default radius is **0.25 world units**; scene is 200m with 7.5m columns.
   Raised to 2.0m — still nothing.
2. Raw AO buffer read luma p50 **228/255** (white = unoccluded), and was
   **byte-identical** across a camera near/far change. A buffer that does not
   respond to the scene is not merely mistuned.
3. **Control: swapped GTAOPass for SSAOPass on the identical scene.** SSAO
   responded immediately — edgeEnergy 19.65 -> 22.07, p01 214 -> 33 (dark areas
   appeared). So the shared depth/normal input is VALID and the fault was GTAO
   configuration, not the pipeline. This is what the control was for.
4. SSAO at kernelRadius 4m gave broad ambient occlusion — measurable in the
   histogram, but not the "objects meet the ground" cue the judges asked for.
   Tightened to 1m / maxDistance 2m: **visible contact darkening on the plinth
   under the sphere**, where it had been uniformly flat white.

**Root cause class, and it generalises:** both AO passes ship defaults tuned for
a ~1m scene (GTAO radius 0.25, SSAO maxDistance 0.1). A 200m world silently
disables them — the pass runs, costs frame time, and produces nothing. Nothing
in the objective gate can see this. Two independent blind judges named it twice
before it was found.

| metric | GTAO | SSAO tight |
|---|---|---|
| edgeEnergy (hero) | 19.65 | 21.97 |
| dynamicRange (hero) | 183 | 175 |
| p01 (hero) | 214 | 39 |
| fps p50 | 60 | 60 |

**Next:** re-judge. Two judge rounds both named occlusion as the dominant gap and
it is now genuinely addressed, so this is the first change with a real chance of
moving a win rate that has been flat at 0.

## R8 — third blind judge: win rate STILL 0% (owner: single, sequential)

| judge round | build | score |
|---|---|---|
| r003 | pre-AO | 0W/4L — 0% |
| r005 | GTAO (silently disabled) | 0W/4L — 0% |
| r007 | SSAO contact darkening working | 0W/4L — 0% |

Brief SHA `3a476a74f6671ea9` unchanged across all three, so no round was graded
on softer criteria than the one before it.

**Three rounds, zero movement.** The AO fix was real — contact darkening is
visible now and was not before — and it did not flip a single pair. Stated
plainly rather than framed as progress.

New findings this round (so the stop condition is NOT met despite the flat rate):

- The sphere reflects a **two-band sky gradient**, never the twelve columns
  physically surrounding it. The environment is a sky-only PMREM, not a scene
  probe. Named in two of four pairs.
- **No aerial depth**: near and far columns sit at identical contrast and
  saturation. No distance haze.
- **The ring beams are flat black boxes** with visibly misaligned segment joints
  on the right side — a defect in the forged entablature, not in the shading.
- Still "nothing sits on the ground" — the SSAO fix is real but insufficient at
  the column bases and the plinth-to-sand junction.

**The root cause all three judges keep circling, in different words:** "single
flat albedo", "every element same untextured diffuse", "value range comes from
albedo rather than light". Only the columns have baked PBR. The ground plane,
the ring beams, the plinth and the debris do not — and by area those are most of
the frame.

**Next, highest leverage, and the judge named it outright:** texture the two
largest surfaces in frame — the ground plane and the ring beams. Everything else
is second-order while most of the screen is untextured diffuse. Then a real
reflection probe (CubeCamera) so the hero metal reflects its own scene, and
distance fog for aerial depth.

Objective gate flat throughout (warn 4, fps 60, edgeEnergy 19.6, instability 0),
which remains the point: three judge rounds found four new defect classes that
no metric here can see.
