# Studio Foundation WebGPU patch series

These ordered patches are the additional source inputs used to prepare the
browser WebGPU template build. They apply to the official Godot commit in
`../engine-lock.toml` and are verified by SHA-256 before use.

1. `0001-studio-webgpu-engine.patch` - WebGPU engine, renderer, browser platform,
   resource, and build integration.
2. `0002-studio-webgpu-spirv.patch` - required vendored SPIR-V headers and tools.
3. `0003-studio-webgpu-tint.patch` - required vendored Tint source and license.
4. `0004-godot-4.7.1-webgpu-interfaces.patch` - Godot 4.7.1 interface adaptation
   and reproducible WebGPU shader-generation fixes.
5. `0005-webgpu-shell-capability-gate.patch` - fail closed when the browser does
   not expose WebGPU instead of silently selecting WebGL.
6. `0006-webgpu-single-thread-stdio.patch` - support the required no-threads web
   build configuration.
7. `0007-tint-storage-buffer-access.patch` - translate write-only SPIR-V storage
   buffers to Tint's supported read-write access mode.
8. `0008-tint-image-ordering.patch` - lower SPIR-V `OpImage` values before
   texture operations that can reference them earlier in module order.
9. `0009-tint-volatile-decoration.patch` - strip the SPIR-V `Volatile` decoration
   (21) that Tint's reader aborts on; without it, coherent compute shaders (e.g.
   `volumetric_fog`) crash shader translation and every 3D scene renders black.
10. `0010-webgpu-transitive-sampler-split.patch` - propagate the combined
    image-sampler split through function call chains, so a `sampler2D` forwarded
    from a wrapper into a deeper helper (e.g. tonemap's `texture2D_bicubic`, and
    `taa_resolve`) no longer produces invalid SPIR-V (`OpFunctionCall` argument
    type mismatch) that silently fails Tint translation.
11. `0011-webgpu-flatten-decoration-literals.patch` - stop `flatten_binding_arrays`
    from rewriting `OpDecorate`/`OpMemberDecorate` literal arguments (Offset,
    ArrayStride, ...). A struct-member Offset literal that collided with an array
    type id was being remapped, corrupting the struct layout into invalid SPIR-V.
12. `0012-tint-texture-function-params.patch` - Tint spirv-reader fix: convert
    texture types on function PARAMETERS, not only global vars. Godot forward-mobile
    passes lightmap/shadow textures by parameter; those kept `spirv::type::Image`
    and crashed Tint's texture lowering (`ProcessCoords` assert) on any 3D scene.

13. `0013-webgpu-sampler-texture-stage-visibility.patch` - give sampler/texture
    bind-group-layout entries precise per-stage visibility from a WGSL reachability
    scan instead of the `u.stages` union. Godot forward-mobile declares up to 22
    samplers visible to every stage, but the vertex stage samples none and the
    fragment stage at most 7; the over-approximation tripped WebGPU's hard
    16-samplers-per-stage limit so every 3D pipeline failed to create (verified on a
    Tesla P40: an unshaded 3D mesh renders at 60 fps with 0 GPUValidationError;
    lit/shadowed scenes needed `0014` as well).

