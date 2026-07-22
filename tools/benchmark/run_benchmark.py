#!/usr/bin/env python3
"""Run a finite Godot scene benchmark and print normalized JSON metrics."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402

RESULT_PREFIX = "BENCHMARK_RESULT "
ERROR_MARKERS = ("SCRIPT ERROR", "Parse Error", "ERROR: Failed to load script")


class BenchmarkError(RuntimeError):
    """An actionable benchmark failure."""


def project_dir(game: str, root: Path | None = None) -> Path:
    root = (root or senv.repo_root()).resolve()
    game_path = (root / game).resolve()
    if not game_path.is_relative_to(root):
        raise BenchmarkError(f"game must stay inside the repository: {game}")
    project = game_path / "project" if (game_path / "project").is_dir() else game_path
    for relative in ("project.godot", "tests/benchmark_scene.gd"):
        if not (project / relative).is_file():
            raise BenchmarkError(f"missing {relative} under {project}")
    return project


def extract_result(output: str) -> dict[str, object]:
    lines = [line for line in output.splitlines() if line.startswith(RESULT_PREFIX)]
    if not lines:
        raise BenchmarkError("Godot did not print a BENCHMARK_RESULT line")
    try:
        result = json.loads(lines[-1][len(RESULT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"invalid BENCHMARK_RESULT JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise BenchmarkError("BENCHMARK_RESULT must be a JSON object")
    required = {"scene", "warmup_frames", "sample_frames", "duration_ms", "fps"}
    missing = sorted(required - result.keys())
    if missing:
        raise BenchmarkError(f"BENCHMARK_RESULT missing fields: {', '.join(missing)}")
    return result


def run_benchmark(
    game: str, scene: str, warmup: int, frames: int, timeout: int
) -> dict[str, object]:
    project = project_dir(game)
    godot = senv.find_godot()
    if not godot:
        raise BenchmarkError("Godot not found (set GODOT_BIN or run just doctor)")
    sync = senv.run(
        [sys.executable, str(senv.repo_root() / "tools" / "godot" / "sync_addons.py")],
        timeout=60,
    )
    if sync.returncode != 0:
        raise BenchmarkError(f"addon sync failed\n{(sync.stdout + sync.stderr)[-3000:]}")
    import_run = senv.run(
        [godot, "--headless", "--path", str(project), "--import"], cwd=project, timeout=timeout
    )
    import_output = (import_run.stdout or "") + (import_run.stderr or "")
    errors = [line for line in import_output.splitlines() if any(x in line for x in ERROR_MARKERS)]
    if import_run.returncode != 0 or errors:
        raise BenchmarkError("Godot import failed\n" + "\n".join(errors or [import_output[-3000:]]))
    with tempfile.TemporaryDirectory(prefix="studio-benchmark-") as temp_dir:
        engine_file = str(Path(temp_dir) / "godot-benchmark.json")
        args = [
            godot,
            "--headless",
            "--path",
            str(project),
            "--benchmark",
            "--benchmark-file",
            engine_file,
            "--script",
            "res://tests/benchmark_scene.gd",
            "--",
            "--scene",
            scene,
            "--warmup",
            str(warmup),
            "--frames",
            str(frames),
        ]
        proc = senv.run(args, cwd=project, timeout=timeout)
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            raise BenchmarkError(f"Godot benchmark exited {proc.returncode}\n{output[-3000:]}")
        result = extract_result(output)
        engine_path = Path(engine_file)
        if engine_path.is_file():
            try:
                engine_metrics = json.loads(engine_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise BenchmarkError(f"Godot wrote invalid benchmark JSON: {exc}") from exc
            result["engine"] = engine_metrics
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", default="templates/godot-game")
    parser.add_argument("--scene", default="res://scenes/game.tscn")
    parser.add_argument("--warmup", type=int, default=120)
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    if args.warmup < 0 or args.frames < 1 or args.timeout < 1:
        parser.error("warmup must be non-negative; frames and timeout must be positive")
    senv.load_dotenv()
    try:
        result = run_benchmark(args.game, args.scene, args.warmup, args.frames, args.timeout)
    except BenchmarkError as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 1
    print(RESULT_PREFIX + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
