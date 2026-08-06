#!/usr/bin/env python3
"""brief-to-battle — the world-level half of the frozen benchmark (M4).

brief-to-asset proves an agent can make things. brief-to-battle proves it
can make things WORK: entities that compile with proof, a scenario that runs
deterministically, and outcomes that match the brief.

An agent receives a workspace dir containing brief.json and the available
World IR entity documents. It answers with:

  world.json    a World IR world document (entities + scenario reference)
  battle.json   the scenario replay (sim_replay v0.1, contracts inline)

The harness then scores, from artifacts and kernels — never from the agent's
own claims:

  validity      the world document validates and its entities compile
  semantics     the world proof's own checks all pass (parts, hierarchy,
                collision, payload)
  gameplay      the deterministic run's navigation outcomes equal the
                brief's expect_navigation
  determinism   the same replay run twice yields the same final state hash
  efficiency    wall time and attempts

Usage:
  python benchmarks/brief-to-battle/bench.py --agent "python3 .../agents/scripted_world.py"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "tools" / "worldc"))
sys.path.insert(0, str(REPO / "tools" / "sim"))
sys.path.insert(0, str(REPO / "tools" / "bforge"))

import kernel  # noqa: E402
import worldc  # noqa: E402
from bforge.client import Forge  # noqa: E402

DIMENSIONS = ("validity", "semantics", "gameplay", "determinism")


def score_brief(brief: dict, agent_cmd: str, work_root: Path) -> dict:
    workspace = work_root / brief["id"]
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "brief.json").write_text(json.dumps(brief, indent=2) + "\n")
    # the brief's available entity docs are staged into the workspace
    for _name, rel in brief.get("available_entities", {}).items():
        src = REPO / rel
        if src.is_file():
            (workspace / src.name).write_bytes(src.read_bytes())

    started = time.time()
    proc = subprocess.run(
        [*agent_cmd.split(), str(workspace)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    agent_seconds = round(time.time() - started, 3)

    result: dict = {
        "id": brief["id"],
        "category": brief["category"],
        "agent_seconds": agent_seconds,
        "agent_exit": proc.returncode,
        "attempts": 1,
        "dimensions": {},
    }
    metrics_path = workspace / "metrics.json"
    if metrics_path.is_file():
        result["attempts"] = int(
            json.loads(metrics_path.read_text()).get("attempts", 1)
        )

    world_path = workspace / "world.json"
    battle_path = workspace / "battle.json"
    if proc.returncode != 0 or not world_path.is_file() or not battle_path.is_file():
        result["dimensions"] = {
            d: {"pass": False, "detail": "agent produced no world/scenario"}
            for d in DIMENSIONS
        }
        result["pass"] = False
        return result

    # ---- validity: world validates and compiles end to end
    json.loads(world_path.read_text())  # surface malformed JSON before validating
    try:
        worldc.load_world(world_path)
        validity = True
        detail = "world document validates"
    except worldc.WorldIRError as exc:
        validity = False
        detail = str(exc)[:200]
    result["dimensions"]["validity"] = {"pass": validity, "detail": detail}
    if not validity:
        for d in ("semantics", "gameplay", "determinism"):
            result["dimensions"][d] = {"pass": False, "detail": "world invalid"}
        result["pass"] = False
        return result

    # ---- semantics: the world proof's own contract checks
    try:
        proof = worldc.compile_world(
            world_path, cache_dir=workspace / "cache", forge_factory=Forge
        )
        result["world_cache_key"] = proof["world_cache_key"]
        result["world_proof"] = str(Path(proof["cache"]["dir"]) / "world_proof.json")
        semantics = proof["status"] == "pass"
        detail = (
            "all world-proof checks pass"
            if semantics
            else str([c for c in proof["checks"] if not c["ok"]])[:200]
        )
    except (worldc.WorldIRError, Exception) as exc:  # noqa: BLE001
        proof = None
        semantics = False
        detail = f"{type(exc).__name__}: {exc}"[:200]
    result["dimensions"]["semantics"] = {"pass": semantics, "detail": detail}
    if proof is None:
        for d in ("gameplay", "determinism"):
            result["dimensions"][d] = {
                "pass": False,
                "detail": "world failed to compile",
            }
        result["pass"] = False
        return result

    # ---- gameplay: deterministic outcomes match the brief
    try:
        run = kernel.run_replay(battle_path)
        expected = brief.get("scenario", {}).get("expect_navigation", {})
        actual = run["navigation"]
        mismatches = [
            f"{name}: expected {want}, got {actual.get(name)}"
            for name, want in expected.items()
            if actual.get(name) is not want
        ]
        result["dimensions"]["gameplay"] = {
            "pass": not mismatches,
            "detail": "; ".join(mismatches) or "outcomes match the brief",
        }
    except kernel.SimError as exc:
        run = None
        result["dimensions"]["gameplay"] = {
            "pass": False,
            "detail": f"{exc.code}: {exc}"[:200],
        }

    # ---- determinism: same replay, same final hash, twice
    if run is not None:
        try:
            again = kernel.run_replay(battle_path)
            same = again["state_hash"] == run["state_hash"]
            result["dimensions"]["determinism"] = {
                "pass": same,
                "detail": "identical final state hash"
                if same
                else "hash drift between runs",
            }
            result["state_hash"] = run["state_hash"]
        except kernel.SimError as exc:
            result["dimensions"]["determinism"] = {
                "pass": False,
                "detail": str(exc)[:200],
            }
    else:
        result["dimensions"]["determinism"] = {"pass": False, "detail": "no run"}

    result["pass"] = all(result["dimensions"][d]["pass"] for d in DIMENSIONS)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    parser.add_argument("--agent", required=True)
    parser.add_argument("--brief", default="")
    parser.add_argument("--out", default="")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="also rewrite SUMMARY.md (only the reference baseline is CI-diffed)",
    )
    parser.add_argument("--work-root", default="")
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
                prefix="battlebench_",
                dir=BENCH / "out" if (BENCH / "out").is_dir() else None,
            )
        )
    )
    work_root.mkdir(parents=True, exist_ok=True)

    results = []
    for brief_path in briefs:
        brief = json.loads(brief_path.read_text())
        print(f"[brief] {brief['id']}: {brief['text']}")
        results.append(score_brief(brief, args.agent, work_root))
        print(
            f"  -> {'PASS' if results[-1]['pass'] else 'FAIL'} ({results[-1]['agent_seconds']}s)"
        )

    passed = sum(1 for r in results if r["pass"])
    scorecard = {
        "benchmark": "brief-to-battle/v0.1",
        "agent": args.agent,
        "briefs": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 4),
        "results": results,
    }
    out = Path(args.out) if args.out else work_root / "scorecard.json"
    out.write_text(json.dumps(scorecard, indent=2) + "\n", encoding="utf-8")

    if not args.summary:
        print(f"[score] {passed}/{len(results)} briefs passed -> {out}")
        return 0 if passed == len(results) else 1

    agent_label = args.agent.replace(str(REPO) + "/", "").replace(str(REPO), ".")
    lines = [
        "# brief-to-battle scorecard",
        "",
        f"agent: `{agent_label}`",
        "",
        f"verdict: **{passed}/{len(results)} briefs passed**",
        "",
        "| brief | validity | semantics | gameplay | determinism |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in results:
        marks = ["✓" if r["dimensions"][d]["pass"] else "✗" for d in DIMENSIONS]
        lines.append(f"| {r['id']} | {' | '.join(marks)} |")
    lines += [
        "",
        "The world is compiled with proof (entity proofs + scenario binding),",
        "the scenario runs deterministically, and outcomes are scored against",
        "the brief's expected navigation — never against the agent's claims.",
        "",
        "Rerun: `just battlebench` (reference agent). Times, paths, and hashes",
        "live in scorecard.json (machine-dependent); this file is the diffed",
        "public number.",
        "",
    ]
    (BENCH / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[score] {passed}/{len(results)} briefs passed -> {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
