#!/usr/bin/env python3
"""Real-GPU screenshot of a Godot web export via Playwright (tests/browser/capture.mjs).

  python tools/screenshots/capture_web.py [--game templates/godot-game] \
      [--preset web-webgl] [--out captures/web-webgl.png] [--wait 6000] [--size 1280x720]

Unlike headless Godot (dummy renderer, no rasterization), a browser renders the
actual WebGL/WebGPU canvas, so this produces true screenshots on CI agents.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402


def main() -> int:
    senv.load_dotenv()
    browser_dir = senv.repo_root() / "tests" / "browser"
    if not (browser_dir / "node_modules" / "playwright-core").is_dir():
        print("playwright-core not installed — run: cd tests/browser && npm ci", file=sys.stderr)
        return 2
    node = shutil.which("node")
    if not node:
        print("node not found on PATH", file=sys.stderr)
        return 2
    return subprocess.call([node, str(browser_dir / "capture.mjs"), *sys.argv[1:]], cwd=browser_dir)


if __name__ == "__main__":
    sys.exit(main())
