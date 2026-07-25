# The Chariot Club

The game behind the live demo at
<https://lxsolutions.github.io/studio-foundation/> — a Roman colosseum with
crowded stands, chariot teams, and real-time shadows, running in a browser
through Godot 4.7.1 on this repository's patched WebGPU backend.

It is published here so the demo can be rebuilt and audited rather than taken on
trust. **That is not a relicense.** Per [`../LICENSE`](../LICENSE), a game
directory without its own LICENSE file is all rights reserved; this one has none.
Read it, build it, verify the claims — but it is not open source, and the
Foundation's own licence does not extend to it.

## Build it

You need the patched WebGPU export templates. They are not stock Godot templates
and they are not in this repo — download both from the
`godot-4.7.1-webgpu-p0014` release and unpack them where
`project/export_presets.cfg` expects (`engine/artifacts/templates/`), or build
them yourself with `just engine-build`.

```sh
just GAME=games/chariot export-browser-webgpu
```

That wraps `tools/godot/export_game.py`, which does the post-export step that
matters: a raw `godot --export-release` web build starts on whatever the preset
says and dies with *"Failed to get pre-initialized device"*, because the runtime
needs the driver selected by CLI args in `GODOT_CONFIG`. `configure_web_renderer`
rewrites that. Do not skip it and do not export by hand.

There is also `export-browser-webgl` (`web-webgl` preset), which works with
stock installed templates and is the fallback if WebGPU is unavailable.

## Two settings that will cost you an afternoon

- **`variant/thread_support=false`** in the `web-webgpu` preset. Setting it true
  demands cross-origin isolation (COOP/COEP headers), which GitHub Pages does not
  send — the game then fails to boot at all. This was the original blocker that
  kept the demo off Pages, and it is easy to reintroduce by toggling threads in
  the Godot export UI.
- The `custom_template/*` paths are **relative** (`../../../engine/artifacts/...`).
  They only resolve when the project sits at `games/chariot/` inside a full
  checkout of this repository.

## Verifying the render

The claim is 60 fps at roughly 490–630 draw calls and ~23M primitives per frame,
with zero `GPUValidationError`, on an NVIDIA Tesla P40. Verify it from the
engine's own counters rather than a screenshot — a headless/Xvfb browser cannot
composite the canvas, so pixel readback proves nothing. Expect roughly 13 s from
cold load to first rendered frame; the ~45 MB wasm download dominates, not shader
compilation.

## Layout

| | |
|---|---|
| `project/` | the Godot project (`src/core` is engine-independent and headless-testable; `src/presentation` holds the Godot nodes) |
| `server/` | the Rust game server (`cargo test` under `server/`) |
| `assets-source/` | authoring sources for generated assets |
| `docs/` | design notes |
