---
name: bforge
description: Build game-ready 3D assets with Blender — props, modular kits, terrain, characters with rigs and animation, materials, LODs, collision, glTF export. Use whenever the task involves making, fixing, inspecting or exporting a 3D model, texture, environment piece or character for a game, or when someone says "make a model/asset/prop/character", "generate 3D", "export a GLB", or mentions Blender.
---

# bforge — headless Blender asset forge

`bforge` drives a persistent background Blender session through 138 typed
operations. It never needs the Blender GUI, it is deterministic (same params +
same seed → same mesh, forever), and every generated asset comes out chamfered,
UV'd, materialled, pivoted and validated against the studio's ADR 0006 rules.

## How to reach it

**As MCP tools** (preferred — the `bforge` MCP server is registered in
`.mcp.json`): `bforge_ops`, `bforge_describe`, `bforge_run`, `bforge_run_batch`,
`bforge_session`. Use `bforge_run_batch` to do a whole asset in one round trip.

**As a CLI**, for shell and CI work:

```bash
python tools/bforge/bforge/cli.py doctor            # verify the chain
python tools/bforge/bforge/cli.py ops --tag prop    # discover
python tools/bforge/bforge/cli.py help prop.barrel  # parameters
python tools/bforge/bforge/cli.py run prop.barrel height=1.2 seed=4 --render sheet.png
python tools/bforge/bforge/cli.py make crate_a --recipe prop.crate --export
```

**As a Python library**, for anything scripted:

```python
import sys; sys.path.insert(0, "tools/bforge")
from bforge import Forge
with Forge() as forge:
    forge.call("session.reset")
    forge.call("prop.crate", name="crate_a", size=[1, 1, 1], seed=3)
    forge.call("export.asset", asset_id="crate_a")
```

## The loop that produces good assets

Do not generate and hand over. Generate, **look**, critique, fix, then export.

1. `session.reset`
2. a recipe — `prop.*`, `kit.*`, `env.*`, `char.*` — or compose with `build.*`
3. `render.contact_sheet` — **then actually read the returned PNG**. The
   wireframe panel shows wasted triangles; the checker panel shows UV stretch
   and texel-density mismatch. Neither is visible in a triangle count.
4. `check.critique` — returns findings with the exact op that fixes each one
5. apply fixes, re-render, repeat until clean
6. `gameready.collision`, and `gameready.lod` if it is over budget
7. `export.asset` — writes .blend master + .glb + .meta.json + contact sheet

## Rules that matter

- **Sizes are metres.** A crate is 0.9, a door is 2.1, a human is 1.8.
- **Use `meta.palette` colour names** (`stone_grey`, `wood_oak`, `iron`,
  `leaf_green`, …) instead of inventing RGB. Palette discipline is what makes a
  set of assets look like one game.
- **One `uv_scale` across a whole set.** Mismatched texel density is the most
  common reason individually-fine assets look wrong side by side; `uv.report`
  and `check.critique` both measure it.
- **Procedural materials must be baked** (`material.bake`) before export —
  glTF cannot express a noise node, and an unbaked one arrives in-engine as
  flat grey. `export.gltf` blocks on this by default.
- **Seed everything.** Vary `seed` for variants; keep it fixed for
  reproducibility.
- Prefer a recipe over hand-composing primitives — recipes already know the
  right proportions, chamfers and UV strategy for their asset class.

## Where things land

Outputs go to `assets-generated/bforge/` (gitignored, reproducible). Committed
masters belong in `assets-source/` per ADR 0006. `export.asset` writes the
`.meta.json` sidecar with AI provenance that `just asset-validate` requires.

## Reference

- Full op reference with every parameter: `docs/bforge/OPS.md`
- Architecture and rationale: `tools/bforge/README.md`
- Design decision: `docs/adr/0014-bforge-agent-asset-authoring.md`

## Gotchas

- Renders use **Cycles on CPU**. EEVEE and Workbench need a GPU context and
  hard-crash headless Blender — do not switch engines to "speed things up".
- Scene state persists between ops. If a daemon crash loses it, rebuild from
  `session.reset`; `bforge_session action='restart'` gets a fresh process.
- `render.contact_sheet` costs a few seconds. Use `tile=300, samples=16` while
  iterating and raise them only for a final review image.
- `render.sprite` preflights sheet size, views, supersampling, float buffers,
  and samples before Blender allocates or renders. The 16-view
  `size=512, supersample=2, samples=96` profile is the exact work ceiling;
  reduce any of those controls if the budget rejects a call. Directional views
  share one camera distance, world target, ground anchor, and pixels-per-metre
  scale; use the returned `framing`/sidecar contract instead of per-frame crop.
