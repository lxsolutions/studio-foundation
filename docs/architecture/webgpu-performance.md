# WebGPU vs WebGL2: measured performance, and three real games verified

> **Purpose.** [`webgpu-runtime-status.md`](webgpu-runtime-status.md) establishes
> *that* WebGPU renders. This file answers the next two questions: **is it
> faster than the WebGL2 fallback**, and **does it hold up on real games rather
> than a purpose-built showcase scene?**
>
> **Measured:** 2026-07-24, NVIDIA Tesla P40, headed Chrome under Xvfb.
> **Engine:** patch series 0001-0014 (tag `godot-4.7.1-webgpu-p0014`).

---

## TL;DR

**WebGPU runs the same game at ~2.5-3x the frame rate of WebGL2, at roughly half
the draw calls.** Three real games — not showcase scenes — render on WebGPU
hardware with **0 `GPUValidationError`**.

The 60 fps figure is almost certainly vsync-capped, so it is a **floor, not a
ceiling**: the true headroom is larger than this table can show.

---

## The A/B: same game, same scene, same GPU

The Deep's `VerticalSlice`, exported twice and run back to back. **Primitive
counts are identical in both runs** (37726 / 37396), which is the control that
proves both builds drew the same content.

| Build | Renderer | fps | Draws/frame | Jolt errors |
| --- | --- | --- | --- | --- |
| **This repo** (patch-0014 WebGPU template) | `WebGPU 1.0 - Forward Mobile` | **60, 60** | **64-65** | 1 |
| Control (stock **official** Godot 4.7.1 web template) | `OpenGL ES 3.0 (WebGL 2.0) - Compatibility` | **24, 23, 25, 20** | 124-125 | 0 |

Everything else was held constant: same project, same machine, same Chrome, same
harness, same window.

### What this does and does not prove

Honest caveat: **two variables move together** — the renderer (Forward Mobile vs
Compatibility) *and* the engine build (ours vs stock). It is not a
single-variable experiment.

It is, however, the comparison that matters in practice, because Compatibility
*is* what WebGL2 gives you — Godot's WebGL2 path cannot run Forward Mobile. So
the table reflects the real product choice rather than a synthetic one.

