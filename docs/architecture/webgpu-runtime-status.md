# WebGPU 4.7.1 runtime status and investigation log

Last reconciled: 2026-07-25 against current `main` commit
`023563c068d8639747453425da91bcaa46a3577d`.

This document is a dated engineering log. The concise current claim map is
[webgpu-evidence.md](webgpu-evidence.md).

## Current status

| Track | Source | Renderer | Hardware result | Artifact status |
|---|---|---|---|---|
| Published release | Official Godot 4.7.1 plus patches `0001–0014` | WebGPU Forward Mobile | Renders lit/shadowed 3D and three game scenes on an NVIDIA Tesla P40 with 0 `GPUValidationError` | p0014 release/debug archives published |
| Current `main` | Official Godot 4.7.1 plus patches `0001–0022` | Forward Mobile plus unfinished WebGPU Forward+ investigation | Forward+ pipeline warm-up completes, but 18 `GPUValidationError` entries remain and no frame renders | No p0022 archives published |

The p0014 downloads do not contain patches `0015–0022`. Current main and the
published release are different artifacts.

## Current Forward+ investigation

Forward+ was selected and run on an NVIDIA Tesla P40 through Chrome/WebGPU. It
has therefore been hardware-tested, but it has not rendered successfully.

| Patch checkpoint | Measured result |
|---|---|
| `0015–0017` | Offline harness at Vulkan 1.1 / SPIR-V 1.3: 199 modules translated, 6 Tint failures, 3 skipped; no hardware render claim |
| `0018` | Compiler aborts and wasm traps removed; device limits requested; `GPUValidationError` 168 → 106; still no frame |
| `0019` | Integer sampled-texture types derived from WGSL; 106 → 42 |
| `0020` | Negative LOD clamp and storage-to-sampled type fix; 42 → 38 |
| `0021` | Required storage-texture formats added; 38 → 26 |
| `0022` | Shadow-entry sample type derived from WGSL; 26 → 18 |

The remaining 18 errors are validation failures, not a measured rendered frame.
No current-main templates have completed rebuild, browser acceptance, artifact
recording, and publication as a p0022 release.

### Why Forward+ was investigated

Every published WebGPU export used Forward Mobile because the WebGPU export path
selected `--rendering-method mobile`. In this Godot tree, Forward Mobile
hard-disables the Forward+ SSAO, SSIL, SSR, SDFGI, VoxelGI, and volumetric-fog
paths. Forward+ is compiled into the template and can be selected for
investigation with:

```sh
python tools/godot/export_game.py --preset web-webgpu --rendering-method forward_plus
```

Forward+ also exposed bindings and shader variants that Forward Mobile does not
exercise. Offline translation was necessary evidence but did not predict
bind-group-layout validation on hardware.

### Patch 0015: no-subgroup cluster builder

WebGPU exposed no subgroup support, while the cluster builder used
`subgroupBallot`, `subgroupBroadcastFirst`, `subgroupOr`, and
`gl_HelperInvocation`. Patch 0015 added a plain-atomics fallback and selected it
when subgroup limits are zero.

The fallback preserves the operation's result because invocations in the
elected group write the same word and bit and `atomicOr` is idempotent. This
translation result did not establish runtime success.

### Patch 0016: offline harness parity

The earlier harness used Vulkan 1.0 / SPIR-V 1.0 while the engine reports Vulkan
1.1 / SPIR-V 1.3. It also resolved repo-relative includes from the working
directory and enumerated several variants without the defines used by the
engine. Patch 0016 corrected those inputs, isolated Tint aborts per module, and
added the small `glsl2spv` build/probe tools.

After patch 0017's SSR storage-format fix, the dated offline result was:

- 199 translated modules;
- 0 GLSL compilation failures;
- 6 Tint failures;
- 3 skipped variants.

The six failures were two Forward Mobile subpass tonemap variants, one
unselected 16-bit FSR variant, two unselected subgroup variants, and an editor
debug visualization. Patch 0018 later showed that unselected variants could
still be fatal because `ShaderRD` compiled the listed variants before runtime
selection.

### Patches 0018–0022: hardware validation

Patch 0018 removed three abort classes:

- unselected subgroup variants containing `gl_HelperInvocation`;
- the unselected FSR 16-bit variant;
- `isnan`/`isinf` paths unsupported by the Tint reader.

It also requested the compute and storage-texture limits the adapter exposed.
That allowed validation errors to be observed rather than losing the page to a
wasm trap.

Patches 0019–0022 then corrected sampled-texture component types, negative LOD
bounds, read-only-storage conversion types, storage-texture formats, and two
shadow-entry sample-type sites. The current count is 18.

## Published Forward Mobile result

The p0014 release closed the Forward Mobile 3D chain:

