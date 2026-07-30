# references — you supply the bar

This directory is deliberately empty in the repository, and it is the one part of
the loop that cannot be shipped.

## Why nothing is committed here

A reference set is frames captured from the product you intend to beat. Those
frames are someone else's work. Committing them to a public repository would be
redistribution, so the loop ships the *method* and you supply the *bar*.

## Creating a bar

Put 3–8 frames representing the target's real range — not only its best shot —
into `references/<name>/`, then calibrate:

```bash
node tools/gauntlet/harness/calibrate.mjs --references tools/gauntlet/references/<name>
```

That writes `CALIBRATION.json`: per-metric bands (min / p25 / median / max)
derived from the frames. The objective gate then judges against *those numbers*
rather than against constants.

Legitimate sources, roughly in order of preference:

1. **Your own previous best build.** Once you beat a bar, your last passing
   build becomes the bar. This is the ratchet, and it is the only source that
   compounds.
2. **A build you can capture yourself**, e.g. a public web game measured with
   `harness/shotset.mjs --url <url>`. Keep the frames local.
3. **Official press-kit imagery**, where the publisher licenses it for that use.

## Why calibration is not optional

Fixed thresholds were tried first and were wrong in both directions at once:
they flagged four defects on a deliberately dark, well-crafted reference frame,
and simultaneously passed a build measuring 10.5 on a metric where the real bar
was 28.4. A bar you cannot measure is a bar you cannot be shown losing to.

Full reasoning: `../BLUEPRINT.md` §4f.
