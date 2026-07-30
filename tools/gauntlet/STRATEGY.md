# Strategy: how to actually make AAA-looking games with Opus 5

Everything here is downstream of measurements taken in this repo, on a Tesla
P40, against a real reference. Where a claim has a number, the number is real.
Where it does not, it is marked as judgement.

---

## The one thing to understand first

**AAA visual quality is an ASSET problem, not a RENDERING problem.**

A Call of Duty frame looks like that because thousands of individually
authored, uniquely-UV'd, individually-textured assets went into it. The
renderer is good, but the renderer is not the moat. The pipeline is.

This is not theory. It is the measured shape of our own failure:

| round | change | edgeEnergy | what actually happened |
|---|---|---|---|
| 1 | baseline | 10.45 | 2.4x short of the bar |
| 2–3 | tile one detail texture over everything | 36–38 | metric passed, **frame got worse** |
| 4 | (harness fix) | 38.02 | clean gate, and the sphere is a **disco ball** |

We bought the metric with repetition. Sobel cannot tell detail from tiling. The
reference hits 28 honestly, via `greeble.js` — a *kit system* that generates
unique structure per object and welds by material, so "a hundred pieces cost
six draws". That is the indie approximation of a AAA asset pipeline, and it is
the entire difference.

**Corollary: you cannot out-asset Call of Duty.** Do not try. See §1.

---

## 1. Choose a bar you can win against

This is the highest-leverage decision in the whole endeavour, and it is made
before a line of code.

Photoreal military realism is a pure asset-density war. Matt Shumer aimed
there and published the result himself: **5.05/10 across eleven critics, and
in blind A/B every critic in every round picked the real Call of Duty frame.**
Zero wins. That is what aiming at an unwinnable bar costs.

Aim instead where **art direction substitutes for asset budget**:

| bar | why it is winnable |
|---|---|
| Journey / Sable | flat-ish shading, huge silhouettes, the grade does the work |
| Return of the Obra Dinn | 1-bit dither — literally cheaper the more stylised it gets |
| Hyper Light Drifter | deliberate palette, zero material realism required |
| Outer Wilds | scale and mood, not surface fidelity |
| The Long Silence | dark, greebled sci-fi — measured, matchable, and it is a web game |

You have an art direction nobody in that wave has: the Hellenic futurism of
Riftline. Build your own thing against a stylised bar. Every advantage you own
applies; none of Activision's do.

---

## 2. Industrialise assets — this is your actual moat

Nobody in the viral wave has a real asset pipeline. Anshu used the community
Blender MCP (GUI-dependent, hand-taught over an evening, then dumped to a
skill). **You have bforge**: headless, deterministic, 106 ops, with
`render.contact_sheet` → look → `check.critique` → `export.asset` already
codified as an ADR.

That is a durable, compounding advantage and it is currently sitting unused in
this loop. Priorities:

1. **A kit system before any hero asset.** One parametric kit that emits unique
   pieces beats fifty bespoke models. This is what `greeble.js` is, and it is
   why one file surfaces the player hull, every freighter, every station and
   every derelict in the reference.
2. **Unique detail per instance, never one tiling map.** Vary UV scale, rotate,
   offset, and mix two or three decorrelated maps. Repetition reads as cheap
   and *scores as detail*, which is the worst combination possible.
3. **bforge for hero pieces**, procedural kit for everything else.
4. **Bake, do not compute.** The reference bakes each world once into a cubemap
   holding albedo + height. Runtime cost is a lookup.

---

## 3. Coherence beats fidelity

"Zero external assets" is not purity, and it is not even mainly about
licensing. It is that **one material and lighting vocabulary makes everything
belong to the same world.** Mixed downloaded assets are exactly what reads as
AI slop — mismatched scale, mismatched grade, mismatched wear.

Note the honesty gap here: two of the celebrated builds quietly use external
models anyway (shxwat's Ferrari is a glTF; Claude-for-speed ships "vehicle
GLBs"). Coherence is the reason to go procedural, and it survives whether or
not anyone else keeps the rule.

---

## 4. The loop is the engine — and it must not be gameable

```
pose → capture (real GPU) → objective gate → blind sealed judge → fix largest gap → repeat
```

Four properties, each of which we learned the hard way:

- **The bar is a file, not an adjective.** "AAA quality" cannot be lost to.
- **Thresholds come from the bar, not from constants.** Fixed constants were
  wrong in *both* directions at once: they flagged four defects on the
  reference's (beautiful) dark title screen, and passed our build at 10.45
  when the bar is 28.4.
- **The builder never grades itself, and cannot edit the grader.** Steal
  Anshu's clause verbatim: *"You cannot alter the judge's prompt to try to
  relax this condition."*
- **Look at the frames. Every round.** Across this build the numbers were wrong
  four separate ways — too strict on dark art, too lenient on flat shading,
  fooled by animation, then satisfied by tiling. All four were obvious on sight
  and invisible in the report.

---

## 5. Iteration velocity IS quality

Output quality is a function of **completed rounds**. So the budget to protect
is rounds-per-hour, and everything that costs a round is expensive.

- **TypeScript, strict, preflight-gated.** A capture round costs ~4 minutes on
  the remote GPU; `tsc --noEmit` costs ~2 seconds. Never spend the former to
  discover the latter.
- **Deterministic posing.** Pause + seed + named camera. Without it, run N and
  N−1 differ for reasons unrelated to your change and no comparison means
  anything. It also takes capture from ~19 s to ~200 ms.
- **Measure on real hardware.** Software rendering does not just make it slow —
  it *changes the objective numbers* and invents defects that do not exist.
- **This is why not C++.** Unreal and CoD use it because their iteration cost
  amortises over 300-person teams and four-year schedules. Ours does not.

---

## 6. Ownership discipline

From Shumer's own README, contradicting his own viral prompt: **sequential
single-owner passes beat parallel fan-out decisively** — +1.00 versus +0.46,
defects 66 → 26.

- **ONE owner, sequential:** lighting + sky + indirect + tonemap + post. One
  coupled system. Parallel agents each "fix" it and undo each other.
- **ONE owner, sequential:** controller + camera + input feel.
- **Parallel is fine:** audio, HUD, world content, enemy behaviour, tooling.

---

## 7. Effort order, by measured leverage

1. **Asset detail density** — the measured gap was 2.4–3.6x. Nothing else is close.
2. **Light transport** — indirect bounce, contact shadows, AO, falloff.
3. **Material response** — roughness *variation* above all.
4. **Grade** — highlight roll-off, black point, dither before quantising.
5. **Motion integrity** — z-fighting, shadow acne, temporal noise.

---

## 8. The ratchet

Once you beat a bar, **the bar becomes your own previous best**. Recalibrate
against your last passing build and the loop compounds instead of plateauing.
This is the part nobody in the wave does: they ship one demo and stop.

And the kit from §2 is reusable across every game you own. Eighteen venues, one
Hellenic-futurism kit. That is the multiplier that turns a one-off demo into a
studio.

---

## What this is not

It is not a promise of one-shot AAA. Nobody in that wave achieved it, and every
one of them says so in their own thread: *"This took a few steps, not
one-shot."* / *"Claude did not actually finish the goal... I manually stopped
it."* / *"Still drops some frames."* / $632.65 for one game.

What is real: a disciplined loop, an inspectable bar, an asset pipeline, and
hours of runtime produce something markedly better than a prompt does. The
demos are real work. The 30-second videos are the best 30 seconds.
