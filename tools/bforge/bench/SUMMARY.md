# bforge bench

verdict: **PASS** — 5/5 runs green (mean 0.3s per brief, 12610 triangles total)

| brief | tris | seconds | gate | structure |
| --- | --- | --- | --- | --- |
| crate from a one-line brief | 444 | 0.1 | pass | ok |
| a wolf with a synthesized trot | 1036 | 0.2 | pass | ok |
| an armored warden that walks | 5146 | 0.3 | pass | ok |
| a whole Age-1 camp in one call | 5796 | 0.5 | pass | ok |
| a 2D concept become a solid | 188 | 0.2 | pass | ok |

Rerun: `uv run --project tools python tools/bforge/bench.py [runs]` — the numbers are produced by the runner, not by memory.
