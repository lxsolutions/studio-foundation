# WebGPU evidence matrix

Last reconciled: 2026-07-25 against `main` commit
`023563c068d8639747453425da91bcaa46a3577d`.

This is the canonical public claim-to-evidence map. It distinguishes the
published Forward Mobile release from current-main Forward+ investigation work.
Historical investigation detail remains in
[webgpu-runtime-status.md](webgpu-runtime-status.md); measurements are not
promoted to a newer patch level without a new build and run.

## Release boundary

| State | Patch range | Public artifacts | Renderer result |
|---|---|---|---|
| Published `godot-4.7.1-webgpu-p0014` | `0001–0014` | Release and debug archives below | Forward Mobile renders |
| Current `main` | `0001–0022` | No p0022 archives published | Forward Mobile remains the last rendered path; Forward+ reaches pipeline validation but does not render |

Patches `0015–0022` are not included in the p0014 downloads.

## Claims and evidence

| Claim | Current status | Exact evidence | Applicable patch / release | Reproduction command | Known caveat |
|---|---|---|---|---|---|
| Official Godot base | Godot 4.7.1 stable is the sole active upstream at commit `a13da4feb8d8aefc283c3763d33a2f170a18d541` | `[godot.official]` and `[godot.webgpu].base_commit` in [`engine-lock.toml`](../../engine/engine-lock.toml); [ADR 0002](../adr/0002-webgpu-patch-series.md) | p0014 and current `main` | `just engine-versions` | The disposable patched build tree is not a second upstream |
| Historical backend lineage | The initial backend came from David Walter's MIT-licensed `dwalter/godotwebgpu` commit `f329e39ce8db7acaa5c9d6628a530fb769969228` | [`NOTICE.md`](../../NOTICE.md), [`engine-lock.toml`](../../engine/engine-lock.toml), and [provenance](webgpu-integration.md) | Historical source input; current maintenance is Studio Foundation | `just attribution` | The lineage repository is not fetched by `engine-fetch`; attribution does not imply current maintenance |
| Patch reproducibility | Current `main` locks 22 ordered patches and all 22 applied to a pristine official checkout at the latest measured checkpoint | Lockfile checksums; [`verify_patch_series.py`](../../engine/scripts/verify_patch_series.py); [`verify_patch_apply.py`](../../engine/scripts/verify_patch_apply.py); merged PR #33 | Current `main`, `0001–0022` | `just engine-verify-patches`; `python engine/scripts/verify_patch_apply.py` | Checksum verification is offline; clean-tree application fetches official Godot unless a local clone is supplied |
| Published p0014 templates | Both public release assets are downloadable and identified by exact byte count and SHA-256 | GitHub release assets, release digests, and `[releases.godot_4_7_1_webgpu_p0014]` in [`engine-lock.toml`](../../engine/engine-lock.toml) | `godot-4.7.1-webgpu-p0014`, patches `0001–0014`, Forward Mobile | `gh release download godot-4.7.1-webgpu-p0014 --repo lxsolutions/studio-foundation` followed by `sha256sum` or `Get-FileHash` | The separately recorded `[artifacts.export_templates]` pair is a locally accepted build pair with different bytes; it is not the release identity |
| WebGPU-only browser context | The browser gate observes adapter, device, and active WebGPU canvas-context requests and rejects any WebGL or WebGL 2 request | [`capture.mjs`](../../tests/browser/capture.mjs), [`run_browser_smoke.py`](../../tools/godot/run_browser_smoke.py), and the p0014 runtime gate record | p0014 | `just run-browser-smoke` after a p0014 export | `navigator.gpu` alone is insufficient evidence; the engine-owned requests must be observed |
| Minimal lit and shadowed 3D | Six PBR meshes, a directional light, and real-time shadows rendered at 59–60 fps and 36 draws/frame with 0 `GPUValidationError` on an NVIDIA Tesla P40 | [`webgpu_showcase.gd`](../../templates/godot-game/project/scenes/webgpu_showcase.gd), [runtime log](webgpu-runtime-status.md), and [live showcase](https://lxsolutions.github.io/studio-foundation/showcase/index.html) | p0014, Forward Mobile | Export with p0014, register [`render_probe.gd`](../../tools/verification/render_probe.gd), run headed Chrome/WebGPU, and inspect counters/errors for at least 60 seconds | A headless GPU canvas may read back black even while rendering; counters plus zero validation errors are the acceptance signals |
| Chariot verification | 60 fps, 489–631 draws, 551–693 objects, ~23.0M primitives/frame, 0 `GPUValidationError` | [p0014 performance record](webgpu-performance.md) and public source under [`games/chariot`](../../games/chariot) | p0014, Forward Mobile | Follow [`games/chariot/README.md`](../../games/chariot/README.md) and the render-probe procedure in the performance record | Chariot source is public for reproduction but remains all rights reserved under `games/LICENSE` |
| Riftline verification | 58–60 fps, 139–140 draws, 907–908 objects, ~63.3K primitives/frame, 0 `GPUValidationError` | [p0014 performance record](webgpu-performance.md) | p0014, Forward Mobile | Export the recorded scene with p0014 and use the same P40 render-probe harness | The consuming game's source is outside this repository; the measured result is retained as release evidence, not independently repeatable here |
| The Deep verification | 60 fps, 64–65 draws, 646–811 objects, ~37.7K primitives/frame, 0 `GPUValidationError` | [p0014 performance record](webgpu-performance.md) | p0014, Forward Mobile | Export `VerticalSlice` with p0014 and use the same P40 render-probe harness | The consuming game's source is outside this repository; the Jolt regression below was observed in this run |
| WebGPU versus WebGL 2 A/B | The p0014 WebGPU run measured 60 fps and 64–65 draws; the official WebGL 2 control measured 20–25 fps and 124–125 draws on the same game, scene, P40, Chrome, and harness | [A/B table and method](webgpu-performance.md#the-ab-same-game-same-scene-same-gpu) | p0014 WebGPU Forward Mobile vs official Godot 4.7.1 WebGL 2 Compatibility | Follow [Reproducing](webgpu-performance.md#reproducing) for back-to-back exports and record identical primitive counts | Two variables changed together: renderer and engine build. This is a product-path comparison, not a single-variable renderer benchmark |
| Payload and startup | p0014 release wasm measured 45.8 MB uncompressed / 12.0 MB over GitHub Pages gzip; at 12 Mbps, initial frames appeared around 13 seconds and 80 pipelines built within ~2 seconds of engine start | [payload and startup record](webgpu-payload-and-startup.md) | Published p0014 demo | Load the public demo with caching disabled and 12 Mbps throttling; use `DOMContentLoaded` and page-internal elapsed time | Network, cache, CPU, browser, and host change startup time; do not relabel these measurements as p0022 |
| Current Forward+ WebGPU status | Hardware-tested investigation path; after patch 0022, 18 `GPUValidationError` entries remain and no frame renders | Patch progression in [`engine/patches/README.md`](../../engine/patches/README.md), [current runtime status](webgpu-runtime-status.md), and merged PR #33 | Current `main`, patches `0015–0022`; no published templates | Build current `main`, export with `--rendering-method forward_plus`, run the P40 browser harness, and count validation errors | Pipeline warm-up and shader compilation are not a rendered-frame claim; p0014 remains the published Forward Mobile release |
| Known Jolt concave-collider regression | One concave terrain collider failed in the p0014 WebGPU build while the official WebGL 2 control logged no Jolt error | [Known regression](webgpu-performance.md#known-regression-jolt-concave-collision) | Observed with p0014 | Run The Deep A/B and compare Jolt logs | Rendering was unaffected, but missing collision is gameplay-significant; root cause remains unknown |
| Platforms and GPU vendors | NVIDIA Tesla P40 is the recorded hardware; Safari/iOS, native Android/iOS, and non-NVIDIA GPU vendors are unverified | This matrix, [`BOOTSTRAP_REPORT.md`](../../BOOTSTRAP_REPORT.md), and the hardware fields above | All releases/current `main` | Repeat browser and native device gates on each target and record adapter, browser, OS, artifact hash, renderer, and errors | Browser feature detection is not platform verification; no portability claim is made from one NVIDIA GPU |

## Published p0014 asset identity

<!-- public-evidence-p0014-assets:start -->

| Asset | Bytes | SHA-256 |
|---|---:|---|
| `godot.web.template_release.webgpu.zip` | 11,910,848 | `9f137f0b58c9e7c56d3430feb8fd00b1223d68d3b07b0fb5fcf2cadad8edea9b` |
| `godot.web.template_debug.webgpu.zip` | 11,729,626 | `659ad2ee4af91835a92aec8d8e1213c9ab4e91a2bc99083c69d352ce134fe539` |

<!-- public-evidence-p0014-assets:end -->

These values identify the downloadable GitHub release, not whatever archives
happen to exist under `engine/artifacts/` in a local checkout.
