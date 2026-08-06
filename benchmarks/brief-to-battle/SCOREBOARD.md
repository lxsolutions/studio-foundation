# brief-to-battle scoreboard

Model agents against the frozen battle brief, scored from the compiled world
and the deterministic run. The reference agent holds the 2/2 control baseline
(`SUMMARY.md`, CI-diffed). Model runs are dated evidence, not CI-diffed.

## 2026-08-06 — Claude Code (headless `claude -p`; contracts precomputed by the wrapper)

**1/1 — PASS** (scorecard: `SCOREBOARD-2026-08-06-claude-code.json`)

The model authored `world.json` (two gate instances, expected navigation) and
`battle.json` (initial state + event stream) for the frozen fortress battle.
The harness then proved, from artifacts and kernels only:

- the world document validated and both entity proofs compiled;
- the world proof's contract checks all passed;
- the deterministic run ended with the main gate not blocking (destroyed/open)
  and the side gate still blocking — exactly the brief;
- the same replay run twice produced the same final state hash.

Wall time 124.6s, one attempt. That is the complete BRIEF→BATTLE loop on an
external model: brief → world → compiled entities → deterministic battle →
machine-checked outcome.

Codex (`codex exec`) was unavailable for a second run: the account hit its
usage limit (retry 2026-08-08). The codex_cli.py wrapper is committed and
ready; rerun then.
