# brief-to-asset scoreboard

Model agents against the frozen brief set, scored by the harness from the
compiled artifacts. The reference agent holds the 6/6 control baseline
(`SUMMARY.md`, regenerated and diffed in CI). Model runs are dated, published
evidence — not CI-diffed, because model output is not deterministic.

## 2026-08-06 — Claude Code (headless `claude -p`, full op schema in prompt)

**3/6 briefs passed** (scorecard: `SCOREBOARD-2026-08-06-claude-code.json`)

| brief | result | failure class |
| --- | --- | --- |
| barrel | ✓ | — |
| crate | ✓ | — |
| wolf | ✓ | — |
| camp | ✗ | assumed object name (`camp` vs the `camp_*` objects env.camp actually makes) |
| gladius | ✗ | budget gate (`check.asset` rejected the build) |
| warden | ✗ | hallucinated enum value (`char.outfit piece="pauldron"` — not in the catalog) |

Earlier prompt iterations, same model, same brief (crate), for the record:

1. Summary-only catalog → schema hallucination (`shape` vs `mode`, missing `name`).
2. Full op schema → a sophisticated recipe that missed the mandatory
   `material.bake` finishing step; the export gate correctly rejected
   procedural nodes glTF cannot express.
3. Prompt hardened with the finishing contract → 3/6 on the full set.

The gates, not the model, decide what passes. That is the point of the
benchmark: API-mismatch and finishing-step failures are measured, named, and
published instead of hidden behind a good-looking screenshot.
