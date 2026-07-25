# AI-native graphics production

How an AI agent actually produces game art at quality, and what has to exist for
that to work. Written from doing it — every claim below traces to a specific
failure or win building The Chariot Club's venue, crowd and props with
[bforge](../../tools/bforge/README.md) (ADR 0014).

## The thesis

**Generation is not the bottleneck. Judgement, integration and iteration speed
are.**

Generating a hippodrome, a crowd, a horse and eight props took minutes. What
cost hours was telling good output from bad, keeping forty assets consistent
with each other, and discovering that something correct in isolation was broken
in the game.

Every capability below exists to attack one of those three, not to make
generation faster.

---

## 1. Instruments, not eyes

An agent looking at a render can tell you *something is wrong*. It usually
cannot tell you *what*, and it is confidently wrong about quantities.

**The case that proved it.** A stone prop rendered near-white. Three full
re-renders went into "fixing" the material — tightening the wear mask, adding
blotch layers, adjusting the albedo stack. The material had been correct the
whole time. The light rig was roughly 4x too hot, from a calibration constant
that had been guessed and never verified. A twenty-line numeric readout
(`check.image`) identified it immediately: the subject's dominant colour was
`#d5d2cd` where the albedo was `#6d6152`, with zero blown highlights — which
means over-exposure, not a broken shader.

**The rule.** Turn every perceptual question into a measured one, and return
the measurement automatically with the artefact.

| Question | Instrument |
| --- | --- |
| Is this over-lit or is the material wrong? | luma histogram, blown/crushed fraction, dominant colours vs the requested albedo |
| Does it read at gameplay distance? | render at true on-screen pixel size, measure silhouette contrast against backdrop |
| Is this expensive? | draw calls and material count, not triangles alone |
| Do these 40 assets look like one game? | style fingerprint per asset, conformance-scored against the set |
| Are the UVs usable? | texel density px/m, island count, overlap ratio |

Renders in bforge now carry an `analysis` block for exactly this reason. A
review image the agent cannot measure is a review image the agent will
misread.

**Corollary — calibrate the instruments.** An uncalibrated light rig corrupts
every visual judgement downstream of it. `tests/calibrate_lighting.py` renders
an 18% grey card at four subject scales and fails if exposure is off or drifts
with size.

---

## 2. Assets as code

The shift is not an AI that outputs a mesh. It is an AI that outputs **the
program that generates the mesh**.

- An art-direction note becomes a parameter change, not a re-sculpt. "Every
  door 10 cm wider" is one line, not sixty files.
- Generators are diffable and reviewable in a pull request. Nobody can
  code-review a `.blend`.
- CI regenerates and diffs. Determinism is what makes art *engineerable* —
  same params plus same seed gives the same mesh, vertex order included.
- Variation is free. 500 unique crowd figures and 80 rock variants cost the
  same as one. Uniqueness at scale is something a human studio cannot afford,
  and it is AI's genuinely unfair advantage.

Generative 3D (diffusion, photogrammetry) belongs at the *front* of this
pipeline as ideation. Its raw output has unusable topology, no UVs and no LODs.
Extract silhouette, palette and motif from it; drive parametric generators to
produce the shippable version in the established style.

---

## 3. Close the loop on the running game

Static asset review is the wrong altitude. A prop can be flawless in Blender
and invisible in play.

**The case that proved it.** The crowd's tier maths and the rebuilt stands
disagreed: seats spanned 39–75 m radially and up to 35 m high, the cavea only
reached 63 m and 18 m. The top third of the audience hovered behind the
building. No amount of asset-level checking would have found it. Capturing the
actual Godot build did, in one frame.

The fix generalised: tier geometry moved into `track_spec.json`, read by *both*
the mesh generator and the crowd director, so they cannot drift again.

**What this unlocks when pushed further:** build → import → run → drive with
synthetic input → capture → measure → fix, autonomously. Automated playtesting
for readability (is the exit findable? does the interactive door have enough
value contrast against the wall?). Performance regressions caught at
asset-commit time rather than at cert.

