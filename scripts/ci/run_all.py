#!/usr/bin/env python3
"""Run the repository's local CI stages through the documented just recipes."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PR_RECIPES: tuple[str, ...] = ("test", "lint", "secret-scan")
STAGE_RECIPES: dict[str, tuple[str, ...]] = {
    "pr": PR_RECIPES,
    "nightly": PR_RECIPES + ("test-db", "audit", "attribution"),
}

RecipeRunner = Callable[[str], int]


def run_recipe(recipe: str) -> int:
    """Run one just recipe without a shell and return its exit code."""
    just = shutil.which("just")
    if just is None:
        print("[ci] ERROR: just not found (run: just doctor)", file=sys.stderr)
        return 127
    return subprocess.run([just, recipe], cwd=REPO, check=False).returncode


def run_stage(stage: str, runner: RecipeRunner = run_recipe) -> int:
    """Run a named stage fail-fast, preserving the failing recipe's exit code."""
    recipes = STAGE_RECIPES[stage]
    print(f"[ci] stage={stage} recipes={','.join(recipes)}", flush=True)
    for recipe in recipes:
        print(f"[ci] START {recipe}", flush=True)
        code = runner(recipe)
        if code != 0:
            print(f"[ci] FAIL {recipe} (exit {code})", file=sys.stderr, flush=True)
            return code
        print(f"[ci] PASS {recipe}", flush=True)
    print(f"[ci] PASS stage={stage}", flush=True)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=sorted(STAGE_RECIPES), default="pr")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return run_stage(args.stage)


if __name__ == "__main__":
    sys.exit(main())
