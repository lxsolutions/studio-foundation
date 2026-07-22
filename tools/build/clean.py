#!/usr/bin/env python3
"""Remove known generated workspace outputs without touching source files."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ROOT_OUTPUTS = (
    "assets-generated",
    "build",
    "dist",
    "exports",
    ".codex-temp",
    ".ruff_cache",
    ".pytest_cache",
    "tests/artifacts",
)
PROJECT_OUTPUTS = (
    ".godot",
    "exports",
    "assets/generated",
    "addons/studio_core",
)
DEEP_OUTPUTS = (
    "engine/.cache",
    "engine/artifacts",
    "tools/.venv",
    "tests/browser/node_modules",
    "infra/nakama/node_modules",
)


def lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def ensure_inside(path: Path, repo_root: Path) -> Path:
    root = lexical_absolute(repo_root)
    target = lexical_absolute(path)
    if target == root or not target.is_relative_to(root):
        raise ValueError(f"refusing cleanup outside the repository: {target}")
    return target


def collect_targets(repo_root: Path, *, deep: bool = False) -> list[Path]:
    root = lexical_absolute(repo_root)
    candidates = [root / relative for relative in ROOT_OUTPUTS]

    for family in ("games", "templates"):
        family_root = root / family
        if not family_root.is_dir():
            continue
        for project_file in family_root.glob("*/project/project.godot"):
            project = project_file.parent
            candidates.extend(project / relative for relative in PROJECT_OUTPUTS)
        for manifest in family_root.glob("*/server/Cargo.toml"):
            candidates.append(manifest.parent / "target")

    candidates.append(root / "services" / "target")
    for search_root in (root / "tools", root / "scripts", root / "engine"):
        if search_root.is_dir():
            candidates.extend(
                path
                for path in search_root.rglob("__pycache__")
                if ".venv" not in path.parts and ".cache" not in path.parts
            )
    if deep:
        candidates.extend(root / relative for relative in DEEP_OUTPUTS)

    unique = {
        ensure_inside(path, root) for path in candidates if path.exists() or path.is_symlink()
    }
    return sorted(unique, key=lambda path: path.as_posix())


def _clear_readonly(function, path: str, _error) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def remove_tree(path: Path, *, retries: int = 6, delay: float = 0.2) -> None:
    """Remove a tree, tolerating short-lived Windows executable/AV locks."""
    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_clear_readonly)
            return
        except PermissionError:
            if attempt + 1 >= retries:
                raise
            time.sleep(delay * (attempt + 1))


def remove_target(path: Path, repo_root: Path, *, dry_run: bool = False) -> None:
    target = ensure_inside(path, repo_root)
    if dry_run:
        return
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        remove_tree(target)


def clean(repo_root: Path, *, deep: bool = False, dry_run: bool = False) -> list[Path]:
    targets = collect_targets(repo_root, deep=deep)
    for target in targets:
        remove_target(target, repo_root, dry_run=dry_run)
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="list outputs without removing them")
    parser.add_argument(
        "--deep",
        action="store_true",
        help="also remove dependency/engine caches (.venv, node_modules, engine cache)",
    )
    args = parser.parse_args()
    try:
        targets = clean(REPO_ROOT, deep=args.deep, dry_run=args.dry_run)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    action = "would remove" if args.dry_run else "removed"
    for target in targets:
        print(f"{action}: {target.relative_to(REPO_ROOT)}")
    print(f"{action} {len(targets)} generated path(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
