"""Environment discovery shared by doctor, pipeline, exports, and studio-mcp.

Stdlib only. No machine-specific absolute paths: discovery walks env vars, PATH,
then *conventional* install locations (winget package dirs, Program Files).
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# tools/pylib/studio_tools/env.py -> repo root is parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]


def repo_root() -> Path:
    return REPO_ROOT


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Minimal KEY=VALUE .env loader. Existing process env always wins."""
    path = path or REPO_ROOT / ".env"
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


def run(
    argv: list[str],
    timeout: int = 120,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a command with captured output. Never uses shell=True."""
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd or REPO_ROOT),
        env=merged,
        encoding="utf-8",
        errors="replace",
    )


def _first_existing(patterns: list[str]) -> str | None:
    for pattern in patterns:
        matches = sorted(glob.glob(pattern), reverse=True)  # prefer newest version dirs
        for m in matches:
            if os.path.isfile(m):
                return m
    return None


def which_any(names: list[str]) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def find_cargo() -> str | None:
    found = which_any(["cargo"])
    if found:
        return found
    home = Path.home() / ".cargo" / "bin" / ("cargo.exe" if os.name == "nt" else "cargo")
    return str(home) if home.is_file() else None


def find_just() -> str | None:
    found = which_any(["just"])
    if found:
        return found
    if os.name == "nt":
        localapp = os.environ.get("LOCALAPPDATA", "")
        return _first_existing(
            [
                rf"{localapp}\Microsoft\WinGet\Links\just.exe",
                rf"{localapp}\Microsoft\WinGet\Packages\Casey.Just_*\just.exe",
            ]
        )
    return None


def find_godot() -> str | None:
    """Locate the Godot binary; on Windows prefer the *console* exe (usable stdout)."""
    env_bin = os.environ.get("GODOT_BIN")
    if env_bin and Path(env_bin).is_file():
        return env_bin
    found = which_any(["godot4", "godot"])
    if found:
        return found
    if os.name == "nt":
        localapp = os.environ.get("LOCALAPPDATA", "")
        return _first_existing(
            [
                rf"{localapp}\Microsoft\WinGet\Packages\GodotEngine.GodotEngine_*\Godot_v*console.exe",
                rf"{localapp}\Microsoft\WinGet\Packages\GodotEngine.GodotEngine_*\Godot_v*.exe",
                r"C:\Program Files\Godot\Godot_v*console.exe",
            ]
        )
    if sys.platform == "darwin":
        mac = "/Applications/Godot.app/Contents/MacOS/Godot"
        return mac if os.path.isfile(mac) else None
    return None


def find_blender() -> str | None:
    env_bin = os.environ.get("BLENDER_BIN")
    if env_bin and Path(env_bin).is_file():
        return env_bin
    found = which_any(["blender"])
    if found:
        return found
    if os.name == "nt":
        return _first_existing(
            [
                r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
            ]
        )
    if sys.platform == "darwin":
        mac = "/Applications/Blender.app/Contents/MacOS/Blender"
        return mac if os.path.isfile(mac) else None
    return None


def godot_version(binary: str) -> str | None:
    try:
        proc = run([binary, "--version"], timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"(\d+\.\d+(?:\.\d+)?\.\w+\.[\w.]+)", text)
    return match.group(1) if match else (text.strip().splitlines()[0] if text.strip() else None)


def blender_version(binary: str) -> str | None:
    try:
        proc = run([binary, "--version"], timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"Blender\s+(\d+\.\d+\.\d+)", proc.stdout or "")
    return match.group(1) if match else None


def engine_lock() -> dict:
    import tomllib

    lock_path = REPO_ROOT / "engine" / "engine-lock.toml"
    with open(lock_path, "rb") as fh:
        return tomllib.load(fh)


def godot_templates_dir() -> Path | None:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Godot" / "export_templates" if appdata else None
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Godot/export_templates"
    return Path.home() / ".local/share/godot/export_templates"


def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def find_browsers() -> dict[str, str]:
    """Installed system browsers usable by Playwright channels (no downloads)."""
    found: dict[str, str] = {}
    if os.name == "nt":
        pf, pf86 = os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")
        candidates = {
            "chrome": [
                rf"{pf}\Google\Chrome\Application\chrome.exe",
                rf"{pf86}\Google\Chrome\Application\chrome.exe",
            ],
            "msedge": [
                rf"{pf86}\Microsoft\Edge\Application\msedge.exe",
                rf"{pf}\Microsoft\Edge\Application\msedge.exe",
            ],
            "firefox": [rf"{pf}\Mozilla Firefox\firefox.exe"],
        }
        for channel, paths in candidates.items():
            for p in paths:
                if os.path.isfile(p):
                    found[channel] = p
                    break
    else:
        for channel, names in {
            "chrome": ["google-chrome", "chromium", "chromium-browser"],
            "msedge": ["microsoft-edge"],
            "firefox": ["firefox"],
        }.items():
            path = which_any(names)
            if path:
                found[channel] = path
    return found
