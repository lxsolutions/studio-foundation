# WebGPU 4.7.1 runtime status & investigation checkpoint

> **Purpose.** A single, evidence-based snapshot of where the browser WebGPU
> runtime actually stands. Much of this state otherwise lives only in ephemeral
> build/smoke logs under `engine/.cache/` and uncommitted edits in this worktree.
> This file is the handoff — update it whenever the runtime status changes.
>
> **Last reconciled:** 2026-07-27, from `origin/main` @ `0f2bab8` (patch series
> 0001–0022). Supersedes the 2026-07-23 reconciliation, which predated patches
> 0018–0022 and still listed Forward+ on hardware as untested.
> **Scope:** the ADR 0002 runtime-acceptance gate. The editor and WebGL fallback
> are unaffected and green.

---

## TL;DR

> **✅ Updated 2026-07-24: 3D now renders in-browser on real hardware.** The
> original symptom (a lit *or even unshaded* 3D mesh came out black; translation
> stalled on the runtime-specialized scene shader) was a chain of shader-translation
> and bind-group defects, not one bug. Patches 0009–0014 fix the whole chain —
> verified on an NVIDIA Tesla P40 (headed Chrome/WebGPU): the 3D scene draws a lit,
> perspective-projected mesh at 60 fps with **0 `GPUValidationError`** (was 2283).
> The historical root-cause analysis is kept below in **§3D rendering gap** for the
> record.

The boot/RefCounted blocker was genuinely fixed and both templates are locked: the
ADR 0002 gate — rebuild → export → browser WebGPU probe (active canvas context, no
runtime error) → visual compare **1.2%** vs the WebGL baseline — is green **for the
neutral template's 2D menu**, and `engine-lock.toml [artifacts.export_templates]`
records `web_webgpu_release` (`3642cf5e…`) + `web_webgpu_debug` (`1f1ed2b5…`). The
automated gate historically rendered only a 2D Control scene; 3D is now **verified
manually on GPU hardware** (NVIDIA Tesla P40 — six PBR meshes with real-time shadows, 59–60 fps, 0 `GPUValidationError`).
Folding that 3D render into the automated gate is the remaining CI task — hosted
CI now proves the patch series (checksums + a clean-tree apply) on every change,
but a render probe needs a GPU runner and remains self-hosted work.

**One sentence on which renderer that means.** Everything shipped and published —
the live demo, the templates, the performance A/B — is **Forward Mobile**, which
`tools/godot/export_game.py` calls "the hardware-verified default". **Forward+**
is opt-in (`--rendering-method forward_plus`) and **has never rendered a frame.**
As of patches 0023–0029 it gets substantially further — the scene shader
translates, the cluster builder exists, scene pipelines are created and command
buffers encoded, and clears attachment compatibility across 44 measured
pipeline/pass pairs. It renders the 2D UI; the 3D scene is black. The frontier is
now resource and bind-group compatibility.
See §Forward+ on hardware (0023–0029). Do not read a Forward Mobile result as a
Forward+ result, and do not read "the render loop runs" as "a frame rendered".

