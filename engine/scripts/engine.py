#!/usr/bin/env python3
"""Engine source and patch tooling: versions / fetch / build / rebase.

Single source of truth is engine/engine-lock.toml. Engine sources are cached
out-of-tree in engine/.cache (gitignored, never committed).

  python engine/scripts/engine.py versions   # print locked pins and local cache state
  python engine/scripts/engine.py fetch      # fetch official Godot + apply local patches
  python engine/scripts/engine.py build      # build pinned WebGPU export templates
  python engine/scripts/engine.py rebase     # test the patch series on a newer Godot ref
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from patch_series import PatchSeriesError, patch_state, verified_patches
from rebase import RebaseError, cmd_rebase, rebase_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = REPO_ROOT / "engine"
CACHE_DIR = ENGINE_DIR / ".cache"
LOCK_FILE = ENGINE_DIR / "engine-lock.toml"
PATCHED_CACHE_DIR = CACHE_DIR / "studio-webgpu"


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
        available = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=dest,
            capture_output=True,
            check=False,
        )
        if available.returncode != 0:
            print(f"[fetch] retrieving missing commit {commit}")
            git("fetch", "--filter=blob:none", "origin", commit, cwd=dest)
    print(f"[fetch] checkout {name} @ {commit} ({ref})")
    git("checkout", "--detach", commit, cwd=dest)
    return dest


def _patches_are_applied(source: Path, patches: list) -> bool:
    """Confirm that every disjoint locked patch is present in the derived tree."""
    for patch in reversed(patches):
        proc = subprocess.run(
            ["git", "apply", "--reverse", "--check", str(patch.path)],
            cwd=source,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return False
    return True


def prepare_patched_source(
    lock: dict,
    official_dir: Path,
    patches: list,
    *,
    cache_dir: Path = CACHE_DIR,
) -> Path:
    """Create or reuse the deterministic official-Godot + local-patches worktree."""
    destination = cache_dir / PATCHED_CACHE_DIR.name
    state_file = destination / ".studio-foundation-patch-state.json"
    expected_state = patch_state(lock, patches)

    if destination.exists():
        if state_file.is_file():
            try:
                current_state = json.loads(state_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PatchSeriesError(
                    f"invalid patch-state file: {state_file}"
                ) from exc
            if current_state == expected_state and _patches_are_applied(
                destination, patches
            ):
                print(f"[fetch] reusing verified patched source {destination}")
                return destination
        raise PatchSeriesError(
            f"{destination} exists but does not match engine-lock.toml; "
            "move this disposable cache aside and run engine-fetch again"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    base_commit = str(lock["godot"]["webgpu"]["base_commit"])
    print(f"[fetch] creating patched source from official Godot @ {base_commit}")
    git(
        "worktree",
        "add",
        "--detach",
        str(destination),
        base_commit,
        cwd=official_dir,
    )
    for patch in patches:
        print(f"[fetch] checking {patch.relative}")
        git("apply", "--check", str(patch.path), cwd=destination)
        git("apply", str(patch.path), cwd=destination)
    state_file.write_text(
        json.dumps(expected_state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def cmd_versions(lock: dict) -> int:
    official = lock["godot"]["official"]
    integration = lock["godot"]["webgpu"]
    toolchain = lock["toolchain"]
    print(
        f"official godot : {official['tag']} @ {official['commit'][:12]}  ({official['repo']})"
    )
    print(
        f"studio webgpu  : base {integration['base']} @ "
        f"{integration['base_commit'][:12]}  status={integration['status']}"
    )
    print(
        f"source lineage : {integration['source_lineage_commit'][:12]}  "
        f"({integration['source_lineage_repo']})"
    )
    print(
        f"toolchain      : emscripten {toolchain['emscripten']}, scons {toolchain['scons']}, "
        f"python {toolchain['python']}, rust {toolchain['rust']}"
    )
    for name, key in (
        ("official", "godot-official"),
        ("patched", PATCHED_CACHE_DIR.name),
    ):
        dest = CACHE_DIR / key
        state = "cached" if (dest / ".git").exists() else "not fetched"
        print(f"cache {name:11s}: {state} ({dest})")
    patches = lock.get("patches", {}).get("series", [])
    print(f"patch series   : {len(patches)} patch(es)")
    return 0


def cmd_fetch(lock: dict) -> int:
    official = lock["godot"]["official"]
    try:
        patches = verified_patches(lock, ENGINE_DIR)
        official_dir = fetch_repo(
            "godot-official", official["repo"], official["commit"], official["tag"]
        )
        prepare_patched_source(lock, official_dir, patches)
    except (PatchSeriesError, OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("[fetch] done — official source and Studio WebGPU patches are ready")
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


def artifact_destination(
    source_dir: Path | None, engine_dir: Path = ENGINE_DIR
) -> Path:
    """Keep candidate templates separate from artifacts produced by the locked integration."""
    if source_dir:
        return engine_dir / "artifacts" / "candidates" / source_dir.name / "templates"
    return engine_dir / "artifacts" / "templates"


def cmd_build(lock: dict, source_dir: Path | None = None) -> int:
    """Build web export templates from the patched source or a candidate worktree.

    Requires: scons (tools venv `engine` group) and emsdk with the pinned
    emscripten already installed + activated (emsdk install X && emsdk activate X).
    """
    source = source_dir or PATCHED_CACHE_DIR
    artifact_dir = artifact_destination(source_dir)
    if not (source / "SConstruct").is_file():
        print(
            "error: engine source is not ready; fetch pins or prepare the selected workspace",
            file=sys.stderr,
        )
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
            print(
                f"error: {em_dir} has no emcc.bat — activate emsdk {em_version} first",
                file=sys.stderr,
            )
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
        proc = subprocess.run([*scons, *flags, f"-j{jobs}"], cwd=source, env=build_env)
        if proc.returncode != 0:
            print(f"[build] {profile} FAILED (exit {proc.returncode})", file=sys.stderr)
            rc = proc.returncode
            break
        print(f"[build] {profile} OK", flush=True)
    if rc == 0:
        _install_templates(source, artifact_dir)
    return rc


def _install_templates(source: Path, dest: Path | None = None) -> None:
    """Copy built web template zips into the selected artifact destination.

    scons names its output godot.web.template_{release,debug}.wasm32.zip, but
    export_presets.cfg's web-webgpu preset (custom_template/release, .../debug)
    points at ...webgpu.zip — rename on copy so the preset actually resolves."""
    dest = dest or ENGINE_DIR / "artifacts" / "templates"
    dest.mkdir(parents=True, exist_ok=True)
    zips = sorted((source / "bin").glob("godot.web.template_*.zip"))
    for z in zips:
        target = dest / z.name.replace(".wasm32.zip", ".webgpu.zip")
        shutil.copy2(z, target)
        print(f"[install] {z.name} -> {target.relative_to(REPO_ROOT)}", flush=True)
    if not zips:
        print("[install] WARNING: no template zips found under bin/", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["versions", "fetch", "build", "rebase"])
    parser.add_argument(
        "--official-ref", default="", help="official commit/tag (default: lock pin)"
    )
    parser.add_argument("--branch", default="", help="dedicated merge branch name")
    parser.add_argument(
        "--workspace", default="", help="directory name under engine/.cache/rebases"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the plan without changing Git state",
    )
    parser.add_argument(
        "--json", action="store_true", help="machine-readable rebase result"
    )
    args = parser.parse_args()
    lock = load_lock()
    if args.command == "versions":
        return cmd_versions(lock)
    if args.command == "fetch":
        return cmd_fetch(lock)
    if args.command == "build":
        try:
            source_dir = rebase_workspace(args.workspace) if args.workspace else None
        except RebaseError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return cmd_build(lock, source_dir)
    return cmd_rebase(lock, args)


if __name__ == "__main__":
    sys.exit(main())
