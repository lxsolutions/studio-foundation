#!/usr/bin/env python3
"""Engine provenance tooling: versions / fetch / build / rebase.

Single source of truth is engine/engine-lock.toml. Engine sources are cached
out-of-tree in engine/.cache (gitignored, never committed).

  python engine/scripts/engine.py versions   # print locked pins and local cache state
  python engine/scripts/engine.py fetch      # clone pinned official + fork sources
  python engine/scripts/engine.py build      # (not yet implemented) scons template build
  python engine/scripts/engine.py rebase     # (not yet implemented) fork rebase workspace
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = REPO_ROOT / "engine"
CACHE_DIR = ENGINE_DIR / ".cache"
LOCK_FILE = ENGINE_DIR / "engine-lock.toml"


def load_lock() -> dict:
    with LOCK_FILE.open("rb") as fh:
        return tomllib.load(fh)


def git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)


def fetch_repo(name: str, repo: str, commit: str, ref: str) -> Path:
    """Clone (or reuse) a source tree and check out the pinned commit."""
    dest = CACHE_DIR / name
    if not (dest / ".git").is_dir():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"[fetch] cloning {repo} -> {dest}")
        git("clone", "--filter=blob:none", "--no-checkout", repo, str(dest))
    else:
        print(f"[fetch] reusing existing clone {dest}")
        git("fetch", "--filter=blob:none", "origin", commit, cwd=dest)
    print(f"[fetch] checkout {name} @ {commit} ({ref})")
    git("checkout", "--detach", commit, cwd=dest)
    return dest


def cmd_versions(lock: dict) -> int:
    official = lock["godot"]["official"]
    fork = lock["godot"]["webgpu_fork"]
    toolchain = lock["toolchain"]
    print(f"official godot : {official['tag']} @ {official['commit'][:12]}  ({official['repo']})")
    print(f"webgpu fork    : base {fork['base']} @ {fork['commit'][:12]}  status={fork['status']}")
    print(f"                 ({fork['repo']})")
    print(f"toolchain      : emscripten {toolchain['emscripten']}, scons {toolchain['scons']}, "
          f"python {toolchain['python']}, rust {toolchain['rust']}")
    for name, key in (("official", "godot-official"), ("webgpu fork", "godot-webgpu")):
        dest = CACHE_DIR / key
        state = "cached" if (dest / ".git").is_dir() else "not fetched"
        print(f"cache {name:11s}: {state} ({dest})")
    patches = lock.get("patches", {}).get("series", [])
    print(f"patch series   : {len(patches)} patch(es)")
    return 0


def cmd_fetch(lock: dict) -> int:
    official = lock["godot"]["official"]
    fork = lock["godot"]["webgpu_fork"]
    fetch_repo("godot-official", official["repo"], official["commit"], official["tag"])
    fetch_repo("godot-webgpu", fork["repo"], fork["commit"], fork["branch"])
    series = lock.get("patches", {}).get("series", [])
    for entry in series:
        patch = ENGINE_DIR / entry["file"]
        print(f"[fetch] applying patch {patch.name}")
        git("apply", str(patch), cwd=CACHE_DIR / "godot-webgpu")
    print("[fetch] done — sources ready in engine/.cache")
    return 0


def _find_emsdk_env_bat(expected: str) -> Path | None:
    """Locate emsdk_env.bat for an emsdk install containing the pinned version."""
    candidates = [
        Path.home() / "emsdk",
        Path(os.environ.get("EMSDK", "")) if os.environ.get("EMSDK") else None,
        Path("C:/emsdk"),
    ]
    for root in [c for c in candidates if c]:
        bat = root / "emsdk_env.bat"
        if bat.is_file():
            return bat
    return None


def cmd_build(lock: dict) -> int:
    """Build web export templates from the pinned WebGPU fork.

    Requires: scons (tools venv `engine` group) and emsdk with the pinned
    emscripten already installed + activated (emsdk install X && emsdk activate X).
    """
    fork_dir = CACHE_DIR / "godot-webgpu"
    if not (fork_dir / "SConstruct").is_file():
        print("error: fork sources not fetched — run: just engine-fetch", file=sys.stderr)
        return 2
    em_version = lock["toolchain"]["emscripten"]
    build_env = os.environ.copy()
    if not shutil.which("emcc"):
        bat = _find_emsdk_env_bat(em_version)
        if not bat:
            print(
                f"error: emcc not on PATH and no emsdk found — install/activate emsdk {em_version}:\n"
                f"  git clone https://github.com/emscripten-core/emsdk ~\\emsdk\n"
                f"  ~\\emsdk\\emsdk install {em_version} && ~\\emsdk\\emsdk activate {em_version}",
                file=sys.stderr,
            )
            return 2
        # emsdk_env.bat ultimately puts <root> and <root>/upstream/emscripten on
        # PATH; do that directly instead of shelling out (robust across hosts).
        root = bat.parent
        em_dir = root / "upstream" / "emscripten"
        if not (em_dir / "emcc.bat").is_file():
            print(f"error: {em_dir} has no emcc.bat — activate emsdk {em_version} first", file=sys.stderr)
            return 2
        print(f"[build] using emsdk at {root}")
        build_env["PATH"] = f"{em_dir};{root};" + build_env.get("PATH", "")
        build_env["EMSDK"] = str(root)
        if not shutil.which("emcc", path=build_env["PATH"]):
            print("error: emcc still not found after PATH update", file=sys.stderr)
            return 2
    scons = [sys.executable, "-m", "SCons"]
    targets = lock["build"]["web_webgpu"]
    jobs = str(os.cpu_count() or 4)
    rc = 0
    for profile in ("target_release", "target_debug"):
        flags = targets[profile]
        print(f"[build] scons {' '.join(flags)} -j{jobs}", flush=True)
        proc = subprocess.run([*scons, *flags, f"-j{jobs}"], cwd=fork_dir, env=build_env)
        if proc.returncode != 0:
            print(f"[build] {profile} FAILED (exit {proc.returncode})", file=sys.stderr)
            rc = proc.returncode
            break
        print(f"[build] {profile} OK", flush=True)
    if rc == 0:
        _install_templates(fork_dir)
    return rc


def _install_templates(fork_dir: Path) -> None:
    """Copy built web template zips into engine/artifacts/templates for export.

    scons names its output godot.web.template_{release,debug}.wasm32.zip, but
    export_presets.cfg's web-webgpu preset (custom_template/release, .../debug)
    points at ...webgpu.zip — rename on copy so the preset actually resolves."""
    dest = ENGINE_DIR / "artifacts" / "templates"
    dest.mkdir(parents=True, exist_ok=True)
    zips = sorted((fork_dir / "bin").glob("godot.web.template_*.zip"))
    for z in zips:
        target = dest / z.name.replace(".wasm32.zip", ".webgpu.zip")
        shutil.copy2(z, target)
        print(f"[install] {z.name} -> {target.relative_to(REPO_ROOT)}", flush=True)
    if not zips:
        print("[install] WARNING: no template zips found under bin/", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["versions", "fetch", "build", "rebase"])
    args, _rest = parser.parse_known_args()
    lock = load_lock()
    if args.command == "versions":
        return cmd_versions(lock)
    if args.command == "fetch":
        return cmd_fetch(lock)
    if args.command == "build":
        return cmd_build(lock)
    print(
        "error: 'engine rebase' is not implemented yet — see docs/runbooks/godot-fork-rebase.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
