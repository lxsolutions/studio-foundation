# The overnight prompt

Paste as one message, replace the two `<<< >>>` slots, go to sleep.

Every clause exists because its absence cost a measured round. Do not trim it —
the length is the point. `BLUEPRINT.md` holds the evidence behind each one.

---

```
/loop /goal Build <<<TITLE>>> — a browser game whose visual craft beats <<<REAL GAME TO BEAT>>> — and do not stop until a sealed blind judge picks ours.

THE BAR — before any game code
- Capture 4-8 frames of the target into tools/gauntlet/references/<name>/ covering
  its real range, not only its best shot. Then:
    node tools/gauntlet/harness/calibrate.mjs --references tools/gauntlet/references/<name>
  That derives the thresholds. Fixed constants are wrong in BOTH directions: they
  flagged four defects on a beautiful dark reference AND passed a build 3x short
  of the real bar.
- If you cannot capture the target lawfully, say so and propose the closest
  inspectable substitute. Never proceed against an adjective.

PICK A WINNABLE BAR
Photoreal military realism is an asset-density war you lose. Matt Shumer aimed
there and published the result: 5.05/10, and in blind A/B every critic in every
round picked the real Call of Duty frame. Aim where art direction substitutes for
asset budget: Journey, Sable, Obra Dinn, Outer Wilds, Hyper Light Drifter.
PREFER AN INTERIOR OR ENCLOSED SPACE. This is the most underrated decision here:
in an interior every pixel lands on something, which is exactly why the densest
reference frames are ship interiors and corridors.

SUBSTRATE
- TypeScript, strict. Preflight BUILDS (`npx tsc`), never `--noEmit` — the browser
  loads the emitted .js, so a typecheck-only gate lets an edited .ts pass while
  the capture measures the PREVIOUS compile.
- Three.js on WebGL2. WebGPU works on smeagol if a system genuinely needs compute,
  but then everything iterates through --remote.
- First increment, before content: import tools/gauntlet/runtime/gauntlet-hooks.js
  and register seed, camera, stats, probe, scene, ready. Nothing downstream is
  measurable or reproducible without it.

ASSETS — RUN THIS BEFORE HAND-WRITING ANY GEOMETRY
    python tools/bforge/bforge/cli.py ops
106 ops already exist: arch.colonnade, kit.set, build.greeble, env.scatter,
env.terrain, prop.debris, prop.pillar, char.humanoid. I hand-wrote a worse column
than `prop.pillar` produces in one line.
- Surface with material.pbr (layered: edge wear from curvature, cavity dirt from
  AO, micro-detail) then material.bake_pbr. NOT material.set + material.bake —
  the flat preset bakes a uniform grey that arrives in-engine looking untextured.
- Run check.critique and DO WHAT IT SAYS; it names the exact fixing op.
- render.contact_sheet, then LOOK at the image. The checker panel shows UV
  stretch; the wireframe panel shows wasted triangles.
- Detail geometry needs resolution to exist in: 20 flutes at 32 radial segments
  aliased into a smooth cylinder — 640 triangles that rendered as if absent.

FILL THE FRAME — the actual gap, measured over nine rounds
Detail must COVER the frame, not sit on one hero prop. Removing tiled ground
wallpaper collapsed detail 35 -> 12, because a single authored asset cannot carry
a frame that is 70% empty ground. The bar scores 28-30 because every surface in
it is authored. Watch `dead-space` and `blockEdgeP10`: the bar never drops below
2.47; an empty build bottoms out at 0.23.
- Never tile one texture over everything. It satisfies edge-energy while the
  frame gets visibly worse. That is reward hacking and it will fool you.
- Vary per instance: yaw, scale, seed. Twelve copies of one mesh at one rotation
  read as a stamp.
- Panel/seam textures must never wrap a sphere.

EVERY ROUND — one command
    node tools/gauntlet/harness/round.mjs \
      --url http://127.0.0.1:8099/<path> --shots shots.json \
      --references tools/gauntlet/references/<name> \
      --remote smeagol --note "<what changed>"

Obey the verdict:
  VOID      software renderer — the round is meaningless, re-run on smeagol
  REGRESSED your last change made it worse; revert or rethink BEFORE continuing
  FIX       objective defects listed — fix them, do NOT spend a judge round
  JUDGE     mechanically clean, blind deck built

On JUDGE: spawn a FRESH sub-agent and give it ONLY the deck directory and
JUDGE_BRIEF.md — not the build, the diff, this prompt, or which frame is ours.
Then `judge.mjs reveal`, and fix the single largest gap it named. One thing,
properly.

ALWAYS OPEN THE FRAMES AND LOOK. Every real defect found while building this
framework was invisible in the numbers: a shot scoring "no objective defects"
that was a disco ball; a camera sitting inside a column reported as an ordinary
weak frame; four defects invented by a software rasterizer that do not exist on
real hardware.

BEFORE BELIEVING A REGRESSION, ask whether the BUILD changed or the RULER did.
Two rounds were lost to a harness bug reported as a content defect, and one
"regression" was only the gate being calibrated for the first time.

OWNERSHIP — where these runs usually fail
- Lighting + sky + indirect + tonemap + post is ONE owner, SEQUENTIAL. It is one
  coupled system. Measured: three parallel rounds moved quality +0.46; one
  sequential pass moved it +1.00 and cut defects 66 -> 26.
- Player controller + camera + input feel is ONE owner, sequential.
- Parallelise only genuinely independent surfaces: audio, HUD, world content,
  enemy behaviour, tooling.

INTEGRITY — absolute
- You may not edit the judge brief, relax its criteria, or re-run it until it
  agrees. Wanting to is the signal the work is not there yet.
- You may not mark this done because it looks good. Show the score.
- Any run printing SOFTWARE RENDERER DETECTED is void.
- If you cap coverage anywhere, say what you dropped.

PLAYABILITY — a beautiful build with dead controls passes every visual gate
    node tools/gauntlet/harness/playtest.mjs --url <url> --checks playtest.json
Assert that input moves the player, events fire, and no transform went NaN.

STOP CONDITION
Two consecutive rounds with no new findings AND a flat judge win rate. Not after
N rounds. Not when it looks good.

EVERY ROUND append to PROGRESS.md: round, what changed, who owned it, objective
deltas, judge win rate, largest gap named, what is next and why. Terse. It is what
I read in the morning.

Work autonomously. I am asleep. Do not ask questions — make the call, write down
the assumption, and keep going.
```

