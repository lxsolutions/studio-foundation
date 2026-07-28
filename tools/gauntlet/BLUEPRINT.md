# The Gauntlet Blueprint

Reverse-engineered from primary sources on 2026-07-28: the Claude-of-Duty
repository and its published scoring data, Anshu's full prompt dump, the
Shumer method writeup, and the cost/runtime numbers the builders posted
themselves. Where the popular summary of this wave disagrees with the
builders' own receipts, the receipts win and are cited here.

---

## 1. What actually happened, with numbers

### The demo that started it scored 5/10 and never won a single blind comparison

Matt Shumer's `Claude-of-Duty` README publishes its own grading. Eleven
independent critics scored the build against real Call of Duty frames across
four rounds:

| Round | Score (0–10) |
|-------|--------------|
| 1     | 3.59 |
| 2     | 4.14 |
| 3     | **4.05** ← went down |
| 4     | 5.05 |

And the line that matters most, from the same README: in blind A/B, *every
critic in every round picked the real Call of Duty frame*. Most shots were
rated "AMATEUR"; two reached "CLOSE". Measured performance was **28–30 fps
p50 and 14–17 fps p99** on Apple silicon.

The stated success condition of the famous prompt — "don't stop until the
critic prefers ours" — was never met. The 30-second video went viral; the
README did not.

### The other headline builds, in their authors' own words

- **The Long Silence** (Anshu, 24-hour run): *"This took a few steps, not
  one-shot."* and *"Claude did not actually finish the goal. The judge kept
  critiquing and it kept going overnight, then I manually stopped it."*
- **Kart Royale** (Ryan Campbell): *"Still drops some frames."*
- **Homeworld-style RTS** (mikeluan123): **$632.65** for one game — 4.6M
  output tokens, 837M cache reads.
- **Ferrari 458 studio** (shxwat): *"The model is a glTF file"* — an external
  asset, and it is a turntable viewer, not a game.
- **ZEUS / Higgsfield**: generative **video**, labelled "Made with AI". Not a
  playable thing at all.

So of the eleven links in the original brief: several are the same FPS and its
derivatives, one is a car viewer built on a downloaded model, one is AI video,
one is commentary. Two are genuinely impressive interactive builds.

**You are comparing your whole product to other people's best 30 seconds.**

---

## 2. The formula, stated precisely

Everything real in this wave reduces to five moves. The first is the one
people skip.

### Move 1 — A bar the grader can LOOK AT

Not "AAA quality". Not "mind-blowing". A **file on disk**: real frames from
the game you intend to beat. Adjectives cannot be lost to; images can.

### Move 2 — The builder never grades itself

A separate agent, fresh context, no build history, sees two frames labelled
only A and B and must pick one. It is not told which is yours. This is the
single highest-leverage element, and it is the one that produced the honest
3.59→5.05 curve above instead of an agent reporting success.

### Move 3 — An anti-reward-hacking clause

From Anshu's prompt, verbatim and worth stealing exactly:

> *"You cannot alter the judge's prompt to try to relax this condition."*

Without this, a long-running agent eventually notices that editing the judge
is cheaper than satisfying it.

### Move 4 — Everything procedural, for coherence not quality

Zero external assets is not a quality technique — it is a **consistency**
technique. When every surface comes from the same material and lighting
vocabulary, nothing looks pasted in. That coherence is what reads as
"engine-like". Mixed downloaded assets are what read as slop.

### Move 5 — Long runtime, and paying for it

6 to 24 hours. Hundreds of dollars. Loop until improvements stop mattering,
not until round three.

---

## 3. Where the popular advice is wrong

### Wrong: "Fan out sub-agents" is the core trick

The Claude-of-Duty README says the opposite of its own viral prompt:

> *"Sequential single-owner passes beat parallel fan-out decisively."*

Three rounds of six parallel agents moved the score **+0.46**. One sequential
pass with a single owner per coupled concern moved it **+1.00** and cut defects
from **66 → 26**.

The reason is stated plainly: rendering, skybox and indirect lighting are one
coupled system. Parallel agents each "fixed" it and undid each other.

**Rule: parallelise across independent systems, never across a coupled one.**
Audio, input and HUD can run in parallel. Lighting, tonemapping, sky and
post-processing are ONE owner, one pass, sequentially.

### Wrong: "You must use Three.js"

Claude of Duty is Three.js r180 on **WebGL2**, not WebGPU. The Long Silence —
the best-looking of the set — uses a **hand-written WebGL2 renderer with no
Three.js scene graph at all**, borrowing only the ShaderMaterial API.

