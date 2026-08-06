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

## 2026-08-06 — Claude Code, hold_the_gate (inverted defense brief)

**0/1 — FAIL** (scorecard: `SCOREBOARD-2026-08-06-claude-code-hold-the-gate.json`)

The world document was valid and compiled. The scenario failed the BRIEF's
tactics, not the API: the brief requires holding the main gate (blocking at
the end) while opening the side gate for the escort. The model issued
`unlock` + `open` on the MAIN gate (so it ended open, not blocking) and never
issued `unlock` on the side gate (so its `open` events were absorbed by the
lock — it ended closed and blocking). Exactly the inverted outcome the brief
forbids.

This is the finding the battle half exists for: document-level correctness
does not imply tactical correctness, and only a deterministic outcome check
can tell the difference.

## 2026-08-06 — Claude Code, hold_the_gate, attempt 2 (variance check)

**0/1 — FAIL, same systematic gap** (scorecard:
`SCOREBOARD-2026-08-06-claude-code-hold-the-gate-attempt-2.json`)

Not variance. On the second run the model correctly unlocked and opened the
side gate — then closed and locked it again (ticks 8 and 13), and once more
unlocked and opened the MAIN gate at ticks 14–15. Two runs, two different
paths, same inversion: the gate that must hold ends open, the gate that must
open ends closed. A systematic reasoning gap on inverted/defense briefs, not
luck.
