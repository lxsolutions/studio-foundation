# The overnight prompt

Paste this as a single message. Replace the three `<<< >>>` slots. Everything
else is load-bearing — the clauses about the judge, the ownership rules and the
stop condition are what separate this from "make me a cool game", and each one
exists because its absence is visible in the public builds (see BLUEPRINT.md).

---

```
/loop /goal Build <<<TITLE>>> — a browser game whose visual craft beats <<<REAL GAME TO BEAT>>> — and do not stop until a sealed blind judge picks ours.

THE BAR — establish before writing any game code
- Reference frames live in gauntlet/references/<<<BAR NAME>>>/. If that directory is
  empty, tell me exactly what to put there, then continue with everything that
  does not depend on it. Do not proceed against an adjective.
- "AAA quality" is not a bar. A frame is a bar.

SUBSTRATE
- **TypeScript**, strict, with `tsc --noEmit` as a preflight gate. Not for
  cleanliness — for feedback latency. A capture round costs ~4 minutes on the
  remote GPU; a typecheck costs ~2 seconds. Never spend the former to discover
  the latter. `round.mjs` runs it automatically when tsconfig.json exists.
- Three.js. Default to WebGL2 so it runs everywhere including this box, which
  has no GPU at all. WebGPU IS available on smeagol (verified: webgpu=nvidia /
  pascal), so you may target it if the game genuinely needs compute — but then
  ALL iteration must go through --remote smeagol.
- MEASURE ON smeagol, ALWAYS. Never gate visuals or performance on this box:
  the software rasterizer degrades the image enough to change the objective
  numbers and invent defects that do not exist on real hardware (measured:
  edgeEnergy 6.2 software vs 11.81 on a Tesla P40; 4 findings vs 0).
    node harness/serve.mjs --root . --port 8099 &
    node harness/shotset.mjs --remote smeagol --url http://127.0.0.1:8099/<path> ...
- Zero external assets beyond three.js. Every mesh, texture, material, animation
  and sound generated in code. This is for COHERENCE, not purity — one material
  and lighting vocabulary is what makes it read as a real engine.
- Exception: you MAY author hard-surface meshes with bforge (studio-foundation,
  ADR 0014) and export GLB into the build. Prefer that over blocky primitives.
  Generate -> render.contact_sheet -> LOOK at the image -> check.critique -> fix
  -> export.asset. Never a GUI-dependent Blender MCP.
- First increment, before anything else: import runtime/gauntlet-hooks.js and
  register seed, camera, stats and ready. Nothing downstream is measurable
  without it.

EVERY ROUND — one command does the deterministic part
    node gauntlet/harness/round.mjs \
      --url http://127.0.0.1:8099/<path> \
      --shots shots.json \
      --references gauntlet/references/<<<BAR NAME>>> \
      --remote smeagol \
      --note "<what you changed this round>"

It prints one of four verdicts. Obey it:
  VOID      software renderer — the round is meaningless, re-run on smeagol
  REGRESSED your last change made it worse; revert or rethink BEFORE continuing
  FIX       objective defects listed — fix them, do NOT spend a judge round
  JUDGE     mechanically clean, blind deck built

On JUDGE: spawn a FRESH sub-agent and give it ONLY the deck directory and
JUDGE_BRIEF.md. It must not see the build, the diff, this prompt, or which frame
is ours. Collect its JSON, then:
    node gauntlet/harness/judge.mjs reveal --dir <judgeDir> --answers verdict.json
Then fix the single largest gap it named. One thing, properly.

ALWAYS open the frames and LOOK at them. Every real defect found while building
this framework was invisible in the numbers — a shot scored "no objective
defects" and still read as a 2010 tech demo.

OWNERSHIP — this is where these runs usually fail
- Lighting + sky + indirect + tonemap + post is ONE owner working SEQUENTIALLY.
  It is one coupled system. Parallel agents each "fix" it and undo each other:
  measured at +0.46 for three parallel rounds vs +1.00 for one sequential pass,
  with defects 66 -> 26.
- Player controller + camera + input feel is ONE owner, sequential.
- Parallelise only genuinely independent surfaces: audio, HUD/menus, world
  content, enemy behaviour, tooling.

INTEGRITY — absolute
- You may not edit the judge brief, relax its criteria, or re-run it until it
  agrees. If you want to, that is the signal the work is not there yet.
- You may not mark this done because it "looks good". Show the score.
- If any report prints SOFTWARE RENDERER DETECTED, that run is void — re-run it
  with --remote smeagol. Do not publish a software fps as if it were real, and
  do not act on visual findings from a software run.
- If you cap coverage anywhere, say what you dropped. Silent truncation reads as
  completeness.

EFFORT ORDER — highest visual leverage first
1. Light transport: indirect bounce, contact shadows, AO, falloff.
2. Material response: roughness VARIATION above all else.
3. Surface detail at multiple scales (watch edgeEnergy — flat shading is the
   loudest tell of procedural work).
4. Tonemap and grade: highlight roll-off, black point, dither before quantising.
5. Motion integrity: unstable-pixels, z-fighting, shadow acne.

STOP CONDITION
Stop when two consecutive rounds produce no new findings AND the judge win rate
has not moved. Not after N rounds. Not when it looks good.

EVERY ROUND, append to PROGRESS.md: round number, what changed, who owned it,
objective deltas, judge win rate, the largest gap named, and what is next. Terse.
It is what I read in the morning.

Work autonomously. I am asleep. Do not ask me questions — make the call, write
down the assumption, and keep going.
```

---

## Choosing the bar

Pick a bar you can actually beat on craft rather than on budget. Photoreal
military realism is the worst possible target from a GPU-less box: it is pure
pixel throughput, and it is what every one of these viral demos already loses at
(5.05/10, zero blind wins).

Strong choices instead — art direction beats horsepower:

| Target | Why it is winnable |
|---|---|
| **Journey** / **Sable** | Flat-ish shading, huge silhouettes, colour grading does the work |
| **Hyper Light Drifter** | Deliberate palette, no material realism needed |
| **Return of the Obra Dinn** | 1-bit dither — literally cheaper the more stylised it gets |
| **Tunic** / **Death's Door** | Clean shapes, strong light, tiny material budget |
| **Outer Wilds** | Scale and mood, not surface fidelity |

You already have an art direction nobody else in that wave has: the Hellenic
futurism of Riftline, and a headless deterministic asset forge (bforge) that is
strictly better than the community Blender MCP the 24-hour run used. Building
your own IP against a stylised bar plays every advantage you have; building a
Call of Duty clone plays none of them.