| Gate | Status | Evidence |
| --- | --- | --- |
| Patch series (0001–0022) applies to official 4.7.1 `a13da4feb8` | ✅ **enforced in CI** | `.github/workflows/patch-series.yml` — checksums + a clean-tree apply on every push and PR |
| Web templates compile (release + debug, `nothreads`, `webgpu=yes`) | ✅ | `bin/godot.web.template_*.wasm32.nothreads.*` |
| Tint SPIR‑V→WGSL translation (storage‑buffer + OpImage ordering) | ✅ | patches 0007, 0008 |
| **Emdawn/Godot `RefCounted` ODR collision** (the heap‑buffer‑overflow) | ✅ **fixed in source** | `engine/toolchain/patches/0001-emdawn-private-namespace.patch`, locked in `[toolchain.emdawnwebgpu]` |
| Rebuild + browser probe (2D menu) with the backport | ✅ 2026‑07‑24 | 2D menu, 1.2% vs WebGL |
| **3D render on GPU hardware** (NVIDIA Tesla P40) | ✅ 2026‑07‑24 — patches 0009–0014 | six PBR meshes + real-time shadows, 59–60 fps, 36 draws/frame, 0 `GPUValidationError` |
| **3D rendering under WebGPU** | 🟢 **in-browser render VERIFIED on an NVIDIA Tesla P40 (patches 0009–0013)** — 3D scene draws a lit mesh at 60 fps, 0 GPUValidationError | §3D rendering gap |
| **3D scene-shader translation** | 🟢 **177/182 translate offline** (was 174); the runtime-specialized scene shader also translates *and renders* after patches 0011–0013 | §3D rendering gap |
| Template artifacts locked in `engine-lock.toml` | ✅ | `[artifacts.export_templates]`: release + debug + sha256 |
| **Forward+ (clustered) shader translation** | 🟢 **translates offline** after patch 0015 — was impossible before | §Forward+ |
| **Forward+ compiles on hardware** | 🟢 2026‑07‑25 — patches 0018–0022 | Tesla P40: full GI/SDFGI/SSAO/SSIL/VoxelGI stack compiles, **0 aborts, 0 wasm traps**. Compilation, not rendering |
| **Forward+ renders a 3D frame** | 🔴 **no** — the 2D UI draws, the 3D scene is black. As of 0023–0029 it runs at 53 fps submitting 319 draws / 2.0M primitives and clears attachment validation (44 pairs, 0 mismatches); the geometry never reaches the presented image | §Forward+ on hardware (0023–0029), with a side-by-side against the Forward Mobile control |
| **Forward+ D24 fallback on adapters without `depth32float-stencil8`** | ⚪ **not measured** — implemented in 0028, but this box has the feature, so the fallback path has never run | §Forward+ on hardware (0023–0029) |

Reference point: a **release** WebGPU export passed a (shallow, non‑ASAN) browser
proof on 2026‑07‑22 — `navigator.gpu` + adapter + active canvas context + 103/103
headless (`engine/.cache/oswt-proof/.studio/verification.json`). ASAN hardening
then surfaced the `RefCounted` overflow that proof did not catch; that is now
fixed and awaiting the re‑verified rebuild.

---

## Forward+ — the renderer ceiling (2026‑07‑25)

Everything above was measured on **Forward Mobile**, because
`tools/godot/export_game.py` hardcoded `--rendering-method mobile` for the
`web-webgpu` preset. Per‑game `project.godot` values never mattered; that one
string decided it for every export the studio has ever produced.

That caps quality at a level no amount of art can lift. In this tree,
`render_forward_mobile.cpp` returns `false` from `_render_buffers_can_be_storage()`
(⇒ no SSAO, SSIL, SSR), `is_dynamic_gi_supported()` (⇒ no SDFGI, no VoxelGI) and
`is_volumetric_supported()` (⇒ no volumetric fog), and hardcodes
`get_max_elements()` to 256 clustered elements. Forward+ inherits the
`RendererSceneRenderRD` base, which returns `true` to all three and reads
`rendering/limits/cluster_builder/max_clustered_elements`.

Forward+ was already compiled into the same template (`forward_clustered/SCsub`
is unconditional) and already a legal web value (`main.cpp` declares
`rendering_method.web` as `forward_plus,mobile,gl_compatibility`; the web export
plugin handles it). It had simply never been selected.

**Two defects blocked it, both in `cluster_render.glsl`, both fixed by patch 0015:**

1. **Subgroup ops with no fallback.** The cluster builder elects one writer per
   cluster via `subgroupBallot`/`subgroupBroadcastFirst`/`subgroupOr`. WebGPU has
   no subgroup support at all — the driver already reported `LIMIT_SUBGROUP_*` as
   `0` — but **nothing in `servers/rendering/` ever read those limits.** 0015 adds
   an appended `USE_SUBGROUPS` variant pair plus a plain-atomics fallback that is
   bit-identical (every invocation the ballot would group writes the same word and
   bit; `atomicOr` is idempotent), and makes the builder honour the limit.
2. **A Tint abort on `gl_HelperInvocation`** —
   `TINT_UNIMPLEMENTED unhandled SPIR-V BuiltIn: HelperInvocation (val = 23)`.
   Same failure mode as the `Volatile` decoration fixed in 0009: an abort is a
   wasm trap, i.e. a frozen page. `cluster_render.glsl` is the engine's only live
   user of that builtin (the other, in `scene_forward_lights_inc.glsl`, is inside
   `#if 0`), which is exactly why Forward Mobile was unaffected.

