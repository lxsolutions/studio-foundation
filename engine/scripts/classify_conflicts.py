#!/usr/bin/env python3
"""Classify Godot-fork merge conflicts and recommend resolutions.

During a WebGPU-backend rebase/merge onto a new official Godot, most conflicted
files fall into three buckets. This tool automates the triage that was previously
done by hand (see docs/runbooks/godot-fork-rebase.md and the godot-fork skill):

  mechanical  — docs, translations, mono SDK, CI, changelog/version. Recommend official.
  base-lag    — the fork made no WebGPU/rendering change to the file; the conflict is
                purely upstream drift. Recommend official.
  fork-touched— the fork's diff on this file contains WebGPU/renderer logic. Recommend
                HAND-UNION: never blanket-resolve; merge fork's additive code with
                upstream's changes (see SKILL exceptions: spirv-headers, mesh_storage).

Usage (from the fork clone, mid-merge):
  python engine/scripts/classify_conflicts.py [--fork-dir engine/.cache/godot-webgpu] \
      [--base <merge-base-sha>] [--json] [--apply-safe]

--apply-safe  checks out --theirs (official) for mechanical + base-lag files and stages
              them, leaving only fork-touched files for a human/agent. Always review first.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Patterns that mark a fork diff as carrying real backend/renderer logic.
FORK_LOGIC = re.compile(
    r"webgpu|wgpu|tint|wgsl|spirv|rendering_device|RenderingDevice|API_TRAIT|mapped_at_creation",
    re.IGNORECASE,
)
# Paths that are mechanical regardless of content.
MECHANICAL = re.compile(
    r"^(doc/|CHANGELOG|README|misc/|\.github/|editor/translations/|modules/mono/|.*\.po$)"
    r"|^version\.py$"
)
# Files where fork-touched resolution is known to keep the FORK side (exceptions).
KEEP_FORK = {
    "thirdparty/README.md",
    "thirdparty/spirv-headers/include/spirv/unified1/spirv.hpp11",
}


def git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def conflicted_files(fork_dir: Path) -> list[str]:
    out = git(["diff", "--name-only", "--diff-filter=U"], fork_dir)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def fork_added_logic(fork_dir: Path, base: str, path: str) -> bool:
    diff = git(["diff", base, "HEAD", "--", path], fork_dir)
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            if FORK_LOGIC.search(line):
                return True
    return False


def classify(fork_dir: Path, base: str, files: list[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {"mechanical": [], "base-lag": [], "fork-touched": []}
    for path in files:
        if MECHANICAL.search(path):
            buckets["mechanical"].append(path)
        elif fork_added_logic(fork_dir, base, path):
            buckets["fork-touched"].append(path)
        else:
            buckets["base-lag"].append(path)
    return buckets


def recommendation(path: str, bucket: str) -> str:
    if path in KEEP_FORK:
        return "keep-fork (--ours): known exception, fork pinned this dependency"
    if bucket in ("mechanical", "base-lag"):
        return "take-official (--theirs)"
    return "HAND-UNION: merge fork's additive WebGPU code with upstream changes"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fork-dir", default="engine/.cache/godot-webgpu")
    parser.add_argument("--base", default="", help="merge-base SHA (default: auto-detect vs official)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--apply-safe", action="store_true", help="resolve mechanical+base-lag with official")
    args = parser.parse_args()

    fork_dir = Path(args.fork_dir).resolve()
    if not (fork_dir / ".git").is_dir():
        print(f"error: no git repo at {fork_dir}", file=sys.stderr)
        return 2
    files = conflicted_files(fork_dir)
    if not files:
        print("no merge conflicts — tree is clean")
        return 0

    base = args.base
    if not base:
        for ref in ("official/HEAD", "official/master", "official/main"):
            try:
                base = git(["merge-base", "HEAD", ref], fork_dir).strip()
                if base:
                    break
            except subprocess.CalledProcessError:
                continue
    if not base:
        print("error: could not determine merge-base; pass --base <sha>", file=sys.stderr)
        return 2

    buckets = classify(fork_dir, base, files)
    if args.json:
        print(json.dumps({k: {p: recommendation(p, k) for p in v} for k, v in buckets.items()}, indent=2))
    else:
        for bucket in ("mechanical", "base-lag", "fork-touched"):
            files = buckets[bucket]
            print(f"\n== {bucket} ({len(files)}) ==")
            for path in files:
                print(f"  {path}\n      -> {recommendation(path, bucket)}")
        total = sum(len(v) for v in buckets.values())
        print(f"\ntotal: {total} conflicted; {len(buckets['fork-touched'])} need hand-union")

    if args.apply_safe:
        safe = buckets["mechanical"] + buckets["base-lag"]
        for path in safe:
            if path in KEEP_FORK:
                continue
            subprocess.run(["git", "checkout", "--theirs", "--", path], cwd=fork_dir, check=True)
            subprocess.run(["git", "add", path], cwd=fork_dir, check=True)
        print(f"\n[apply-safe] resolved {len(safe)} file(s) with official; "
              f"{len(buckets['fork-touched'])} fork-touched remain for review", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
