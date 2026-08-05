# bforge bench

verdict: **PASS** — 5/5 runs green, all briefs byte-identical across regeneration (12278 triangles total)

| brief | tris | gate | deterministic | structure |
| --- | --- | --- | --- | --- |
| crate from a one-line brief | 428 | pass | ✓ | ok |
| a wolf with a synthesized trot | 1076 | pass | ✓ | ok |
| an armored warden that walks | 4902 | pass | ✓ | ok |
| a whole Age-1 camp in one call | 5684 | pass | ✓ | ok |
| a 2D concept become a solid | 188 | pass | ✓ | ok |

Every brief is forged twice from a reset session and the two GLB exports must hash identically (SHA-256 in report.json) — determinism is a checked property, not a slogan. Wall-clock seconds live in report.json (machine-dependent); this file carries only deterministic outputs and is what CI diffs.

Scope: programmatic op briefs over the persistent daemon — this bench proves the ops, gates, and export; natural-language brief evaluation is the BRIEF->BATTLE track (strategy/FRONTIER.md).

Rerun: `uv run --project tools python tools/bforge/bench.py [runs]` — the numbers are produced by the runner, not by memory.