**Why Forward+ is the better fit for WebGPU, not merely the prettier one:** Forward
Mobile's single untranslatable shader, `tonemap_mobile.glsl`, is also the *only*
shader in the engine using subpasses (`subpassLoad`/`input_attachment`) — a
concept WebGPU does not have. Mobile is designed around tile-based subpass
merging; Forward+ is built on compute and storage buffers, which WebGPU has
natively.

**Measured after 0015–0017** (offline, GPU-free, at the engine's real target env of
Vulkan 1.1 / SPIR‑V 1.3): **199 modules compiled, 0 GLSL failures, 6 Tint failures,
3 skipped.** *None of the six blocks Forward+ under WebGPU:*

| Failure | Blocks Forward+? |
| --- | --- |
| `tonemap_mobile` `subpass` ×2 | No — Forward Mobile only; WebGPU has no subpasses |
| `fsr_upscale` `normal` (16-bit math) | No — the driver reports `SUPPORTS_HALF_FLOAT` false, so `fsr.cpp` selects `FALLBACK`, which translates |
| `cluster_render` `subgroups` ×2 | No — WebGPU selects the no-subgroups variant added by 0015 |
| `sdfgi_debug_probes` | No — editor debug visualisation |

SSAO, SSIL, SDFGI, VoxelGI, volumetric fog, subsurface scattering, TAA, SSR and the
clustered scene shader all translate. Note that `ssao_blur`, `ssil_blur` and
`subsurface_scattering` were previously *assumed* to translate — they were in fact
never compiled, because the harness enumerated them without the `MODE_`/
`USE_*_SAMPLES` defines the engine actually builds them with (fixed in 0016).

**None of the above is hardware-verified — it is offline translation only.**
Translating is not rendering. That prediction held: Forward+ binds far more
aggressively than Mobile, and the next five patches were all things only
hardware could show. See the section below.

## Forward+ on hardware — 168 → 18 (patches 0018–0022, 2026‑07‑25)

Run on a **Tesla P40** through Chrome/WebGPU, exporting with
`export_game.py --preset web-webgpu --rendering-method forward_plus`.

| Patch | What hardware showed | `GPUValidationError` | Aborts / wasm traps |
| --- | --- | --- | --- |
| — | first Forward+ run: page died mid shader-compile, only 2D canvas shaders built | 168 | 1 |
| 0018 | `ShaderRD` compiles *every* variant, and Tint aborts rather than erroring — **a variant the device will never select is fatal merely by being listed**. Plus nine device limits that predated Forward+'s compute passes | 106 | **0** |
| 0019 | sampled-texture `sampleType` was hardcoded `Float`; Forward+ reads cluster data, VoxelGI and SDFGI as **integer** textures — 32 of the remaining failures, the largest single class | 42 | 0 |
| 0020 | negative sampler `min_lod` (legal in Vulkan, rejected by WebGPU) + storage-to-sampled sample type taken from format instead of the shader | 38 | 0 |
| 0021 | the storage-format table recorded its `RGBA8Unorm` *initialiser* on no match, so an unknown format silently succeeded with the wrong answer; `rgb10a2unorm` appears 26× in Forward+'s WGSL and was missing | 26 | 0 |
| 0022 | the same format-vs-shader correction at the two shadow-entry sites 0020 missed | **18** | 0 |

**Status: compiles, does not render. Forward+ has never produced a frame.**

Be exact about this, because the progression above is easy to over-read. What
0018–0022 bought is that the full GI/SDFGI/SSAO/SSIL/VoxelGI stack **compiles**
on real hardware and nothing aborts — which genuinely matters, since a
`GPUValidationError` fails one pipeline gracefully whereas an abort is a wasm
trap and a dead page. It is not a rendering claim. #29 said so in as many words
— *"Forward+ still does not render. This clears the abort layer, not the finish
line"* — and no patch since has claimed otherwise: 0019–0022 report validation
counts and abort counts, never an fps figure or a draw count, which is exactly
what the Forward Mobile verifications do report.

**`mobile` therefore remains the default and everything published runs Forward
Mobile.** Forward+ is an investigation path, not something to ship or to cite.
Pipeline warm-up and shader compilation are not a rendered-frame claim.

The recurring lesson across all five: **WebGPU validates a bind-group layout
against the *shader*, not against our idea of the texture's format.** Wherever
the driver still infers a type from a format, expect the next one.

Worth recording from 0021: three consecutive attempts reported "no change" and
the fix was twice reverted as unproven. The build script piped `engine.py build`
through `tail`, so the pipeline's exit status was `tail`'s — **a failed build
looked successful**, and every measurement was of a stale binary. `CLAUDE.md`
warns about exactly this.

