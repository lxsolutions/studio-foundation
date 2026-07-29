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

## R9 — judge-directed material work on the two largest surfaces (owner: lighting/materials, sequential)

The judge named the fix outright: "texture and break up the two largest
surfaces — the ring beams and the sand plane". Did exactly that.

**Ground.** Replaced the flat untextured PlaneGeometry with `env.terrain`
(110x110m dunes, 24.2k tris, `flatten_center=26` so the colonnade and plinth
stay level), surfaced with `material.pbr` + baked at **253.5 px/m**. Relief in
the distance also removes the hard straight plane-meets-sky seam the judge
flagged in an earlier round. edgeEnergy 19.62 -> 20.60.

**Entablature — the black beams were a BAKE failure, not a shading one.**
`uv.report` on the colonnade:

| stage | uv_area | coverage | texel density |
|---|---|---|---|
| recipe UVs | **138.6** | 1.0 | 330 px/m |
| after unwrap | 0.043 | 4.3% | 5.8 px/m |
| after uv.pack | 0.043 | 4.3% | 5.8 px/m |

`uv_area 138.6` means the recipe's UVs deliberately TILE (uv_scale 3m per tile).
Baking into tiled UVs makes many faces share the same 0-1 region, so the bake
overwrites itself and the entablature received no valid texels — it rendered
black. Re-unwrapping fixes the black but atlases 1333 m² into one 2048 map,
which can only ever give ~6 px/m; matching the terrain would need a ~40k texture.

**Pipeline rule, and it generalises:** `material.bake_pbr` is for props with
unique UVs. Large architecture authored with a `uv_scale` tiling layout must
keep those UVs and take a TILING material in-engine instead. Baking it is the
wrong pipeline, not a wrong setting.

Shipped the re-unwrapped version for now because lit-but-soft beats black; the
correct fix (export unbaked, apply a tiling stone material in-engine) is the
next material task. edgeEnergy 22.69, fps 60, instability 0, warn 4.

**Not done: the games.** Fourth loop without touching Chariot Club, The Deep,
Riftline or Plato's Plaza. The justification each time was that the defect being
chased lived in shared tooling and would propagate — true for the AO scale bug
and true for this bake/tiling rule. It is no longer true: nothing in the template
now blocks taking the harness to a real game. Chariot Club is next, first action,
no preconditions.

## R10 — took the harness to Chariot Club, found a toolset gap (owner: tooling)

First real game, as committed. Two results, one about the game and one about the
harness.

**About the game.** Chariot Club's `web-webgpu` export genuinely renders through
WebGPU — `Application rendered through: webgpu`, fps p50 60 / p99 30 on the P40.
Independent confirmation that ADR 0002's patch series works on hardware, from a
shipped game rather than the template.

**About the harness — the finding worth keeping.** The capture reported a boot
frame showing the DEFAULT Godot splash, which would violate the standing
Asha-Arena-laurels rule, and a `settled` frame at 98.95% black. Both looked like
real regressions. They are not verifiable from this build: the export is dated
2026-07-25 while Chariot's source last changed 2026-07-27.

**The harness measured a two-day-old build and said nothing.** That is the same
bug class as the stale-JS capture fixed earlier for TypeScript (preflight now
emits before capturing), left unguarded for engine exports — and an engine export
is far more likely to drift, because nothing rebuilds it automatically.

Implemented `--source` / `--build`: compares newest mtime on each side, warns on
stderr before anything expensive runs, and stamps a STALE BUILD banner into the
report plus `summary.staleBuild`. Verified against the real export:

```
[shotset] STALE BUILD: source is 46.7h newer than the build.
  source 2026-07-27T15:42:06Z   build 2026-07-25T16:59:18Z
```

No claim is made about the Godot splash or the black frame. They may be real
defects or artefacts of a stale export; the honest answer is that this build
cannot settle it.

**Next:** re-export Chariot (`just GAME=games/chariot export-web`) and re-run
with `--source`/`--build` set. If the splash and the black frame survive a fresh
export they are real defects in a shipped game, found by the harness on its
first outing against one.

## R11 — Chariot re-export: a real game bug, and a retraction (owner: tooling)

Re-exported Chariot fresh so the previous round's suspicions could be settled.
The staleness guard went quiet, which is the correct behaviour.

**RETRACTION.** The earlier claim that `web-webgpu` "renders through WebGPU at
60 fps p50 — the first evidence ADR 0002's patch series works on hardware" was
WRONG, and it reached the PR body, VERIFICATION.md and ADR 0017. Cause: the
`applicationRenderer` probe called `getContext('webgpu')` on the page's canvas.
On a canvas with no context that does not report a context, it CREATES one. The
export had failed to initialise, its canvas was bare, and the probe manufactured
the answer it then reported. Corrected in all three places.

