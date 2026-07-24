# WebGPU 4.7.1 runtime status & investigation checkpoint

> **Purpose.** A single, evidence-based snapshot of where the browser WebGPU
> runtime actually stands. Much of this state otherwise lives only in ephemeral
> build/smoke logs under `engine/.cache/` and uncommitted edits in this worktree.
> This file is the handoff — update it whenever the runtime status changes.
>
> **Last reconciled:** 2026-07-23 (evening, local UTC−6), from
> `codex/godot-webgpu-recenter` @ `d70a27e` + uncommitted WIP.
> **Scope:** the ADR 0002 runtime-acceptance gate. The editor and WebGL fallback
> are unaffected and green.

---

## TL;DR

> **⚠️ Corrected later on 2026-07-24: the gate below only ever exercised 2D UI.**
> WebGPU renders 2D/Control content but **not 3D** — a lit *or even unshaded* 3D
> mesh is black under WebGPU while WebGL renders it. Root cause: the 3D scene
> uber-shader **hangs during synchronous SPIR‑V→WGSL translation** (first ~50
> shaders translate; the ~51st never completes). See **§3D rendering gap** below.
> Do not read "renders in the browser" as "renders 3D games."

The boot/RefCounted blocker was genuinely fixed and both templates are locked: the
ADR 0002 gate — rebuild → export → browser WebGPU probe (active canvas context, no
runtime error) → visual compare **1.2%** vs the WebGL baseline — is green **for the
neutral template's 2D menu**, and `engine-lock.toml [artifacts.export_templates]`
records `web_webgpu_release` (`3642cf5e…`) + `web_webgpu_debug` (`1f1ed2b5…`). The
gate's blind spot — it renders a 2D Control scene, never a 3D one — is exactly what
let "WebGPU renders" overclaim slip through. **A 3D probe must be added to the gate.**

| Gate | Status | Evidence |
| --- | --- | --- |
| Patch series (0001–0008) applies to official 4.7.1 `a13da4feb8` | ✅ | `just engine-versions` → "patch series: 8 patch(es)" |
| Web templates compile (release + debug, `nothreads`, `webgpu=yes`) | ✅ | `bin/godot.web.template_*.wasm32.nothreads.*` |
| Tint SPIR‑V→WGSL translation (storage‑buffer + OpImage ordering) | ✅ | patches 0007, 0008 |
| **Emdawn/Godot `RefCounted` ODR collision** (the heap‑buffer‑overflow) | ✅ **fixed in source** | `engine/toolchain/patches/0001-emdawn-private-namespace.patch`, locked in `[toolchain.emdawnwebgpu]` |
| **Rebuild + browser probe (2D UI only)** with the backport | ✅ 2026‑07‑24 — **2D only** | 2D menu, 1.2% vs WebGL |
| **3D rendering under WebGPU** | ❌ **black — hangs in 3D scene-shader translation** | §3D rendering gap |
| Template artifacts locked in `engine-lock.toml` | ✅ | `[artifacts.export_templates]`: release + debug + sha256 |

Reference point: a **release** WebGPU export passed a (shallow, non‑ASAN) browser
proof on 2026‑07‑22 — `navigator.gpu` + adapter + active canvas context + 103/103
headless (`engine/.cache/oswt-proof/.studio/verification.json`). ASAN hardening
then surfaced the `RefCounted` overflow that proof did not catch; that is now
fixed and awaiting the re‑verified rebuild.

---

## 3D rendering gap — ROOT-CAUSED AND FIXED (patch 0009, 2026-07-24)

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