## Forward+ on hardware — 18 → the render loop runs (patches 0023–0029, 2026‑07‑28)

Same host: a Tesla P40 through headed Chrome/WebGPU under Xvfb, Chariot exported
with `--rendering-method forward_plus`, measured by
`tests/browser/render-probe.mjs` (which reads the canvas back and counts distinct
colours, so a cleared-but-never-drawn buffer cannot be mistaken for a frame).

**Forward+ still has not presented a 3D frame — but it is no longer doing
nothing.** Measured on the same host with the same scene and camera as the
Forward Mobile control:

| | Forward Mobile (control) | Forward+ |
| --- | --- | --- |
| renderer reported by the engine | `mobile` | `forward_plus` |
| draw calls / frame | 93 | **319** |
| primitives / frame | — | **2,024,578** |
| fps | — | **53** |
| canvas dominant-colour fraction | 0.336 (varied) | **0.987 (near-uniform)** |
| `GPUValidationError` | 0 | 5816 |

![Forward Mobile renders the colosseum](../images/forward-mobile-control.png)
![Forward+ renders the 2D UI and nothing else](../images/forward-plus-3d-black.png)

The engine is running Forward+ at 53 fps and submitting two million primitives
across 319 draws. **The 2D UI renders correctly; the entire 3D scene is black.**
The 1.3% of non-black pixels is the UI text.

Godot's global draw counter includes canvas and tonemap work, so it alone does
not show that the *scene* path submitted anything. Counting actual
`draw`/`drawIndexed` commands per pipeline through `pass-trace.mjs` does:

```json
{"draw_calls_total": 233159,
 "draw_calls_by_shader": {"SceneForwardClusteredShaderRD": 223338,
                          "CanvasShaderRD": 6874, "SkyShaderRD": 983,
                          "TonemapShaderRD": 982, "BlitShaderRD": 982},
 "distinct_pairs": 50, "matched_pairs": 50, "mismatched_pairs": 0}
```

**223,338 real geometry draw calls are issued under the clustered scene shader**,
and sky, tonemap and blit pipelines are all driven.

Be precise about what that does and does not establish. It shows the CPU-side
Godot renderer and the browser's command *recording* path reach the scene shaders
and issue the draws. It does **not** show those draws executed on the GPU: an
invalid bind group or texture view poisons its command buffer, and the rejection
happens at `finish()`/`submit()` — after Godot has already incremented its
counters and after these wrappers have already observed the calls. So the
correct statement is "the scene workload is recorded", not "the scene workload
runs and its output is discarded".

That distinction points the investigation at **command validity** — not at
culling, camera placement, lighting, attachment formats, or whether geometry was
submitted, all of which are now ruled out.

`tests/browser/binding-trace.mjs` settles which resource fails first. It wraps
each `createBindGroup` in its own `pushErrorScope('validation')`, so a failure is
attributed to that exact call rather than correlated by timestamp, and it records
the descriptor at creation time because WebGPU objects will not report afterwards
what they were made from. The first non-cascade failure, in command order:

```
createBindGroup #282   layout bgl:SsEffectsDownsampleShaderRD:1:set1
  binding 0
    supplied  textureView  viewFormat=r16float  textureFormat=r32float
    expected  storageTexture format=r32float
```

The texture is correctly promoted to `r32float`; the **view was created with the
un-promoted logical format**. That view is invalid, every bind group referencing
it is invalid, and so is the command buffer holding the scene draws — while the
canvas UI, encoded separately, presents normally. Fixed by patch 0030.

Through 0022 it stopped in shader translation. It now compiles the scene shader,
builds its cluster list, creates scene pipelines, encodes command buffers, and
clears render-pass/pipeline attachment validation entirely — 44 distinct
pipeline/pass pairs, zero mismatches. What remains are four measured resource and
binding mismatches. Each layer cleared has revealed a different problem, not the
same one restated.

> **How this was nearly missed.** The first version of the render probe read the
> canvas back with `drawImage` + `getImageData`, which returns solid black on this
> Chrome/Xvfb/WebGPU host *even while the page is demonstrably rendering*. It
> reported the Forward Mobile control — the image above — as a uniform cleared
> buffer. Every verdict it produced was a false negative, including the Forward+
> ones. The probe now measures the composited screenshot clipped to the canvas,
> and is calibrated against three controls on this host: a WebGPU clear-only page
> (`not-rendered`), a page with HTML chrome outside a cleared canvas
> (`not-rendered`), and Forward Mobile (`rendered`, 93 draws). A verification tool
> without a positive control is an assumption.

