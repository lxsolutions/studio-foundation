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
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RULES_REL = Path("docs") / "claims.toml"
# Remote surfaces (the GitHub description) need the network. A fetched surface
# that disagrees always fails; a surface that could not be fetched is a notice,
# never a false red on a flaky link — unless CLAIMS_REQUIRE_REMOTE=1, which
# makes the skip itself a failure (set it, with GITHUB_TOKEN, when the policy
# job should insist).
REQUIRE_REMOTE = bool(os.environ.get("CLAIMS_REQUIRE_REMOTE"))


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


def github_description(repo_slug: str) -> str:
    """The repository description as GitHub serves it (public repos need no
    token; GITHUB_TOKEN is used when present so hosted runs are not
    rate-limited)."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo_slug}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "studio-foundation-check-claims",
        },
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response).get("description") or ""


def _check_text(label: str, text: str, rule: dict, derived: dict, problems: list[str]) -> None:
    """Every pattern must occur; every number it captures must equal the key."""
    key = rule["key"]
    if key not in derived:
        problems.append(f"claims.toml: unknown derived key {key!r}")
        return
    expected = derived[key]
    group = int(rule.get("group", 1))
    for pattern in rule["patterns"]:
        matches = list(re.finditer(pattern, text))
        if not matches:
            problems.append(
                f"{label}: pattern not found: {pattern!r} "
                f"(expected {key}={expected} to be stated this way)"
            )
            continue
        for match in matches:
            found = int(match.group(group))
            if found != expected:
                problems.append(
                    f"{label}: claims {found} but {key} is {expected} (matched {match.group(0)!r})"
                )


def check(repo: Path = REPO, require_remote: bool = REQUIRE_REMOTE) -> list[str]:
    """Return a list of human-readable violations; empty means consistent."""
    rules = tomllib.loads((repo / RULES_REL).read_text(encoding="utf-8"))
    derived = derive_values(repo)
    problems: list[str] = []

    for surface in rules.get("surface", []):
        path = repo / surface["file"]
        if not path.is_file():
            problems.append(f"{surface['file']}: missing surface file")
            continue
        _check_text(surface["file"], path.read_text(encoding="utf-8"), surface, derived, problems)

    for remote in rules.get("remote", []):
        label = f"{remote['kind']} ({remote['repo']})"
        if remote["kind"] != "github_description":
            problems.append(f"claims.toml: unknown remote surface kind {remote['kind']!r}")
            continue
        try:
            text = github_description(remote["repo"])
        except (urllib.error.URLError, OSError, ValueError) as exc:
            if require_remote:
                problems.append(f"{label}: could not fetch the description ({exc})")
            else:
                print(
                    f"claim check notice: {label} not fetched ({exc}); set CLAIMS_REQUIRE_REMOTE=1 to fail instead"
                )
            continue
        _check_text(label, text, remote, derived, problems)

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
