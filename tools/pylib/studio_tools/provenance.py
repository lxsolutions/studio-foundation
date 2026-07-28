"""Build provenance for the WebGPU patch series.

Two halves, for two different situations:

*Stamping* is cooperative. A build produced from this repository records what it
was made of — base engine commit, the ordered patch series, toolchain pins — as
a `provenance.json` next to the artifact. Anyone can recompute the series id from
the public repository and confirm the stamp is honest.

*Detection* is heuristic, and applies when no stamp is available. The patch
series introduces strings that stock Godot does not contain, so `scan_artifact`
reports which of them a build carries and `classify` turns that into a lineage
indication.

Be honest about its strength. In the calibration recorded in the marker table it
found 11/11 expected markers in a Studio build and none in the stock Godot 4.7.1
web template, which is useful discrimination for those two artifacts. It does not
follow that every derivative is detectable — strings can be rewritten, optimised
away, or independently coincide — nor that a match establishes legal
noncompliance. A positive result is evidence worth investigating, not a verdict.

The point is not to threaten anyone. MIT already requires the notice; this makes
compliance something you can check and, via `required_attribution`, something you
can satisfy by copying two paragraphs.

Stdlib only, by repository policy.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SERIES_ID_PREFIX = "sfwebgpu-1"
MARKERS_FILE = "webgpu-markers.json"

# Artifacts worth scanning inside an export directory or template zip. A release
# wasm is the interesting one; the JS shell and the pck are cheap to check too.
SCANNABLE_SUFFIXES = (".wasm", ".js", ".pck", ".zip", ".html")

# Cap per-file reads so a hostile or merely enormous artifact cannot exhaust
# memory. Engine wasm is ~45 MB; 512 MB is far above anything legitimate.
MAX_SCAN_BYTES = 512 * 1024 * 1024


class ProvenanceError(RuntimeError):
    """Provenance could not be computed, stamped, or verified."""


@dataclass(frozen=True)
class Marker:
    """One byte string the patch series puts into a built engine.

    `tier` is what finding it proves:
      webgpu-backend  a Godot WebGPU rendering backend is present at all, which
                      stock Godot has never shipped. Lineage runs back to
                      dwalter/godotwebgpu.
      studio-series   this specific Studio Foundation 4.7.1 series, from patches
                      0004+ — work that exists nowhere else.
    """

    name: str
    tier: str
    pattern: bytes
    introduced_by: str
    note: str = ""


@dataclass
class ScanResult:
    path: Path
    scanned_files: list[str] = field(default_factory=list)
    hits: dict[str, list[str]] = field(default_factory=dict)  # marker name -> files
    stamp: dict | None = None
    skipped: list[str] = field(default_factory=list)

    def tier_hits(self, markers: list[Marker], tier: str) -> list[str]:
        by_name = {m.name: m for m in markers}
        return sorted(n for n in self.hits if by_name[n].tier == tier)


# --------------------------------------------------------------------------- id


def series_id(base_commit: str, patches: list[tuple[str, str]]) -> str:
    """Deterministic id for an ordered patch series.

    `patches` is [(relative path, sha256)] in apply order. Order is part of the
    identity: the same patches applied in a different order are a different
    engine, and 0016 proved that empirically.

    Anyone can recompute this from the public repository, which is the point —
    a stamp nobody can independently derive proves nothing.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", base_commit or ""):
        raise ProvenanceError(f"base commit must be a full 40-hex sha: {base_commit!r}")
    if not patches:
        raise ProvenanceError("a series with no patches has no identity")

    # Fields are length-prefixed rather than delimiter-joined. With a plain
    # separator, a patch whose *filename* contained that separator could hash
    # identically to a different series -- the encoding has to be injective, not
    # merely readable.
    parts = [
        SERIES_ID_PREFIX.encode("ascii"),
        b"\x00base\x00",
        base_commit.encode("ascii"),
        f"\x00n{len(patches)}\x00".encode("ascii"),
    ]
    for relative, digest in patches:
        normalized = relative.replace("\\", "/").encode("utf-8")
        if not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
            raise ProvenanceError(f"patch {relative} needs a lowercase sha256")
        parts.append(f"{len(normalized)}:".encode("ascii"))
        parts.append(normalized)
        parts.append(digest.encode("ascii"))
    return f"{SERIES_ID_PREFIX}:{hashlib.sha256(b''.join(parts)).hexdigest()[:16]}"


