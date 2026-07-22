#!/usr/bin/env python3
"""Generate a disposable game and run its Godot and Rust test suites."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import new_game
from clean import remove_tree

REPO_ROOT = Path(__file__).resolve().parents[2]


def run(command: list[str]) -> int:
    print("[generated-test] " + " ".join(command), flush=True)
    return subprocess.call(command, cwd=REPO_ROOT)


def main() -> int:
    games_root = (REPO_ROOT / "games").resolve()
    games_root.mkdir(parents=True, exist_ok=True)

    reserved = Path(tempfile.mkdtemp(prefix="ci_generated_", dir=games_root))
    game_id = reserved.name
    reserved.rmdir()
    destination = games_root / game_id
    try:
        destination = new_game.generate_game(
            game_id,
            "CI Generated Game",
            repo_root=REPO_ROOT,
            games_root=games_root,
        )
        if destination.resolve().parent != games_root:
            raise RuntimeError(f"generated test escaped games root: {destination}")
        relative = destination.relative_to(REPO_ROOT).as_posix()

        godot_code = run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "godot" / "run_godot.py"),
                "--game",
                relative,
                "--tests",
            ]
        )
        if godot_code != 0:
            return godot_code

        return run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "cargo_env.py"),
                "test",
                "--target-dir",
                str(REPO_ROOT / "services" / "target"),
                "--manifest-path",
                str(destination / "server" / "Cargo.toml"),
            ]
        )
    finally:
        if destination.is_dir() and destination.resolve().parent == games_root:
            remove_tree(destination)


if __name__ == "__main__":
    raise SystemExit(main())
