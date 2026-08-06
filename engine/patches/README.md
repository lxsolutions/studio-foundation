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

19. `0019-webgpu-integer-texture-sample-types.patch` - derive a sampled texture's
    BGL `sampleType` from the WGSL component type. The driver scanned Tint's output
    for each binding's dimension, depth-ness and multisampled-ness but never its
    component type, so every sampled binding was declared `Float` -- including the
    ones the shader reads as integers. Forward Mobile samples almost nothing as an
    integer; Forward+ reads cluster data, VoxelGI and SDFGI that way, making this
    32 of its 106 remaining validation failures and the largest single class.
    `texture_2d<u32>` is now Uint, `<i32>` Sint, `<f32>` Float, with depth and
    MSAA-float precedence preserved, and samplers paired with integer textures
    forced to NonFiltering. Measured on a Tesla P40: `GPUValidationError` 106 -> 42.

20. `0020-webgpu-lod-clamp-and-storage-sample-type.patch` - two conformance
    defects Forward+ exposes. Godot passes sampler `min_lod`/`max_lod` straight
    through and Forward+ produces a negative one; Vulkan ignores that, WebGPU
    rejects the sampler ("LOD clamp bounds contain a negative number"). Mip 0 is
    the floor, so clamping to zero is what the shader already assumes. And the
    read-only-storage-to-sampled conversion chose its `sampleType` from the
    texture FORMAT, which yields `UnfilterableFloat` for formats whose WGSL is
    `texture_2d<i32>` - WebGPU validates the layout against the SHADER, so the
    scanned component type now wins. Measured on a Tesla P40:
    `GPUValidationError` 42 -> 38.

21. `0021-webgpu-storage-texture-formats.patch` - add the storage-texture formats
    Forward+ uses. The tables mapping Tint's `texture_storage_*<FORMAT, ...>` onto a
    `WGPUTextureFormat` initialise `tf` to `RGBA8Unorm` and then RECORD it when no
    branch matches, so an unrecognised format is not merely unknown - the lookup
    succeeds and returns the wrong answer. `rgb10a2unorm` appears 26 times in the
    WGSL Forward+ produces and was missing; Forward Mobile never noticed because it
    barely uses storage textures. Only formats present in the pinned Dawn header are
    added (the 16-bit *norm* variants are not core WebGPU and do not compile).
    Measured on a Tesla P40: format mismatches 6 -> 0, `GPUValidationError` 38 -> 26.

22. `0022-webgpu-shadow-entry-sample-type.patch` - the same correction `0020` made
    to the read-only-storage path, applied to the two "shadow entry" sites that were
    missed. They derived `sampleType` from the texture FORMAT, and
    `_texture_sample_type_for_format()` answers `UnfilterableFloat` wherever it has
    no better answer, while the shader declares `texture_2d<i32>`. WebGPU validates
    a layout against the SHADER, so the scanned declaration wins. Measured on a
    Tesla P40: Sint mismatches 4 -> 0, `GPUValidationError` 26 -> 18.

23. `0023-webgpu-stage-correct-storage-buffers.patch` - keep fragment storage
    buffers writable, and off the vertex stage. The WGSL post-pass demoted every
    read_write storage buffer to read-only in BOTH stages; WebGPU only forbids a
    writable storage buffer in the vertex stage, and the cluster builder is a
    fragment shader whose entire job is to `atomicOr` into an SSBO, so the
    demotion rewrote Tint's correct output into a module WGSL rejects outright
    (atomics in `storage` must be read_write). Demote in the vertex stage only,
    and never a buffer whose struct contains `atomic<>`; the read-only cache is
    keyed by (set,binding) and filled once per stage, so read-write now wins over
    whichever stage was scanned last; and a binding whose resolved type is
    Storage no longer carries vertex visibility. Measured on a Tesla P40
    (Chariot, Forward+): WGSL parse failures (atomics) 3 -> 0, ClusterRender
    layout/pipeline 6 -> 0, read-write-in-vertex-visibility 2 -> 0,
    `GPUValidationError` 18 -> 14.

24. `0024-webgpu-textureload-identifier-boundary.patch` - match `textureLoad` on
    a whole identifier, not a prefix. The read-only-storage-to-sampled conversion
    adds a mip-level argument by searching for `"textureLoad(" + var_name`, and
    SDFGI's preprocess shader declares both `src_light` and `src_light_aniso`, so
    the prefix matched the longer name too and it received a second mip argument
    - a four-argument `textureLoad` that invalidated SdfgiPreprocessShaderRD
    variant 8. A rewrite for binding x may now only touch a call whose first
    argument is exactly the identifier x, applied at both the shadow-texture and
    direct-variable sites, which shared the hazard. Measured on a Tesla P40
    (Chariot, Forward+): SDFGI WGSL parse failures 1 -> 0, cascading
    invalid-module 1 -> 0, `GPUValidationError` 14 -> 6 (with 0025).

