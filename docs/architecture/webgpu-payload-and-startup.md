# WebGPU payload size and cold start — measured

Measured 2026-07-24 against the published demo
(<https://lxsolutions.github.io/studio-foundation/>) on an NVIDIA Tesla P40 through
Chrome/WebGPU. Numbers here are observations, not estimates.

## What the download actually costs

| Artifact | Size on disk | Over the wire |
|---|---|---|
| Our WebGPU web template (`godot.web.template_release.webgpu.zip`, nothreads) | 11.9 MB | — |
| Our uncompressed `godot.wasm` | **45.8 MB** | **12.0 MB** (GitHub Pages gzip) |
| Stock official Godot 4.7.1 `web_nothreads_release` `godot.wasm` | **39.5 MB** | — |
| **Cost attributable to the WebGPU stack** | **+6.3 MB (≈16%)** | — |

That +6.3 MB is the vendored Tint SPIR-V→WGSL translator, the SPIR-V tooling it needs,
and the WebGPU rendering driver. It is a real cost, but the bulk of the payload is
Godot itself — a stock Godot web export is already ~39.5 MB before we add anything.

The build is *already* size-optimized: Godot's web platform defaults to `-Os` and thin
LTO (`platform/web/detect.py`), and its own comment notes `-Os` saves ~5 MiB over `-O3`
while `-Oz` would only save ~100 KiB more. There is no easy flag left to pull.

## Cold start — where the time really goes

An earlier note in this repo claimed roughly 20 seconds of WGSL shader compilation
before the first frame. **That was wrong**, and it mattered because it pointed
optimization at the wrong thing.

Measured on the live demo with the network throttled to 12 Mbps and HTTP caching
disabled (a realistic first-time visitor):

| Phase | Observation |
|---|---|
| Download (12 MB compressed) | dominates; ~48% complete at 5 s |
| wasm instantiate + engine boot + shader translation + pipeline build | fast — **80 pipelines built within ~2 s** of the engine starting |
| First frames drawn | by **~13 s end to end** |

So **payload size, not shader compilation, is the cold-start bottleneck.** On an
unthrottled datacenter link the same demo is rendering in ~4 s.

The earlier 20 s figure came from a measurement artifact: driving the page with
`page.goto(waitUntil: "load")` waits for the entire 45 MB wasm before returning, so a
probe's `t=0` was already ~14 s into the page's life. Use `domcontentloaded` and read
elapsed time from inside the page.

## Where the remaining size could come from

Not yet done, listed in rough order of expected benefit:

1. **Translate shaders to WGSL at export time instead of at runtime.** Today the engine
   ships SPIR-V and runs Tint inside the wasm to translate it in the browser. Doing that
   translation during export would let the vendored Tint be dropped from the binary
   (most of the +6.3 MB) *and* remove runtime translation work. This is the biggest
   single lever we control, and it is an architectural change, not a flag.
2. **Module stripping / build profiles — measured, and weaker than expected.** The
   largest commonly-cited web lever is dropping the advanced text server (which embeds
   ICU). Built and measured:

   | Build | `godot.wasm` | gzipped |
   |---|---|---|
   | ours, full | 45.81 MB | 11.87 MB |
   | ours, `module_text_server_adv_enabled=no` + `fb=yes` | 44.25 MB | 11.30 MB |
   | **saving** | **1.56 MB (3.4%)** | **0.57 MB (4.8%)** |

   Half a megabyte off the wire in exchange for losing complex-script and bidirectional
   text support is a bad trade for a general-purpose template, so this is **not**
   applied to the published build. Recorded here so the option does not get
   re-investigated on the assumption that it is a big win.
3. **Better compression at the edge.** GitHub Pages serves gzip; Brotli would cut the
   transfer further but is not controllable from Pages.

## Loading UX

Because the first load is dominated by a large download, the demo ships
`boot-overlay.js`, which keeps a progress screen up until frames are genuinely being
produced. Detecting "rendering has started" is less obvious than it looks:

- Watching `requestAnimationFrame` for smooth frames **does not work** — while the
  engine is merely downloading, the page is idle and rAF already runs at a clean 60 fps.
- Watching for pipeline creation to go quiet **does not work either** — Godot builds a
  few canvas pipelines early, then creates none for many seconds while Tint translates
  the scene shaders, so it signals completion far too early.
- What does work: **sustained `GPUQueue.submit` traffic**. A running render loop submits
  a command buffer every frame, and no loading phase imitates that.

The overlay also wraps `GPUDevice.create*Pipeline*` so it can show real progress while
the viewer waits.
