# Studio Foundation verification report

Last updated: 2026-07-25

This report summarizes current evidence and keeps older investigation results
dated. The canonical claim-level record is
[`docs/architecture/webgpu-evidence.md`](docs/architecture/webgpu-evidence.md).

## Current public state

| Area | Current evidence |
|---|---|
| Official engine source | Godot 4.7.1 stable commit `a13da4feb8d8aefc283c3763d33a2f170a18d541` is the sole active upstream |
| Backend lineage | David Walter's MIT-licensed `dwalter/godotwebgpu` commit `f329e39ce8db7acaa5c9d6628a530fb769969228` is the historical origin of the initial backend |
| Current maintenance | Studio Foundation owns the 4.7.1 port, 22-patch curation, later renderer/shader fixes, build/export tooling, validation, release evidence, MCP tooling, and distribution layer |
| Current-main source | Patches `0001–0022` are checksum-locked; all 22 applied to a pristine official checkout at the latest recorded clean-tree gate |
| Published release | `godot-4.7.1-webgpu-p0014` contains patches `0001–0014`, uses Forward Mobile, and publishes release/debug templates; it does not contain patches `0015–0022` |
| Published artifact identity | Release `9f137f0b…edea9b` (11,910,848 bytes); debug `659ad2ee…fe539` (11,729,626 bytes), recorded in `[releases.godot_4_7_1_webgpu_p0014]` |
| Browser context | The p0014 runtime gate observed adapter, device, and active WebGPU canvas-context requests and rejected any WebGL/WebGL 2 request |
| Forward Mobile rendering | The p0014 minimal lit/shadowed scene, Chariot, Riftline, and The Deep rendered on an NVIDIA Tesla P40 with 0 `GPUValidationError` |
| Forward+ investigation | Current main has been run on the P40. Patch 0022 reduced the remaining validation-error count to 18, but Forward+ still produces no rendered frame |
| Fallback | Official Godot WebGL 2 Compatibility remains the maintained browser fallback |

The current-main 22-patch tree has no published template release. The p0014
download must not be described as a p0022 build.

## Artifact provenance

`engine/engine-lock.toml` intentionally retains two byte identities:

- `[releases.godot_4_7_1_webgpu_p0014]` identifies the archives actually
  attached to the public p0014 GitHub release.
- `[artifacts.export_templates]` identifies a separately accepted local build
  pair recorded by `engine-record-artifacts`.

The byte counts and hashes differ. Neither set was rewritten during this
documentation reconciliation.

## Verified Forward Mobile evidence

- Minimal scene: six PBR meshes, directional light, real-time shadows,
  59–60 fps, 36 draws/frame, 0 `GPUValidationError`.
- Chariot: 60 fps, 489–631 draws/frame, ~23.0M primitives/frame,
  0 `GPUValidationError`.
- Riftline: 58–60 fps, 139–140 draws/frame, ~63.3K primitives/frame,
  0 `GPUValidationError`.
- The Deep: 60 fps, 64–65 draws/frame, ~37.7K primitives/frame,
  0 `GPUValidationError`.
- The Deep A/B: p0014 Forward Mobile WebGPU measured 60 fps / 64–65 draws;
  official 4.7.1 Compatibility WebGL 2 measured 20–25 fps / 124–125 draws,
  with the same scene, GPU, browser, and harness.

The A/B changes renderer and engine build together. It is a product-path
comparison, not a single-variable renderer benchmark. All figures above are
p0014 measurements; they are not p0022 measurements.

## Current Forward+ evidence

Patches `0015–0017` established offline translation coverage. Hardware runs
beginning with patch `0018` then exposed runtime compiler aborts, device-limit
requests, and bind-group-layout mismatches. Patches `0018–0022` reduced the
observed `GPUValidationError` progression from 168 to 106, 42, 38, 26, and
finally 18.

Current claim boundary:

- Hardware was used.
- Pipeline warm-up no longer aborts.
- Forward+ still does not render a frame.
- No p0022 release/debug templates have been published or accepted as a public
  release.

## Historical checkpoints

These statements describe their dated states and are retained so the
investigation is auditable:

- **2026-07-22:** a shallow release browser proof reached WebGPU adapter/device/
  canvas setup, but later ASAN work found the Emdawn/Godot `RefCounted`
  collision. That proof was not sufficient release evidence by itself.
- **2026-07-24, before the P40 3D run:** the offline reproducer reported
  177/182 shader modules translating after patch 0010. Browser 3D verification
  was still pending at that checkpoint.
- **2026-07-24, p0014 close:** patches `0013–0014` resolved the Forward Mobile
  binding defects; lit and shadowed 3D then rendered on the P40 with no
  validation errors.
- **2026-07-25, after patches `0015–0017`:** the corrected offline harness
  reported 199 translated modules, 6 Tint failures, and 3 skipped variants at
  Vulkan 1.1 / SPIR-V 1.3. This was translation evidence, not a hardware render.
- **2026-07-25, after patch `0018`:** Forward+ was hardware-run but still did
  not render; 106 validation errors remained.

Full investigation detail is retained in
[`webgpu-runtime-status.md`](docs/architecture/webgpu-runtime-status.md).

## Known limitations and unverified claims

- The p0014 Jolt web build failed one concave terrain collider that the official
  WebGL 2 control accepted. Rendering was unaffected; physics behavior was not.
- Safari/iOS WebGPU is unverified.
- Native Android and iOS device runs are unverified.
- AMD, Intel, Apple, Qualcomm, and other non-NVIDIA GPU vendors are unverified.
- The GPU evidence was not produced by independent third-party validation.
- Database-backed integration tests and console-provider paths are outside this
  WebGPU release evidence.

## Reproduce the fast evidence

```sh
just engine-verify-patches
just public-evidence-validate
just test-python
just lint
just release-validate --allow-dirty
```

The long source/build sequence is:

```sh
just engine-fetch
just engine-build
just engine-validate
just engine-record-artifacts
just release-validate --allow-dirty
```

`engine-record-artifacts` records a local accepted pair. Publishing or replacing
a GitHub release requires a separate release manifest update and complete
browser/hardware validation.