Detection is now passive: an init-script hook wraps
`HTMLCanvasElement.prototype.getContext` and records what the page asks for.
Caught because a control run produced an impossible result — a `web-webgl`
export reporting `webgpu`.

**REAL BUG in a shipped game**, both exports fresh, staleness clean:

| export | applicationRenderer | boot | black% | console errors |
|---|---|---|---|---|
| web-webgl | `webgl2` | 2.3s | 0.07–0.25 | 0 |
| web-webgpu | **`no-context-requested`** | 18.9s | **98.94–99.13** | **25** |

The WebGPU export renders a black screen. It never obtains a context, because
shader translation aborts:

```
Tint SPIR-V→WGSL failed: var: struct size (32) is smaller than the end of the
last member (224) — %instances:ref<storage, InstanceDataBuffer_1_1_a64, ...>
WebGPU: SPIR-V→WGSL conversion failed for stage 1.
```

Same family as the historical Tint/volumetric_fog failure: Tint rejects a
shader, the stage never compiles, the screen goes black. Here it is an
InstanceDataBuffer whose declared struct size (32) is smaller than its last
member's end (224).

**fps p50 was 60 on the broken build**, because it was drawing nothing. A
performance gate alone would have passed this.

**Next:** the Tint struct-size error is a concrete, actionable defect in the
WebGPU patch series — an instancing storage buffer whose std430 layout is
mis-declared. That is worth its own investigation and is the single highest-value
thing found in this whole run, because it is a real bug in shipped code rather
than a template exercise.

## R12 — Tint struct-size bug: narrowed, not yet fixed (owner: engine)

Chased the black-screen defect. Ruled out and established, in order:

1. **Not the shader source.** `InstanceData` in
   `forward_clustered/scene_forward_clustered_inc.glsl` is byte-identical
   between `godot-official` and `studio-webgpu`. Its std430 layout computes to
   176 bytes (208 with USE_DOUBLE_PRECISION), so a declared size of 32 is not
   something the GLSL asks for.
2. **Not `strip_restrict_decoration`.** It removes only Restrict (19),
   InputAttachmentIndex (43) and Volatile (21) — none affect layout — and its
   OpDecorate/OpMemberDecorate word offsets are correct.
3. **It is not one struct — it is four, with identical numbers:**

```
InstanceDataBuffer_1_1_a64  @(1,2)   size 32, last member ends 224
OmniLights_1_1_a64          @(0,6)   size 32, last member ends 224
SpotLights_1_1_a64          @(0,8)   size 32, last member ends 224
AreaLights_1_1_a64          @(0,10)  size 32, last member ends 224
```

`InstanceData`, `LightData` and `AreaLight` have completely different layouts.
They cannot all genuinely be 32 bytes ending at 224. **Identical constants
across unrelated types means these are synthesized, not computed** — something
in the SPIR-V pipeline is emitting a fixed size/stride for every storage buffer
it rewrites. All four share the mangled suffix `_1_1_a64`.

4. **All four are Forward+ (clustered) shaders**, and
   `project.godot` sets `renderer/rendering_method.web="gl_compatibility"`. That
   is why `web-webgl` works at all — it uses the GL Compatibility renderer and
   never touches RenderingDevice. The WebGPU export is compiling
   forward_clustered regardless.

**Two candidate fixes, in order of cost:**

- **Cheap and probably shippable today:** force Forward *Mobile* for the WebGPU
  web target. Existing studio knowledge is that Mobile is the shipping tier and
  Forward+ has never been clean under WebGPU; avoiding forward_clustered avoids
  these four buffers entirely. Needs an export-preset/override change plus a
  re-export and a harness run to confirm.
- **The actual bug:** find the pass synthesizing size 32 / stride for rewritten
  storage buffers. `flatten_binding_arrays` (p11) and `infer_readonly_storage`
  (p12) are the prime suspects since they rewrite storage-buffer types. Proving
  it needs a per-pass SPIR-V dump and a decoration diff, then an engine rebuild
  to test — more than one loop.

**Not attempted:** editing `project.godot` to test the Mobile override. That
file lives in the main checkout, which currently has ~20 uncommitted files from a
parallel session, and a speculative renderer change there is not a safe end-of-
loop action.

Harness improvement from this round: console-error capture was truncating at 400
chars, which cut the Tint diagnostic mid-sentence and hid the fact that four
buffers were failing rather than one. Raised to 8000.

## R13 — root cause found: SPIR-V literal corruption (owner: engine)

**`flatten_binding_arrays` corrupts std430 layout literals.** It does a blunt
whole-word ID substitution across every instruction, and excludes literal
operands for only three opcodes — `OpConstant`, `OpSpecConstant`, `OpSwitch`.
It does NOT exclude `OpDecorate` or `OpMemberDecorate`, whose operands include
**ArrayStride** and **Offset**. Any layout literal whose numeric value happens to
equal a flattened array type ID is rewritten to that array's element type ID.