The same A/B also surfaces a regression that belongs to **us**, and it is
reported here rather than buried: the stock build logs **0** Jolt errors while
ours fails to build one concave terrain collider (see
[Known regression](#known-regression-jolt-concave-collision) below).

---

## Three real games verified on WebGPU

Previous verification used a purpose-built showcase (six PBR meshes, 36
draws/frame). These are shipping game scenes, taken as-is:

| Game | Scene | fps | Draws/frame | Objects | Prims/frame | `GPUValidationError` |
| --- | --- | --- | --- | --- | --- | --- |
| The Chariot Club | `Spectator` | 60 | 489-631 | 551-693 | ~23.0M | **0** |
| Riftline | `Riftline` | 58-60 | 139-140 | 907-908 | ~63.3K | **0** |
| The Deep | `VerticalSlice` | 60 | 64-65 | 646-811 | ~37.7K | **0** |

Chariot sustains 60 fps while submitting **~23 million primitives per frame** —
roughly 600x the showcase scene's geometry. Draw counts vary between samples
because the camera is moving and frustum culling is working, which is itself
evidence the frame is live rather than frozen.

**No game needed a renderer change.** All three ship
`rendering_method.web="gl_compatibility"` in `project.godot`; the `web-webgpu`
preset's post-export step injects the CLI override, and CLI args beat project
settings.

---

## Cold start: ~20s to first frame — and it is NOT shader compilation

Measured on Chariot over a LAN-local server, and the reason several earlier
investigations wrongly concluded "3D is black":

| Milestone | Time |
| --- | --- |
| WebGPU device acquired | +1.3s |
| `studio: boot completed` | +8.7s |
| All WGSL module-compilation log entries | **+17.9s → +18.0s** |
| **First drawn frame (non-zero draw calls)** | **+20.9s** |

**Shader compilation is not the bottleneck.** Every one of the 21 compilation-log
entries lands inside a **single sub-second burst**, and the count is identical
across all three games regardless of scene size (Riftline +17.4s, Chariot
+17.9s, The Deep +24.5s) — they are the engine's own built-in shaders
(`CanvasShaderRD`, `SceneForwardMobileShaderRD`, `TonemapMobileShaderRD`), not
game content. An independent run against the *published* demo, throttled to
12 Mbps with caching disabled, agrees: **80 pipelines built within ~2s** of the
engine starting, with total time to first frame ~13s **dominated by downloading
the 45.8 MB wasm**.

So the cost is **engine startup — fetching and instantiating a 45.8 MB wasm,
then engine and scene init — not WGSL translation**. For reference, the WebGL 2
control reached its first frame at **+13.0s** on the same harness, so WebGPU adds
real startup overhead, but far less than the raw ~20s figure suggests.

Three consequences:

1. **Any capture window shorter than ~25s screenshots a blank canvas.**
   `tests/browser/capture.mjs` previously defaulted to 6s, which could not
   photograph a real 3D scene before it drew anything. The default is now 25s.
   This holds regardless of *why* the first frame is late.
2. **Payload size is the lever** — shrinking/streaming the wasm and compressing
   transfer beats shader precompilation, which is already only ~2s.
3. Measure first-frame latency with the **engine's own draw counters**, and
   beware `page.goto(waitUntil: "load")`: it waits for the entire wasm and can
   start a probe clock ~14s late, inflating every number after it.

> **Correction (2026-07-24).** An earlier revision of this file attributed the
> cold start to "a fixed per-session shader-compilation cost" and called shader
> precompilation the highest-value optimization. The compilation-burst timing and
> the throttled-network run above both refute that; the claim is corrected here
> rather than quietly dropped.

---

## Verifying a render without a screenshot

On a headless GPU host, the WebGPU canvas **cannot be composited back**:
screenshots, `drawImage`, and `getImageData` all return pure black even while
the GPU renders correctly. A green-clear control confirms this — it also reads
`[0,0,0,0]`.

**A black capture is therefore not evidence of failure.** Judge instead by:

1. **Engine draw counters** — [`tools/verification/render_probe.gd`](../../tools/verification/render_probe.gd),
   registered as an autoload, prints per-frame `draws`/`objects`/`prims`.
2. **0 `GPUValidationError`** and no pipeline-creation failures in the browser
   console.

Together these are decisive; neither alone is.

---

## Reproducing

1. Export the game against the WebGPU templates
   (`just export-browser-webgpu`, or `export_game.py`). **Do not** bypass that
   tooling with a bare `godot --export-release`: the official editor cannot emit
   the WebGPU-only `renderingDriver` shell field, and the build then dies with
   `WebGPU: Failed to get pre-initialized device`.
2. Copy `tools/verification/render_probe.gd` into the project as
   `res://render_probe.gd` and register it as an autoload.
3. Serve over a GPU host and run headed Chrome under Xvfb with
   `--enable-unsafe-webgpu --enable-features=Vulkan --ignore-gpu-blocklist`
   (headless Chrome only ever gets SwiftShader, never the NVIDIA adapter).
4. Give it **>= 60s**, then read the console.

---

## Known regression: Jolt concave collision

Our build only. The stock official template does not exhibit it.

```
Failed to build Jolt Physics concave polygon shape with {vertex_count=6738}.
It returned the following error: 'Need triangles to create a mesh shape!'.
This shape belongs to 'ActiveStratum:<StaticBody3D#...>'
```

- **Web only** — does not reproduce in a native Windows run of the same project.
- The face array is well-formed: 6738 vertices is exactly 2246 triangles, built
  by `SurfaceTool` from non-degenerate quads.
- Rendering is unaffected (0 GPU errors); this is a **physics** defect.
- Impact: in a digging game, terrain with no collider likely means falling
  through the world.
- Leading hypothesis: a Jolt compile-flag or threading difference in our web
  build, not the WebGPU patches — physics should not depend on the renderer.

Tracked as engine-lane work; not yet root-caused.
