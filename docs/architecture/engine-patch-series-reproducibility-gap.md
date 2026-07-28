# The engine patch series does not reproduce a buildable engine

- Status: **confirmed, unresolved**
- Found: 2026-07-28, while landing the SPIR-V literal fix
- Affects: `engine/patches/`, `engine/engine-lock.toml`, ADR 0002, ADR 0008

## What happened

`engine/engine-lock.toml` presents three checksummed patches as the complete,
reproducible definition of the Studio WebGPU engine:

```toml
[patches]
series = [
  { file = "patches/0001-studio-webgpu-engine.patch", sha256 = "..." },
  { file = "patches/0002-studio-webgpu-spirv.patch",  sha256 = "..." },
  { file = "patches/0003-studio-webgpu-tint.patch",   sha256 = "..." },
]
```

Regenerating the workspace from that series (`engine.py fetch`, which verifies
every checksum and reports "patches are ready") produces a tree that **does not
compile**:

```
platform\web\display_server_web.cpp:1260:33: error: use of undeclared identifier
  'MAIN_WINDOW_ID'; did you mean 'DisplayServerEnums::MAIN_WINDOW_ID'?
12 errors generated.
scons: *** [bin\obj\platform\web\display_server_web...o] Error 1
```

The previously-working `engine/.cache/studio-webgpu` tree has the qualified name.
So the engine that builds today contains local edits that were never captured
into the patch series.

## Scope

Diffing the working cache against a tree regenerated purely from the series
(excluding `.git`, `bin`, `thirdparty`, `__pycache__`, generated files) shows
**13 source files** that differ:

```
drivers/webgpu/rendering_context_driver_webgpu.cpp
drivers/webgpu/rendering_context_driver_webgpu.h
drivers/webgpu/rendering_device_driver_webgpu.cpp
drivers/webgpu/rendering_device_driver_webgpu.h
drivers/webgpu/spirv_preprocess.cpp
drivers/webgpu/tint_cli/main.cpp
drivers/webgpu/wgsl_precompile.py
platform/web/detect.py
platform/web/display_server_web.cpp
servers/rendering/renderer_rd/cluster_builder_rd.cpp
servers/rendering/renderer_rd/cluster_builder_rd.h
servers/rendering/renderer_rd/shaders/cluster_render.glsl
servers/rendering/renderer_rd/shaders/effects/screen_space_reflection_filter.glsl
```

The cluster-builder and cluster-render files are the Forward+ bring-up work.
Losing `engine/.cache/` — which the tooling itself calls "this disposable cache"
— would lose all of it.

## Why this matters

- ADR 0008 rests on the patch series being the maintained, replaceable delta
  against official Godot. A series that cannot rebuild the shipping engine does
  not provide that property.
- `engine-lock.toml`'s checksums verify that the patches are *unmodified*, not
  that they are *sufficient*. Both checks passed while the result failed to
  compile — the guarantee is weaker than it appears.
- A clean-machine build, a CI build, or any contributor following the runbook
  gets a tree that does not compile.

## Suggested resolution

1. Diff the working cache against a series-only regeneration (the 13 files
   above) and fold each difference into the appropriate patch.
2. Add a gate that regenerates from the series **into a scratch tree** and
   compiles it, so "the series builds" is asserted rather than assumed. This is
   exactly the class of drift `--source`/`--build` staleness detection catches
   for game exports; the engine needs the same discipline.
3. Until then, treat `engine/.cache/studio-webgpu` as **not** disposable, and say
   so in `engine/README.md` — the tooling currently invites deleting it.

## Note on scope

This was found incidentally, while applying an unrelated one-function fix. It is
recorded rather than fixed because folding 13 files of engine work back into a
checksummed patch series is a substantial change that deserves its own review,
and because a parallel session currently holds uncommitted work across
`engine/patches/`, `engine/engine-lock.toml` and `engine/scripts/`.