That is exactly the observed signature: four unrelated buffers
(`InstanceDataBuffer`, `OmniLights`, `SpotLights`, `AreaLights`) all reporting
the same impossible size 32 ending at 224. Identical constants across types with
different layouts means substitution, not miscomputation.

What made it solvable: raising the harness's console truncation 400 -> 8000,
which revealed four failures instead of one. At 400 chars this looked like a
single-struct layout bug and would have been chased in the wrong place.

Fix written and specified in
`docs/architecture/webgpu-spirv-literal-corruption.md`: add `OP_DECORATE`,
`OP_MEMBER_DECORATE`, `OP_NAME`/`OP_MEMBER_NAME` to the literal-exclusion block
with `literal_start = 2`, plus the missing `OP_MEMBER_NAME = 6` constant. The
change only *stops* substituting words that were never IDs, so it cannot regress
a case that previously worked.

**NOT built or verified.** The generated tree at `engine/.cache/studio-webgpu/`
is rebuilt from the patch series, so the edit there does not persist; per ADR
0002/0008 it belongs in `engine/patches/0001-studio-webgpu-engine.patch` (the
patch that adds the file — 77 references; 0002 has none), followed by a checksum
refresh, `engine-fetch`, `engine-build`, re-export and a harness run. That is a
long build and a checksummed patch-series change, neither of which is a safe
end-of-loop action.

Interim shipping option, unchanged: force Forward Mobile for the WebGPU web
target. All four failing buffers are Forward+ shaders.

## R14 — fix landed in the patch series; a reproducibility gap found on the way

**The SPIR-V fix is in `engine/patches/0001-studio-webgpu-engine.patch`**, hunk
re-counted 2674 -> 2699, verified to apply cleanly against pristine 4.7.1, lock
checksum updated, and `spirv_preprocess.cpp` compiles with zero errors. Build
still linking at time of writing; **the rendering result is NOT yet confirmed**.

**The patch series does not build.** Regenerating the workspace purely from the
three checksummed patches produces a tree that fails to compile
(`MAIN_WINDOW_ID` undeclared in `display_server_web.cpp`). Diffing against the
working cache shows **13 source files** present only in the cache — including
`cluster_builder_rd.cpp/.h`, `cluster_render.glsl` and all four WebGPU drivers,
i.e. the Forward+ bring-up work. `engine-lock.toml`'s checksums verify the
patches are *unmodified*, not that they are *sufficient*: both checks passed
while the build failed. Written up in
`docs/architecture/engine-patch-series-reproducibility-gap.md`.

Deleting `engine/.cache/studio-webgpu` — which the tooling calls "this
disposable cache" — would destroy that work. It is not disposable today.

**Near-miss:** `engine/patches/*` are UNTRACKED in the main checkout; a parallel
session holds an in-progress rewrite of the whole series plus a new
`patch_series.py`. I first copied the patched file across from there, caught it
via a checksum mismatch against the branch baseline, reverted, and re-applied
the 25 lines to the branch's own committed patch. The PR contains only my change.

**Next:** finish the link, re-export Chariot, and run
`shotset.mjs --source/--build` against `web-webgpu`. Success is
`applicationRenderer: webgpu` with black% in low single digits and zero console
errors, matching the `web-webgl` control. Until that runs, no claim.

## R15 — ENGINE BUG FIXED AND CONFIRMED; next blocker identified (owner: engine)

**The SPIR-V literal fix works.** Built both profiles, installed the validated
template pair, re-exported Chariot, re-ran the harness on the P40:

**`Tint struct-size error: GONE.`**

The four buffers (`InstanceDataBuffer`, `OmniLights`, `SpotLights`,
`AreaLights`) no longer report impossible layouts. `flatten_binding_arrays` was
substituting `ArrayStride`/`Offset` literals with array element type IDs; adding
`OpDecorate`/`OpMemberDecorate`/`OpName`/`OpMemberName` to the literal-exclusion
block resolved it.

**Screen is still black — a different, well-scoped blocker now surfaces:**

```
[JS-PCREATE-FAIL#4] label="pipe#4:SceneForwardMobileShaderRD:9"
Texture binding (group:1, binding:8) is TextureSampleType::Depth but used
statically with a sampler (group:1, binding:28) that's
SamplerBindingType::Filtering
```

A depth texture sampled with a **filtering** sampler. WebGPU forbids this —
depth requires non-filtering or comparison — where Vulkan does not. Note the
shader is `SceneForwardMobile`, not Forward+, so this is on the shipping tier.
There is already a `fix_depth2_images` pass (p06) in the pipeline, so this
family has been handled before; this is a distinct case in the bind-group
layout rather than the image type.

**Two false negatives on the way to this, both my own tooling:**

1. Tested an export built from a **four-day-old installed template**, because
   `--profile release` cannot install (the tool validates the release+debug
   pair). Reported "still black, fix failed" — wrong, and withdrawn.
