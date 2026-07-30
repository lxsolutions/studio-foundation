# gauntlet

A measured quality loop for building games with an agent. Reverse-engineered
from the July 2026 wave of "Opus 5 one-shotted this game" demos, then corrected
against those builders' own published data.

- **`BLUEPRINT.md`** — what those people actually did, with their receipts, and
  where the popular summary of it is wrong. Read this first.
- **`PROMPT.md`** — the overnight prompt, ready to paste.
- **`harness/`** — the sensor and the judge.
- **`tools/gauntlet/runtime/gauntlet-hooks.js`** — drop into a game to make it poseable.
- **`references/`** — you supply the bar: real frames from the thing to beat.

## Why this exists

The viral demos are real work, but the method as popularly described has three
holes, and they are the reason a casual attempt produces something that "sucks":

1. The comparison is not reproducible — the camera moves between runs, so no
   change can be shown to have helped.
2. The observation is too expensive — capturing a live WebGL frame measured
   **19.4 s** here, and the next capture timed out. You cannot iterate on that.
3. The judge is spent on frames that are mechanically broken, which is an
   opinion applied to a bug.

This fixes all three, and adds the thing nobody checks: **what hardware the
numbers came from.**

## One round, one command

`just` is the front door; the raw commands below are equivalent.

```bash
just gauntlet-serve
just REFS=tools/gauntlet/references/<bar> REMOTE=smeagol NOTE="what changed" gauntlet-round
```

```bash
node tools/gauntlet/harness/serve.mjs --root . --port 8099 &
node tools/gauntlet/harness/round.mjs --url http://127.0.0.1:8099/templates/three-game/ \
  --shots templates/three-game/shots.json \
  --references tools/gauntlet/references/<bar> --remote smeagol --note "what changed"
```

Verdicts: **VOID** (software renderer, round is meaningless) · **REGRESSED**
(the last change made it worse — revert before building on it) · **FIX**
(objective defects listed) · **JUDGE** (clean; blind deck built).

It appends to `runs/history.json` and prints a metric delta against the previous
round, so a regression is caught the round it happens rather than three rounds
later. That is not hypothetical — it caught one while this framework was being
built (`edgeEnergy` 10.85 → 7.29 after a bad lighting change).

## Manual steps

```bash
# 1. serve whatever you are building
node tools/gauntlet/harness/serve.mjs --root . --port 8099

# 2. measure it (objective, no opinions)
node tools/gauntlet/harness/shotset.mjs --url http://127.0.0.1:8099/tools/gauntlet/fixtures/contract-demo/ \
  --shots tools/gauntlet/fixtures/contract-demo/shots.json --out runs/r001

# 3. build a blind deck against your reference frames
node tools/gauntlet/harness/judge.mjs pair --candidates runs/r001/frames \
  --references tools/gauntlet/references/<bar> --out runs/r001/judge

# 4. hand ONLY runs/r001/judge/deck + JUDGE_BRIEF.md to a fresh sub-agent,
#    collect its JSON verdicts, then:
node tools/gauntlet/harness/judge.mjs reveal --dir runs/r001/judge --answers verdict.json
```

`tools/gauntlet/fixtures/contract-demo/` is a dependency-free scene that implements the full
runtime contract — use it to verify the harness works before trusting it.

## The contract

A game that imports `tools/gauntlet/runtime/gauntlet-hooks.js` and calls
`gauntlet.register({ seed, camera, stats, ready })` becomes **poseable**: the
harness pauses it, seeds it, points the camera, steps a fixed number of frames,
and captures. Same shot definition, same pixels, every run.

Without it the harness still works, but it says so in the report, and those
shots are best-effort rather than reproducible.

## `--geometry-pass`: is the detail modelled, or printed?

`edgeEnergy` measures high-frequency contrast. It cannot tell detail you
**modelled** from detail you **printed on a texture**, and it will happily
report "at the reference bar" for a nearly flat room wearing a busy tiling map.
That happened three rounds running before this existed.

Add `--geometry-pass` and the harness re-renders each shot a second time with
every material swapped for a neutral matte, stepping at `dt = 0` so the
simulation state is byte-identical and *only* the shading differs:

```bash
node tools/gauntlet/harness/shotset.mjs --url ... --shots ... --geometry-pass --out runs/r002
```

The report then carries, per shot, the matte frame's edge energy and what
fraction of the shaded frame's detail survives with the textures off. Measured
on the greebled hold: 40–50%.

Opt in by registering one more hook:

```js
gauntlet.register({
  materials: (mode) => {            // 'beauty' | 'flat'
    world.traverse((o) => { if (o.isMesh) o.material = materialModes[mode]; });
  },
});
```

Games that skip it get `skipped` in the report rather than an invented number.

There is no threshold on this and it does not gate — texture is not cheating,
and a good scene needs both. It is there because a low ratio is the single
strongest signal that a still frame will lose a blind A/B despite passing every
objective check. The matte frames are also worth *opening*: with the shine gone,
they showed a missing ceiling and near-zero panel relief that no metric caught.

## Hardware: measure on smeagol, always

`awesome-o` has **no GPU** — only *Microsoft Remote Display Adapter* and
*Microsoft Basic Display Adapter (SeaBIOS VBE)*. Everything here is
CPU-rasterized and `navigator.gpu` returns no adapter.

So the harness runs the browser on **smeagol** (Tesla P40 + V100) over one SSH
tunnel, while the dev server and the loop stay local:

```bash
node tools/gauntlet/harness/serve.mjs --root . --port 8099 &
node tools/gauntlet/harness/shotset.mjs --remote smeagol \
  --url http://127.0.0.1:8099/templates/three-game/ \
  --shots templates/three-game/shots.json --out runs/r001
```

```
local :8099 --(ssh -R)--> smeagol :8099    game reaches the remote browser
local :9222 <--(ssh -L)-- smeagol :9222    CDP reaches the local harness
```

### The recipe, measured — every part was necessary

| ingredient | why |
|---|---|
| `VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json` | otherwise ANGLE picks the **llvmpipe** ICD and reports a "Vulkan" device that is software |
| `--use-gl=angle --use-angle=vulkan --enable-features=Vulkan` | routes WebGL onto the NVIDIA device |
| **xvfb-run, i.e. HEADED** | headless gives real WebGL but **software WebGPU**. Only headed yields `webgpu=nvidia / pascal` |
| page served over `http://127.0.0.1` | `navigator.gpu` is simply **absent** on `data:` and `file:` origins (not a secure context) |

### Why this is not optional

The same build, same shots, software vs Tesla P40:

| metric | software | Tesla P40 |
|---|---|---|
| fps p50 | 13.3 | **60** |
| `edgeEnergy` (hero) | 6.2 | **11.81** |
| findings | 4 × `no-surface-detail` | **0** |

The software rasterizer did not merely make it slow — it **degraded the image
enough to change the objective measurements**, inventing four defects that do
not exist on real hardware. You cannot tune visual quality on a software
renderer, because even the numbers lie. This is why every report stamps the
adapter.
