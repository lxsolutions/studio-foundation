#!/usr/bin/env python3
"""Apply the whole WebGPU patch series to a pristine official Godot tree.

`verify_patch_series.py` checks that the patches are locked, complete, ordered and
unmodified. It cannot check that they actually *apply*, and that gap has already
cost us once: patch 0016 was generated against a working tree where
`drivers/webgpu/tint_cli/glsl2spv.cpp` existed as an untracked local file, so it
emitted a modification hunk for a path no patch creates. Checksums matched,
ordering was contiguous, nothing was unlocked — and `git apply` failed on every
clean tree, taking `engine-fetch` down with it entirely.

Reverse-applying a patch against the tree it was generated from proves only
self-consistency. It structurally cannot detect a hunk whose target exists solely
because of uncommitted local state. Only a clean-tree apply can.

Unlike its sibling this DOES need network and a git checkout, so it is a separate,
slower job rather than something bolted onto the fast checksum gate.

Usage:
  python engine/scripts/verify_patch_apply.py                  # clone into a temp dir
  python engine/scripts/verify_patch_apply.py --godot <path>   # reuse a local clone

Exit status is 0 when the whole series applies, 1 otherwise.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_series import PatchSeriesError, verified_patches  # noqa: E402

ENGINE_DIR = Path(__file__).resolve().parents[1]
LOCK_PATH = ENGINE_DIR / "engine-lock.toml"


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def prepare_tree(base_commit: str, repo: str, godot: Path | None, workdir: Path) -> Path:
    """Return a checkout of `base_commit`, cloning it if one was not supplied."""
    if godot is not None:
        tree = workdir / "tree"
        print(f"[apply] using local clone {godot}")
        res = run(["git", "worktree", "add", "--detach", str(tree), base_commit], godot)
        if res.returncode != 0:
            raise SystemExit(f"error: could not create worktree:\n{res.stderr}")
        return tree

    tree = workdir / "godot"
    print(f"[apply] cloning {repo} @ {base_commit[:12]} (blobless, single commit)")
    run(["git", "init", "-q", str(tree)], workdir)
    run(["git", "remote", "add", "origin", repo], tree)
    res = run(["git", "fetch", "-q", "--depth", "1", "--filter=blob:none",
               "origin", base_commit], tree)
    if res.returncode != 0:
        raise SystemExit(f"error: fetch failed:\n{res.stderr}")
    res = run(["git", "checkout", "-q", "FETCH_HEAD"], tree)
    if res.returncode != 0:
        raise SystemExit(f"error: checkout failed:\n{res.stderr}")
    return tree


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--godot", type=Path, default=None,
                        help="existing official-Godot clone to branch a worktree from")
    parser.add_argument("--keep", action="store_true", help="leave the tree on disk")
    args = parser.parse_args()

    if not LOCK_PATH.is_file():
        print(f"error: missing {LOCK_PATH}", file=sys.stderr)
        return 1
    with LOCK_PATH.open("rb") as handle:
        lock = tomllib.load(handle)

    try:
        patches = verified_patches(lock, ENGINE_DIR)
    except PatchSeriesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    webgpu = lock["godot"]["webgpu"]
    base_commit = str(webgpu["base_commit"])
    repo = str(lock["godot"]["official"]["repo"])

    workdir = Path(tempfile.mkdtemp(prefix="studio-patch-apply-"))
    try:
        tree = prepare_tree(base_commit, repo, args.godot, workdir)
        for patch in patches:
            check = run(["git", "apply", "--check", str(patch.path)], tree)
            if check.returncode != 0:
                print(f"\nerror: {patch.relative} does not apply to a clean "
                      f"{base_commit[:12]} tree:", file=sys.stderr)
                print(check.stderr.rstrip(), file=sys.stderr)
                return 1
            applied = run(["git", "apply", str(patch.path)], tree)
            if applied.returncode != 0:
                print(f"\nerror: {patch.relative} failed to apply:", file=sys.stderr)
                print(applied.stderr.rstrip(), file=sys.stderr)
                return 1
            print(f"  applied {patch.relative}")
        print(f"\npatch series applies cleanly — {len(patches)} patches over {base_commit[:12]}")
        return 0
    finally:
        if args.godot is not None:
            run(["git", "worktree", "prune"], args.godot)
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