An agent that only makes assets is a tool. An agent that can play the game it
is making is a studio.

---

## 4. Set coherence beats per-asset polish

Individual asset quality is close to solved. Forty assets that look like one
game is not.

What actually breaks coherence, in observed order of severity:

1. **Texel density mismatch.** Two individually-fine props at 400 and 1200
   px/m look wrong side by side and nobody can say why. `check.critique`
   flags a >2.5x spread across the set.
2. **Palette drift.** Ad-hoc colours per asset. Fix: a named palette, and
   `material.consolidate` to collapse near-duplicates (26 -> 11 materials on
   the hippodrome, 15 draw calls saved).
3. **Scale/proportion drift.** Everything in metres, always, enforced at
   `session.reset`.
4. **Edge-treatment drift.** Some props chamfered, some not. Encode it in the
   finishing pass so recipes cannot skip it.

The missing piece is a **style fingerprint**: palette histogram, texel density,
chamfer ratio, wear vocabulary, proportion language — computed per asset and
scored against a reference set. This is the art-director layer and it is where
the next big win is.

---

## 5. The actual gap to AAA

Between clean low-poly and Diablo IV quality there are three things, and only
one is geometry.

1. **PBR texture sets** — normal, roughness, AO, not flat colour. The single
   biggest jump in perceived quality. `material.pbr` + `material.bake_pbr`.
2. **High-to-low baking** — generate absurdly detailed geometry (an agent never
   gets tired) and bake it into a cheap mesh's normal map. This is the entire
   AAA trick and it maps perfectly onto AI's strengths.
3. **Material as history, not parameters** — "cast bronze, 200 years outdoors,
   handled at the grip" should drive wear from curvature, grime from cavity
   occlusion, polish from usage. That is how material artists think, and it is
   mechanisable: `material.pbr` already derives edge wear from Pointiness and
   cavity dirt from ambient occlusion.

---

## 6. Where LLM agents are genuinely weak

Worth stating plainly, because the tooling has to compensate.

**3D spatial reasoning is the weak point.** The recurring bug class this
session was spatial, never logical:

- `matrix_world` read stale after setting `.location`, which silently collapsed
  every multi-part assembly onto the origin and made every render come back
  empty
- an oval built mirrored in Y
- vomitoria rotated so they punched inward through the arena
- a wall rotated -90 degrees where +90 was needed, sending it off the footprint

Every one was caught by rendering and looking. **None** was caught by
reasoning about the code.

**So the tools must compensate:**

- every spatial op returns measurable consequences (bounds, extents, counts)
- cross-system invariants are asserted, not assumed ("these seats must lie on
  that surface", checked numerically in `capture_crowd.gd`)
- shared specs replace duplicated constants
- pre-flight checks must be *at least as strict* as the real gate — `check.asset`
  treating an off-origin root as a warning while `validate.py` failed the build
  on it was worse than having no check at all

---

## 7. Build order

1. **Calibrated instruments.** Nothing visual downstream is trustworthy until
   the light rig is verified against a grey card. *(`calibrate_lighting.py`)*
2. **PBR bake set.** The largest single quality jump. *(`material.bake_pbr`)*
3. **High-to-low normal baking.** The AAA bridge.
4. **Style fingerprint and conformance.** The art-director layer.
5. **In-engine capture as a first-class op.** Promote the ad-hoc Godot capture
   into the toolset.
6. **Motion synthesis from morphology.** The horse's gallop was hand-authored;
   gait should derive from limb proportions and speed.

## Operating principle

Build the tools *while* making real art. The use case is the test. Every op in
bforge came from hitting a wall doing actual game work — `build.sweep` from the
racetrack, `session.import` from needing to audit shipped assets, `arch.arcade`
from a Gladiator reference, `check.image` from misdiagnosing a light rig. None
would have come from designing an API up front.

Two axes, both required: **capable** (can it express the thing) and **easy**
(can it be done in a few calls). A 400-line expert-only script means the
capable half shipped and the easy half did not — promote the composition into a
recipe op. That is why `env.amphitheatre` exists.
