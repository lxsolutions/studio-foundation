#!/usr/bin/env python3
"""Run Godot headlessly against a game project: import check and/or test suite.

Usage:
  python tools/godot/run_godot.py --game templates/godot-game --import-only
  python tools/godot/run_godot.py --game games/sandbox --tests

Notes baked in from hard-won debugging:
- Always run --import before scripts (scripts need the .godot import cache).
- Fail the import stage on "SCRIPT ERROR"/"Parse Error" lines even when Godot
  exits 0 — a project that imports with script errors is broken.
- A parse error in a preloaded script can make a scene-based runner hang
  silently; our runner prints a first-line marker and this wrapper enforces a
  hard timeout and dumps captured output on expiry.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402

ERROR_MARKERS = ("SCRIPT ERROR", "Parse Error", "ERROR: Failed to load script")
IGNORED_ERROR_HINTS = (
    # Benign on headless CI machines without audio devices.
    "WASAPI",
    "XAudio2",
)


def project_dir(game: str) -> Path:
    game_path = senv.repo_root() / game
    project = game_path / "project" if (game_path / "project").is_dir() else game_path
    if not (project / "project.godot").is_file():
        raise SystemExit(f"no project.godot under {game_path}")
    return project


def run_godot(
    args: list[str], cwd: Path, timeout: int, *, isolate_user_data: bool = False
) -> tuple[int, str]:
    godot = senv.find_godot()
    if not godot:
        raise SystemExit("Godot not found (set GODOT_BIN in .env or install; see just doctor)")
    # Give every short-lived invocation its own log target. Godot's default
    # user://logs rotation is shared by projects with the same display name and
    # can collide when import and test processes start in the same second.
    with tempfile.TemporaryDirectory(prefix="studio-godot-log-") as log_dir:
        invocation_root = Path(log_dir)
        command = [godot, "--log-file", str(invocation_root / "godot.log"), *args]
        run_env = None
        if isolate_user_data:
            user_root = invocation_root / "user"
            user_root.mkdir()
            run_env = {
                "APPDATA": str(user_root),
                "LOCALAPPDATA": str(user_root),
                "XDG_CONFIG_HOME": str(user_root / "config"),
                "XDG_DATA_HOME": str(user_root / "data"),
            }
        try:
            proc = senv.run(command, timeout=timeout, cwd=cwd, env=run_env)
        except subprocess.TimeoutExpired as exc:
            partial = (exc.stdout or "") + "\n" + (exc.stderr or "")
            print(partial[-4000:], file=sys.stderr)
            raise SystemExit(f"godot timed out after {timeout}s (partial output above)") from exc
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def script_errors(output: str) -> list[str]:
    problems = []
    for line in output.splitlines():
        if any(marker in line for marker in ERROR_MARKERS) and not any(
            hint in line for hint in IGNORED_ERROR_HINTS
        ):
            problems.append(line.strip())
    return problems


def stage_import(project: Path, timeout: int) -> int:
    code, output = run_godot(
        ["--headless", "--path", str(project), "--import"],
        project,
        timeout,
        isolate_user_data=True,
    )
    problems = script_errors(output)
    if problems:
        print("import stage found script errors:", file=sys.stderr)
        for problem in problems[:40]:
            print(f"  {problem}", file=sys.stderr)
        return 1
    if code != 0:
        print(output[-3000:], file=sys.stderr)
        print(f"godot --import exited {code}", file=sys.stderr)
        return code
    print(f"import ok: {project}")
    return 0


def stage_tests(project: Path, timeout: int) -> int:
    code, output = run_godot(
        ["--headless", "--path", str(project), "--script", "res://tests/run_tests.gd"],
        project,
        timeout,
        isolate_user_data=True,
    )
    print(output)
    if "[tests] runner alive" not in output:
        print(
            "runner marker missing — suspect a parse error in an addon or test "
            "(run the same command bare to see the first-second error)",
            file=sys.stderr,
        )
        return 2
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default="templates/godot-game")
    parser.add_argument("--import-only", action="store_true")
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    senv.load_dotenv()
    project = project_dir(args.game)

    # Keep the generated addon copy fresh so results reflect shared sources.
    sync = senv.run([sys.executable, str(Path(__file__).with_name("sync_addons.py"))], timeout=60)
    if sync.returncode != 0:
        print(sync.stdout + sync.stderr, file=sys.stderr)
        return sync.returncode

    code = stage_import(project, args.timeout)
    if code != 0 or args.import_only:
        return code
    if args.tests:
        return stage_tests(project, args.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
