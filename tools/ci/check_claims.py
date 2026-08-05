#!/usr/bin/env python3
"""Fail CI when the repository's prose disagrees with its artifacts.

Verification is this project's brand; its public numbers have drifted from the
code more than once (op counts, patch counts, release boundaries, a committed
catalog whose schema disagreed with the live registry). This script is the
gate: it derives the true values from the pinned artifacts — the bforge
catalog, the bforge test tree, and the engine lock — and checks the rules in
docs/claims.toml against the prose surfaces that quote them.

Stdlib only, so the hosted policy job can run it with a bare interpreter.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RULES_REL = Path("docs") / "claims.toml"


def _count_bforge_tests(tests_dir: Path) -> tuple[int, int]:
    """(total, blender-backed) test methods.

    A suite counts as Blender-backed when it resolves a Blender binary or
    honors BFORGE_SKIP_LIVE — i.e. it boots (or would boot) the daemon.
    """
    total = backed = 0
    for path in sorted(tests_dir.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        n = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )
        total += n
        if "find_blender" in text or "BFORGE_SKIP_LIVE" in text:
            backed += n
    return total, backed


def derive_values(repo: Path) -> dict[str, int]:
    catalog = json.loads((repo / "tools" / "bforge" / "catalog.json").read_text(encoding="utf-8"))
    ops = catalog["ops"]
    lock = tomllib.loads((repo / "engine" / "engine-lock.toml").read_text(encoding="utf-8"))
    tests_total, tests_backed = _count_bforge_tests(repo / "tools" / "bforge" / "tests")
    return {
        "bforge.ops": len(ops),
        "bforge.namespaces": len({op["name"].split(".")[0] for op in ops}),
        "bforge.tests": tests_total,
        "bforge.tests_blender": tests_backed,
        "engine.patches": len(lock["patches"]["series"]),
    }


def check(repo: Path = REPO) -> list[str]:
    """Return a list of human-readable violations; empty means consistent."""
    rules = tomllib.loads((repo / RULES_REL).read_text(encoding="utf-8"))
    derived = derive_values(repo)
    problems: list[str] = []

    for surface in rules.get("surface", []):
        key = surface["key"]
        if key not in derived:
            problems.append(f"claims.toml: unknown derived key {key!r}")
            continue
        expected = derived[key]
        group = int(surface.get("group", 1))
        path = repo / surface["file"]
        text = path.read_text(encoding="utf-8") if path.is_file() else None
        if text is None:
            problems.append(f"{surface['file']}: missing surface file")
            continue
        for pattern in surface["patterns"]:
            matches = list(re.finditer(pattern, text))
            if not matches:
                problems.append(
                    f"{surface['file']}: pattern not found: {pattern!r} "
                    f"(expected {key}={expected} to be stated this way)"
                )
                continue
            for match in matches:
                found = int(match.group(group))
                if found != expected:
                    problems.append(
                        f"{surface['file']}: claims {found} but {key} is {expected} "
                        f"(matched {match.group(0)!r})"
                    )

    for rule in rules.get("forbidden", []):
        for rel in rule["files"]:
            path = repo / rel
            if not path.is_file():
                problems.append(f"{rel}: missing surface file (forbidden-claim rule)")
                continue
            if rule["phrase"] in path.read_text(encoding="utf-8"):
                problems.append(f"{rel}: forbidden claim {rule['phrase']!r} — {rule['reason']}")

    return problems


def main() -> int:
    problems = check()
    if problems:
        print("claim check FAILED — prose disagrees with the pinned artifacts:")
        for problem in problems:
            print(f"  - {problem}")
        print("rules: docs/claims.toml (fix the prose or regenerate the artifact)")
        return 1
    derived = derive_values(REPO)
    summary = ", ".join(f"{key}={value}" for key, value in sorted(derived.items()))
    print(f"claim check OK ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
