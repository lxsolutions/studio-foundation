#!/usr/bin/env python3
"""Classify conflicts left by three-way application of the WebGPU patch series.

The classifier is advisory. It never resolves, stages, resets, or deletes files.
Every patch conflict must be reviewed against the new official Godot source.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RENDERER = re.compile(
    r"webgpu|wgpu|wgsl|tint|spirv|rendering_device|rendering/",
    re.IGNORECASE,
)
THIRD_PARTY_PREFIXES = ("thirdparty/",)
BUILD_PREFIXES = ("SConstruct", "drivers/SCsub", "modules/", "platform/web/")


def git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def conflicted_files(source_dir: Path) -> list[str]:
    output = git(["diff", "--name-only", "--diff-filter=U"], source_dir)
    return [line.strip() for line in output.splitlines() if line.strip()]


def classify_path(source_dir: Path, path: str) -> str:
    if path.startswith(THIRD_PARTY_PREFIXES):
        return "third-party"
    conflict = git(["diff", "--cc", "--", path], source_dir)
    if RENDERER.search(path) or RENDERER.search(conflict):
        return "renderer"
    if path.startswith(BUILD_PREFIXES):
        return "build-integration"
    return "manual-review"


def classify(source_dir: Path, files: list[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {
        "renderer": [],
        "third-party": [],
        "build-integration": [],
        "manual-review": [],
    }
    for path in files:
        buckets[classify_path(source_dir, path)].append(path)
    return buckets


def recommendation(bucket: str) -> str:
    if bucket == "renderer":
        return "hand-merge the local WebGPU behavior with the new official API"
    if bucket == "third-party":
        return "verify the required upstream version and licenses before regenerating"
    if bucket == "build-integration":
        return "review official build changes and preserve only required WebGPU hooks"
    return "review the originating patch and official change manually"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        "--fork-dir",
        dest="source_dir",
        default="engine/.cache/studio-webgpu",
        help="candidate Git worktree; --fork-dir remains as a compatibility alias",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    if not (source_dir / ".git").exists():
        print(f"error: no Git worktree at {source_dir}", file=sys.stderr)
        return 2

    files = conflicted_files(source_dir)
    if not files:
        output: dict[str, object] = {"conflicts": 0, "categories": {}}
        if args.json:
            print(json.dumps(output, indent=2, sort_keys=True))
        else:
            print("no patch-application conflicts")
        return 0

    buckets = classify(source_dir, files)
    result = {
        "conflicts": len(files),
        "categories": {
            bucket: {path: recommendation(bucket) for path in paths}
            for bucket, paths in buckets.items()
            if paths
        },
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for bucket, paths in buckets.items():
            if not paths:
                continue
            print(f"{bucket} ({len(paths)})")
            for path in paths:
                print(f"  {path}: {recommendation(bucket)}")
        print(f"total: {len(files)} conflict(s); all require review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
