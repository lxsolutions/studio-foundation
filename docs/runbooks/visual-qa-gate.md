# Runbook: Visual QA gate

The scene budget gate checks what a scene *asks the renderer for*. The visual
QA gate checks what the player actually *sees*: it renders the shots a game
declares through Godot's real renderer at three device presets and **measures**
the stills — exposure and saturation alarms, calibrated color probes, HUD
on-screen checks, physical-pixel tap-target floors, and overlap between
top-level HUD blocks. A capture nobody measures is a screenshot nobody looks
at; this gate exists because measured captures found eighteen shipped bugs in
one game in a day, every one invisible to the headless suite.

## Run it

```sh
just GAME=games/chariot qa-godot
```

Options pass through: `--shots running,verdict` and `--devices phone` subset a
sweep; `--list` prints the game's declared shots; `--warn-only` reports without
failing. Output: `<project>/build/qa/<shot>__<device>.png` plus `report.json`,
which records renderer, per-still luma/saturation, and every finding. Exit 0
is conformant, 1 is findings, 2 is a tool failure (which is never silently
"passed").

No GPU is required: the default path renders the Compatibility renderer over
ANGLE/D3D11, which rasterizes in software. Each shot runs in its own Godot
process — measured necessity, not caution: repeated desktop-tier world builds
exhaust the software D3D11 device, and per-shot processes turn a crash into
one failed shot instead of a lost sweep.

## Photograph the cinematic tier (GPU host)

The same sweep on a real GPU exercises Forward+ — SSAO, SSIL, SDFGI and
volumetric fog, the tier the WebGPU patch series unblocks:

```sh
GODOT_BIN=~/godot-bin/Godot_v4.7.1-stable_linux.x86_64 \
xvfb-run -a -s '-screen 0 1920x1080x24' \
  python3 tools/godot/qa_capture.py --game games/chariot \
  --method forward_plus --renderer vulkan
```

Evidence to expect in the report: `"renderer_method": "forward_plus"`. On a
Tesla P40 the full Chariot sweep (27 stills) runs in minutes and, as of the
first run, conformant.

## Declare shots for a game

A game declares shots in `res://tests/qa_shots.gd` (the template ships a
starter). The contract, in brief — the full reference is the doc comment in
`shared/godot-addons/studio_core/tools/qa_capture.gd`:

- `shots()` returns dictionaries: scene, devices, per-device render
  `profiles` (a phone still photographs the phone tier's crowd), `setup` and
  `then` driver methods, and `frame`/`hud` check specs.
- Drive state through the same seams the wire uses — server-shaped payloads
  into the client's event handlers, never hand-posed nodes — and declare an
  `env()` offline seam so a still is never of whatever a shared dev box's
  stray server happens to be doing.
- Tag load-bearing HUD Controls into the `qa_hud` group and touch targets
  into `qa_tap`. The tap floor judges the **smallest** dimension in physical
  pixels — a full-height tab still fails at 37 px wide.

## Calibrate, never guess

Bounds and probe colors come from measured captures, not intuition:

1. Run the sweep once with no `frame` spec; `report.json` prints every
   still's luma and saturation.
2. For color probes, box-average the actual PNGs at the candidate point on
   **both renderer tiers** (Compatibility and Forward+ grade differently) and
   set the expected value to the midpoint with a tolerance spanning the pair
   plus run noise.
3. Probes are catastrophe detectors, not colorimeters: loose enough to
   survive a deliberate regrade conversation, tight enough that a black sky,
   a blown frame, or a gray wash sits far outside the band.

A deliberate art change recalibrates in one run — the report prints actuals
next to every failed bound.

## Traps this gate already paid for

- `set_anchors_preset(CENTER*)` pins a control's top-LEFT at the anchor;
  centering requires `GROW_DIRECTION_BOTH`. Hand-computed offset
  compensation goes stale the day a child widens. Six shipped instances.
- A window resize is asynchronous, and a size set during `_initialize` is
  overridden when the window first shows — the runner asks on frame one and
  waits until the OS agrees, or captures come back at project-default size
  silently.
- Text columns must clip or ellipsize (`clip_text`,
  `OVERRUN_TRIM_ELLIPSIS`): one long row otherwise forces its whole board
  off both phone edges.
- A ProgressBar renders at its themed height, not its
  `custom_minimum_size` — space stacks by measured heights.
- Heavy-world teardown on the software device can crash *after* the stills
  are honest; the wrapper trusts a written report over the exit code.
