#!/usr/bin/env python3
"""Validate public current-state claims against the engine provenance lock."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parents[2]
LOCK_PATH = Path("engine/engine-lock.toml")
README_PATH = Path("README.md")
EVIDENCE_PATH = Path("docs/architecture/webgpu-evidence.md")
PAGES_PATH = Path("docs/pages/index.html")

CURRENT_STATUS_MARKER = "public-evidence-current-status"
P0014_ASSET_MARKER = "public-evidence-p0014-assets"

PINNED_DOCS = (
    Path("README.md"),
    Path("NOTICE.md"),
    Path("docs/architecture/webgpu-integration.md"),
    Path("docs/architecture/webgpu-evidence.md"),
)
LINK_CHECK_DOCS = (
    Path("README.md"),
    Path("BOOTSTRAP_REPORT.md"),
    Path("NOTICE.md"),
    Path("engine/README.md"),
    Path("engine/patches/README.md"),
    Path("docs/adr/0002-webgpu-patch-series.md"),
    Path("docs/adr/0008-own-the-distribution-not-the-engine.md"),
    Path("docs/architecture/webgpu-evidence.md"),
    Path("docs/architecture/webgpu-integration.md"),
    Path("docs/architecture/webgpu-payload-and-startup.md"),
    Path("docs/architecture/webgpu-performance.md"),
    Path("docs/architecture/webgpu-runtime-status.md"),
    Path("docs/pages/README.md"),
    Path("docs/runbooks/godot-webgpu-update.md"),
)
REQUIRED_PAGES_LINKS = (
    "demo/index.html",
    "showcase/index.html",
    "https://github.com/lxsolutions/studio-foundation",
    "https://github.com/lxsolutions/studio-foundation/releases/tag/godot-4.7.1-webgpu-p0014",
    "https://github.com/lxsolutions/studio-foundation/blob/main/"
    "docs/architecture/webgpu-evidence.md",
)
CURRENT_STATUS_STALE_PHRASES = (
    "currently 14 patches",
    "13 patches",
    "patch series (0001–0013)",
    "forward+ not hardware tested",
    "forward+ has never been hardware tested",
    "forward+ translates but has not been run",
    "no accepted artifacts",
    "no public game proof",
    "game source unavailable",
    "game content is not published",
    "browser verification pending",
    "3d verification pending",
    "no downloadable templates",
    "source is not reproducible",
)

MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")


def read_text(root: Path, relative: Path) -> str:
    return (root / relative).read_text(encoding="utf-8")


def read_lock(root: Path) -> dict:
    with (root / LOCK_PATH).open("rb") as handle:
        return tomllib.load(handle)


def marked_section(text: str, marker: str) -> str:
    start = f"<!-- {marker}:start -->"
    end = f"<!-- {marker}:end -->"
    if start not in text or end not in text:
        raise ValueError(f"missing marker pair: {marker}")
    section = text.split(start, 1)[1].split(end, 1)[0]
    if not section.strip():
        raise ValueError(f"empty marked section: {marker}")
    return section


def patch_number(entry: dict) -> int:
    filename = Path(str(entry.get("file", ""))).name
    match = re.match(r"(\d{4})-", filename)
    if match is None:
        raise ValueError(f"patch filename lacks a four-digit prefix: {filename}")
    return int(match.group(1))


def public_release(lock: dict) -> dict:
    return lock.get("releases", {}).get("godot_4_7_1_webgpu_p0014", {})


def forward_plus_development(lock: dict) -> dict:
    return lock.get("development", {}).get("webgpu_forward_plus", {})


def validate_current_table(readme: str, lock: dict) -> list[str]:
    problems: list[str] = []
    try:
        section = marked_section(readme, CURRENT_STATUS_MARKER)
    except ValueError as exc:
        return [str(exc)]

    series = lock.get("patches", {}).get("series", [])
    if not series:
        return ["engine lock has no patch series"]
    count = len(series)
    last = patch_number(series[-1])
    official = str(lock.get("godot", {}).get("official", {}).get("commit", ""))
    release = public_release(lock)
    release_tag = str(release.get("tag", ""))
    release_through = release.get("patch_through")
    forward_plus = forward_plus_development(lock)
    validation_errors = forward_plus.get("gpu_validation_errors")

    required = (
        (official, "official Godot commit"),
        (f"`0001–{last:04d}` ({count} patches)", "current-main patch range/count"),
        (release_tag, "published release tag"),
        (
            f"`0001–{int(release_through):04d}` ({int(release_through)} patches)"
            if isinstance(release_through, int)
            else "",
            "published patch range/count",
        ),
        (
            f"no p{last:04d} templates are published",
            "unpublished current-main artifact status",
        ),
        (
            f"{validation_errors} `GPUValidationError` entries remain",
            "current Forward+ error count",
        ),
        ("no frame renders", "current Forward+ render limitation"),
    )
    for needle, label in required:
        if not needle or needle not in section:
            problems.append(f"README current-status table is missing {label}: {needle!r}")

    lowered = section.casefold()
    for phrase in CURRENT_STATUS_STALE_PHRASES:
        if phrase.casefold() in lowered:
            problems.append(f"README current-status table contains stale phrase: {phrase!r}")
    return problems


def validate_pins(public_docs: dict[Path, str], lock: dict) -> list[str]:
    problems: list[str] = []
    official = str(lock.get("godot", {}).get("official", {}).get("commit", ""))
    lineage = str(lock.get("godot", {}).get("webgpu", {}).get("source_lineage_commit", ""))
    for path, text in public_docs.items():
        if official not in text:
            problems.append(f"{path.as_posix()} does not contain the locked official commit")
        if path != README_PATH and lineage not in text:
            problems.append(f"{path.as_posix()} does not contain the locked lineage commit")
    return problems


def validate_attribution(readme: str, pages: str) -> list[str]:
    problems: list[str] = []
    for label, text in (("README.md", readme), ("docs/pages/index.html", pages)):
        required = (
            "David Walter",
            "dwalter/godotwebgpu",
            "Studio Foundation maintains",
            "Official Godot",
            "upstream",
        )
        for phrase in required:
            if phrase not in text:
                problems.append(f"{label} is missing required attribution text: {phrase!r}")
    return problems


def validate_release_boundary(lock: dict) -> list[str]:
    problems: list[str] = []
    series = lock.get("patches", {}).get("series", [])
    release = public_release(lock)
    provenance = lock.get("artifacts", {}).get("export_templates_provenance", {})
    forward_plus = forward_plus_development(lock)
    official = lock.get("godot", {}).get("official", {}).get("commit")

    if release.get("tag") != "godot-4.7.1-webgpu-p0014":
        problems.append("published release tag must be godot-4.7.1-webgpu-p0014")
    if release.get("patch_through") != 14:
        problems.append("published p0014 release must stop at patch 14")
    if provenance.get("patch_through") != 14:
        problems.append("locally accepted template provenance must stop at patch 14")
    if release.get("official_commit") != official:
        problems.append("published p0014 official commit must match godot.official.commit")
    if release.get("renderer") != "Forward Mobile":
        problems.append("published p0014 renderer must be Forward Mobile")
    if series and release.get("patch_through") == len(series):
        problems.append(
            "published p0014 release must not implicitly inherit the current-main patch count"
        )
    if forward_plus.get("patch_through") != len(series):
        problems.append("Forward+ development evidence must match the current patch count")
    if forward_plus.get("hardware_tested") is not True:
        problems.append("Forward+ development evidence must record hardware_tested = true")
    validation_errors = forward_plus.get("gpu_validation_errors")
    if (
        not isinstance(validation_errors, int)
        or isinstance(validation_errors, bool)
        or validation_errors < 0
    ):
        problems.append("Forward+ gpu_validation_errors must be a non-negative integer")
    if forward_plus.get("rendered_frame") is not False:
        problems.append("Forward+ development evidence must not claim a rendered frame")
    if forward_plus.get("published_templates") is not False:
        problems.append("Forward+ development evidence must not claim published templates")
    return problems


def validate_release_assets(evidence: str, lock: dict) -> list[str]:
    problems: list[str] = []
    try:
        section = marked_section(evidence, P0014_ASSET_MARKER)
    except ValueError as exc:
        return [str(exc)]

    release = public_release(lock)
    for key in ("web_webgpu_release", "web_webgpu_debug"):
        record = release.get(key)
        if not isinstance(record, dict):
            problems.append(f"published release lock record is missing: {key}")
            continue
        filename = str(record.get("file", ""))
        digest = str(record.get("sha256", ""))
        byte_count = record.get("bytes")
        formatted_bytes = f"{byte_count:,}" if isinstance(byte_count, int) else ""
        for needle, label in (
            (filename, "filename"),
            (digest, "SHA-256"),
            (formatted_bytes, "byte count"),
        ):
            if not needle or needle not in section:
                problems.append(f"evidence matrix {key} does not match lock {label}")
    return problems


def validate_pages(pages: str, lock: dict) -> list[str]:
    problems: list[str] = []
    series = lock.get("patches", {}).get("series", [])
    release_through = public_release(lock).get("patch_through")
    forward_plus = forward_plus_development(lock)
    validation_errors = forward_plus.get("gpu_validation_errors")
    last = patch_number(series[-1]) if series else 0

    for needle, label in (
        (f'data-current-main-patches="{len(series)}"', "current-main patch count"),
        (f'data-published-patch-through="{release_through}"', "published patch count"),
        (f"<code>0001–{last:04d}</code>", "current-main patch range"),
        (f"{validation_errors} validation errors remain", "Forward+ validation count"),
        ("no frame renders", "Forward+ render limitation"),
    ):
        if needle not in pages:
            problems.append(f"Pages source is missing {label}: {needle!r}")
    for link in REQUIRED_PAGES_LINKS:
        if link not in pages:
            problems.append(f"Pages source is missing required public link: {link}")

    lowered = pages.casefold()
    for phrase in CURRENT_STATUS_STALE_PHRASES:
        if phrase.casefold() in lowered:
            problems.append(f"Pages source contains stale phrase: {phrase!r}")
    return problems


def validate_forward_plus_evidence(evidence: str, lock: dict) -> list[str]:
    problems: list[str] = []
    forward_plus = forward_plus_development(lock)
    for needle, label in (
        (
            f"patch {forward_plus.get('patch_through'):04d}",
            "Forward+ patch checkpoint",
        ),
        (
            f"{forward_plus.get('gpu_validation_errors')} `GPUValidationError` entries remain",
            "Forward+ validation count",
        ),
        ("no frame renders", "Forward+ render limitation"),
        ("no published templates", "Forward+ publication limitation"),
    ):
        if needle not in evidence:
            problems.append(f"evidence matrix is missing {label}: {needle!r}")
    return problems


def markdown_link_problems(root: Path, relative: Path, text: str) -> list[str]:
    problems: list[str] = []
    for raw_target in MARKDOWN_LINK.findall(text):
        target = raw_target.strip().strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:", "data:")):
            continue
        path_part = unquote(target.split("#", 1)[0])
        if not path_part:
            continue
        resolved = (root / relative.parent / path_part).resolve()
        if not resolved.is_relative_to(root.resolve()):
            problems.append(f"{relative.as_posix()}: link escapes repository: {target}")
        elif not resolved.exists():
            problems.append(f"{relative.as_posix()}: broken local link: {target}")
    return problems


def validate(root: Path = REPO) -> list[str]:
    lock = read_lock(root)
    readme = read_text(root, README_PATH)
    evidence = read_text(root, EVIDENCE_PATH)
    pages = read_text(root, PAGES_PATH)
    pinned_docs = {path: read_text(root, path) for path in PINNED_DOCS}

    problems: list[str] = []
    problems.extend(validate_current_table(readme, lock))
    problems.extend(validate_pins(pinned_docs, lock))
    problems.extend(validate_attribution(readme, pages))
    problems.extend(validate_release_boundary(lock))
    problems.extend(validate_release_assets(evidence, lock))
    problems.extend(validate_forward_plus_evidence(evidence, lock))
    problems.extend(validate_pages(pages, lock))
    for relative in LINK_CHECK_DOCS:
        problems.extend(markdown_link_problems(root, relative, read_text(root, relative)))
    return problems


def main() -> int:
    try:
        problems = validate()
        lock = read_lock(REPO)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"public evidence validation failed: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("public evidence validation failed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    patch_count = len(lock["patches"]["series"])
    release_through = public_release(lock)["patch_through"]
    print(
        "public evidence OK: "
        f"{patch_count} current patches, p0014 through patch {release_through:04d}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