`three/webgpu` is real and production-ready (r171+, automatic WebGL2 fallback).
But the renderer is not the variable that made these look good.

### Wrong: "They one-shotted it"

None of them did. Every author says so in their own thread.

---

## 4. What nobody in that wave is doing (the actual edge)

These are the gaps this framework closes.

### 4a. Their comparisons are not reproducible

Every capture is at whatever camera gameplay happened to leave. So frame N and
frame N−1 differ for reasons unrelated to the change. "It looks better now" is
unfalsifiable, and a judge grading drifting frames is measuring noise.

**Fix:** `runtime/gauntlet-hooks.js`. The game exposes pause / step / seed /
camera. The harness poses it identically every run. Same shot definition →
same pixels → a diff means something.

### 4b. They screenshot a game running flat out

Measured here: capturing one frame of a live WebGL demo took **19.4 seconds**,
and the next attempt timed out entirely. A loop that can observe its work every
19 seconds is not a loop.

**Fix:** pause at the rAF boundary, then capture. The compositor is free, so
capture drops to ~200 ms.

### 4c. They spend expensive judge rounds on mechanically broken frames

Crushed blacks, blown highlights, a flat histogram, gradient banding, an
untextured flat-shaded surface — all of these are *exactly measurable* and
none need an opinion.

**Fix:** `harness/analyze.mjs` gates the judge. Frames that fail objective
checks get fixed mechanically first. The judge only ever sees frames that are
already clean, so its rounds are spent on taste, which is the only thing it is
actually good for.

### 4d. Nobody checks what hardware the numbers came from

A perf number from a software rasterizer is worse than no number — it looks
real.

**Fix:** every run stamps the actual WebGL/WebGPU adapter and refuses to
present timings quietly when it detects SwiftShader/WARP/llvmpipe.

> This caught a live problem on the first run of this very framework. See
> §6 — it turned out to matter more than everything else here.

### 4e. Single-frame judging misses everything that only breaks in motion

Z-fighting, shadow acne, temporal shimmer and undersampled specular are
invisible in a still and obvious in play.

**Fix:** step one frame with the camera locked and diff. On a correct renderer
that is ~0%. Anything above ~1.5% is a real defect no still-frame judge or
human eyeball will ever catch.

---

## 5. The loop, as engineered

```
  pose ──► capture ──► objective gate ──► [clean?] ──► blind A/B judge
   ▲                       │  no                            │
   │                       ▼                                │ loses
   │              mechanical fix (single owner)              │
   └──────────────────────────────────────────────────────◄─┘
                     largest-gap fix, one owner
```

Stop condition: not "N rounds". Stop when two consecutive rounds produce no
new findings and the judge's win rate stops moving. Log what was dropped —
a silent cap reads as "covered everything" when it wasn't.

---

## 6. The finding that outranks all of the above

While verifying this framework on this machine, the provenance guard reported:

```
WebGL adapter: ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)
WebGPU adapter: no-adapter
```

Confirmed at the hardware level:

```
Name : Microsoft Remote Display Adapter
Name : Microsoft Basic Display Adapter   (VideoProcessor: SeaBIOS VBE(C) 2011)
```

**This box has no GPU.** It is a virtual display over RDP. Consequences:

1. Every browser game built or reviewed here renders on a **CPU rasterizer**.
   That is why capturing one frame of a third-party WebGL demo took 19 seconds.
2. **WebGPU is entirely unavailable** — `navigator.gpu.requestAdapter()`
   returns nothing, under every flag combination, headed and headless, in both
   the automated browser and the interactive one.
3. Therefore any judgement of "this game looks and feels worse than theirs"
   formed on this machine is confounded. Shumer measured 28–30 fps on real
   Apple silicon; the same build here would be single-digit.

### Solved: the gate runs on smeagol

`harness/remote.mjs` now runs the browser on smeagol (Tesla P40 + V100) over one
SSH tunnel while the dev server and loop stay local. Verified end-to-end:
`WebGL adapter: ANGLE (NVIDIA, Vulkan 1.4.312 (NVIDIA Tesla P40))`,
`WebGPU adapter: nvidia`, fps p50 60.

The recipe is in the README. Two parts were non-obvious and both were found by
measuring rather than assuming:

- `VK_ICD_FILENAMES` must pin the NVIDIA ICD, or ANGLE selects **llvmpipe** and
  reports a "Vulkan" device that is software.
- Headless gives real WebGL but **software WebGPU**. Only headed-under-xvfb
  yields a hardware WebGPU adapter. A headless run would have reported a
  working adapter and quietly benchmarked SwiftShader.

