#!/usr/bin/env python3
"""Verify the WebGPU patch series against engine-lock.toml.

The project's central claim is that the WebGPU backend is a transparent,
checksum-locked series of patches on an official Godot commit — so drift between
the patch files and the lock is exactly the failure worth catching automatically.

Checks, in order:
  1. every patch named in the lock exists, and its SHA-256 matches,
  2. no patch file on disk is missing from the lock (an unlocked patch would be
     applied by nobody, or worse, silently ignored),
  3. the series is ordered and contiguous by its NNNN- prefix.

Stdlib only (tomllib needs Python 3.11+), so this runs anywhere without a
toolchain — no Godot, no Emscripten, no GPU.

Exit status is 0 when the series is intact, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_series import PatchSeriesError, verified_patches  # noqa: E402

ENGINE_DIR = Path(__file__).resolve().parents[1]
LOCK_PATH = ENGINE_DIR / "engine-lock.toml"


def main() -> int:
    if not LOCK_PATH.is_file():
        print(f"error: missing {LOCK_PATH}", file=sys.stderr)
        return 1

    with LOCK_PATH.open("rb") as handle:
        lock = tomllib.load(handle)

    # 1. Locked patches exist and match their recorded checksums.
    try:
        patches = verified_patches(lock, ENGINE_DIR)
    except PatchSeriesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    locked = {patch.relative for patch in patches}

    # 2. Nothing on disk is left out of the lock.
    on_disk = {
        f"patches/{path.name}"
        for path in sorted((ENGINE_DIR / "patches").glob("*.patch"))
    }
    unlocked = sorted(on_disk - locked)
    if unlocked:
        print("error: patch files present but not locked in engine-lock.toml:", file=sys.stderr)
        for name in unlocked:
            print(f"  {name}", file=sys.stderr)
        return 1

    # 3. The series is ordered and contiguous.
    numbers = []
    for patch in patches:
        match = re.match(r"patches/(\d{4})-", patch.relative)
        if not match:
            print(f"error: patch is not NNNN- prefixed: {patch.relative}", file=sys.stderr)
            return 1
        numbers.append(int(match.group(1)))

    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        print(
            f"error: patch series must be ordered and contiguous; got {numbers}",
            file=sys.stderr,
        )
        return 1

    base = lock["godot"]["webgpu"]["base_commit"]
    print(f"patch series OK — {len(patches)} patches, checksums match, applied over {base[:12]}")
    for patch in patches:
        print(f"  {patch.relative}  {patch.sha256[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