2. `--source`/`--build` staleness could not catch it: the export was genuinely
   newer than everything, while *consuming* a stale template. A fan-in check
   cannot see a skipped middle step.

Added `--chain a,b,c` — each element must be newer than the one before, which
models `patches -> templates -> export` and catches exactly that. Also made a
non-existent chain link an error rather than epoch 0, after a typo produced a
spurious "495908h older" break.

**Next:** the depth-sampler validation error. Concrete and bounded: find where
the WebGPU driver builds bind-group layouts and declare samplers paired with
depth textures as non-filtering (or comparison).

## R16 — second engine bug: Depth textures paired with Filtering samplers (owner: engine)

Traced the blocker that surfaced after the SPIR-V fix. Both sites in
`rendering_device_driver_webgpu.cpp` that build bind-group layouts carried:

```cpp
if (is_ms && !is_depth) {
    samp_entry.sampler.type = WGPUSamplerBindingType_NonFiltering;
}
```

The override existed for multisampled textures and **explicitly excluded depth**.
But WebGPU rejects a `TextureSampleType::Depth` binding used with a
`SamplerBindingType::Filtering` sampler — Vulkan permits it, WebGPU does not.
So the one case that needed the downgrade was the one case guarded out.

Fixed at both sites: depth downgrades to NonFiltering unless the sampler is
already Comparison (which is legal for depth). Applied to the build tree and to
`engine/patches/0001-...` (driver hunk 8856 -> 8869), patch re-verified against
pristine 4.7.1, lock checksum updated. Build of both profiles running.

**Not verified.** Same discipline as before: no claim until the templates
install, Chariot re-exports, and the harness confirms. Two engine defects are now
fixed in the series; whether the frame renders depends on whether more remain —
the prior history here is a chain, not a single blocker.

## R17 — depth-sampler fix applied to the WRONG binding path (owner: engine)

Built both profiles, installed templates, re-exported, re-ran. **The
depth/sampler error is unchanged.** My fix did not address this case.

Why: the error is texture `group:1 binding:8` with sampler `group:1 binding:28`.
I fixed `UNIFORM_TYPE_SAMPLER_WITH_TEXTURE`, where the preprocessor emits the
pair adjacently at `binding*2+0` / `binding*2+1`. Bindings 8 and 28 are not a
pair — `entry.binding = u.binding * 2` puts them at uniform indices 4 and 14.
This is a **standalone** `UNIFORM_TYPE_SAMPLER` used in-shader with a
**standalone** depth `UNIFORM_TYPE_TEXTURE`.

`UNIFORM_TYPE_SAMPLER` (line ~4267) sets Filtering unless reflection marks it
comparison, and has no notion of what texture it is used with — that pairing
exists only in the shader.

**What the real fix needs:** the driver already reflects WGSL into
`wgsl_is_depth_texture` and `wgsl_is_comparison_sampler`
(`rendering_device_driver_webgpu.cpp`, map populated ~line 3979). It needs a
companion pass recording `textureSample*(tex, samp, ...)` pairings, so a sampler
used with a depth texture can be declared NonFiltering. Well-scoped, but a
reflection addition rather than a one-line guard.

**The combined-case fix is kept.** The same WebGPU rule applies there and the
`!is_depth` guard was wrong regardless; it is a latent bug fixed, just not this
one. Labelled as such rather than reverted or claimed.

**Scoreboard, honest:**

| defect | status |
|---|---|
| SPIR-V literal corruption | **fixed, confirmed on hardware** |
| Depth+Filtering, combined bindings | fixed, untested, NOT this bug |
| Depth+Filtering, standalone bindings | **open** — needs sampler/texture pairing reflection |

Chariot's WebGPU export still renders black.

**Aside — The Deep measured** (no engine dependency): `applicationRenderer:
no-canvas`, 0 canvases. It is a DOM/CSS game, not canvas-rendered. 60 fps p50,
script 0.01 ms/frame, dynamic range 224, boot 21.3s. The harness handles it, but
`edgeEnergy`-style surface metrics are meaningless for DOM content — worth a
note before anyone calibrates a bar against it.

## R18 — interior probe: the number is reachable, the frame is not yet (owner: content)

Target sharpened by the owner: make Long-Silence-class work easy. Went at the
mechanism the reference names in its own README — `greeble.js`, one system
surfacing everything, welded per material.

Built the bforge equivalent: `kit.room` (16x16m, 4.2m) + `build.greeble`
(density 0.45, depth 0.06, cuts=1) -> 5,616 -> **115,054 tris** of panel geometry.

**Three tooling lessons, each measured:**

1. `cuts=2` blew the 300s daemon budget. Subdividing every face twice before
   panelling is exponential; `cuts=1` plus material layers is the right shape.
