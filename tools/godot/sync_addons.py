#!/usr/bin/env python3
"""Sync shared Godot addons + protocol fixtures into game projects.

shared/godot-addons/* is the single source of truth; every game project's
addons/ copy is GENERATED (gitignored, pre-commit-protected). Run after any
addon change: `just godot-sync-addons`.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402

ADDONS_SRC = senv.repo_root() / "shared" / "godot-addons"
FIXTURES_SRC = senv.repo_root() / "shared" / "protocol" / "fixtures"


def game_projects() -> list[Path]:
    projects = [senv.repo_root() / "templates" / "godot-game" / "project"]
    games_dir = senv.repo_root() / "games"
    if games_dir.is_dir():
        for game in sorted(games_dir.iterdir()):
            project = game / "project"
            if (project / "project.godot").is_file():
                projects.append(project)
    return [p for p in projects if (p / "project.godot").is_file()]


def sync_project(project: Path) -> None:
    for addon_dir in sorted(ADDONS_SRC.iterdir()):
        if not addon_dir.is_dir():
            continue
        dest = project / "addons" / addon_dir.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(addon_dir, dest)
        # Golden protocol fixtures ride along inside the synced addon so
        # res:// tests can reach them (res:// cannot escape the project).
        fixtures_dest = dest / "testing" / "fixtures"
        fixtures_dest.mkdir(parents=True, exist_ok=True)
        for fixture in FIXTURES_SRC.glob("*.json"):
            shutil.copy2(fixture, fixtures_dest / fixture.name)
    print(f"synced addons -> {project.relative_to(senv.repo_root())}")


def main() -> int:
    projects = game_projects()
    if not projects:
        print("no game projects found", file=sys.stderr)
        return 1
    for project in projects:
        sync_project(project)
    return 0


if __name__ == "__main__":
    sys.exit(main())
