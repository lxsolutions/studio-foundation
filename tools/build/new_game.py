#!/usr/bin/env python3
"""Generate a new game from the tracked Godot/Rust template."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_REL = Path("templates/godot-game")
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
SKIP_PARTS = {".godot", "addons", "captures"}


def validate_inputs(name: str, display_name: str) -> tuple[str, str]:
    name = name.strip()
    display_name = display_name.strip()
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("name must use lowercase snake_case and start with a letter")
    if len(name) > 48:
        raise ValueError("name must be 48 characters or fewer")
    if name in WINDOWS_RESERVED or name == "studio_game_template":
        raise ValueError(f"name is reserved: {name}")
    if not display_name:
        raise ValueError("display name must not be empty")
    if len(display_name) > 80:
        raise ValueError("display name must be 80 characters or fewer")
    if any(character in display_name for character in ('"', "\\", "\n", "\r")):
        raise ValueError("display name must not contain quotes, backslashes, or newlines")
    return name, display_name


def bundle_id(name: str) -> str:
    """Return an Android/iOS-safe identifier shared by both export presets."""
    return "org.studio." + name.replace("_", "")


def tracked_template_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", TEMPLATE_REL.as_posix()],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    prefix = TEMPLATE_REL.as_posix() + "/"
    files = []
    for raw_path in result.stdout.decode("utf-8").split("\0"):
        if raw_path:
            files.append(Path(raw_path.removeprefix(prefix)))
    return files


def should_copy(relative: Path) -> bool:
    return not any(part in SKIP_PARTS for part in relative.parts) and relative.suffix != ".import"


def render_bytes(data: bytes, name: str, display_name: str) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    replacements = {
        "studio_game_template": name,
        "Studio Game Template": display_name,
        "org.studio.template": bundle_id(name),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("utf-8")


def copy_template(
    template_root: Path,
    destination: Path,
    relative_files: Iterable[Path],
    name: str,
    display_name: str,
) -> int:
    copied = 0
    for relative in relative_files:
        if not should_copy(relative):
            continue
        source = template_root / relative
        if not source.is_file():
            raise FileNotFoundError(f"tracked template file is missing: {source}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        rendered = render_bytes(source.read_bytes(), name, display_name)
        target.write_bytes(rendered)
        shutil.copystat(source, target)
        copied += 1
    return copied


def reset_build_info(project: Path) -> None:
    payload = {
        "version": "0.1.0+dev",
        "git_commit": "unknown",
        "built_at": "",
        "channel": "dev",
    }
    (project / "build_info.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def sync_shared_addon(repo_root: Path, project: Path) -> None:
    addons_root = repo_root / "shared" / "godot-addons"
    fixtures_root = repo_root / "shared" / "protocol" / "fixtures"
    if not addons_root.is_dir():
        raise FileNotFoundError(f"shared addon source is missing: {addons_root}")
    for addon in sorted(path for path in addons_root.iterdir() if path.is_dir()):
        destination = project / "addons" / addon.name
        shutil.copytree(addon, destination)
        fixtures_destination = destination / "testing" / "fixtures"
        fixtures_destination.mkdir(parents=True, exist_ok=True)
        for fixture in sorted(fixtures_root.glob("*.json")):
            shutil.copy2(fixture, fixtures_destination / fixture.name)


def generate_game(
    name: str,
    display_name: str,
    *,
    repo_root: Path = REPO_ROOT,
    games_root: Path | None = None,
    relative_files: Iterable[Path] | None = None,
) -> Path:
    name, display_name = validate_inputs(name, display_name)
    template_root = repo_root / TEMPLATE_REL
    games_root = games_root or repo_root / "games"
    destination = games_root / name
    if destination.exists():
        raise FileExistsError(f"game already exists: {destination}")
    if not template_root.is_dir():
        raise FileNotFoundError(f"game template is missing: {template_root}")

    games_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=games_root))
    try:
        files = (
            list(relative_files)
            if relative_files is not None
            else tracked_template_files(repo_root)
        )
        copied = copy_template(template_root, staging, files, name, display_name)
        if copied == 0:
            raise RuntimeError("game template contained no source files")
        reset_build_info(staging / "project")
        sync_shared_addon(repo_root, staging / "project")
        staging.replace(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    try:
        destination = generate_game(args.name, args.display_name)
    except (
        ValueError,
        FileExistsError,
        FileNotFoundError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    relative = destination.relative_to(REPO_ROOT).as_posix()
    print(f"generated {relative}")
    print(f"next: just GAME={relative} test-godot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
