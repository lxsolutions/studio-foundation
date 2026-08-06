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

## 2026-08-06 — RETRACTION: both hold_the_gate failures below were our bug

**The two `hold_the_gate` FAIL entries in this file are withdrawn.** They
measured a defect in the harness, not in the model.

`agents/claude_battle.py` ended its prompt with a hardcoded goal sentence:

> Your scenario must end with: the main gate destroyed or open (not blocking),
> the side gate intact and closed (blocking).

That is the `fortress_battle` objective, and `hold_the_gate` is its exact
inverse. The wrapper was instructing the model to open the gate the brief said
to defend, and the harness then scored the model's obedience as a tactical
reasoning failure. The "systematic, not variance" conclusion was really a
constant: both runs matched the injected instruction, which is why they looked
so consistent.

With the goal sentence derived from each brief's `expect_navigation`
(`goal_clause()`), the same brief and the same model **pass on the first
attempt** (66.5s, scorecard
`SCOREBOARD-2026-08-06-claude-code-hold-the-gate-corrected.json`): the model
locks and closes the main gate at tick 0, unlocks and opens the side gate, and
holds through a 12-per-tick attack/repair exchange for the full 20 ticks. The
tactics were never the problem.

`tests/test_battlebench.py::WrapperIsBriefNeutral` now fails if the prompt
template states any outcome, or if a derived goal contradicts a brief. It fails
against the old wrapper and passes against the fix.

The lesson is the uncomfortable one for a project whose thesis is that AI
output must be proven: **the harness needs the same adversarial scrutiny as the
model.** A published failure that is actually your own misfiring instrument is
worse than no benchmark, because it spends credibility to buy a false finding.
The two entries below are kept, struck through, rather than deleted — retracted
evidence should stay auditable.

## ~~2026-08-06 — Claude Code, hold_the_gate (inverted defense brief)~~ RETRACTED

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

## ~~2026-08-06 — Claude Code, hold_the_gate, attempt 2 (variance check)~~ RETRACTED

**0/1 — FAIL, same systematic gap** (scorecard:
`SCOREBOARD-2026-08-06-claude-code-hold-the-gate-attempt-2.json`)

Not variance. On the second run the model correctly unlocked and opened the
side gate — then closed and locked it again (ticks 8 and 13), and once more
unlocked and opened the MAIN gate at ticks 14–15. Two runs, two different
paths, same inversion: the gate that must hold ends open, the gate that must
open ends closed. A systematic reasoning gap on inverted/defense briefs, not
luck.

## 2026-08-06 — Claude Code, hold_the_gate, corrected harness

**1/1 — PASS** (scorecard:
`SCOREBOARD-2026-08-06-claude-code-hold-the-gate-corrected.json`)

First attempt, 66.5s, all four dimensions green. The model's scenario:

    [0, gate_main, lock]      [0, gate_side, open]
    [0, gate_main, close]     [0, gate_side, unlock]
    [2..20, gate_main, attack 12 / repair 12 alternating]

It locks the defended gate so stray `open` events are absorbed, opens the
escort route, and sustains the repair cadence the brief permits for the full
20 ticks. Main gate ends intact and blocking; side gate ends open. That is the
brief, exactly.
