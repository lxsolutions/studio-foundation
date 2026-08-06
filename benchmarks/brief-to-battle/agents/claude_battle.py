#!/usr/bin/env python3
"""brief-to-battle agent wrapper for the claude CLI (headless).

The wrapper does the cryptographic work (compiling + hashing the simulation
contracts — a model cannot); the model does the creative work: the world
document and the event stream. The harness scores the compiled world and the
deterministic outcome.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "worldc"))
sys.path.insert(0, str(REPO / "tools" / "bforge"))

import worldc  # noqa: E402
from bforge import recipe as recipe_mod  # noqa: E402

TIMEOUT_S = 900

PROMPT = """You are an agent in the brief-to-battle benchmark. Author a world and a
deterministic battle scenario. You are judged by compiling the world with
proof and running the scenario through a deterministic kernel — never by
your prose.

THE BRIEF: {brief_text}

EXPECTED OUTCOMES (navigation at scenario end): {expect_navigation}

PART 1 — write {workspace}/world.json in exactly this shape:

{{
  "world_ir": "0.1",
  "world": "fortress",
  "entities": {{
{world_entities}
  }},
  "scenario": "battle.json",
  "expect_navigation": {expect_navigation}
}}

PART 2 — write {workspace}/battle.json in exactly this shape (a deterministic
replay; T is an integer tick, verbs come from the affordance list below):

{{
  "sim_replay": "0.1",
  "seed": 0,
  "ticks": 20,
  "entities": {{
{replay_entities}
  }},
  "initial": {{
{replay_initial}
  }},
  "events": [
    [T, "<entity>", "<verb>", <arg or null>],
    ...your scenario...
  ]
}}

RULES:
- Valid JSON only in both files. No commentary files. Do not modify any other file.
- Copy the contract object and contract_sha256 EXACTLY as given (they are
  precomputed for you — do not alter a single byte).
- The entities in this scenario are: {entity_list}.
- Available verbs: open, close, lock, unlock (no argument); attack, repair
  (nonnegative integer amount).
- A locked gate ignores open/close. At health 0 a gate is destroyed and hangs
  open. openness integrates at 250 milli-units per tick toward its target.
- Use ticks 0..20 only. Your scenario must end with: {goal_line}
"""

# A gate "blocks navigation" when it is intact and shut. The goal sentence is
# derived from the brief's expect_navigation so the wrapper stays brief-neutral
# — a hardcoded goal would tell the model the answer to one brief and the wrong
# answer to every other one.
def render_block(names, line) -> str:
    """Comma-separated JSON object members, one per entity, indented for the
    template. The scenario's entity count comes from the brief, not the
    wrapper — a two-entity assumption would cap the corpus at gate pairs."""
    return ",\n".join(f"    {line(n)}" for n in names)


def goal_clause(name: str, blocks: bool) -> str:
    if blocks:
        return f"{name} intact and closed (blocking)"
    return f"{name} destroyed or open (not blocking)"


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    brief = json.loads((workspace / "brief.json").read_text())
    doc_file = "fortress_gate.json"
    contract = worldc.sim_contract(worldc.load_entity(workspace / doc_file))
    contract_sha = hashlib.sha256(recipe_mod.canonicalize(contract)).hexdigest()

    entities = brief.get("scenario", {}).get("entities", {})
    names = sorted(entities)
    if not names:
        print("brief has no scenario entities", file=sys.stderr)
        return 1

    expect = brief["scenario"]["expect_navigation"]
    missing = [n for n in names if n not in expect]
    if missing:
        print(f"brief lacks expect_navigation for {missing}", file=sys.stderr)
        return 1
    goal_line = ", ".join(goal_clause(n, expect[n]) for n in names)

    prompt = PROMPT.format(
        goal_line=goal_line,
        workspace=workspace,
        brief_text=brief["text"],
        expect_navigation=json.dumps(expect),
        entity_list=", ".join(names),
        world_entities=render_block(
            names, lambda n: f'"{n}": {{ "doc": "{doc_file}" }}'
        ),
        replay_entities=render_block(
            names,
            lambda n: f'"{n}": {{ "contract": {json.dumps(contract)}, '
            f'"contract_sha256": "{contract_sha}" }}',
        ),
        replay_initial=render_block(
            names, lambda n: f'"{n}": {{ "health": 100, "locked": true }}'
        ),
        doc_file=doc_file,
        contract_json=json.dumps(contract),
        contract_sha=contract_sha,
    )
    proc = subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "Write"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
    )
    (workspace / "agent_stdout.txt").write_text(proc.stdout[-8000:])
    (workspace / "agent_stderr.txt").write_text(proc.stderr[-4000:])
    (workspace / "metrics.json").write_text(
        json.dumps({"attempts": 1, "agent_exit": proc.returncode}) + "\n"
    )
    missing = [
        f for f in ("world.json", "battle.json") if not (workspace / f).is_file()
    ]
    if missing:
        print(f"model produced no {missing}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