def series_from_lock(lock: dict) -> tuple[str, list[tuple[str, str]]]:
    """Pull (base commit, ordered patches) straight out of engine-lock.toml."""
    try:
        base = lock["godot"]["webgpu"]["base_commit"]
    except (KeyError, TypeError) as exc:
        raise ProvenanceError("engine-lock.toml has no [godot.webgpu] base_commit") from exc
    series = lock.get("patches", {}).get("series", [])
    if not series:
        raise ProvenanceError("engine-lock.toml has no patch series")
    return base, [(str(e.get("file", "")), str(e.get("sha256", ""))) for e in series]


# ----------------------------------------------------------------------- stamp


def build_stamp(lock: dict, *, artifact: dict | None = None) -> dict:
    """The provenance record written beside a build."""
    base, patches = series_from_lock(lock)
    webgpu = lock["godot"]["webgpu"]
    toolchain = lock.get("toolchain", {})
    stamp = {
        "schema": 1,
        "kind": "studio-foundation-webgpu-build",
        "series_id": series_id(base, patches),
        "engine": {
            "upstream": lock.get("godot", {}).get("official", {}).get("repo"),
            "base_tag": webgpu.get("base"),
            "base_commit": base,
            "patch_count": len(patches),
        },
        "lineage": {
            "webgpu_backend_origin": webgpu.get("source_lineage_repo"),
            "webgpu_backend_commit": webgpu.get("source_lineage_commit"),
        },
        "toolchain": {
            "emscripten": toolchain.get("emscripten"),
            "scons": toolchain.get("scons"),
        },
        "license": "MIT",
        "attribution_required": True,
        "notice": "NOTICE.md",
        "patches": [
            {"order": i, "file": f.replace("\\", "/"), "sha256": d}
            for i, (f, d) in enumerate(patches, start=1)
        ],
    }
    if artifact:
        stamp["artifact"] = artifact
    return stamp


def required_attribution(stamp: dict) -> str:
    """The text a downstream build must carry to satisfy MIT.

    Emitted verbatim so complying is copy-and-paste rather than research.
    """
    engine = stamp.get("engine", {})
    lineage = stamp.get("lineage", {})
    return "\n".join(
        [
            "This software includes the Studio Foundation WebGPU backend for Godot",
            "Engine, distributed under the MIT License.",
            "",
            f"  Patch series: {stamp.get('series_id', 'unknown')}",
            f"  Godot base:   {engine.get('base_tag')} @ {engine.get('base_commit')}",
            "  Source:       https://github.com/lxsolutions/studio-foundation",
            "",
            "The WebGPU rendering backend originated in "
            f"{lineage.get('webgpu_backend_origin') or 'dwalter/godotwebgpu'}",
            f"(commit {lineage.get('webgpu_backend_commit') or 'unknown'}), MIT License.",
            "Godot Engine is (c) 2014-present Godot Engine contributors and",
            "(c) 2007-2014 Juan Linietsky and Ariel Manzur, MIT License.",
        ]
    )


# -------------------------------------------------------------------- markers


