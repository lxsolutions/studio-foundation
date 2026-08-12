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
`godot-4.7.1-webgpu-p0033` release and unpack them where
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

## The four circus factions

Every race accrues to a faction: Blues, Greens, Reds, Whites (the Byzantine
Veneta/Prasina/Russata/Albata). The layer is deliberately thin:

- `project/src/core/circus_factions.gd` owns the faction data, membership
  validation, silk→faction resolution, and the 9/6/4/2 points table.
  `server/src/factions.rs` mirrors it — change both or change neither.
- `RaceState` tags each finisher with a faction (explicit wire key, else the
  entry's silk resolved to its nearest faction; colorless entries take the
  faction-first fallback palette in gate order — the same palette the
  broadcast tints from, so the color a horse wears is the faction it scores
  for) and folds the race's `faction_points` tally.
- The broadcast paints the faction kit on the big readable surfaces (saddle
  cloth, car front, charioteer tunic); the plume and crest keep the stable's
  own silk. The laurel board and the tabula close a settled race with the
  four-faction tally.
- A rider declares for a faction at the sign-in gate; `AuthStore` persists it
  (`user://rider.cfg`, localStorage `arc_faction` on the web). It is
  local-only until the racing wire carries a faction key.
- The Rust server persists membership + per-race faction points
  (`server/migrations/0002_circus_factions.sql`, PostgreSQL when
  `DATABASE_URL` is set, in-memory otherwise) and answers three game-owned
  application payloads over the studio protocol: `faction_join`,
  `race_record` (server derives points from places), and `standings_fetch`
  (the season tally per faction).

## Ghost time-trial duels ("beat my lap")

The async 1v1 settle: save a finished race as a challenge ghost, then race
against its replay on the sand.

- `project/src/core/ghost_run.gd` owns the run: recording from the spectate
  tick stream (normalized to a millisecond race clock against the official
  timeMs), serialization, replay interpolation, the win/loss verdict, and the
  plausibility bounds. `server/src/ghosts.rs` mirrors the bounds — change both
  or change neither.
- `project/src/core/ghost_store.gd` keeps ghosts under `user://ghosts/`
  (schema-versioned JSON, the StudioReplay convention). Its `transport` seam
  takes a Callable answering the server's payloads — the studio bridge wires
  it (see below); unset or parked means local-only. The callable may be a
  coroutine, so the store's call sites await it; a synchronous transport
  resolves without suspending, which is how the test suite drives it.
- The rider view records every race you ride. The laurel board offers
  **SAVE AS A CHALLENGE GHOST** after a finish; the stable's GHOSTS desk lists
  your ghosts, loads one by id, and arms it. An armed ghost replays as a
  spectral biga (faction-tinted translucency, no shadows, no new art) — with
  the exhibition between races, against the live tick clock during one. It
  lives outside the live field's collections, so nothing can collide with it
  or score it. Your next finish settles the duel on the laurel board.
- The Rust server stores and returns runs verbatim via `ghost_submit` /
  `ghost_fetch` (`server/migrations/0003_ghost_runs.sql`): it applies the
  shared bounds and derives nothing else from a client's claims.

## The identity bridge, and ghosts by URL

The client now speaks the studio protocol, so a ghost can leave the machine
that set it.

- `project/src/presentation/studio_client.gd` is the websocket client for the
  in-repo Rust server, built on studio_core's `StudioWsTransport` +
  `StudioProtocol` (the addon stays untouched). The rider and stands views
  wire `GhostStore.transport` to its `transport_mapping` (`ghost_submit` →
  `submit`, `ghost_fetch` → `fetch`). The protocol carries no correlation
  ids, so in-flight requests settle through one FIFO queue. The bridge is
  opportunistic: no server URL, a failed connect, or a dropped socket parks
  it for the session, and every request then answers an immediate
  offline-shaped refusal — the store falls back to local-only, exactly as
  before the bridge. `RACING_STUDIO_URL` overrides the server address (set
  but empty parks the bridge); the default `wss://racing.ashaarena.com/studio`
  is the mount the deploy is expected to expose.
- Identity rides the submit, not the handshake. The token source is the plaza
  handoff: a fresh `?t=` token captured at the sign-in gate, else the
  same-origin `arb_token` localStorage key (what the plaza writes and the
  Minerals bridge reads). The owner code is deliberately NOT a token — the
  club has no verify endpoint for it — so code-signed riders submit under the
  claimed member, as before the bridge.
- Server side, `server/src/identity.rs` verifies a presented token the way
  the Minerals satellite does (`siege/PLAZA_INTEGRATION.md`): bearer against
  `{PLAZA_BASE_URL}/api/siege/loadout`, which answers the stable plaza `key`
  and authoritative `handle`; the ghost's `member_key` becomes
  `plaza:<sha256(key) truncated>`, never the raw key or token, and the
  verified handle wins over the client claim. `PLAZA_BASE_URL` unset means no
  verifier and the claimed member stands (dev, tests). A presented token that
  fails verification fails the submit outright. The verifier is a trait
  (`PlazaVerifier`); tests use `StubPlazaVerifier`. What remains for a live
  deploy: set `PLAZA_BASE_URL` on the server (the plaza origin, e.g.
  `https://platosplaza.com`; `http://127.0.0.1:8091` in dev, mirroring
  Minerals' `ARENA_API`) and confirm the plaza accepts the stables handoff
  token as a session at that endpoint — no live plaza was reachable from this
  environment, so the HTTP verifier is exercised only by contract, not
  against the real service.
- Ghosts are links now: `?ghost=<id>` on the game URL is read at boot by the
  rider and the stands (and scrubbed from the address bar like the token),
  loaded through the store, and armed on the sand. The GHOSTS desk's LINK
  button copies `<origin>/?ghost=<id>` to the clipboard; a server `g-…` id
  travels, a local `ghost_…` id only resolves where it was saved.
