#!/usr/bin/env python3
"""Validate release pins, licenses, manifests, and source-tree cleanliness."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402
from studio_tools.release import NOASSERTION, InventoryError, collect_inventory  # noqa: E402

APPROVED_LICENSE_IDS = {
    "0BSD",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "BSL-1.0",
    "CC0-1.0",
    "CDLA-Permissive-2.0",
    "ISC",
    "LLVM-exception",
    "MIT",
    "MIT-0",
    "PostgreSQL",
    "Unicode-3.0",
    "Unlicense",
    "Zlib",
}
REQUIRED_PATHS = (
    "LICENSE",
    "NOTICE.md",
    "games/LICENSE",
    "docs/adr/0013-dependency-license-policy.md",
    "docs/architecture/dependency-licenses.md",
    "engine/engine-lock.toml",
    "services/Cargo.lock",
    "templates/godot-game/server/Cargo.lock",
    "tools/uv.lock",
    "tests/browser/package-lock.json",
    "tools/release/audit_deps.py",
    "tools/release/attribution.py",
    "tools/release/make_sbom.py",
)


def license_ids(expression: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9.-]*", expression)
        if token not in {"AND", "OR", "WITH"}
    }


def license_expression_is_approved(expression: str) -> bool:
    # Older Cargo manifests used MIT/Apache-2.0 before SPDX required explicit OR.
    expression = expression.replace("/", " OR ")
    tokens = re.findall(
        r"\(|\)|AND|OR|WITH|[A-Za-z0-9][A-Za-z0-9.+-]*",
        expression,
    )
    if "".join(tokens) != re.sub(r"\s+", "", expression):
        return False
    position = 0

    def primary() -> bool:
        nonlocal position
        if position >= len(tokens):
            raise ValueError("unexpected end of license expression")
        token = tokens[position]
        position += 1
        if token == "(":
            value = disjunction()
            if position >= len(tokens) or tokens[position] != ")":
                raise ValueError("unclosed license expression")
            position += 1
            return value
        if token in {"AND", "OR", "WITH", ")"}:
            raise ValueError(f"unexpected token {token}")
        return token in APPROVED_LICENSE_IDS

    def with_exception() -> bool:
        nonlocal position
        value = primary()
        while position < len(tokens) and tokens[position] == "WITH":
            position += 1
            value = primary() and value
        return value

    def conjunction() -> bool:
        nonlocal position
        value = with_exception()
        while position < len(tokens) and tokens[position] == "AND":
            position += 1
            value = with_exception() and value
        return value

    def disjunction() -> bool:
        nonlocal position
        value = conjunction()
        while position < len(tokens) and tokens[position] == "OR":
            position += 1
            value = conjunction() or value
        return value

    try:
        approved = disjunction()
    except ValueError:
        return False
    return approved and position == len(tokens)


def validate_engine_lock(root: Path) -> list[str]:
    path = root / "engine" / "engine-lock.toml"
    with path.open("rb") as handle:
        lock = tomllib.load(handle)
    problems = []
    official = lock.get("godot", {}).get("official", {})
    integration = lock.get("godot", {}).get("webgpu", {})

    for label, value in (
        ("godot.official.commit", official.get("commit")),
        ("godot.webgpu.base_commit", integration.get("base_commit")),
        ("godot.webgpu.source_lineage_commit", integration.get("source_lineage_commit")),
        (
            "godot.webgpu.historical_tree_commit",
            integration.get("historical_tree_commit"),
        ),
    ):
        if not re.fullmatch(r"[0-9a-f]{40}", str(value or "")):
            problems.append(f"engine pin {label} must be a full SHA-1")
    if integration.get("base_commit") != official.get("commit"):
        problems.append("godot.webgpu.base_commit must match godot.official.commit")
    for label, entry in (("godot.official", official), ("godot.webgpu", integration)):
        if not entry.get("license"):
            problems.append(f"engine pin {label}.license is missing")

    patch_root = (root / "engine" / "patches").resolve()
    series = lock.get("patches", {}).get("series", [])
    if not series:
        problems.append("engine patch series must not be empty")
    for index, entry in enumerate(series, start=1):
        relative = str(entry.get("file", "")).replace("\\", "/")
        raw_expected = str(entry.get("sha256", ""))
        expected = raw_expected.lower()
        patch = (root / "engine" / relative).resolve()
        if not patch.is_relative_to(patch_root):
            problems.append(f"engine patch {index} escapes engine/patches")
            continue
        if not patch.is_file():
            problems.append(f"engine patch is missing: {relative}")
            continue
        if raw_expected != expected or not re.fullmatch(r"[0-9a-f]{64}", expected):
            problems.append(f"engine patch {relative} requires a lowercase SHA-256")
            continue
        with patch.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != expected:
            problems.append(
                f"engine patch checksum mismatch for {relative}: expected {expected}, got {actual}"
            )
    return problems


def validate_game_manifests(root: Path) -> list[str]:
    problems = []
    for manifest in sorted((root / "games").glob("*/server/Cargo.toml")):
        with manifest.open("rb") as handle:
            package = tomllib.load(handle).get("package", {})
        label = manifest.relative_to(root)
        if package.get("publish") is not False:
            problems.append(f"{label}: proprietary game server must set publish = false")
        license_file = package.get("license-file")
        if not license_file:
            problems.append(f"{label}: proprietary game server must use games/LICENSE")
            continue
        resolved = (manifest.parent / str(license_file)).resolve()
        if resolved != (root / "games" / "LICENSE").resolve():
            problems.append(f"{label}: license-file must resolve to games/LICENSE")
    return problems


def validate_inventory(root: Path) -> list[str]:
    problems = []
    for component in collect_inventory(root):
        if component.local:
            continue
        if component.license == NOASSERTION:
            problems.append(f"{component.purl}: missing declared license")
            continue
        if not license_expression_is_approved(component.license):
            unknown = license_ids(component.license) - APPROVED_LICENSE_IDS
            problems.append(
                f"{component.purl}: no approved license choice"
                + (f" (unreviewed: {', '.join(sorted(unknown))})" if unknown else "")
            )
    return problems


def tree_is_clean(root: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return False, (proc.stdout + proc.stderr).strip()
    return not proc.stdout.strip(), proc.stdout.strip()


def validate(root: Path, allow_dirty: bool = False) -> list[str]:
    problems = [
        f"missing required release input: {relative}"
        for relative in REQUIRED_PATHS
        if not (root / relative).is_file()
    ]
    if not problems:
        problems.extend(validate_engine_lock(root))
        problems.extend(validate_game_manifests(root))
        problems.extend(validate_inventory(root))
    if not allow_dirty:
        clean, detail = tree_is_clean(root)
        if not clean:
            problems.append("working tree is not clean" + (f":\n{detail}" if detail else ""))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-dirty", action="store_true", help="skip only the clean-tree gate")
    args = parser.parse_args(argv)
    root = senv.repo_root().resolve()
    try:
        problems = validate(root, allow_dirty=args.allow_dirty)
    except (InventoryError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"release validation failed: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("release validation failed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    scope = "pins, manifests, and licenses"
    if not args.allow_dirty:
        scope = "clean tree, " + scope
    print(f"release validation ok: {scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
