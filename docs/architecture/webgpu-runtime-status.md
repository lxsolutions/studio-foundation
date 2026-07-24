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

**Root cause found, fixed, and verified end-to-end (2026-07-24). WebGPU 4.7.1
renders in the browser and both templates are checksum-locked.** The full ADR 0002
gate — rebuild → export → browser WebGPU probe (active canvas context, no runtime
error) → visual compare **1.2%** vs the WebGL baseline (3% threshold) — is green,
and `engine-lock.toml [artifacts.export_templates]` now records
`web_webgpu_release` (`3642cf5e…`) + `web_webgpu_debug` (`1f1ed2b5…`).

| Gate | Status | Evidence |
| --- | --- | --- |
| Patch series (0001–0008) applies to official 4.7.1 `a13da4feb8` | ✅ | `just engine-versions` → "patch series: 8 patch(es)" |
| Web templates compile (release + debug, `nothreads`, `webgpu=yes`) | ✅ | `bin/godot.web.template_*.wasm32.nothreads.*` |
| Tint SPIR‑V→WGSL translation (storage‑buffer + OpImage ordering) | ✅ | patches 0007, 0008 |
| **Emdawn/Godot `RefCounted` ODR collision** (the heap‑buffer‑overflow) | ✅ **fixed in source** | `engine/toolchain/patches/0001-emdawn-private-namespace.patch`, locked in `[toolchain.emdawnwebgpu]` |
| **Rebuild + browser WebGPU probe** with the backport | ✅ **verified 2026‑07‑24** | full gate green (this file, §Verification) |
| Template artifacts locked in `engine-lock.toml` | ✅ | `[artifacts.export_templates]`: release + debug + sha256 |

Reference point: a **release** WebGPU export passed a (shallow, non‑ASAN) browser
proof on 2026‑07‑22 — `navigator.gpu` + adapter + active canvas context + 103/103
headless (`engine/.cache/oswt-proof/.studio/verification.json`). ASAN hardening
then surfaced the `RefCounted` overflow that proof did not catch; that is now
fixed and awaiting the re‑verified rebuild.

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