def load_markers(data_dir: Path) -> list[Marker]:
    """Read the marker table.

    Markers live in data, not code, because they are calibrated against real
    binaries: a marker that also appears in stock Godot is worse than useless,
    so the table records what each one was measured against.
    """
    path = data_dir / MARKERS_FILE
    if not path.is_file():
        raise ProvenanceError(f"marker table is missing: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProvenanceError(f"marker table is not valid JSON: {exc}") from exc

    markers: list[Marker] = []
    seen: set[str] = set()
    for entry in raw.get("markers", []):
        name = entry.get("name", "")
        tier = entry.get("tier", "")
        pattern = entry.get("pattern", "")
        if not name or name in seen:
            raise ProvenanceError(f"marker names must be present and unique: {name!r}")
        if tier not in ("webgpu-backend", "studio-series"):
            raise ProvenanceError(f"marker {name} has unknown tier {tier!r}")
        if not pattern:
            raise ProvenanceError(f"marker {name} has an empty pattern")
        seen.add(name)
        markers.append(
            Marker(
                name=name,
                tier=tier,
                pattern=pattern.encode("utf-8"),
                introduced_by=entry.get("introduced_by", ""),
                note=entry.get("note", ""),
            )
        )
    if not markers:
        raise ProvenanceError("marker table is empty")
    return markers


# --------------------------------------------------------------------- detect


def _scan_bytes(blob: bytes, markers: list[Marker]) -> list[str]:
    return [m.name for m in markers if m.pattern in blob]


def _candidate_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(
        p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in SCANNABLE_SUFFIXES
    )


def scan_artifact(path: Path, markers: list[Marker]) -> ScanResult:
    """Look for series markers in a build we did not necessarily produce.

    Accepts a file (.wasm/.js/.pck/.zip), or a directory holding a web export.
    Zips are scanned member by member without extracting to disk, so a template
    archive can be checked in place.
    """
    if not path.exists():
        raise ProvenanceError(f"nothing to scan at {path}")

    result = ScanResult(path=path)
    for candidate in _candidate_files(path):
        rel = str(candidate.relative_to(path)) if path.is_dir() else candidate.name
        if candidate.suffix.lower() == ".zip":
            _scan_zip(candidate, rel, markers, result)
            continue
        try:
            size = candidate.stat().st_size
        except OSError as exc:
            result.skipped.append(f"{rel}: {exc}")
            continue
        if size > MAX_SCAN_BYTES:
            result.skipped.append(f"{rel}: {size} bytes exceeds the scan cap")
            continue
        try:
            blob = candidate.read_bytes()
        except OSError as exc:
            result.skipped.append(f"{rel}: {exc}")
            continue
        result.scanned_files.append(rel)
        for name in _scan_bytes(blob, markers):
            result.hits.setdefault(name, []).append(rel)

    if path.is_dir():
        stamp_file = path / "provenance.json"
        if stamp_file.is_file():
            try:
                result.stamp = json.loads(stamp_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result.stamp = None
    return result


def _scan_zip(archive: Path, rel: str, markers: list[Marker], result: ScanResult) -> None:
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                member = Path(info.filename)
                if member.suffix.lower() not in SCANNABLE_SUFFIXES:
                    continue
                if info.file_size > MAX_SCAN_BYTES:
                    result.skipped.append(
                        f"{rel}!{info.filename}: {info.file_size} bytes exceeds the scan cap"
                    )
                    continue
                label = f"{rel}!{info.filename}"
                with zf.open(info) as handle:
                    blob = handle.read(MAX_SCAN_BYTES)
                result.scanned_files.append(label)
                for name in _scan_bytes(blob, markers):
                    result.hits.setdefault(name, []).append(label)
    except (OSError, zipfile.BadZipFile) as exc:
        result.skipped.append(f"{rel}: {exc}")


# -------------------------------------------------------------------- verdict

VERDICT_STUDIO_SERIES = "studio-series"
VERDICT_WEBGPU_BACKEND = "webgpu-backend"
VERDICT_NONE = "no-webgpu-backend"

# One marker can be a coincidence — a string that happens to appear in unrelated
# code. Two independent markers in the same tier is the threshold for a claim.
STUDIO_SERIES_THRESHOLD = 2


def classify(result: ScanResult, markers: list[Marker]) -> dict:
    """Turn marker hits into a lineage verdict.

    Deliberately conservative: it is far worse to accuse an unrelated project of
    carrying our code than to miss a real derivative. Below the threshold the
    verdict says "inconclusive" rather than guessing.
    """
    studio = result.tier_hits(markers, "studio-series")
    backend = result.tier_hits(markers, "webgpu-backend")

    if len(studio) >= STUDIO_SERIES_THRESHOLD:
        verdict = VERDICT_STUDIO_SERIES
        summary = (
            f"carries {len(studio)} markers unique to the Studio Foundation WebGPU patch series"
        )
        attribution = True
    elif backend:
        verdict = VERDICT_WEBGPU_BACKEND
        summary = (
            f"carries {len(backend)} Godot-WebGPU-backend markers but fewer than "
            f"{STUDIO_SERIES_THRESHOLD} Studio Foundation series markers; lineage "
            "beyond the shared backend is inconclusive"
        )
        attribution = False
    else:
        verdict = VERDICT_NONE
        summary = "no Godot WebGPU backend markers found"
        attribution = False

    return {
        "verdict": verdict,
        "summary": summary,
        "attribution_required": attribution,
        "studio_series_markers": studio,
        "webgpu_backend_markers": backend,
        "scanned_files": len(result.scanned_files),
        "skipped": result.skipped,
        "stamp_series_id": (result.stamp or {}).get("series_id"),
    }
