#!/usr/bin/env python3
"""Capture and compare browser-rendered Godot visual-regression images."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402


class VisualError(RuntimeError):
    """An actionable visual-regression failure."""


def project_dir(game: str, root: Path | None = None) -> Path:
    root = (root or senv.repo_root()).resolve()
    game_path = (root / game).resolve()
    if not game_path.is_relative_to(root):
        raise VisualError(f"game must stay inside the repository: {game}")
    project = game_path / "project" if (game_path / "project").is_dir() else game_path
    if not (project / "project.godot").is_file():
        raise VisualError(f"no project.godot under {game_path}")
    return project


def artifact_paths(project: Path, preset: str, root: Path | None = None) -> tuple[Path, Path]:
    root = (root or senv.repo_root()).resolve()
    relative = project.resolve().relative_to(root)
    label = "__".join(relative.parts[:-1] if relative.name == "project" else relative.parts)
    baseline = project / "captures" / f"visual-{preset}-baseline.png"
    candidate = root / "build" / "visual" / label / f"visual-{preset}-candidate.png"
    return baseline, candidate


def capture(game: str, preset: str, output: Path, wait: int, size: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(senv.repo_root() / "tools" / "screenshots" / "capture_web.py"),
        "--game",
        game,
        "--preset",
        preset,
        "--out",
        str(output.resolve()),
        "--wait",
        str(wait),
        "--size",
        size,
    ]
    proc = subprocess.run(command, cwd=senv.repo_root(), check=False)
    if proc.returncode != 0 or not output.is_file():
        raise VisualError(f"browser capture failed with exit code {proc.returncode}")


def compare(baseline: Path, candidate: Path, max_diff_ratio: float, tolerance: int) -> int:
    command = [
        sys.executable,
        str(senv.repo_root() / "tools" / "screenshots" / "compare_screenshots.py"),
        str(baseline),
        str(candidate),
        "--max-diff-ratio",
        str(max_diff_ratio),
        "--channel-tolerance",
        str(tolerance),
    ]
    return subprocess.run(command, cwd=senv.repo_root(), check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["baseline", "capture", "compare"])
    parser.add_argument("--game", default="templates/godot-game")
    parser.add_argument("--preset", default="web-webgl", choices=["web-webgl", "web-webgpu"])
    parser.add_argument("--wait", type=int, default=6000)
    parser.add_argument("--size", default="1280x720")
    parser.add_argument("--max-diff-ratio", type=float, default=0.001)
    parser.add_argument("--channel-tolerance", type=int, default=8)
    args = parser.parse_args(argv)
    if args.wait < 0 or not 0 <= args.max_diff_ratio <= 1 or not 0 <= args.channel_tolerance <= 255:
        parser.error("wait and tolerances must be within their valid ranges")
    project = project_dir(args.game)
    baseline, candidate = artifact_paths(project, args.preset)
    try:
        capture(args.game, args.preset, candidate, args.wait, args.size)
        if args.action == "capture":
            print(f"visual candidate: {candidate}")
            return 0
        if args.action == "baseline":
            baseline.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, baseline)
            print(f"visual baseline updated: {baseline}")
            return 0
        if not baseline.is_file():
            raise VisualError(f"baseline missing: {baseline} (run visual-baseline first)")
        return compare(baseline, candidate, args.max_diff_ratio, args.channel_tolerance)
    except VisualError as exc:
        print(f"visual regression failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
