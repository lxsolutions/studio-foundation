#!/usr/bin/env python3
"""Scan reviewable working-tree files for credential patterns without printing secrets."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "tools" / "hooks"
sys.path.insert(0, str(HOOKS))

from pre_commit import (  # noqa: E402
    SECRET_EXEMPT_SUFFIXES,
    SECRET_EXEMPT_VALUES,
    SECRET_PATTERNS,
)


def reviewable_paths(repo: Path = REPO) -> list[Path]:
    """Return tracked and non-ignored untracked paths from Git."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed: {message or result.returncode}")
    return [
        Path(raw.decode("utf-8", errors="surrogateescape"))
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def path_problem(path: Path) -> str | None:
    """Return a policy finding for forbidden environment files."""
    posix = path.as_posix()
    if posix == ".env" or posix.startswith(".env.") and not posix.endswith(".example"):
        return "environment file"
    return None


def scan_text(text: str) -> list[str]:
    """Return credential labels found in text; never return matched values."""
    findings: list[str] = []
    for pattern, label in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0)
            if any(exempt in value for exempt in SECRET_EXEMPT_VALUES):
                continue
            findings.append(label)
            break
    return findings


def scan_bytes(path: Path, content: bytes) -> list[str]:
    """Scan text-like bytes, honoring the hook's documented file exemptions."""
    if path.as_posix().endswith(SECRET_EXEMPT_SUFFIXES):
        return []
    if b"\0" in content[:8000]:
        return []
    return scan_text(content.decode("utf-8", errors="replace"))


def scan_repository(repo: Path = REPO, paths: list[Path] | None = None) -> list[tuple[Path, str]]:
    findings: list[tuple[Path, str]] = []
    for relative in paths if paths is not None else reviewable_paths(repo):
        policy_problem = path_problem(relative)
        if policy_problem is not None:
            findings.append((relative, policy_problem))
            continue
        absolute = repo / relative
        if not absolute.is_file():
            continue
        for label in scan_bytes(relative, absolute.read_bytes()):
            findings.append((relative, f"possible {label}"))
    return findings


def main() -> int:
    try:
        paths = reviewable_paths()
        findings = scan_repository(paths=paths)
    except (OSError, RuntimeError) as error:
        print(f"[secret-scan] ERROR: {error}", file=sys.stderr)
        return 2
    if findings:
        for path, label in findings:
            print(f"[secret-scan] FAIL {path.as_posix()}: {label}", file=sys.stderr)
        print(f"[secret-scan] blocked: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print(f"[secret-scan] ok ({len(paths)} reviewable files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