2. Baking it to a unique atlas gave **0.4 px/m** (1688 m2 into one 2048 map).
   Box-projecting at a shared 2m scale gave **507 px/m** — a ~1200x difference.
   This is the same rule the colonnade taught, violated again: **bake_pbr is for
   props; large architecture takes geometry + a tiling material in-engine.**
3. `check.critique` caught 43 zero-area faces left by greeble and named
   `gameready.optimize`. Applied; 42 removed.

**The measurement that matters:**

| configuration | edgeEnergy (best shot) |
|---|---|
| greeble geometry only, flat `iron` preset | 5.12 |
| greeble + tiling material through box UVs | **26.58** |
| the bar | 28.38 median |

So the toolset **can** reach the bar's surface-density number, and an enclosed
space is what makes it reachable — nine rounds on an open plaza never passed 22.

**But the frame is not there, and the number is again texture-driven.** Looking
at it: no ceiling (kit.room's roof option unset), surfaces read as wet plastic
(roughness needs variation, metalness too high), and **the 115k triangles of
greeble are invisible** — 0.06m panels on a 16m wall do not resolve at these
framings. The 26.58 comes from the tiling panel seams, not from the geometry.

That is the third time `edgeEnergy` has been satisfied by a tiling texture
rather than authored density. The metric measures high-frequency contrast; it
cannot tell earned detail from printed detail. Only the blind judge has ever
caught that distinction.

**Also fixed by looking, invisible in metrics:** the first interior run scored
edgeEnergy 0 on two shots. Cause: Blender Z-up -> glTF (x, z, -y) puts the room
on NEGATIVE Z, and all four cameras were at positive Z — every shot was outside
the box photographing an exterior wall.

**Next:** roof on, metalness down and roughness variation up, greeble depth up
(~0.15m) so panels actually read, and props in the room. Then judge it — the
objective gate has now said "at the bar" three times while the frame was not.

## R19 — a metric that separates modelled detail from printed detail

R18 ended with `edgeEnergy` reporting "at the reference bar" for the third time
on a frame whose form was carried almost entirely by a tiling texture. A metric
that cannot tell earned detail from printed detail should not be the only thing
gating a still frame, so this round built the instrument that separates them.

**`--geometry-pass`**: with the world paused, re-render the SAME frame with all
materials swapped for a neutral matte, at dt=0 so the simulation state is
byte-identical. Only the shading differs. Games opt in through a new
`materials(mode)` runtime hook; without it the harness reports the pass as
skipped rather than inventing a number.

Measured on the hold, same frame, same camera:

| shot | shaded | matte | earned |
|---|---|---|---|
| hero   | 16.18 | 6.56 | 40.5% |
| corner | 23.66 | 9.82 | 41.5% |
| low    | 15.48 | 6.31 | 40.8% |
| detail | 18.26 | 9.15 | 50.1% |

It paid for itself on the first run. The matte frame made two things obvious
that the beauty frame's sheen was hiding: **the greeble panels have almost no
relief** (they read as inset outlines, not extruded plates), and **there is
still no roof**. Both were invisible in every number the harness produces.

**Correction to what this round set out to test.** The re-forge did not land:
`export.gltf` wants `objects`/`out`, not `object`/`path`, so it failed and the
old GLB stayed on disk. This round therefore measured the SAME geometry as R18
with only the material changed. The honest reading is that the material change
(roughness .65 -> .92, metalness .35 -> .08) lowered shaded edge energy 26.58 ->
23.66 and cut crushed blacks 12.6% -> 4.6%. The 9.82 matte number is the first
trustworthy measure of what the geometry actually contributes, because it is the
same frame; R18's 5.12 was two different scenes and should not be compared to it.

**Also caught: `tsc --noEmit` in the capture path.** Typechecking does not emit,
so the browser ran a stale `interior.js` for a whole capture round -- the exact
staleness class `--source`/`--build` exists to catch, bypassed because I called
`shotset.mjs` directly instead of `round.mjs`, which emits. Numbers barely moved
and the new hook was absent; that was the tell.

**The tooling defect this round actually fixed.** Writing one eight-step recipe
cost four failed runs, one per parameter-spelling mismatch. Measured across the
catalog: "which object" is spelled five ways -- `name` (64 ops), `object` (12),
`objects` (11), `target` (4), `mesh` (2) -- and the output path two ways, `out`
(9) and `path` (7). Worse, `material.set` declares BOTH `object` and `name`,
where `name` is the MATERIAL's name, so the most common guess was silently
accepted as something else and failed three frames later with "object name must
be a non-empty string, got None".

`Op.coerce` now normalises alias groups: any spelling maps onto the one the op
declares, with scalar/list coercion, and where the op genuinely means two
different things by two spellings it raises an error that names the fix instead
of mis-assigning. 10 tests, built from the committed catalog so they track the
real ops, including a sweep asserting all four alternate spellings resolve for
every single-selector op (40+).

**Next:** re-forge with the roof and deeper greeble actually landing, then judge.
The objective gate has now said "at the bar" three times while the frame was not.

## R20 — the geometry lands; corner clears the bar; blacks crush

The re-forge finally took. Same recipe, one change from R19: the export path.

**End-to-end proof of the spelling fix.** R19's recipe was rewritten with
deliberately sloppy, inconsistent spellings -- `name` for every op, `path` for
the export -- which is what an agent actually writes. All nine ops ran clean in
one shot, where the same recipe previously cost four failed runs.

**A third defect in the same family, found by the same recipe.** `export.gltf`
resolves `out` relative to an implicit `assets-generated/bforge/` root, which
nothing states, so an absolute-looking relative path silently DOUBLED:
`assets-generated/bforge/assets-generated/bforge/gauntlet/hold_interior.glb`.
The op reported `ok: true` and a valid 16 MB file, just not where asked, and the
capture that followed measured the old asset. Filed to fix: an export whose
`out` already begins with the asset root is unambiguously this mistake.

**Measured, with the roof and 0.18 m greeble actually present:**

| shot | edgeEnergy | earned | dyn range | black% |
|---|---|---|---|---|
| hero   | 22.83 | 56.6% | 108 | 23.8 |
| corner | **34.59** | 53.5% | 199 | 22.2 |
| low    | 21.35 | **68.0%** | 113 | 27.3 |
| detail | 23.02 | 47.7% | 193 | 24.8 |
| _bar_  | _8.19-30.38, median 28.38_ | — | _median 195_ | _max 5.29_ |

corner is **past the reference band's maximum**, and it gets there with over
half its detail modelled rather than printed -- the first time both have been
true at once. Earned detail went 40-50% -> 48-68% purely from panel depth.
The emissive practicals closed the dynamic-range gap: 76-84 -> 108-199.

**The frame, looked at:** roof with structural beams, two visible light strips,
warm/cool separation across the space, floor plating with recessed channels,
real depth into a dark far corner. First frame this session that could plausibly
sit beside the reference.

**New defect, and it is real: 22-27% of every frame is crushed to black against
the reference's 5.29% ceiling.** Enclosing the room removed the sky that was
lifting the shadows, and nothing replaced it. Also still true: the walls carry
much less relief than the ceiling, and the room is empty -- no crates, pipes or
machinery, which is most of what the reference's frames actually contain.

**The p99 question from R18 is closed.** New spike reporting: "12 spikes over
100 ms, all in the first quarter -- load cost, not a runtime hitch; worst at
frame 20 of 403". It was shader compilation, not a stutter.

**Next:** lift the shadows without flattening the contrast, then judge. This is
the first build worth spending a judge round on.

## R21 — objective gate CLEAN; all four shots above the bar's median

Owner: lighting, sequentially, one lever at a time. Four measurements.

| change | hero | corner | low | detail | warns |
|---|---|---|---|---|---|
| R20 baseline | 22.83 | 34.59 | 21.35 | 23.02 | 4 |
| hemisphere + ambient | 23.28 | 34.82 | 21.81 | 23.36 | 4 |
| **strips emit light; ground colour** | 29.72 | 32.70 | 26.90 | 29.94 | 2 |
| exposure 1.00 -> 1.14 | 32.41 | 35.86 | 29.56 | 32.85 | 1 |
| roof-apex lamp | **33.53** | **35.67** | **29.78** | **32.74** | **0** |

Bar: edgeEnergy 8.19-30.38, median 28.38. **All four shots are above the median
and the objective gate is clean: 0 fatal, 0 warn, 0 page errors.** Earned detail
holds at 39-54%, so the gain is not a texture trick.

**Why the first lighting attempt did almost nothing.** Raising the hemisphere
light moved crushed black 23.8% -> 20.9%: nearly nothing, because the crushed
pixels were almost entirely CEILING. A hemisphere light gives downward-facing
surfaces its GROUND term, and that was set to the darkest colour in the scene.
Two real causes, both found by opening the frame rather than reading the number:

1. The ground colour lights the ceiling. It was 0x3a2c20.
2. **An emissive material in Three.js glows but emits nothing.** The four
   practicals were bright floating rectangles lighting no surface, so the
   ceiling directly above each fixture stayed black. Giving each strip an actual
   PointLight took blacks 20.9% -> 9.3% on corner and raised edge energy at the
   same time.

**Exposure beat ambient for the last of it.** Ambient lifts the histogram floor
by flattening every form it touches, which spends the edge energy the geometry
just earned; exposure scales the whole curve, so relative contrast survives.
1.00 -> 1.14 lifted blacks AND raised edge energy on all four shots.

**The last warn got a targeted fix, not a global one.** `low` is the only camera
that looks up into the 6.6 m pitched roof apex, which nothing reached. A dim
lamp in the roof space cleared it; another exposure bump would have paid for one
camera's problem out of every other camera's contrast.

**Still true, and not measurable:** the walls carry much less relief than the
ceiling, and the room is empty. The reference's frames are full of crates,
pipes and machinery. That is the next gap, and it is a content gap, not a
lighting or material one.

**Next: judge.** The gate is clean, so a blind round is finally earned. Every
previous round would have been spent on a frame with measurable defects.

## R22 — JUDGE: 2W / 2L — 50% — AT_OR_ABOVE_REFERENCE

First non-zero judge result. The win rate had been flat at 0% across three
previous rounds. Brief sha `3a476a74f6671ea9`, unchanged since the first round,
so the criteria did not drift. Fresh sub-agent, deck and brief only.

| pair | our shot | reference | judge picked | result |
|---|---|---|---|---|
| 001 | corner.png | moved.png   | ours | **WIN** |
| 003 | hero.png   | title.png   | ours | **WIN** |
| 002 | detail.png | settled.png | ref  | loss |
| 004 | low.png    | wake.png    | ref  | loss |

**Both losses have the same diagnosis, arrived at independently:**

> "a bare volume lit by two striplights where the identical wet band repeats at
> the same height on every wall panel and there is not a single object in the
> room for the light to occlude or bounce off"

> "A is a bare wall parallel to camera with nothing in front of it ... no
> contact darkening at the wall/floor join"

Two named gaps, both content rather than lighting or material:
1. **The room is empty.** Nothing for light to occlude, nothing to cast contact
   shadow, no focal point. The reference's frames are full of consoles, seating,
   grating and machinery.
2. **The tiling repeats.** One material at one UV scale across every surface, so
   the same specular band lands at the same height on every panel.

**A measurement bug caught in the same round, and it is the worst class.**
`reveal` first reported a confident **0% BELOW_REFERENCE** for this exact deck.
The verdicts carried the judge's choice under `winner` rather than `better`, so
every pair fell through a `if (!k) continue` path and scored as a default loss.
The tool reported the precise opposite of the truth, in the same format and with
the same confidence as a real result.

That is the same failure as the destructive `getContext` probe: an instrument
manufacturing a defensible-looking number when it cannot read its input. Fixed
three ways, each verified: choice is read from any of better/winner/choice/pick/
preferred; a verdict carrying none of them throws; and a pair with no verdict at
all throws rather than counting as a loss.

**Next:** props and set dressing, and per-surface material variation to break
the repeat. Both were also visible by eye, and the judge named them unprompted,
which is the strongest signal yet that they are the real remaining gap.

## R23 — judge holds at 50%; the toolset learns to see a defect it was shipping

Second blind round on the props build: **2W / 2L — 50% — AT_OR_ABOVE_REFERENCE**,
same two pairs won (corner, hero), same two lost (detail, low). Brief sha
unchanged. The win rate did not move, but the round produced new findings, so
the stop condition is not met.

**What the judge saw that no metric did:**

> "one prop on the right resolves as a **solid black slab with no surface at all**"
> "plain **untextured** box props"
> "cast shadows are **razor-hard with no penumbra growth** for a 3 m tube light"

**The geometry pass separated the two prop complaints in one look.** In the matte
frame the props are visibly, densely panelled — so "untextured" was not a
modelling failure, it was texel scale: box UVs are world-derived at 2 m per tile,
so a 1.2 m crate spans 0.6 of a tile and renders as a flat wash. **One material
at one UV scale cannot serve both a 16 m room and a 1.2 m crate.** Props now get
their own material at 4x/8x repeat.

But the black slab was still black in the *matte* pass, under a uniform
material — so it was geometry, not shading.

**Measured, threshold-free.** Comparing each triangle's winding against its own
stored normals, post-`build.cleanup`:

| object | greebled | tris wound against their normals |
|---|---|---|
| cargo_a | yes | 30 (1.48%) |
| cargo_b | yes | 24 (1.40%) |
| locker  | yes | 22 (1.49%) |
| drum    | yes, cylinder | 3 (0.17%) |
| pipe    | **no** | **0** |

Signed volume is positive on all five, so this is localised bad faces rather
than a flipped mesh. `build.greeble` pushes 35% of its panels INWARD, and an
inward extrusion keeps the side-wall winding of an outward one; `build.cleanup`
does not fix it because it is not a manifold problem — non-manifold edges were
already down to 0/3/3/0/0 when these were measured.

**The fix that matters most is that the toolset can now SEE it.**
`check.critique` gained an `inverted_normals` metric and an error-severity
finding. It is threshold-free: each face is compared against itself, so there is
nothing to tune. Verified against the same five assets, it reports 30/24/3/22/0
— identical to an independent offline analysis that parsed the GLB binary
directly. Two independent implementations, same numbers.

This is the session's recurring lesson in its other form: the earlier three cases
were instruments *inventing* numbers; this is an instrument *not measuring* a
defect at all, which let a visible black hole in a prop ship past a clean gate.

**Still open:** the greeble op itself should not produce these faces, and
shadows are razor-hard with no penumbra. Both are named next.

## R24 — greeble geometry fixed; strongest objective state so far

| shot | edgeEnergy | earned | black% | vs R23 |
|---|---|---|---|---|
| hero   | 34.01 | 43.3% | 1.82 | 32.88 -> 34.01 |
| corner | **38.79** | 41.5% | 1.44 | 34.72 -> 38.79 |
| low    | 30.16 | 50.1% | 3.46 | 29.03 -> 30.16 |
| detail | 34.23 | 32.6% | 0.33 | 31.74 -> 34.23 |
| _bar_  | _8.19-30.38, median 28.38_ | — | _max 5.29_ | |

All four shots are now at or above the reference band's MAXIMUM, and crushed
black is below the reference's own worst frame on every shot. Gate clean.

**The greeble fix, in three measured steps.** Original: 30 inverted faces on the
probe box (1.48%), 2022 tris.
1. Hand the offset to `inset_region` instead of extruding and translating by
   hand -> 13 inverted, 890 tris. Fixes the inward-panel winding.
2. Skip faces too narrow to hold their own inset border -> **0** inverted, but
   490 tris. Isolated by measurement: same box and seed gave 0 inverted with no
   bevel and 27 with a 0.03 m bevel, at both deep and shallow settings, which
   rules depth out and names the chamfer.
3. That single inset slopes the rim into the offset, making every panel a
   truncated pyramid. Insetting flat and THEN offsetting at zero thickness ->
   1098 tris with perpendicular walls, 2 inverted (0.18%).

**A process failure worth recording.** Step 2 was measured together with a shadow
change, and earned detail collapsed 48% -> 28%. That was nearly attributed to the
shadows. Isolating -- same assets, shadows reverted -- gave matte edge energy
10.5/10.1/11.6/10.0 versus 10.5/10.1/11.8/9.4, so the shadows were innocent and
the geometry loss was real. **Changing two things in one round nearly cost the
diagnosis**, in a session whose whole method is one owner, one lever, one
measurement.

**Honest note on the depth clamp:** bounding panel depth by the width of the face
it sits on did not change any measured number, because no tested setting came
near the limit. Kept as a guard for extreme parameters, not claimed as a win.

**Still imperfect:** the room carries 792 inverted faces out of 86k triangles
(0.9%) against 1 across all five props. `kit.room` JOINS its pieces, so they meet
at coincident faces -- 2599 non-manifold edges -- and greebling across those
seams is a different problem from the one fixed here. Recorded, not rushed.

## R25 — JUDGE DROPPED to 25%; ambient occlusion was missing entirely

Third blind round on the R24 build: **1W / 3L — 25% — BELOW_REFERENCE**, down
from 50% twice. **The objective numbers went UP while the judge went DOWN** --
all four shots were at or above the reference band's maximum, gate clean, and it
lost a pair it had won twice. That divergence is the finding: the gate is
necessary and is not sufficient, and the judge is the bar.

**The note the judge repeated in every single round, in different words:**

> "no AO where it meets the beam below"
> "meets the floor with no contact darkening at all"
> "pasted on rather than sitting in the room"

**This scene had no ambient occlusion at all.** The outdoor template has a tuned
SSAO pass; it was never carried across. Three rounds of verdicts named it and it
was read as three separate complaints instead of one systematic gap.

Adding it took earned detail from 43/41/50/33% to **52.5/51.8/57.2/34.8%** --
contact darkening is geometric, so it survives the matte pass -- with the gate
still clean and edge energy still at or above the band maximum.

**Three self-inflicted diagnostics on the way, all worth recording:**

1. The first SSAO build rendered four completely blank frames, luma 6.94 on
   every shot -- exactly the page's CSS background, so the canvas drew nothing.
   Cause: **`OutputPass` is not optional once a pass follows `RenderPass`.**
   Without it the chain is never composited to screen. Bisecting cost three
   rounds: composer with RenderPass alone rendered fine, and SSAO still broke it
   with the shader injection removed and with VSM reverted, ruling out both.
2. The first of those measurements was taken while a background re-forge was
   rewriting the room GLB. The browser recorded `hold_interior.glb
   net::ERR_ABORTED`. **Do not measure an asset while something is writing it.**
3. The browser pane reported `canvas 0x0` and `frames: 0`, because a pane that
   is not displayed does not composite and its rAF never runs. It cannot be used
   to diagnose rendering.

**The black slab is room geometry, not a prop.** Props verified clean -- 0 flipped
faces across all five, by two independent implementations. The room carries 447
inverted faces in 88k triangles. `kit.room` JOINS overlapping pieces; welding
BEFORE greeble rather than after took non-manifold edges 2599 -> 767 and inverted
faces 792 -> 447, but pieces that genuinely interpenetrate cannot be welded apart.
That needs kit.room to union its solids, and is recorded rather than rushed.