### 4f. Absolute quality thresholds are wrong in both directions at once

The first version of the objective gate used fixed constants. Pointed at the
best-looking build in the entire wave — The Long Silence — it reported four
defects on a frame that is genuinely beautiful: `flat-histogram`, `banding`,
`no-surface-detail`, `unstable-pixels`. The frame was a deliberately dark,
moody ship interior. The constants encoded one aesthetic and called every other
one broken.

The same constants were simultaneously far too **lenient**. `no-surface-detail`
fired below edgeEnergy 8; our starter scored 10.45 and sailed through — while
the actual bar measures **28–30 on identical hardware**. The gate was
congratulating us for being 3x short.

So the fix is not better constants. It is: **measure the bar, then judge against
the bar.** `harness/calibrate.mjs` analyses the reference frames and derives the
bands. Measured from four Long Silence frames on a Tesla P40:

| metric | min | p25 | median | max |
|---|---|---|---|---|
| edgeEnergy | 8.19 | 19.74 | **28.38** | 30.38 |
| dynamicRange | 44 | 151 | 195 | 195 |
| occupiedLevels | 243 | 248 | 248 | 248 |
| whitePct | 0 | 0.01 | 0.02 | **0.02** |
| combGaps | 72 | 77 | 136 | 180 |

Two things fall out immediately. They almost never clip a highlight (0.02%
peak). And they have *more* gradient banding than we do (combGaps up to 180 vs
our 27) — so the absolute banding detector was chasing a non-problem.

The calibrated gate then reports the thing that actually matters:

> `hero` **below-bar-surface-detail** — Surface detail 11.81 vs longsilence band
> 8.19–30.38 (median 28.38) — **2.4x short of the bar**.

That is the whole answer to "their graphics are better than mine and I don't get
it", as a number, per shot, with the dimension named.

### 4g. The objective gate is gameable — proven on our own build

Four rounds against the calibrated bar, all measured on a Tesla P40:

| round | change | edgeEnergy | instability | verdict |
|---|---|---|---|---|
| 1 | baseline | 10.45 | 0.03 | FIX (2.4x short) |
| 2 | panel maps, fluting, slabs | **36.27** | 2.08 | REGRESSED |
| 3 | anisotropy + mipmaps | 38.03 | 2.67 | REGRESSED |
| 4 | harness fix (dt=0 static diff) | 38.02 | **0** | JUDGE |

Round 4 passed every objective check and scored *above* the bar's median
(28.38). Then we looked at the frame: the focal sphere had become a **disco
ball**, the columns read as stacked brick instead of fluted stone, and the
ground tiled visibly. The build got **worse** while the metric got **better**.

Sobel edge energy cannot distinguish detail from repetition. Tiling a texture
over everything satisfies it perfectly. That is reward hacking, committed
accidentally, by an agent that was trying to satisfy its own gate.

Two conclusions, and they are the load-bearing ones in this whole document:

1. **Objective gates are necessary and never sufficient.** They exist to stop
   you wasting judge rounds on broken frames, not to tell you the work is good.
   Anything that can be optimised directly will eventually be optimised
   directly, including by you.
2. **Look at the frames. Every round.** Across this entire build, the numbers
   were wrong in four different directions: too strict on dark art direction,
   too lenient on flat shading, fooled by animation into reporting instability,
   and finally satisfied by tiling. Every single one was obvious on sight.

### 4h. Instrument bugs masquerade as content bugs

Rounds 2 and 3 were both flagged REGRESSED for rising "pixel instability". The
cause was not the scene. The static-camera check advanced simulation time by one
frame, so a rotating *textured* prop legitimately changed pixels — whereas the
earlier rotating *untextured* sphere had not, because a spinning uniform sphere
renders identically. Re-rendering at dt=0 instead took instability to exactly
**0**.

Two rounds were spent chasing a defect that lived in the measuring instrument.
Before believing a regression, check whether the thing that changed was the
build or the ruler.

### The sting in the tail

Running the identical build and shot set on both machines:

| metric | software | Tesla P40 |
|---|---|---|
| fps p50 | 13.3 | **60** |
| `edgeEnergy` (hero) | 6.2 | **11.81** |
| findings | 4 × `no-surface-detail` | **0** |

The software path did not only make it slow. It **degraded the image enough to
change the objective measurements**, manufacturing four defects that do not
exist on real hardware. Three rounds of "fixing" those would have been three
rounds spent chasing an artifact of the measuring instrument.

That is the deepest lesson available from this whole exercise, and it is one no
one in the viral wave is checking: **validate the instrument before trusting
the metric.**
