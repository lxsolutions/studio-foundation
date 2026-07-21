# Runbook: Rebase the WebGPU fork onto a new official Godot

Scope: bringing `engine/.cache/godot-webgpu` (dwalter/godotwebgpu) from its
pinned base (4.6.2) up to the studio's editor-of-record (4.7.1) so its export
templates read the same .pck format our editor writes.

Per ADR 0002 the fork is largely AI-generated and treated as **untrusted input**:
after any rebase, a full test + visual-regression pass is required before the
new templates may be used for exports.

## Current state (2026-07-20)

- Branch `webgpu-4.7.1-rebase` in `engine/.cache/godot-webgpu` holds an
  in-progress **merge** of official `a13da4feb8d8aefc283c3763d33a2f170a18d541`
  (4.7.1-stable) into fork `f329e39ce8db` (webgpu-4.6.2). A merge (not a linear
  rebase) was chosen to preserve the fork's 348-commit history and because the
  fork↔official trees share merge-base `89cea143`.
- Merge surface: 348 fork commits, 3444 official commits, 1776 fork-touched
  files. Initial conflict count: **119 files**.
- **54 mechanical conflicts already auto-resolved** (docs, `editor/translations/*.po`,
  `modules/mono` SDK files, `.github`, `CHANGELOG`/`README`/`misc/`, `version.py`)
  by taking official (`--theirs`) — these carry no fork-specific logic.
- **Resolution progress (2026-07-20):** 54 mechanical auto-resolved + `platform/web`
  (`display_server_web.h`, `detect.py`) resolved by hand (union of fork's
  `WEBGPU_ENABLED` include with official's forward-decls; official's
  `EnumVariable`/assertion refactor taken). **63 core-engine conflicts remain.**
  The merge is mid-state in git's index on branch `webgpu-4.7.1-rebase` — this
  survives across sessions; just `cd` in and continue.
- Remaining (see `engine/rebase-4.7.1-conflicts.txt` for the original list):
  drivers 13, scene 10, servers 10, editor 9, thirdparty 7, modules 3. The critical ones are where the fork's
  renderer work meets upstream 4.6.2→4.7.1 changes:
  `servers/rendering/rendering_device.cpp` (18 markers),
  `servers/rendering/rendering_device_driver.h`,
  `servers/rendering/renderer_rd/renderer_compositor_rd.cpp`,
  `servers/rendering/renderer_rd/forward_mobile/render_forward_mobile.cpp`,
  `servers/display/display_server.{cpp,h}`, `platform/web/*`.

## The fork's actual surface (what must survive)

Additive (safe, keep `--ours`): `drivers/webgpu/` (tint_wrapper, spirv_preprocess,
wgsl_precompile, webgpu_objects, rendering_shader_container_webgpu, tint_cli/*),
plus `platform/web/js/*` WebGPU glue.

Overlapping (the real merge work): ~30 files under `servers/rendering/renderer_rd/`
where the fork patched the RD renderer for WebGPU. Each conflict here needs a
human/agent to verify the fork's WebGPU path still composes with 4.7.1's RD changes
— never blanket-resolve.

## Resume steps

1. `cd engine/.cache/godot-webgpu && git status` (merge in progress on
   `webgpu-4.7.1-rebase`).
2. Resolve remaining conflicts subsystem by subsystem, starting with
   `platform/web` (smallest, most fork-relevant), then `servers/rendering`, then
   `drivers`, `scene`, `editor`, `thirdparty`, `modules`.
   For `thirdparty`, prefer official (`--theirs`) unless the fork deliberately
   pinned a different library version (check the fork's commit message).
3. `git add` resolved files; `git commit` the merge when `git diff --check` is clean.
4. Rebuild: `just engine-build` (scons 4.9.1 + emsdk 4.0.11 — both installed).
5. **Mandatory validation gate** (ADR 0002): `just test`, then
   `just export-browser-webgpu` and confirm the WebGPU build boots past pack load
   (previously failed with `Pack version unsupported: 4`), then
   `just capture-web --preset web-webgpu` and `just compare-screenshots` against
   the WebGL baseline before claiming WebGPU support in BOOTSTRAP_REPORT.md.
6. Update `engine/engine-lock.toml` (`godot.webgpu_fork.commit/base`) and ADR 0002.

## Alternative (if the merge proves too entangled)

Export WebGPU with a pinned 4.6.2 editor instead (matches the fork as-is).
Faster to green, but the editor-of-record stays 4.7.1 and the pack-format gap
persists for every future Godot bump. The merge is the correct long-term fix.
