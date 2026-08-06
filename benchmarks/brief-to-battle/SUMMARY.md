# brief-to-battle scorecard

agent: `python3 benchmarks/brief-to-battle/agents/scripted_world.py`

verdict: **1/1 briefs passed**

| brief | validity | semantics | gameplay | determinism |
| --- | --- | --- | --- | --- |
| fortress_battle | ✓ | ✓ | ✓ | ✓ |

The world is compiled with proof (entity proofs + scenario binding),
the scenario runs deterministically, and outcomes are scored against
the brief's expected navigation — never against the agent's claims.

Rerun: `just battlebench` (reference agent). Times, paths, and hashes
live in scorecard.json (machine-dependent); this file is the diffed
public number.
