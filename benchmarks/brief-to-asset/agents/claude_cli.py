#!/usr/bin/env python3
"""brief-to-asset agent wrapper for the claude CLI (headless).

Receives a workspace dir containing brief.json; prompts the model with the
brief and the compact bforge op catalog; the model writes recipe.json. The
harness scores the artifact, never the transcript.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "bforge"))
from bforge import schema as schema_mod  # noqa: E402

TIMEOUT_S = 600

PROMPT = """You are an agent in the brief-to-asset benchmark. Produce a bforge Recipe IR
document that builds the briefed asset. You may ONLY use the ops listed below,
with exactly these parameter names. Output is judged by compiling the recipe
and measuring the artifact — not by your prose.

RECIPE FORMAT (write exactly this shape to {workspace}/recipe.json):

{{
  "recipe_version": 1,
  "asset_id": "{asset_id}",
  "brief": "<the brief text>",
  "steps": [
    {{ "op": "<op name>", "args": {{ "<param>": <value> }} }}
  ],
  "requirements": {requirements},
  "export": {{ "engine": "godot", "category": "{category}" }}
}}

RULES:
- Write the file {workspace}/recipe.json with valid JSON only. No prose file, no commentary file.
- Use only ops and parameters from the catalog below, with EXACTLY the listed
  parameter names and types. Every op that creates or modifies an object takes
  `name` (the object's snake_case id); later ops reference that same name.
- Sizes are metres. Use a seed (integer) on generative ops for determinism.
- Stay inside the requirements (triangle/material budgets; collision if required).
- session.reset is NOT needed, and do NOT add export.asset/check.asset steps —
  the harness finishes, gates, and exports for you.
- FINISHING CONTRACT: procedural materials (material.pbr, material.detail_normal,
  noise/AO/bump node graphs) CANNOT be expressed by glTF. If you use them, you
  MUST add a material.bake step for that object afterwards, or the export gate
  will reject the asset. Simple preset materials need no bake.
- Do not modify any other file.

BRIEF: {brief_text}

REQUIREMENTS: {requirements}

CATEGORY: {category}

AVAILABLE OPS (name — parameters with types and defaults — summary):
{catalog}
"""


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    brief = json.loads((workspace / "brief.json").read_text())
    catalog = schema_mod.load_catalog()
    catalog_text = "\n".join(
        "- "
        + op["name"]
        + " — "
        + ", ".join(
            f"{k}: {v.get('type', 'any')}"
            + ("=" + json.dumps(v["default"]) if "default" in v else " (required)")
            for k, v in op["inputSchema"].get("properties", {}).items()
        )
        + " — "
        + op["summary"][:80]
        for op in catalog
    )
    req = {
        k: v for k, v in brief.get("requirements", {}).items() if k != "payload_kb_max"
    }
    prompt = PROMPT.format(
        workspace=workspace,
        asset_id=brief["id"],
        brief_text=brief["text"],
        requirements=json.dumps(req),
        category=brief["category"] if brief["category"] != "creature" else "character",
        catalog=catalog_text,
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
    if not (workspace / "recipe.json").is_file():
        print("model produced no recipe.json", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
