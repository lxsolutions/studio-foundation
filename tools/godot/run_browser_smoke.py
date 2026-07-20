#!/usr/bin/env python3
"""Thin wrapper around the Node Playwright smoke test in tests/browser.

  python tools/godot/run_browser_smoke.py [--game templates/godot-game] [--preset web-webgl]

Requires `npm ci` to have been run in tests/browser (playwright-core, system
Chrome/Edge — no browser downloads). Exits with the smoke test's status.
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
        print(
            "playwright-core not installed — run: cd tests/browser && npm ci",
            file=sys.stderr,
        )
        return 2
    node = shutil.which("node")
    if not node:
        print("node not found on PATH", file=sys.stderr)
        return 2
    return subprocess.call([node, str(browser_dir / "smoke.mjs"), *sys.argv[1:]], cwd=browser_dir)


if __name__ == "__main__":
    sys.exit(main())
