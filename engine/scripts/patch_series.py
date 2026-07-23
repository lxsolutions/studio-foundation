"""Verification helpers for Studio Foundation's in-repository engine patches."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


class PatchSeriesError(RuntimeError):
    """The committed patch series is missing, unsafe, or does not match its lock."""


@dataclass(frozen=True)
class VerifiedPatch:
    path: Path
    relative: str
    sha256: str


def verified_patches(lock: dict, engine_dir: Path) -> list[VerifiedPatch]:
    """Resolve and checksum every ordered patch without allowing path traversal."""
    patch_root = (engine_dir / "patches").resolve()
    series = lock.get("patches", {}).get("series", [])
    if not series:
        raise PatchSeriesError(
            "engine-lock.toml must contain at least one WebGPU patch"
        )

    verified: list[VerifiedPatch] = []
    for index, entry in enumerate(series, start=1):
        relative = str(entry.get("file", "")).replace("\\", "/")
        raw_expected = str(entry.get("sha256", ""))
        expected = raw_expected.lower()
        if (
            not relative
            or raw_expected != expected
            or not re.fullmatch(r"[0-9a-f]{64}", expected)
        ):
            raise PatchSeriesError(
                f"patch entry {index} requires file and a lowercase SHA-256"
            )
        path = (engine_dir / relative).resolve()
        if not path.is_relative_to(patch_root):
            raise PatchSeriesError(f"patch entry escapes engine/patches: {relative}")
        if not path.is_file():
            raise PatchSeriesError(f"patch file is missing: {relative}")
        with path.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != expected:
            raise PatchSeriesError(
                f"patch checksum mismatch for {relative}: expected {expected}, got {actual}"
            )
        verified.append(VerifiedPatch(path, relative, actual))
    return verified


def patch_state(lock: dict, patches: list[VerifiedPatch]) -> dict[str, object]:
    integration = lock["godot"]["webgpu"]
    return {
        "schema": 1,
        "base_commit": integration["base_commit"],
        "patches": [
            {"file": patch.relative, "sha256": patch.sha256} for patch in patches
        ],
    }