25. `0025-webgpu-render-pass-needs-an-attachment.patch` - a render pass needs an
    attachment, so stop claiming side-effects-only is supported. The driver
    answered `SUPPORTS_FRAGMENT_SHADER_WITH_ONLY_SIDE_EFFECTS` true behind a
    comment asserting WebGPU render passes work with no color attachments; WebGPU
    requires at least one color or depth-stencil attachment and reports exactly
    that ("No attachment was specified."). Godot already has the fallback for
    APIs that cannot rasterize on side effects alone: answering false makes
    `cluster_builder_rd.cpp` create a real color attachment and select the
    `USE_ATTACHMENT` shader variant 0015 added, at the cost of one unused color
    attachment on the cluster-build pass. Measured on a Tesla P40 (Chariot,
    Forward+): attachmentless render-pass errors 2 -> 0, `GPUValidationError`
    14 -> 6 (with 0024).

26. `0026-scene-shader-subgroup-fallback.patch` - give the clustered scene
    shader the no-subgroups path 0015 gave only the cluster builder.
    `scene_forward_clustered.glsl` calls `subgroupMin`/`subgroupMax`/
    `subgroupOr`/`subgroupBroadcastFirst` with no `#ifdef`, and its include
    enables the subgroup extensions unconditionally, so the scene shader failed
    translation ('subgroupOr' must only be called from subgroup uniform control
    flow), no cluster builder was ever created, and `_render_scene` returned
    early on `current_cluster_builder` null every frame - nothing drawn, and no
    validation error to point at why. The reductions are a divergence
    optimisation, not a correctness requirement, so the fallback is four identity
    macros in `scene_forward_clustered_inc.glsl` behind `USE_SUBGROUPS`, which
    `render_forward_clustered.cpp` now defines only when the device reports
    ballot + arithmetic subgroup ops in the fragment stage - the same test
    `cluster_builder_rd.cpp` already applies.

27. `0027-webgpu-request-depth32float-stencil8.patch` - request the
    `depth32float-stencil8` device feature. Forward+ allocates its depth-stencil
    target as `D32_SFLOAT_S8_UINT`, which WebGPU exposes only behind that
    optional feature, and using it without the feature enabled is not a
    validation error - `createRenderPipeline` throws a `TypeError` that stops the
    renderer outright, so nothing after it draws. The JS shell already filters an
    optional-feature list against `adapter.features`, so this is one entry and
    adapters without the feature are unaffected. Forward Mobile never requested
    stencil alongside a 32-bit depth buffer, which is why the gap only surfaces
    once Forward+ gets far enough to create its depth attachment.

28. `0028-webgpu-depth-support-from-the-device.patch` - answer D32 depth support
    from the device, not a table; 0027 is only half of the negotiation.
    `texture_get_usages_supported_by_format()` reported a format supported
    whenever its `WGPUTextureFormat` enum existed, so on an adapter without
    `depth32float-stencil8` Godot still selects `D32_SFLOAT_S8_UINT`, never
    reaches its own `D24_UNORM_S8_UINT` fallback, and texture creation fails with
    no fallback left. The authority is now the created GPUDevice's enabled
    feature set, mirroring the BC/ETC2/ASTC gating the same function already
    applies, and the choice is reported once at device creation under
    `--verbose`. NOT VERIFIED on hardware lacking the feature - the Tesla P40
    exposes it, so the fallback branch has never executed here; recorded as
    unmeasured in `docs/architecture/webgpu-runtime-status.md` rather than
    claimed.

29. `0029-webgpu-unused-color-targets-are-absent.patch` - an unused color target
    is absent, not `rgba8unorm`. Unused fragment output locations were filled
    with a placeholder `WGPUTextureFormat_RGBA8Unorm` plus a None write mask, but
    masking writes does not make a target absent, and the render-pass path
    already emitted a null view for the same slot, so pipeline and pass disagreed
    on every Forward+ scene pipeline. An unused location now emits
    `WGPUTextureFormat_Undefined`, with holes preserved in place rather than
    compacted, because Godot reserves stable `@location()`s for optional outputs
    such as separate specular and motion vectors. Measured on a Tesla P40
    (Chariot, Forward+): attachment-state incompatibility 1018 -> 0, cascading
    invalid CommandBuffer 1005 -> 0, `GPUValidationError` 9004 -> 4780 -
    confirmed by pairing rather than by count (44 distinct pipeline/pass pairs,
    zero mismatches). Still no frame; the remaining classes are unrelated to
    attachments: sampler2DMS binding, comparison-sampler-as-non-comparison, and
    two storage format-promotion mismatches.