---

## What one overnight run actually gets you

Being specific, because "AAA" is the word that makes this feel impossible.

**Reachable in one run:** something that looks like the viral clips — coherent
lighting, authored assets, 60 fps, a real game loop. That is what those demos
are, and we have things they did not: a headless deterministic asset forge, a
calibrated gate, GPU-truth measurement, and a sealed blind judge.

**Not reachable, by anyone yet:** beating Call of Duty. The most-shared build in
that wave scores 5.05/10 against it and has never won a blind comparison.

Budget honestly: mikeluan123 posted **$632.65** for one game; Anshu ran 24 hours
and stopped it manually. This is hours and real money, not minutes.

## Choosing the target

| target | why it is winnable |
|---|---|
| **anything interior / enclosed** | every pixel lands on something — the biggest single lever |
| Journey / Sable | flat-ish shading, huge silhouettes, the grade does the work |
| Return of the Obra Dinn | 1-bit dither — cheaper the more stylised it gets |
| Outer Wilds | scale and mood, not surface fidelity |
| Hyper Light Drifter | deliberate palette, zero material realism required |

You have an art direction nobody in that wave has — the Hellenic futurism of
Riftline — and bforge, which is strictly better than the community Blender MCP
the 24-hour run used. Build your own thing against a stylised interior bar and
every advantage you own applies.