| Patch | What hardware showed | `GPUValidationError` | Frame |
| --- | --- | --- | --- |
| — | baseline, reproducing the 0022 checkpoint exactly | 18 | no |
| 0023 | the runtime **edited Tint's correct output into invalid WGSL** — every read_write storage buffer was demoted to read-only in the fragment stage as well as the vertex stage, over a struct of `atomic<u32>`. WebGPU only forbids writable storage in the *vertex* stage | 14 | no |
| 0024 | `"textureLoad(" + var_name` is a prefix match, so `src_light` also rewrote `src_light_aniso`, which then got a second mip argument | 6 | no |
| 0025 | `SUPPORTS_FRAGMENT_SHADER_WITH_ONLY_SIDE_EFFECTS` returned true; WebGPU requires a render pass to have at least one attachment | 6 | no |
| 0026 | **the actual blocker.** `scene_forward_clustered.glsl` calls `subgroupMin`/`subgroupMax`/`subgroupOr` with no guard of any kind, so the scene shader never translated | 6 | no |
| 0027 | `depth32float-stencil8` is an optional device feature; using it unrequested throws a `TypeError` from `createRenderPipeline`, which stops the renderer rather than failing one pipeline | 3952 | no |
| 0028 | D32 support was answered from a static table, so Godot would pick a format the device cannot create and never reach its own D24 fallback | — | no |
| 0029 | an **unused fragment output was becoming a real `rgba8unorm` target** — masking writes does not make a target absent, and the render-pass path already emitted null for the same slot | 4780 | no |

**Read the 0027 row correctly.** The count rose because the renderer began
running a per-frame loop instead of dying once — thousands of occurrences of a
handful of classes, repeated every frame. Normalised, the remaining classes are:

| Class | Distinct | Status |
| --- | --- | --- |
| ~~pipeline/render-pass attachment state incompatible~~ | — | **closed by 0029** |
| *(all four below are measured mismatches; a shared root cause is suspected, not proven)* | | |
| `sampler2DMS` texture-vs-sampler binding (`ResolveShaderRD`, `SsEffectsDownsample`) | 1 | open |
| comparison sampler bound as non-comparison | 1 | open |
| R8Unorm texture where RGBA8Unorm expected | 1 | open — likely a concrete placeholder format standing in for missing metadata, the same shape of defect as 0029 |
| R16Float view of an R32Float texture | 1 | open — likely a view derived from the logical rather than the physical (promoted) format |
| invalid CommandBuffer / BindGroup / TextureView | 3 | cascades from the above |

The attachment mismatch, captured from the browser and **closed by 0029**:

| | colour targets | depth | samples |
| --- | --- | --- | --- |
| `SceneForwardClusteredShaderRD:19` pipeline, before 0029 | `rgba16float, rgba8unorm, rgba8unorm` | `depth32float-stencil8` | 1 |
| its actual render pass | `rgba16float, null, null` | `depth32float-stencil8` | 1 |
| after 0029 | `rgba16float, null, null` | `depth32float-stencil8` | 1 |

**How that was diagnosed matters, because the first attempt got it wrong.**
Listing pipelines and passes as two independent sets suggested the scene pipeline
was running against a single-target `rgba8unorm` pass with no depth. It was not —
those were the Tonemap and Canvas passes. `tests/browser/pass-trace.mjs` records
every `setPipeline` **against the pass it was issued inside**, which showed the
scene pass had been correct all along and the pipeline was the wrong side. After
0029 it reports 44 distinct pipeline/pass pairs with **zero mismatches**.

**Two results worth keeping regardless of what the next layer costs.**

*The null cluster builder was downstream, and that is measured rather than
argued.* `_render_scene` failed `ERR_FAIL_NULL(current_cluster_builder)` 1234
times per run. Godot allocates that pointer in
`RenderBufferDataForwardClustered::configure()`, which is nowhere near shader
translation, so the two looked independent. Applying 0026 alone:

```
subgroup translation failures   18 -> 0
current_cluster_builder null  1234 -> 0
```

