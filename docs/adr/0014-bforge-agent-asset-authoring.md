# ADR 0014: bforge — agent-operable asset authoring

- Status: Accepted
- Date: 2026-07-24
- Extends: [ADR 0006](0006-blender-master-asset-pipeline.md) (Blender master-asset pipeline)

## Context

ADR 0006 gave us a deterministic pipeline that **validates and exports** master
`.blend` files. It deliberately banned GUI automation and arbitrary remote code
execution into Blender, and it was right to.

But it left a gap: nothing in the pipeline can **author** an asset. Every
`.blend` had to be hand-made in Blender first, which meant the AI-native
positioning this project claims stopped at the studio door. The one discipline
where we had no agent leverage was the one with the largest content backlog.

The obvious fix — adopt a community Blender MCP server — conflicts directly with
ADR 0006 and, on inspection, is a bad tool regardless:

- **Requires a GUI Blender** with a socket add-on. Rules out CI, containers,
  headless build boxes, and the GPU host (`smeagol`) where we do rendering work.
  Our own prior attempt to verify one of these servers stalled on exactly this:
  the last hop could never be confirmed because a GUI Blender could not be
  launched from an automated shell.
- **`execute_blender_code`** is an arbitrary-code-execution surface into a
  process holding unsaved work, which ADR 0006 §Decision explicitly refuses.
- **Not reproducible.** Model-generated `bpy` against live scene state gives a
  different mesh every run, so assets cannot be regression-tested or regenerated
  from source — which breaks the source-hash caching the pipeline depends on.
- **Wrong abstraction.** A few hundred wrappers around `bpy.ops` ("add cube",
  "bevel") asks the model to be a technical artist. It reliably produces meshes
  with unapplied scale, no UVs, no collision, no LODs, and materials glTF cannot
  express — assets that look fine in a viewport grab and import wrong.
- **No feedback.** A single viewport screenshot cannot show topology waste, UV
  stretch, or texel-density mismatch, so the model cannot tell good output from
  bad and neither can its operator.

## Decision

Build **`bforge`** (`tools/bforge/`): a headless, allowlisted, recipe-level
Blender operation layer, and treat it as the authoring front half of the ADR
0006 pipeline rather than a replacement for it.

1. **Persistent headless daemon.** `blender --background` holding one session
   open, speaking marker-framed JSON-line RPC over stdin/stdout. No GUI, no
   sockets, no ports, no firewall prompts. Works over SSH and in CI.
   Amortises Blender's 2–4 s cold start to ~50 ms per op, and lets ops compose
   against shared scene state.

2. **Allowlisted operations, never arbitrary code.** ~89 ops declared through a
   typed registry. This preserves ADR 0006's security stance exactly: the
   supported surface is our scripts, not model-authored Python. There is no
   `execute_code` op and adding one would need a new ADR.

3. **Recipes, not primitives.** The API level is `prop.barrel(height, bands,
   belly)`, `kit.room(size, doors, windows)`, `char.humanoid(build, height)` —
   parameterised generators that already encode the proportions, chamfers, UV
   strategy and triangle budget appropriate to their asset class. Models are
   good at expressing intent and bad at 300-line `bmesh` programs.

4. **Determinism as a contract.** Every generator is seeded; same parameters and
   seed produce the same mesh including vertex order. Environment noise is built
   from `sin`/`cos` rather than a platform noise library so results are
   bit-identical across machines. This is what makes generated assets
   regression-testable and compatible with the pipeline's source-hash cache.

5. **Engine-correctness enforced, not requested.** Every asset passes a fixed
   finishing pass (weld → shade → UV → material → origin → apply transforms).
   `gameready.*` provides LOD chains, collision proxies using the existing
   `-col`/`-convcol` naming convention, per-platform budgets and atlasing.
   `export.gltf` refuses by default to emit an asset with unapplied scale or an
   unbaked procedural material.

6. **A verification loop the agent can actually use.** `render.contact_sheet`
   returns one image containing hero/front/left/top views plus a wireframe pass
   (exposes triangles that buy no silhouette) and a UV-checker pass (exposes
   stretch and texel-density mismatch). `check.critique` returns numeric
   findings, each naming the op that fixes it. `check.asset` runs the same rules
   as `tools/blender/validate.py`, so problems surface while the scene is still
   open rather than at `just asset-validate` time.

7. **One registry, four surfaces.** Typed parameters are declared once and
   generate runtime coercion, MCP schemas, OpenAI/llama.cpp and Anthropic
   function schemas, CLI help, and the markdown reference. Any agent runtime can
   drive it; the MCP server is registered in `.mcp.json` and exposes five
   grouped tools by default (89 individual tools swamps most clients) with a
   `--tools full` mode for clients that prefer per-op schemas.

## Consequences

- The studio can generate, review, validate and ship 3D assets from CI or from
  an agent session with no human in Blender — while ADR 0006's guarantees
  (deterministic, allowlisted, validated, provenance-tracked) all still hold.
- `.blend` remains the committed master and `assets-source/` remains the only
  editable truth. bforge writes masters; it does not bypass them.
- `export.meta` records AI provenance (tool, model, prompt, determinism flag) in
  the sidecar the pipeline already requires, so AI-generated content is
  disclosed by construction rather than by policy.
- **Renders are Cycles/CPU.** EEVEE and Workbench require a live GPU context and
  segfault in background mode without a display server. The wireframe pass is a
  Cycles shader rather than a viewport overlay for this reason. This costs
  render time and buys the ability to run anywhere; where a GPU context exists,
  `engine="eevee"` is opt-in.
- Recipes are a curated set, not a general modelling tool. Anything outside them
  composes from `build.*` primitives, and genuinely bespoke art still belongs to
  a human in Blender. The bet is that most game content is not bespoke.
- Community Blender MCP servers remain **not supported**, unchanged from ADR
  0006. bforge is the supported path.

## Alternatives considered

- **Adopt `ahujasid/blender-mcp`.** Rejected: conflicts with ADR 0006 on both
  GUI automation and remote code execution, and cannot run headless. Retained as
  an optional local developer convenience only, disabled by default.
- **Geometry Nodes graphs instead of `bmesh`.** Rejected for now: node graphs
  built through the Python API are far more verbose than the equivalent `bmesh`
  code, harder to diff in review, and their evaluation still has to be baked
  before export. Worth revisiting for scatter and terrain specifically.
- **A text-to-3D generator (Hyper3D/Rodin, Hunyuan3D, Meshy, Tripo).** Rejected
  as the primary path: output topology and UVs are not game-ready without manual
  cleanup, results are non-deterministic, and most require a third-party account
  and send prompts off-box. Viable later as an *input* to bforge's clean-up and
  game-ready passes, not as a replacement for them.
