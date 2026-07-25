"""Session context handed to every bforge op.

Holds the things an op needs that are *not* Blender state: where outputs go,
the deterministic RNG, and a running log the client gets back with each result.
"""

from __future__ import annotations

import os
import random
from pathlib import Path


class Ctx:
    def __init__(self, workdir: str, out_dir: str):
        self.workdir = Path(workdir).resolve()
        self.out_dir = Path(out_dir).resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.notes: list[str] = []
        self.seed = 0
        self.rng = random.Random(0)

    # -- determinism ----------------------------------------------------
    def reseed(self, seed: int) -> random.Random:
        """Every generator calls this. Same seed + same params => same mesh."""
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        return self.rng

    def sub_rng(self, salt: str) -> random.Random:
        """Independent stream so adding a feature doesn't reshuffle earlier ones."""
        return random.Random(f"{self.seed}:{salt}")

    # -- io -------------------------------------------------------------
    def resolve(self, path: str) -> Path:
        candidate = Path(os.path.expandvars(os.path.expanduser(str(path))))
        if not candidate.is_absolute():
            candidate = self.workdir / candidate
        return candidate.resolve()

    def out_path(self, path: str, suffix: str = "") -> Path:
        """Resolve an output path, defaulting relative paths under out_dir."""
        candidate = Path(os.path.expandvars(os.path.expanduser(str(path))))
        if not candidate.is_absolute():
            candidate = self.out_dir / candidate
        candidate = candidate.resolve()
        if suffix and candidate.suffix.lower() != suffix.lower():
            candidate = candidate.with_suffix(suffix)
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def rel(self, path) -> str:
        """Best-effort repo-relative display path (agents paste these around)."""
        try:
            return str(Path(path).resolve().relative_to(self.workdir)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    # -- reporting ------------------------------------------------------
    def note(self, message: str) -> None:
        """Advice the agent should read even when the op succeeded."""
        self.notes.append(message)

    def drain_notes(self) -> list[str]:
        notes, self.notes = self.notes, []
        return notes