30. `0030-webgpu-view-format-follows-the-texture.patch` - a texture view must
    follow the physical format, not the logical one. R8/RG8/R16/RG16 are not
    WebGPU storage texel formats, so textures in them are promoted to 32-bit at
    creation, but `texture_create_shared` and `texture_create_shared_from_slice`
    took the view format straight from Godot, which supplies the LOGICAL format -
    an r16float view of an r32float texture. An invalid view is not a local
    failure: every bind group referencing it goes invalid, and so does the
    command buffer holding those draws, which is why the 3D scene was black while
    the separately-encoded 2D canvas kept presenting. `_view_format_for_texture`
    promotes the requested format the same way the texture was promoted, and
    passes genuine reinterpretations through unchanged for WebGPU to rule on
    rather than inventing an answer. Measured on a Tesla P40 (headed
    Chrome/WebGPU, Chariot, Forward+): distinct bind-group failure classes
    4 -> 2, R16Float-view-of-R32Float 2 -> 0, [Invalid TextureView] cascades
    2 -> 0. Still black; the next root failure in command order is the SSAO
    interleave layout, addressed in 0032.

31. `0031-webgpu-shared-view-physical-format-invariant.patch` - generalise the
    0030 invariant, which was narrower than it claimed. "Promotes to the same
    thing" admits reinterpretations the caller never declared, and promotion is
    not the only physical transformation this driver performs: where
    `float32-filterable` is unavailable, some logical float32 textures are
    allocated as float16, and 0030 would have resolved a later shared view of one
    back to float32 - recreating the exact class of invalid view it was written
    to eliminate. `_resolve_shared_view_format()` states the rule in both
    directions: a shared or sliced view of the same logical texture inherits the
    physical format, whatever transformation produced it, and only a format
    declared in the texture's viewFormats may differ - exactly one is declared,
    the linear/sRGB counterpart. The format is also resolved before the WGTexture
    wrapper is allocated (no leak on the error path), and `tex->format` is now
    assigned in both paths. No measured change on the Tesla P40, and none
    expected - it reports texture-formats-tier1 AND float32-filterable, so
    neither transformation is exercised; the float32-to-float16 case is
    UNVERIFIED on hardware, recorded as unmeasured exactly like the 0028
    fallback.

32. `0032-godot-ssao-interleave-r8-backport.patch` - match the SSAO interleave
    storage image to its R8 AO target. `ssao_interleave.glsl` declares its
    destination image `rgba8` while `ssao_allocate_buffers()` allocates RB_FINAL
    as `R8_UNORM`, and WebGPU requires the layout's storage-texture format to
    equal the bound texture's exactly. Not a missed promotion - the adapter
    reports texture-formats-tier1, so r8unorm is natively valid for storage and
    `_promote_storage_format` deliberately preserves it - and not the 0021/0029
    placeholder defect, because the runtime WGSL faithfully reflects the shader.
    The declaration itself is stale: upstream Godot already corrected it to
    `layout(r8, ...)` in d9ea5c261eb6 (2026-05-06), so this is an unconditional
    backport - the declaration was wrong on every backend - removable once the
    engine pin moves to a Godot containing that commit. Measured on a Tesla P40
    (headed Chrome/WebGPU, Chariot, Forward+): R8Unorm-vs-RGBA8Unorm bind-group
    failures 1 -> 0, distinct bind-group failure classes 2 -> 1. Scene-bearing
    submissions were still rejected at this point: `commandEncoder.finish` 6708
    calls / 514 invalid, `queue.submit` 514 rejected, every rejected submission
    carrying SceneForwardClusteredShaderRD and none carrying Sky/Tonemap/Canvas/
    Blit.

33. `0033-godot-volumetric-fog-remove-unused-shadow-sampler.patch` - remove the
    dead `shadow_sampler` that was the last remaining bind-group failure.
    `volumetric_fog_process.glsl` declares `sampler shadow_sampler` at binding 11
    and never references it - every real shadow read builds its sampled image
    from `linear_sampler` - so reflection's ShaderStage::None visibility and
    filtering sampler type were the right description of a dead resource, while
    `fog.cpp` nevertheless inserts the renderer's comparison-enabled sampler
    there, and zero visibility does not exempt an entry from bind-group resource
    validation. The resource is dead, so the declaration and its uniform block
    are removed rather than described more accurately; bindings are explicitly
    numbered, so 11 leaves a hole and WebGPU binding 22 simply ceases to exist.
    Not a backport - current Godot master still carries the declaration, and
    removal is a clean upstream-PR candidate because the resource is statically
    unreachable. With it the failure count reaches 0: first verified Forward+
    frame, 2026-07-28, Tesla P40, headed Chrome/WebGPU - 59 fps, 188 objects /
    2,015,266 primitives, 0 rejected command buffers, 0 wasm traps; 0 invalid
    `commandEncoder.finish` out of 10,842, 0 rejected `queue.submit`.

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

The patch series is 0001-0033. The p0033 export templates render Forward+ with
zero validation errors - first verified frame 2026-07-28 on an NVIDIA Tesla P40
under headed Chrome/WebGPU. The accepted template hashes remain checksum-locked
in `engine-lock.toml [artifacts.export_templates]`.