*Patch 0015 fixed half the problem and the docs did not notice.* It gave
`cluster_render.glsl` a no-subgroups variant and taught the cluster builder to
honour `LIMIT_SUBGROUP_*`. The scene shader was never touched and had no guard
at all. "Forward+ compiles" was true of the cluster builder and false of the
thing that actually shades.

**Portability, not just this P40.** 0027 requests `depth32float-stencil8` only
when `adapter.features` exposes it, and 0028 makes the driver answer D32 support
from the *created device's* enabled features. Without 0028 the stack would work
on hardware that happens to have the feature and fail everywhere else, because
Godot's own `D24_UNORM_S8_UINT` fallback is only reachable if this driver admits
D32 is unavailable. That fallback path is untested on real hardware here — this
box has the feature — and is listed under open work.

### Reproducing the sweep

```bash
# ~1 minute; needs only Godot's vendored glslang, not the full Tint build.
bash drivers/webgpu/tint_cli/build_glsl2spv.sh
python drivers/webgpu/wgsl_precompile.py <engine-tree> /tmp/out.gen.h <engine-tree>/bin/glsl2spv
```

On Windows, `bin/tint_convert_cli` must also exist **without** the `.exe`
suffix — Python's `os.path.isfile` does not auto-append it the way Git Bash does.

---

## 3D rendering gap — RESOLVED; in-browser render verified (patches 0009–0013, 2026-07-24)