14. `0014-webgpu-lit-shadow-sampler-types.patch` - make lit and shadowed 3D render.
    Fixes two sampler-description defects remaining after `0013`: bindings reached
    only through helper-function parameters (Godot's lighting/PCF helpers) were
    wrongly demoted to no visibility, and depth textures were paired with Filtering
    samplers, which WebGPU forbids. Adds a driver-owned non-filtering sampler for
    depth slots. Verified on a Tesla P40: six PBR meshes with real-time shadows at
    59-60 fps, 36 draws/frame, 0 GPUValidationError.

15. `0015-webgpu-cluster-builder-no-subgroups.patch` - unblock Forward+ (clustered)
    under WebGPU. The cluster builder's fragment shader elects one writer per
    cluster with subgroup ballot/arithmetic, which WebGPU does not have at all
    (the driver already reported `LIMIT_SUBGROUP_*` as 0, but nothing in
    `servers/rendering` ever read those limits), and guards that election with
    `gl_HelperInvocation`, which aborts Tint's SPIR-V reader outright
    (`TINT_UNIMPLEMENTED ... BuiltIn: HelperInvocation` - a wasm trap in the
    browser, same failure mode as the Volatile decoration fixed in `0009`). Adds
    an appended `USE_SUBGROUPS` variant pair so subgroup-capable drivers are
    untouched, and a plain-atomics fallback that is bit-identical because every
    invocation the ballot would have grouped writes the same word and bit and
    `atomicOr` is idempotent. Forward+ is the renderer that fits WebGPU: Forward
    Mobile's only untranslatable shader, `tonemap_mobile.glsl`, is also the only
    shader in the engine that uses subpasses, which WebGPU has no concept of.

16. `0016-webgpu-offline-harness-engine-parity.patch` - make the GPU-free shader
    harness reproduce the engine; several of its "failures" were its own.
    `glsl2spv` hardcoded Vulkan 1.0 / SPIR-V 1.0 while
    `RenderingShaderContainerWebGPU` reports Vulkan 1.1 / SPIR-V 1.3, so every
    offline result was measured against a target the runtime never uses - and
    because subgroup ops cannot compile at 1.0, that mismatch actively hid the
    `HelperInvocation` abort fixed in `0015`. Repo-relative `#include`s were
    resolved against the CWD rather than the repo root, so AMD's FSR headers
    silently vanished and `fsr_upscale.glsl` failed with a bare syntax error.
    Several variant tables did not match the engine, leaving `ssao_blur`,
    `ssil_blur` and `subsurface_scattering` - three shaders the high-end look
    needs - uncompilable and therefore of unknown status; they all translate once
    given the `MODE_`/`USE_*_SAMPLES` defines the C++ actually builds them with.
    Also stops one crashing module from being reported as an all-modules failure
    (a Tint abort killed the whole `--batch` process and the caller turned that
    into "everything failed"), names failing shaders instead of only counting
    them, stops counting skips as failures, and drops the dead `giprobe_write.glsl`
    (no C++ references it; it uses the reserved word `output`). Adds
    `build_glsl2spv.sh` (glslang-only build, ~1 min instead of ~30, statically
    linked) and `probe_one.py` (single-shader probe that prints the raw Tint
    error).

17. `0017-webgpu-ssr-filter-storage-format.patch` - the last real feature gap.
    `screen_space_reflection_filter.glsl` declared its output image with no format
    qualifier, so glslang emitted `OpTypeImage` with format `Unknown` and Tint
    rejected the module (`textureStore(texture_storage_2d<undefined, write>, ...)`)
    - screen-space reflections were simply unavailable. `rgba16f` matches what the
    sibling shaders in the same chain already declare for the same texture, and is
    provably the format in use: the SSR buffers take `get_base_data_format()`,
    which is `R16G16B16A16_SFLOAT` on every renderer that can reach this shader
    (Forward Mobile overrides it to a packed 10-bit format but cannot run SSR at
    all, since `_render_buffers_can_be_storage()` is false).

18. `0018-webgpu-forward-plus-runtime.patch` - make Forward+ survive pipeline
    warm-up on hardware. 0015-0017 made its shaders *translate*; running it on a
    Tesla P40 showed that was necessary and not sufficient - the page died having
    compiled only 2D canvas shaders. The root cause is worth stating plainly:
    **Godot pushes every shader variant and then selects one, but `ShaderRD`
    compiles them all.** That is fine where the compiler returns an error for
    input it cannot handle; Tint instead calls `TINT_UNIMPLEMENTED`, which is an
    abort, which under WebGPU is a wasm trap and a dead page. So a variant the
    device will never select is fatal merely by being listed. Fixes the variant
    lists in `cluster_builder_rd.cpp` (`gl_HelperInvocation`) and `effects/fsr.cpp`
    (16-bit math), replaces `isnan()`/`isinf()` in `volumetric_fog_process.glsl`
    with an exact `|x| <= FLT_MAX` finiteness test, and requests the compute and
    storage-texture limits Forward+ needs - the shell maxed out nine limits but
    that list predates Forward+, so WebGPU enforced spec defaults the adapter was
    happy to exceed. Measured: aborts and wasm traps 1 -> 0, `GPUValidationError`
    168 -> 106, and the whole GI/SDFGI/SSAO/SSIL/VoxelGI/cluster shader set now
    compiles. Forward+ still does not *render* - the remaining 106 are
    bind-group-layout description bugs, the `0013`/`0014` lineage continuing.

The WebGPU implementation originated in `dwalter/godotwebgpu`. Studio
Foundation owns the 4.7.1 port, scoped patch curation, preparation/build tooling,
and validation. See `../../docs/architecture/webgpu-integration.md` for the
authorship and maintenance boundary.

## Rules

- Apply patches only in the order locked in `engine-lock.toml`.
- Do not add unrelated files from a historical engine branch.
- Preserve all applicable third-party license files.
- Regenerate a patch from a reviewed candidate tree; do not silently hand-edit
  a locked patch.
- Recalculate SHA-256 values and run release validation after regeneration.
- **Verify a regenerated patch against a CLEAN tree**, not against the tree it
  was generated from. `engine/scripts/verify_patch_apply.py` does this.
  Reverse-applying a patch to its own source tree proves only self-consistency;
  it cannot detect a hunk whose target exists solely because of uncommitted
  local state. Patch 0016 shipped exactly that defect — checksums, ordering and
  completeness all passed while `git apply` failed on every clean checkout and
  `engine-fetch` stopped working entirely.
- A checksum change requires review even when the filename is unchanged.

`engine/.cache/studio-webgpu` is disposable output. This directory and
`engine-lock.toml` are source of truth.

The pinned Emdawn port also needs a toolchain-level namespace backport, stored
separately under `engine/toolchain/patches/`. It isolates Dawn's private
`RefCounted` type from Godot's type of the same name and is independently
checksum-locked in `engine-lock.toml`.

As of 2026-07-24 the release/debug rebuild and the engine-owned browser WebGPU
probe (active canvas context + 1.2% visual diff vs the WebGL baseline) both pass;
the accepted templates are checksum-locked in
`engine-lock.toml [artifacts.export_templates]`.