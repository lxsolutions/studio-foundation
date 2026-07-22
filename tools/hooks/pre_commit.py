#!/usr/bin/env python3
"""Pre-commit guardrails (fast, stdlib-only; enable with `just hooks-install`).

Blocks: committed secrets, large binaries outside approved asset locations, direct
edits to generated directories, modified (vs added) migrations, bad migration names,
.blend masters without metadata sidecars, and .env files.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MAX_PLAIN_BYTES = 2 * 1024 * 1024  # 2 MiB anywhere
MAX_ASSET_BYTES = 25 * 1024 * 1024  # 25 MiB in approved asset dirs
APPROVED_BINARY_DIRS = ("assets-source/", "shared/test-fixtures/", "docs/")
GENERATED_MARKERS = ("assets-generated/", "/assets/generated/", "/addons/studio_core/", "exports/")
MIGRATION_RE = re.compile(r"^\d{4}_[a-z0-9_]+\.sql$")
SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key block"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}T3BlbkFJ[A-Za-z0-9]{20,}\b"), "OpenAI API key"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "Slack token"),
    (
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"][^'\"\s]{16,}['\"]"
        ),
        "hardcoded credential",
    ),
]
SECRET_EXEMPT_SUFFIXES = (".example", ".md")
SECRET_EXEMPT_VALUES = (
    "studio_dev_password",
    "studio_test_password",
    "studio_dev_readonly",
    "changeme",
    "placeholder",
)


def sh(args: list[str]) -> str:
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout


def main() -> int:
    status = sh(["git", "diff", "--cached", "--name-status", "--no-renames"]).strip()
    if not status:
        return 0
    problems: list[str] = []
    entries = [line.split("\t", 1) for line in status.splitlines() if "\t" in line]

    for state, path in entries:
        posix = path.replace("\\", "/")

        if posix == ".env" or posix.startswith(".env.") and not posix.endswith(".example"):
            problems.append(f"{path}: .env files must never be committed")
            continue
        if state == "D":
            continue

        if any(marker in posix for marker in GENERATED_MARKERS):
            problems.append(f"{path}: generated directory — outputs are never source (GOAL.md #11)")
            continue

        if "/migrations/" in posix and posix.endswith(".sql"):
            name = posix.rsplit("/", 1)[-1]
            if not MIGRATION_RE.match(name):
                problems.append(f"{path}: migration name must be NNNN_snake_case.sql")
            if state == "M":
                problems.append(
                    f"{path}: never edit an applied migration — add a new one (ADR 0005)"
                )

        # size guard
        try:
            blob = subprocess.run(
                ["git", "cat-file", "-s", f":{path}"], capture_output=True, text=True
            ).stdout.strip()
            size = int(blob) if blob else 0
        except ValueError:
            size = 0
        limit = MAX_ASSET_BYTES if posix.startswith(APPROVED_BINARY_DIRS) else MAX_PLAIN_BYTES
        if size > limit:
            problems.append(
                f"{path}: {size // 1024} KiB exceeds {limit // 1024} KiB limit for this location"
            )

        if posix.endswith(".blend"):
            meta = Path(path).with_suffix("")  # crate_a.blend -> crate_a
            meta_json = str(meta) + ".meta.json"
            staged = {p for _, p in entries}
            if (
                meta_json.replace("\\", "/") not in {s.replace("\\", "/") for s in staged}
                and not Path(meta_json).is_file()
            ):
                problems.append(f"{path}: master asset requires sidecar {meta_json} (ADR 0006)")

        # secret scan on text-ish staged content
        if not posix.endswith(SECRET_EXEMPT_SUFFIXES):
            content = sh(["git", "show", f":{path}"])
            if content and "\x00" not in content[:8000]:
                for pattern, label in SECRET_PATTERNS:
                    for m in pattern.finditer(content):
                        snippet = m.group(0)
                        if any(x in snippet for x in SECRET_EXEMPT_VALUES):
                            continue
                        problems.append(f"{path}: possible {label} — remove before committing")
                        break

    if problems:
        print("pre-commit: BLOCKED\n", file=sys.stderr)
        for p in problems:
            print(f"  * {p}", file=sys.stderr)
        print(
            "\nFix the issues (or, for a true false positive, commit with --no-verify and "
            "say why in the PR description).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