**Fix:** Tint's SPIR-V reader (`Parser::EmitVar`) aborts with `TINT_UNIMPLEMENTED`
"decoration 21" (`Volatile`) on Godot's coherent compute shaders — concretely
`volumetric_fog.glsl`, compiled by Forward Mobile during 3D init. In the browser
that abort is a wasm trap → frozen page → all 3D black. Patch 0009 strips the
`Volatile` decoration in `spirv_preprocess.cpp` (same as `Restrict`). Found and
verified **GPU-free** by building a native offline reproducer of the exact runtime
path — `glsl2spv` (Godot's glslang) → the driver's 11 preprocess passes → Tint
(`tint_convert_cli`): over all 182 engine shaders, `volumetric_fog` was the only
crash, and with 0009 it translates with **0/182** crashes/hangs. In-browser render
verification is still pending a GPU-capable machine (this dev box has none). The
original investigation notes below are retained for context.

**Follow-up — patch 0010 (combined-sampler split is now transitive).** With the
crash gone, 8 of 182 shaders still failed Tint *gracefully* (translation returns
an error → the effect is skipped, 3D still renders). Three of those were the same
class of bug: `split_combined_samplers` rewrites GLSL `sampler2D` into WebGPU's
required separate texture + sampler, but only started that rewrite for functions
called with a combined **global** variable. A combined sampler forwarded through a
wrapper into a deeper helper (Godot's tonemap bicubic-glow `texture2D_bicubic`
chain, and `taa_resolve`) left the wrapper's parameter split (`ptr(Image)`) while
the callee stayed `ptr(SampledImage)` — an invalid `OpFunctionCall` argument-type
mismatch that Tint rejects. Patch 0010 iterates the split to a fixpoint, following
every forwarded combined value and splitting each callee back to the same
underlying global sampler. Verified offline with the same reproducer **plus
SPIRV-Tools validation**: the three shaders now pass validation and translate to
correct WGSL (separate `texture_2d` + `sampler`, `textureSampleLevel` wired to the
split pair), coverage 174 → **177/182**, still 0 crashes. The 5 remaining are
fundamental WGSL feature gaps (subpass `input_attachment` ×2, storage-texture
format inference on `ssr_filter`, vertex-stage `read_write` storage on
`voxel_gi_debug`, vertex `@builtin(position)` on `sdfgi_debug_probes`), not
combined-sampler issues.

**Symptom (original).** WebGPU renders 2D/Control UI (menus) but any 3D scene is black. A
minimal `Node3D` + `BoxMesh` + `Camera3D` probe — even with an **unshaded**
material — renders correctly under WebGL and is black under WebGPU. So it is not a
lighting/shadow issue; it is the base 3D draw path.

**Root cause (instrumented, 2026‑07‑24).** A `WEBGPU_VERBOSE` build shows WebGPU
inits (`WebGPU 1.0 - Forward Mobile - Using Device`), submits ~3 frames, and
translates the first ~50 shaders through Tint fine (2D `CanvasOcclusionShaderRD`
pipelines get created). Then translation of the **~51st shader — the large 3D
`SceneForwardMobile` uber‑shader — hangs and never completes** (`tint_misses`
frozen at 50 after 90 s = a genuine hang, not slowness). The hang is in the
synchronous SPIR‑V→WGSL step in `_translate_spirv_to_wgsl`
(`rendering_device_driver_webgpu.cpp`): either one of the `spirv_preprocess::*`
passes or `tint_wrapper_spirv_to_wgsl`. A per‑pass `[XLATE]` tracer build is in
flight to name the exact step.

**Secondary problem.** `precompiled_hits=0` — `wgsl_precompiled.gen.h` is empty
(`_wgsl_precompiled_count = 0`) because `bin/tint_convert_cli` was never built
(`wgsl_precompile.py` errors out without it). So even once the hang is fixed, every
shader hits slow runtime Tint until the precompile table is populated (build
`drivers/webgpu/tint_cli/build.sh`).

**Reproduce.** Point the neutral template `main_scene` at a Node3D+BoxMesh probe
(unshaded), `export_game.py --preset web-webgpu`, `run_browser_smoke.py` (widen its
`relevant` console filter to include `[shader]|[diag|[js-p|[xlate`), read the last
`[XLATE]`/`[SHADER]` line before the stall.

**Gate blind spot.** The ADR 0002 acceptance gate exercises the neutral template's
**2D** menu, so it passed while 3D was broken. **Add a 3D render probe to the gate**
so "WebGPU renders" can never again mean "2D only."

---

## Root cause (confirmed) — the 36‑byte heap‑buffer‑overflow

The ASAN debug smoke crashed during `RenderingDeviceDriverWebGPU` init, after the
JS‑preinitialized device was imported but before the canvas context was
configured (`webgpuCanvasContexts:0`), with:

```
==ERROR: AddressSanitizer: heap-buffer-overflow ...
WRITE of size 36 at 0x16cf21e8 thread T0
```

**Why 36 bytes:** the pinned Emdawn WebGPU port (`v20250531.224602`, Dawn rev
`ea66c0fa…`) predates Dawn's change that wraps its private implementation types in
an anonymous namespace. Without that isolation, Emdawn's **global** C++
`RefCounted` class collides at WebAssembly link time with **Godot's** global
`RefCounted`. The linker resolves the one symbol to a single definition, so Emdawn
allocates an object sized for *its* `RefCounted` while a constructor/method sized
for the *other* (larger) `RefCounted` writes past the end — a fixed‑size heap
overflow. (Authoritative write‑up: `engine/toolchain/README.md`.)

This also explains why the earlier non‑ASAN release proof "passed": the overflow
wrote into adjacent heap slack instead of tripping a guard. It is real UB either
way.

### Note on the earlier ASAN dead‑ends (now moot)

The all‑day `engine/.cache/studio-webgpu/*.log` experiments — `binding-visibility`,
`null-instance`, `instance-parent`, `malloc-wrap`, `named-stack`,
`spontaneous-callback`, and the unfinished 22:36 no‑opt link — were attempts to
*localize* the crash while the in‑browser ASAN symbolizer kept self‑crashing
(`_emscripten_pc_get_function` → `reading 'getName'` of undefined = wasm built
without a function‑name section). Those are **superseded**: the bug was localized
by ODR reasoning, not by symbolization. If a future crash ever needs symbolizing,
the fix is to rebuild with **`--profiling-funcs`** (keeps the wasm name section)
or use `~/emsdk/upstream/emscripten/emsymbolizer.py` — but that path is not needed
for the current blocker.

---

## The fix — Emdawn private‑namespace backport

`engine/toolchain/patches/0001-emdawn-private-namespace.patch` wraps Emdawn's
private implementation block in `webgpu/src/webgpu.cpp` in an anonymous
`namespace { … }`, giving those types internal linkage so `RefCounted` no longer
collides with Godot's. It is a narrow backport of upstream Dawn commit
`2752c7d71a190c8512f38ceda922253d23876fb4`.

Delivered as a first‑class, checksum‑locked **toolchain input** (ADR 0002 rule 13),
not another engine upstream:

- `engine-lock.toml [toolchain.emdawnwebgpu]` pins `version`, `revision`,
  `source_sha256`, `patched_sha256`, the patch path, `patch_sha256`, and
  `upstream_fix_commit`.
- `engine/scripts/emdawn_port.py` (`prepare_locked_emdawn_port`) locates the
  SDK's built‑in Emdawn package (read‑only), verifies version/Dawn‑rev/`webgpu.cpp`
  SHA, copies it to `engine/.cache/toolchains/emdawnwebgpu`, applies + verifies the
  patch, and hands the local port path to the build via `EMDAWNWEBGPU_PORT`.
- `engine/scripts/tests/test_emdawn_port.py` covers it.
- Already applied in this worktree's cache (patched `webgpu.cpp`, anon namespace
  present).

