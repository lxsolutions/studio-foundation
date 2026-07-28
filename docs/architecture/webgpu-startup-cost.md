# WebGPU browser startup cost — first measurement

> **Purpose.** What a player actually waits through before a Forward+ build is on
> screen, and which part of that wait is worth attacking. Measured rather than
> assumed, because the assumption turned out to be wrong.
>
> **Measured:** 2026-07-28, NVIDIA Tesla P40, headed Chrome under Xvfb, Chariot
> exported with `--rendering-method forward_plus`, patch series 0001–0033.
> **Tool:** `tests/browser/startup-probe.mjs` (`just startup-profile`).

---

## TL;DR — the payload is not the bottleneck

| Configuration | First rendered frame | Transferred |
| --- | --- | --- |
| Broadband (25 Mbit), cold cache | **30.9 s** | 14.0 MB |
| Fast 4G (9 Mbit), cold cache | **38.0 s** | 14.0 MB |
| Broadband, warm cache | **23.3 s** | 11.8 MB |

Two things follow, and neither is what the file listing suggests.

**Bandwidth barely matters.** Cutting the connection from 25 Mbit to 9 Mbit — a
2.8× reduction — costs 7.2 seconds. If download dominated, that gap would be far
larger.

**A warm start still takes 23 seconds.** With the cache helping and nothing left
to discover, the build still needs ~23 s to put a frame on screen. That is
compute: wasm instantiation, engine boot, and shader compilation. Roughly
**three quarters of the cold-start wait is work that shrinking the download
cannot touch.**

The instinct — "45 MB is too big, make it smaller" — is therefore aiming at the
smaller half of the problem.

## Compression is worth 3.9×, and it is not automatic

| File | On disk | gzip | Ratio |
| --- | --- | --- | --- |
| `index.wasm` | 45,813,396 | **11,834,588** | 3.87× |
| `index.pck` | 2,160,816 | 2,078,958 | 1.04× |
| `index.js` | 273,216 | 68,625 | 3.98× |
| **Total transferred** | 48,271,362 decoded | **14,006,289** | **0.29** |

The engine wasm compresses to a quarter of its size. That reduction only happens
if the host negotiates `Content-Encoding`. **A static host that does not — and
Python's `http.server`, used in every local example, does not — makes every
player download 32 MB they did not need to.**

This is the cheapest available improvement and it is a hosting configuration, not
an engineering project. It should be stated in the deployment runbook rather than
discovered.

## Confirmed defect: the engine wasm is never cached

A returning visitor re-downloads the engine wasm in full, every time. Measured by
Resource Timing `transferSize` on a genuine second navigation, with the cache
enabled throughout:

| Resource | Visit 1 transferred | Visit 2 transferred |
| --- | --- | --- |
| `index.js` | 68,940 | **0** — cached |
| `index.pck` | 2,080,009 | **0** — cached |
| `index.wasm` | 11,834,888 | **11,834,888** — re-downloaded |

**Everything caches except the wasm**, which is 85% of the transfer.

Four explanations were tested and eliminated before this was written down:

1. *Missing validators.* The test server was reissued with `ETag` and
   `Last-Modified`. No change.
2. *A reload rather than a navigation.* `page.goto()` twice to one URL is a
   reload, which deliberately bypasses cache for navigation subresources. The
   test now navigates away and back. No change.
3. *The loader opting out.* Godot's loader calls
   `fetch(url, {credentials: "same-origin"})` with no `cache` option, so it uses
   the default policy. It is not opting out.
4. *Measurement error.* `encodedDataLength` on CDP `Network.responseReceived` is
   the header length, not the body, and reading it as a transfer size was wrong.
   Three independent signals now agree: Resource Timing `transferSize`,
   `fromDiskCache`, and the original startup profile.

Two candidate causes remain, and this document does not pick between them:
Chrome caps a single disk-cache entry at a fraction of total cache size, and
11.8 MB may exceed it in this profile; or `WebAssembly.instantiateStreaming`
interacts with the HTTP cache differently from an ordinary fetch. The 7.5 s that
warm starts *do* save is consistent with Chrome's separate compiled-wasm code
cache working even while the bytes come again.

The impact is worth the attention: **fixing this removes 11.8 MB from every
repeat visit**, which on the fast-4G profile is most of the download time.

## What this says to do, in order

1. **Serve compressed.** 3.9× on the dominant asset, configuration-only.
2. **Fix wasm caching.** Confirmed above, and worth 11.8 MB per repeat visit.
   Identify which of the two candidate causes applies before choosing a remedy.
3. **Attack shader compilation.** This is where the remaining ~23 s lives.
   Godot compiles its shader variants at startup; the patch series already
   carries an offline WGSL precompilation harness
   (`drivers/webgpu/wgsl_precompile.py`) used for translation testing, which is
   the obvious place to start looking.
4. **Only then consider payload work** — feature-stripped export templates,
   content-addressed packs, streaming. Real, but the smaller half.

## What is not claimed

- One scene, one machine, one browser. Chariot on a Tesla P40 under Chrome/Linux.
- Throttling is CDP network emulation, not a real network. It models bandwidth
  and latency, not packet loss, jitter, or radio wake-up.
- "First rendered frame" is the first moment the canvas stops being a flat clear,
  measured on a 250 ms poll — so figures are ±250 ms and measure *something on
  screen*, not *playable*.
- No comparison against Forward Mobile or the WebGL2 fallback has been run. The
  existing figures in `webgpu-performance.md` are from patch series 0001–0014 and
  are not comparable.
