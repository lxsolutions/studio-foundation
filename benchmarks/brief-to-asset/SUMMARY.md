# brief-to-asset scorecard

agent: `python3 benchmarks/brief-to-asset/agents/scripted_recipe.py`

verdict: **6/6 briefs passed**

| brief | category | validity | semantics | budget | determinism |
| --- | --- | --- | --- | --- | --- |
| barrel | prop | ✓ | ✓ | ✓ | ✓ |
| camp | environment | ✓ | ✓ | ✓ | ✓ |
| crate | prop | ✓ | ✓ | ✓ | ✓ |
| gladius | weapon | ✓ | ✓ | ✓ | ✓ |
| warden | character | ✓ | ✓ | ✓ | ✓ |
| wolf | creature | ✓ | ✓ | ✓ | ✓ |

Every brief is scored by the harness from the compiled artifact and its
proof, never from the agent's own claims. Determinism is a forced
rebuild that must hash byte-identically.

Rerun: `just briefbench` (reference agent). Times, paths, and hashes
live in scorecard.json (machine-dependent); this file is the diffed
public number.
