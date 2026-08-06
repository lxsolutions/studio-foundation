#!/usr/bin/env python3
"""brief-to-asset — the frozen public benchmark (ADR 0018, M4 first slice).

Several models, one brief set, one compiler, one scorecard. An agent is any
command that receives a brief JSON and a workspace directory and leaves
behind its answer; today that answer is a Recipe IR document. The harness
compiles the recipe through bforge (content-addressed, proof-carrying), then
scores what a marketing page cannot fake:

  validity      the GLB exists, parses, has meshes and materials
  semantics     required nodes/skins/animations/collision are in the binary
  budget        triangles, materials, and payload inside the brief's limits
  determinism   a forced rebuild produces byte-identical GLB
  efficiency    wall time, attempts, and gate failures on the way to a pass

The briefs are frozen. The agent is the variable. The score is computed by
the same gates that ship assets, not by the agent's own opinion.

Usage:
  python benchmarks/brief-to-asset/bench.py --agent "python benchmarks/brief-to-asset/agents/scripted_recipe.py"
  python benchmarks/brief-to-asset/bench.py --agent ... --brief wolf --out scorecard.json
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "tools" / "bforge"))

from bforge import recipe as recipe_mod  # noqa: E402

DIMENSIONS = ("validity", "semantics", "budget", "determinism")


def read_glb_json(path: Path) -> dict:
    data = Path(path).read_bytes()
    if data[:4] != b"glTF":
        raise ValueError("not a GLB")
    json_length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20 : 20 + json_length])


def score_brief(brief: dict, agent_cmd: str, work_root: Path) -> dict:
    """Run one agent against one brief; return the per-dimension result."""
    workspace = work_root / brief["id"]
    workspace.mkdir(parents=True, exist_ok=True)
    started = time.time()
    # agent contract: it receives the workspace dir and writes
    # recipe.json (+ optional metrics.json) into it
    proc = subprocess.run(
        [*agent_cmd.split(), str(workspace)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    agent_seconds = round(time.time() - started, 3)

    # agent contract: it writes recipe.json (+ optional metrics.json) into the workspace
    recipe_path = workspace / "recipe.json"
    result: dict = {
        "id": brief["id"],
        "category": brief["category"],
        "agent_seconds": agent_seconds,
        "attempts": 0,
        "dimensions": {},
    }
    metrics_path = workspace / "metrics.json"
    metrics = json.loads(metrics_path.read_text()) if metrics_path.is_file() else {}
    result["attempts"] = int(metrics.get("attempts", 1))
    result["agent_exit"] = proc.returncode

    if proc.returncode != 0 or not recipe_path.is_file():
        result["dimensions"] = {
            d: {"pass": False, "detail": "agent produced no recipe"} for d in DIMENSIONS
        }
        result["pass"] = False
        return result

    json.loads(recipe_path.read_text())  # surface malformed recipes before cooking
    cache = workspace / "cache"
    cache_a = workspace / "cache-a"

    try:
        proof = recipe_mod.cook(recipe_path, cache_dir=cache)
    except recipe_mod.RecipeError as exc:
        result["dimensions"] = {
            d: {"pass": False, "detail": str(exc)[:200]} for d in DIMENSIONS
        }
        result["pass"] = False
        return result

    result["recipe_hash"] = proof["recipe_hash"]
    result["proof"] = str(Path(proof["cache"]["dir"]) / "proof.json")

    glbs = [a for a in proof["artifacts"] if a["path"].endswith(".glb")]
    glb_path = Path(proof["cache"]["dir"]) / (glbs[0]["path"] if glbs else "")

    # ---- validity
    try:
        gltf = read_glb_json(glb_path)
        validity = bool(gltf.get("meshes")) and bool(gltf.get("materials"))
        detail = f"{len(gltf.get('meshes', []))} meshes, {len(gltf.get('materials', []))} materials"
    except Exception as exc:  # noqa: BLE001 — any parse failure is a validity failure
        gltf, validity, detail = {}, False, f"GLB parse failed: {exc}"
    result["dimensions"]["validity"] = {"pass": validity, "detail": detail}

    # ---- semantics
    failures = []
    semantic = brief.get("semantic", {})
    nodes = {n.get("name", "") for n in gltf.get("nodes", [])}
    for required in semantic.get("nodes", []):
        if required not in nodes:
            failures.append(f"node {required!r} missing")
    if len(gltf.get("skins", [])) < semantic.get("skins_min", 0):
        failures.append("skins below requirement")
    if len(gltf.get("animations", [])) < semantic.get("animations_min", 0):
        failures.append("animations below requirement")
    if len(gltf.get("meshes", [])) < semantic.get("meshes_min", 0):
        failures.append("meshes below requirement")
    if brief.get("requirements", {}).get("require_collision") and not any(
        "-col" in n or "-convcol" in n for n in nodes
    ):
        failures.append("no collision proxy")
    result["dimensions"]["semantics"] = {
        "pass": not failures,
        "detail": "; ".join(failures) or "all required structure present",
    }

    # ---- budget (from the gates' own measurements, not the brief's hopes)
    budget_failures = []
    gates = proof.get("gates", {})
    check = gates.get("check.asset", {})
    if check and not check.get("ok"):
        budget_failures.append("check.asset failed")
    budget = gates.get("gameready.budget", {})
    if budget and not budget.get("within_budget"):
        budget_failures.append("gameready.budget failed")
    payload_cap = brief.get("requirements", {}).get("payload_kb_max")
    if payload_cap and glb_path.stat().st_size > payload_cap * 1024:
        budget_failures.append(
            f"payload {glb_path.stat().st_size // 1024} KB > {payload_cap} KB"
        )
    result["dimensions"]["budget"] = {
        "pass": not budget_failures,
        "detail": "; ".join(budget_failures) or "within budgets",
    }

    # ---- determinism: forced rebuild must hash identically
    try:
        rebuilt = recipe_mod.cook(recipe_path, cache_dir=cache_a)
        glbs_b = [a for a in rebuilt["artifacts"] if a["path"] == glbs[0]["path"]]
        same = glbs_b and glbs_b[0]["sha256"] == glbs[0]["sha256"]
        result["dimensions"]["determinism"] = {
            "pass": bool(same),
            "detail": "byte-identical rebuild" if same else "rebuild hash differs",
        }
    except recipe_mod.RecipeError as exc:
        result["dimensions"]["determinism"] = {"pass": False, "detail": str(exc)[:200]}

    result["pass"] = all(result["dimensions"][d]["pass"] for d in DIMENSIONS)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    parser.add_argument(
        "--agent", required=True, help="agent command; it receives a workspace dir"
    )
    parser.add_argument("--brief", default="", help="run only this brief id")
    parser.add_argument("--out", default="", help="write the scorecard JSON here")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="also rewrite SUMMARY.md (only the reference baseline is CI-diffed)",
    )
    parser.add_argument("--work-root", default="", help="scratch directory for runs")
    args = parser.parse_args(argv)

    briefs = sorted(BENCH.glob("briefs/*.json"))
    if args.brief:
        briefs = [b for b in briefs if b.stem == args.brief]
    if not briefs:
        print("no briefs matched", file=sys.stderr)
        return 2

    work_root = (
        Path(args.work_root)
        if args.work_root
        else Path(
            tempfile.mkdtemp(
                prefix="briefbench_",
                dir=BENCH / "out" if (BENCH / "out").is_dir() else None,
            )
        )
    )
    work_root.mkdir(parents=True, exist_ok=True)

    results = []
    for brief_path in briefs:
        brief = json.loads(brief_path.read_text())
        (work_root / brief["id"]).mkdir(parents=True, exist_ok=True)
        (work_root / brief["id"] / "brief.json").write_text(json.dumps(brief, indent=2))
        print(f"[brief] {brief['id']}: {brief['text']}")
        results.append(score_brief(brief, args.agent, work_root))
        status = "PASS" if results[-1]["pass"] else "FAIL"
        print(f"  -> {status} ({results[-1]['agent_seconds']}s)")

    passed = sum(1 for r in results if r["pass"])
    scorecard = {
        "benchmark": "brief-to-asset/v0.1",
        "agent": args.agent,
        "briefs": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 4),
        "results": results,
    }
    out = Path(args.out) if args.out else work_root / "scorecard.json"
    out.write_text(json.dumps(scorecard, indent=2) + "\n", encoding="utf-8")

    # The committed summary is deterministic-only: no timings, no paths, no
    # hashes — the public pass/fail table CI can diff (scorecard.json keeps
    # the machine-dependent detail). The agent string is normalized so a run
    # from any checkout path diffs clean.
    if not args.summary:
        print(f"[score] {passed}/{len(results)} briefs passed -> {out}")
        return 0 if passed == len(results) else 1

    agent_label = args.agent.replace(str(REPO) + "/", "").replace(str(REPO), ".")
    lines = [
        "# brief-to-asset scorecard",
        "",
        f"agent: `{agent_label}`",
        "",
        f"verdict: **{passed}/{len(results)} briefs passed**",
        "",
        "| brief | category | validity | semantics | budget | determinism |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        marks = ["✓" if r["dimensions"][d]["pass"] else "✗" for d in DIMENSIONS]
        lines.append(f"| {r['id']} | {r['category']} | {' | '.join(marks)} |")
    lines += [
        "",
        "Every brief is scored by the harness from the compiled artifact and its",
        "proof, never from the agent's own claims. Determinism is a forced",
        "rebuild that must hash byte-identically.",
        "",
        "Rerun: `just briefbench` (reference agent). Times, paths, and hashes",
        "live in scorecard.json (machine-dependent); this file is the diffed",
        "public number.",
        "",
    ]
    (BENCH / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[score] {passed}/{len(results)} briefs passed -> {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
