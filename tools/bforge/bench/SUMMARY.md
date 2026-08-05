# bforge bench

verdict: **PASS** — 5/5 runs green (12690 triangles total)

| brief | tris | gate | structure |
| --- | --- | --- | --- | --- |
| crate from a one-line brief | 444 | pass | ok |
| a wolf with a synthesized trot | 1076 | pass | ok |
| an armored warden that walks | 5186 | pass | ok |
| a whole Age-1 camp in one call | 5796 | pass | ok |
| a 2D concept become a solid | 188 | pass | ok |

Deterministic outputs only — wall-clock seconds live in report.json (they are machine-dependent); this file is what CI diffs.

Rerun: `uv run --project tools python tools/bforge/bench.py [runs]` — the numbers are produced by the runner, not by memory.