1. `0009` stripped Tint's unsupported SPIR-V `Volatile` decoration.
2. `0010` propagated combined image/sampler splitting through function calls.
3. `0011` stopped literal decoration operands from being remapped as IDs.
4. `0012` converted texture types on function parameters.
5. `0013` derived precise per-stage sampler/texture visibility.
6. `0014` restored helper-reached bindings and paired depth textures with
   non-filtering samplers.

On the P40, the minimal scene rendered six PBR meshes with a directional light
and real-time shadows at 59–60 fps, 36 draws/frame, and 0
`GPUValidationError`. Chariot, Riftline, and The Deep were then verified with the
same p0014 Forward Mobile build. Exact measurements remain in
[webgpu-performance.md](webgpu-performance.md).

## Historical checkpoints

The following notes are deliberately dated. They describe investigation states
that were true when recorded but are not current status.

### 2026-07-22: shallow browser proof

A release WebGPU export reached `navigator.gpu`, an adapter, and an active
canvas context and passed 103/103 headless checks. The probe was shallow:
subsequent ASAN work found a real Emdawn/Godot `RefCounted` collision. This
checkpoint did not establish 3D rendering or safe release bytes.

### 2026-07-23 to early 2026-07-24: Emdawn/Godot collision

The ASAN debug smoke crashed during `RenderingDeviceDriverWebGPU` initialization
with a 36-byte heap-buffer-overflow. The pinned Emdawn port predated Dawn's
anonymous-namespace isolation, so Emdawn's global C++ `RefCounted` collided at
WebAssembly link time with Godot's global `RefCounted`.

The fix is the checksum-locked
[`0001-emdawn-private-namespace.patch`](../../engine/toolchain/patches/0001-emdawn-private-namespace.patch),
a narrow backport of Dawn commit
`2752c7d71a190c8512f38ceda922253d23876fb4`. The build copies the pinned
Emscripten package into a disposable cache, applies the backport there, and
does not mutate the SDK.

### Early 2026-07-24: 2D gate green, 3D still black

The original automated gate rendered only the neutral template's 2D Control
menu. It reached an active WebGPU context and produced a 1.2% visual difference
from the WebGL baseline, while a 3D scene still appeared black.

Instrumentation showed translation stopping during the 3D shader chain.
Offline work then identified Tint's unsupported `Volatile` decoration and the
later sampler/texture issues. Statements from this checkpoint that browser 3D
verification was pending were superseded by the P40 run later that day.

### 2026-07-24: offline 177/182 checkpoint

After patch 0010, 177 of 182 enumerated shader modules translated in the older
harness, with no crash or hang. The five remaining failures included subpass,
storage-format, vertex storage, and editor-debug paths. This number is retained
as a historical measurement; the corrected patch-0016 harness later enumerated
different module variants and produced the 199/205 result.

### 2026-07-24: p0014 release close

Patches 0013 and 0014 resolved the Forward Mobile binding defects. The minimal
lit/shadowed 3D scene rendered on the P40, and p0014 was published. The release
assets attached to GitHub are identified in
`[releases.godot_4_7_1_webgpu_p0014]`; the separate
`[artifacts.export_templates]` table records a locally accepted build pair with
different bytes.

### 2026-07-25: Forward+ translation-only checkpoint

After patches 0015–0017, all variants needed by the intended Forward+ runtime
path translated in the corrected offline harness. The statement “none of this
is hardware-verified” was accurate at that checkpoint only. Patch 0018 then ran
Forward+ on the P40 and showed that translation did not imply valid runtime
bindings or a rendered frame.

## Remaining risks

- Forward+ does not render and still emits 18 validation errors.
- The p0014 Jolt web build failed one concave terrain collider accepted by the
  official WebGL 2 control.
- The automated gate still does not provide public GPU CI coverage for 3D.
- Safari/iOS, native Android/iOS, and non-NVIDIA GPU vendors are unverified.
- Headless GPU canvas readback can be black even while rendering; the accepted
  hardware method uses engine draw counters plus validation-error logs.

## Reproduction commands

Fast source and documentation gates:

```sh
just engine-verify-patches
just public-evidence-validate
just test-python
```

Published Forward Mobile reproduction:

```sh
gh release download godot-4.7.1-webgpu-p0014 --repo lxsolutions/studio-foundation
just export-browser-webgpu
just run-browser-smoke
```

Current-main Forward+ investigation:

```sh
just engine-fetch
just engine-build
python tools/godot/export_game.py --preset web-webgpu --rendering-method forward_plus
```

Run the latter export in headed Chrome on a GPU host, allow at least 60 seconds,
then record adapter, browser, artifact identity, renderer, draw counters, and
every `GPUValidationError`.
