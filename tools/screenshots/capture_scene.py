#!/usr/bin/env python3
"""Capture a Godot scene to PNG headlessly (agent-readable screenshot command).

  python tools/screenshots/capture_scene.py --game templates/godot-game \
      --scene res://scenes/main_menu.tscn [--size 1280x720] [--frames 5] [--out captures/]

Output lands in <game>/project/captures/<scene_name>.png by default.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402

TOOLS_GODOT = Path(__file__).resolve().parents[1] / "godot"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default="templates/godot-game")
    parser.add_argument("--scene", required=True, help="res:// path to a .tscn")
    parser.add_argument("--size", default="1280x720")
    parser.add_argument("--frames", type=int, default=5)
    parser.add_argument("--out", default="", help="output PNG (default: project captures dir)")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    senv.load_dotenv()
    sys.path.insert(0, str(TOOLS_GODOT))
    from run_godot import project_dir, run_godot  # noqa: PLC0415

    project = project_dir(args.game)
    scene_name = Path(args.scene).stem
    out = args.out or f"user://captures/{scene_name}.png"

    code, output = run_godot(
        [
            "--headless",
            "--path",
            str(project),
            "--script",
            "res://tests/capture_scene.gd",
            "--",
            "--scene",
            args.scene,
            "--out",
            out,
            "--frames",
            str(args.frames),
            "--size",
            args.size,
        ],
        project,
        args.timeout,
    )
    print(output)
    if "[capture] wrote" not in output:
        print("capture failed — no '[capture] wrote' marker", file=sys.stderr)
        return code or 1
    return code


if __name__ == "__main__":
    sys.exit(main())