`engine.py build` (=`just engine-build`) wires this automatically before the scons
web build, so a normal rebuild picks up the fix.

---

## Patch 0008 — `tint-image-ordering` (registered)

`engine/patches/0008-tint-image-ordering.patch` (listed in `engine-lock.toml`
series, sha256 `14af2071…`). In `thirdparty/tint/.../spirv/reader/lower/texture.cc`
the reader lowered `OpImage` *interleaved* in the single `builtin_worklist`, so an
`OpImage` could be lowered **after** a texture builtin that consumes its result.
0008 splits `OpImage` into a separate worklist processed **first**. Verified sound
by reading the applied tree (lines 216–265). A shader‑translation correctness fix,
independent of the `RefCounted` overflow.

---

## Verification (2026-07-24) — how the gate was closed

Run from this worktree, tools venv Python (system Python lacks SCons / PIL):

1. `engine.py build` (via `tools/.venv/Scripts/python.exe`) — release **and** debug
   web templates rebuilt with the locked Emdawn namespace port applied. Both
   installed to `engine/artifacts/templates/*.webgpu.zip`. (`just engine-build`
   fails: its `{{PY}}` is system Python, no SCons — run under the venv.)
2. `export_game.py --game templates/godot-game --preset web-webgpu` → export OK.
3. `capture_web.py … --preset web-webgpu` → **exit 0**: `capture.mjs` throws on an
   inactive context, so this confirms an **active WebGPU canvas context** rendered a
   frame with no runtime error / heap-buffer-overflow.
4. `compare_screenshots.py web-webgl.png web-webgpu.png --max-diff-ratio 0.03` →
   **ratio 0.0120 (1.2%) < 0.03** — pixels verified against the WebGL baseline.
5. `engine.py record-artifacts` → wrote both templates (bytes + sha256) into
   `engine-lock.toml [artifacts.export_templates]` and cleared the `blocker`.
6. Independent wiring check: `test_emdawn_port.py` 4/4 (prepares the exact locked
   port; rejects tampered source/patch/cache).

## Remaining / follow-ups

- **Commit the branch.** Uncommitted here: patch 0008, the Emdawn toolchain backport
  + `emdawn_port.py`, `engine-lock.toml` (flags + toolchain + recorded artifacts),
  ADR 0002 / README / this doc, `smoke.mjs`. Then merge `codex/godot-webgpu-recenter`
  to `main` (currently 4 commits ahead of the last PR).
- **Optional stronger proof:** an ASAN build re-run to show the heap-buffer-overflow
  is gone (the release proof passed pre-fix too, so it is necessary but not
  discriminating). The fix is structural (namespace isolation removes the ODR
  collision at link time) and the functional gate matches the lock's definition of
  done, so this is extra assurance, not a gate.
- **Fix `just engine-build`** to use the tools-venv interpreter so the front-door
  recipe works without the manual venv path.
- Regenerate the disposable applied tree from patches at some point to drop the
  ad-hoc ASAN instrumentation (see Fragility warning).

Already reconciled in this worktree (uncommitted): `engine-lock.toml` build flags
(`threads=no`, `webgpu=yes`, `opengl3=no`), the `[toolchain.emdawnwebgpu]` lock,
the ADR rule 13, and the `blocker` line. The stale, dirty duplicate is the
**primary `studio-foundation` worktree** (`main` @ `459faa0`, 4 behind
`origin/main`, patches 0001–0003 only) — ignore it; this branch is source of truth.

## Fragility warning

Diagnostic instrumentation (extra `EM_ASM` probes in `main.cpp` /
`worker_thread_pool.cpp`, etc.) lives **only** in the disposable applied tree
`engine/.cache/studio-webgpu`, not in any patch. A clean regenerate from the patch
series will drop it. That is fine now the root cause is fixed; fold anything worth
keeping into a `WEBGPU_VERBOSE`‑gated patch before regenerating.
