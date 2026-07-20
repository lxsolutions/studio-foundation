#!/usr/bin/env python3
"""Run a cargo command with the MinGW bin dir on PATH (windows-gnu only).

The rust x86_64-pc-windows-gnu toolchain links through MinGW gcc and fails with
`ld: cannot find dllcrt2.o / -lkernel32` when no MinGW installation is on PATH.
This wrapper locates one (PATH, WinGet WinLibs, MSYS2) and prepends its bin dir,
so `just test-rust` / `just lint-rust` work without manual PATH edits.

Usage: python tools/cargo_env.py <cargo args...>
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "pylib"))

from studio_tools import env as senv  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: cargo_env.py <cargo args...>", file=sys.stderr)
        return 2
    env = os.environ.copy()
    if sys.platform == "win32":
        bin_dir = senv.mingw_bin_dir()
        if bin_dir:
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    cargo = senv.find_cargo() or "cargo"
    return subprocess.call([cargo, *args], env=env)


if __name__ == "__main__":
    raise SystemExit(main())
