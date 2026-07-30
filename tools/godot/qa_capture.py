#!/usr/bin/env python3
"""Run the visual QA gate against a game project.

Usage:
  python tools/godot/qa_capture.py --game games/chariot
  python tools/godot/qa_capture.py --game games/chariot --shots establishing --devices phone

Wraps res://addons/studio_core/tools/qa_capture.gd, which renders the shots a
game declares in res://tests/qa_shots.gd and MEASURES them (exposure,
saturation, color probes, HUD on-screen/tap-size checks). See that script for
the shot contract.

The capture needs a real rasterizer, so this does NOT run --headless. On a
GPU-less box the Compatibility renderer over ANGLE/D3D11 rasterizes in
software; that is the default. On a machine with a live GPU, pass
--method forward_plus --renderer vulkan to photograph the cinematic tier.

Each shot runs in its OWN Godot process. Measured necessity, not caution: a
single process sweeping six shots died partway through — five desktop-tier
colosseum builds exhausted the software D3D11 device. Per-shot processes keep
every job on a fresh device and turn a crash into one failed shot instead of
a lost sweep. Reports are merged into <out>/report.json afterwards.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_godot as rg  # noqa: E402
from studio_tools import env as senv  # noqa: E402

RUNNER = "res://addons/studio_core/tools/qa_capture.gd"


def godot_args(project: Path, method: str, renderer: str, user_args: list[str]) -> list[str]:
    return [
        "--path",
        str(project),
        "--rendering-method",
        method,
        "--rendering-driver",
        renderer,
        "--script",
        RUNNER,
        "--",
        *user_args,
    ]


def list_shots(project: Path, method: str, renderer: str, driver: str, timeout: int) -> list[str]:
    code, output = rg.run_godot(
        godot_args(project, method, renderer, [f"--driver={driver}", "--list"]),
        project,
        timeout,
        isolate_user_data=True,
    )
    if code != 0:
        print(output, file=sys.stderr)
        raise SystemExit("could not list shots (is res://tests/qa_shots.gd present?)")
    names = []
    for line in output.splitlines():
        match = re.match(r"^  (\S+) \(", line)
        if match:
            names.append(match.group(1))
    return names


def out_dir_of(project: Path, out_arg: str) -> Path:
    if not out_arg.startswith("res://"):
        raise SystemExit("--out must be a res:// path (it is resolved inside the project)")
    return project / out_arg[len("res://") :]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default="templates/godot-game")
    parser.add_argument(
        "--driver", default="res://tests/qa_shots.gd", help="game-side shot declaration script"
    )
    parser.add_argument("--out", default="res://build/qa")
    parser.add_argument("--shots", default="", help="comma-separated subset of shot names")
    parser.add_argument("--devices", default="", help="comma-separated subset of device presets")
    parser.add_argument(
        "--method",
        default="gl_compatibility",
        help="rendering method (gl_compatibility works without a GPU)",
    )
    parser.add_argument(
        "--renderer",
        default="",
        help="rendering driver (default: opengl3_angle on Windows, opengl3 elsewhere)",
    )
    parser.add_argument("--list", action="store_true", help="list the game's shots and exit")
    parser.add_argument("--json", action="store_true", help="print the merged report as JSON")
    parser.add_argument("--warn-only", action="store_true")
    # Per shot, not per sweep: on the software rasterizer one desktop-tier
    # Chariot build alone runs tens of seconds.
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    senv.load_dotenv()
    project = rg.project_dir(args.game)

    sync = senv.run([sys.executable, str(Path(__file__).with_name("sync_addons.py"))], timeout=60)
    if sync.returncode != 0:
        print(sync.stdout + sync.stderr, file=sys.stderr)
        return sync.returncode

    code = rg.stage_import(project, args.timeout)
    if code != 0:
        return code

    renderer = args.renderer or ("opengl3_angle" if sys.platform == "win32" else "opengl3")

    if args.list:
        for name in list_shots(project, args.method, renderer, args.driver, args.timeout):
            print(f"  {name}")
        return 0

    if args.shots:
        shot_names = [piece.strip() for piece in args.shots.split(",") if piece.strip()]
    else:
        shot_names = list_shots(project, args.method, renderer, args.driver, args.timeout)
    if not shot_names:
        print("no shots declared", file=sys.stderr)
        return 2

    out_dir = out_dir_of(project, args.out)
    report_path = out_dir / "report.json"
    merged: dict = {"results": [], "findings": 0, "tool_failures": 0, "crashed": []}
    worst = 0

    for name in shot_names:
        if report_path.exists():
            report_path.unlink()
        user_args = [f"--driver={args.driver}", f"--out={args.out}", f"--shots={name}"]
        if args.devices:
            user_args.append(f"--devices={args.devices}")
        if args.warn_only:
            user_args.append("--warn-only")
        try:
            code, output = rg.run_godot(
                godot_args(project, args.method, renderer, user_args),
                project,
                args.timeout,
                isolate_user_data=True,
            )
        except SystemExit as exc:
            # run_godot raises on a hard timeout. One wedged shot may not
            # abort the sweep — that is the whole point of per-shot processes.
            print(f"[{name}] {exc}", file=sys.stderr)
            merged["crashed"].append({"shot": name, "exit_code": "timeout"})
            merged["tool_failures"] += 1
            worst = max(worst, 2)
            continue
        print(output)
        if "[qa] runner alive" not in output:
            print(
                f"[{name}] runner marker missing — parse error in an addon or the driver?",
                file=sys.stderr,
            )
            return 2
        if "nothing to run" in output:
            # Device filter excluded every job of this shot; not a failure.
            continue
        if not report_path.exists():
            # The runner writes the report even when findings fail the run, so
            # a missing report means the process died mid-shot.
            print(
                f"[{name}] godot exited {code} without a report — counting as a crash",
                file=sys.stderr,
            )
            merged["crashed"].append({"shot": name, "exit_code": code})
            merged["tool_failures"] += 1
            worst = max(worst, 2)
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        merged.setdefault("renderer_method", report.get("renderer_method"))
        merged.setdefault("renderer_driver", report.get("renderer_driver"))
        merged["results"].extend(report.get("results", []))
        merged["findings"] += int(report.get("findings", 0))
        merged["tool_failures"] += int(report.get("tool_failures", 0))
        if code not in (0, 1, 2):
            # Engine shutdown crashed AFTER the report was honestly written
            # (heavy-world teardown on the software device does this). The
            # report is the verdict; the corpse is not.
            code = 1 if report.get("findings") else 0
        worst = max(worst, code)

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(merged, indent=2))
    stills = len(merged["results"])
    print(
        f"[qa] sweep: {stills} still(s), {merged['findings']} finding(s), "
        f"{merged['tool_failures']} tool failure(s) -> {report_path}"
    )
    return worst


if __name__ == "__main__":
    sys.exit(main())
