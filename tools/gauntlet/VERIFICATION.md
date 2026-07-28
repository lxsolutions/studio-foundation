# Verification record

Exact commands and observed output, so the claims in ADR 0017 are reproducible
rather than reported. Re-run these after any change to the harness.

All GPU measurements run the browser on **smeagol** (Tesla P40, driver 580.173.02)
over one SSH tunnel. `awesome-o` has no GPU — see "Hardware provenance" below.

## 1. Harness self-test (no GPU required)

```bash
just gauntlet-serve            # or: node tools/gauntlet/harness/serve.mjs --root . --port 8099
just gauntlet-doctor
```

Drives `tools/gauntlet/fixtures/contract-demo/`, a dependency-free scene that
implements the full runtime contract. Expect the report to state
`runtime contract: v1, deterministic` and list the fixture's cameras.

On a machine without a GPU this run will also print
`SOFTWARE RENDERER DETECTED`, which is correct and is the point of the check.

## 2. TypeScript template on real hardware

```bash
node tools/gauntlet/harness/serve.mjs --root . --port 8099 &
node tools/gauntlet/harness/round.mjs \
  --url http://127.0.0.1:8099/templates/three-game/ \
  --shots templates/three-game/shots.json \
  --remote smeagol \
  --note "ported into studio-foundation: tools/gauntlet + templates/three-game"
```

Observed 2026-07-28, `feat/gauntlet-quality-layer` @ `origin/main`:

```
[round 1] preflight: npx tsc --noEmit
[round 1] capturing...
Rendered on: smeagol · profile `webgpu` — Tesla P40 (Pascal) — hardware WebGL + hardware WebGPU
WebGL adapter:  ANGLE (NVIDIA, Vulkan 1.4.312 (NVIDIA Tesla P40 (0x00001B38)), NVIDIA)
WebGPU adapter: nvidia
runtime contract: v1, deterministic · cameras: hero, wide, low, detail

fatal 0 · warn 0 · pageErrors 0
fpsP50 60 · edgeEnergy 9.17 · dynamicRange 130.25 · instability 0
VERDICT: JUDGE (no --references supplied, so no deck was built)
```

`edgeEnergy 9.17` is expected here: `assets-generated/` is gitignored, so the
bforge column is absent and the template falls back to procedural geometry. Forge
it to raise the figure:

```bash
just NAME=gauntlet_column RECIPE=prop.pillar bforge-make
```

## 3. Engine neutrality — the evidence ADR 0017 rests on

The same harness, **no code changes**, measuring a Godot web export:

```bash
node tools/gauntlet/harness/serve.mjs --root . --port 8098 &
node tools/gauntlet/harness/shotset.mjs \
  --remote smeagol --serve-port 8098 \
  --url http://127.0.0.1:8098/games/chariot/project/exports/web-webgl/index.html \
  --out runs/godot-chariot-webgl --seconds 5 --boot-timeout 90000
```

Observed:

```
Rendered on: smeagol · profile `webgpu` — Tesla P40
WebGL adapter:  ANGLE (NVIDIA, Vulkan 1.4.312 (NVIDIA Tesla P40 (0x00001B38)), NVIDIA)
WebGPU adapter: nvidia
Boot to first non-empty frame: 19155 ms
fps p50 60 / p99 30
runtime contract: absent — shots are best-effort and NOT reproducible run-to-run
```

`contract: absent` is correct: the Godot export does not implement the runtime
contract, so the harness degrades to best-effort capture and says so.

## Hardware provenance — why `--remote` is mandatory

`awesome-o` reports only *Microsoft Remote Display Adapter* and *Microsoft Basic
Display Adapter (SeaBIOS VBE)*. There is no GPU; `navigator.gpu.requestAdapter()`
returns nothing under every flag combination tested, headed and headless.

This is not merely a performance caveat. Measured on the identical build and shot
set, software versus Tesla P40:

| metric | software | Tesla P40 |
|---|---|---|
| fps p50 | 13.3 | 60 |
| `edgeEnergy` (hero) | 6.2 | 11.81 |
| findings | 4 × `no-surface-detail` | 0 |

Software rendering degraded the image enough to **change the objective
measurements and invent four defects that do not exist on real hardware.** Every
report therefore stamps the adapter, and a run that prints
`SOFTWARE RENDERER DETECTED` must be treated as void.

### GPU profiles

| profile | device | WebGL | WebGPU |
|---|---|---|---|
| `webgpu` (default) | Tesla P40 (Pascal) | hardware | **hardware** |
| `raster` | Tesla V100 (Volta, 32GB) | hardware | software |

Hardware WebGPU requires a real X surface (xvfb, headed). Headless yields real
WebGL but a SwiftShader WebGPU adapter that reports itself as working, so the
`webgpu` profile deliberately runs headed.
