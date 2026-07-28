#!/usr/bin/env python3
"""Studio Foundation build provenance: stamp our builds, identify anyone else's.

provenance.py id
    Print the series id for the patch series in this repository. Anyone can
    run this on a fresh clone and get the same answer.

provenance.py stamp --dest DIR
    Write provenance.json beside a build.

provenance.py verify PATH [--json]
    Scan a Godot web build -- ours or a third party's -- and report whether
    it descends from this patch series. Exits 0 on a clean report; use
    --require-attribution to exit non-zero when a scanned build carries our
    markers, which is the form a compliance check wants.

provenance.py attribution [--dest FILE]
    Print the MIT attribution text a downstream build must carry.

provenance.py calibrate --ours WASM --control ZIP_OR_WASM
    Re-derive marker candidates by measuring a real build against stock
    Godot. Run this whenever the patch series grows; a marker table nobody
    re-measures rots.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools.provenance import (  # noqa: E402
    ProvenanceError,
    build_stamp,
    classify,
    load_markers,
    required_attribution,
    scan_artifact,
    series_from_lock,
    series_id,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_FILE = REPO_ROOT / "engine" / "engine-lock.toml"
DATA_DIR = Path(__file__).resolve().parent


def load_lock() -> dict:
    if not LOCK_FILE.is_file():
        raise ProvenanceError(f"engine lock is missing: {LOCK_FILE}")
    with LOCK_FILE.open("rb") as handle:
        return tomllib.load(handle)


def cmd_id(_args: argparse.Namespace) -> int:
    base, patches = series_from_lock(load_lock())
    print(series_id(base, patches))
    return 0


def cmd_stamp(args: argparse.Namespace) -> int:
    lock = load_lock()
    artifact = None
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    if args.artifact:
        path = Path(args.artifact)
        if not path.is_file():
            raise ProvenanceError(f"artifact does not exist: {path}")
        artifact = {"name": path.name, "bytes": path.stat().st_size}
    stamp = build_stamp(lock, artifact=artifact)
    out = dest / "provenance.json"
    out.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    print(f"[stamp] {out} ({stamp['series_id']}, {stamp['engine']['patch_count']} patches)")
    return 0


def cmd_attribution(args: argparse.Namespace) -> int:
    text = required_attribution(build_stamp(load_lock()))
    if args.dest:
        Path(args.dest).write_text(text + "\n", encoding="utf-8")
        print(f"[attribution] wrote {args.dest}")
    else:
        print(text)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    markers = load_markers(DATA_DIR)
    result = scan_artifact(Path(args.path), markers)
    report = classify(result, markers)

    # Our own series id, so a report can say whether a stamp matches this repo.
    try:
        base, patches = series_from_lock(load_lock())
        report["this_repo_series_id"] = series_id(base, patches)
    except ProvenanceError:
        report["this_repo_series_id"] = None

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"scanned : {args.path}")
        print(f"files   : {report['scanned_files']}")
        print(f"verdict : {report['verdict']}")
        print(f"          {report['summary']}")
        if report["studio_series_markers"]:
            print(f"series  : {', '.join(report['studio_series_markers'])}")
        if report["webgpu_backend_markers"]:
            print(f"backend : {', '.join(report['webgpu_backend_markers'])}")
        stamp_id = report.get("stamp_series_id")
        if stamp_id:
            same = stamp_id == report.get("this_repo_series_id")
            print(f"stamp   : {stamp_id} ({'matches this repo' if same else 'different series'})")
        elif report["attribution_required"]:
            print("stamp   : none found (markers present without a provenance.json)")
        for note in report["skipped"]:
            print(f"skipped : {note}")
        if report["attribution_required"]:
            print()
            print("This build is a derivative work of the Studio Foundation WebGPU")
            print("patch series and must carry the MIT notice below.")
            print()
            print(required_attribution(build_stamp(load_lock())))

    if args.require_attribution and report["attribution_required"]:
        return 1
    return 0


_RUN = re.compile(rb"[\x20-\x7e]{8,120}")


def _strings(blob: bytes) -> set[bytes]:
    return {m.group() for m in _RUN.finditer(blob)}


def _strings_of(path: Path) -> set[bytes]:
    """Printable runs in a wasm/js file, or in every wasm/js inside a zip."""
    if path.suffix.lower() == ".zip":
        found: set[bytes] = set()
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith((".wasm", ".js")):
                    found |= _strings(zf.read(name))
        return found
    return _strings(path.read_bytes())


def cmd_calibrate(args: argparse.Namespace) -> int:
    ours = Path(args.ours)
    control = Path(args.control)
    for path in (ours, control):
        if not path.is_file():
            raise ProvenanceError(f"calibration input does not exist: {path}")

    positive = _strings_of(ours)
    negative = _strings_of(control)
    unique = positive - negative

    patch_dir = REPO_ROOT / "engine" / "patches"
    base_added: list[bytes] = []
    studio_added: list[bytes] = []
    for patch in sorted(patch_dir.glob("0*.patch")):
        target = base_added if patch.name[:4] in ("0001", "0002", "0003") else studio_added
        for line in patch.read_bytes().splitlines():
            if line.startswith(b"+") and not line.startswith(b"+++"):
                target.append(line[1:])
    base_blob = b"\n".join(base_added)
    studio_blob = b"\n".join(studio_added)

    studio_only = sorted(s for s in unique if s in studio_blob and s not in base_blob)
    backend = sorted(s for s in unique if s in base_blob)

    print(f"positive : {ours.name} -- {len(positive)} distinct strings")
    print(f"control  : {control.name} -- {len(negative)} distinct strings")
    print(f"unique   : {len(unique)}")
    print()
    print(f"candidate studio-series markers ({len(studio_only)}):")
    for s in studio_only:
        print("   ", s.decode("ascii", "replace"))
    print()
    print(f"candidate webgpu-backend markers ({len(backend)}):")
    for s in backend[: args.limit]:
        print("   ", s.decode("ascii", "replace"))
    if len(backend) > args.limit:
        print(f"    ... {len(backend) - args.limit} more")
    print()
    print("Review before promoting any of these into webgpu-markers.json. A")
    print("candidate that is really a Godot core API name will false-positive on")
    print("unrelated builds -- see 'excluded_deliberately' in the marker table.")

    # Every marker we already ship must still be found in the positive sample,
    # or the table has drifted away from what the engine actually builds.
    markers = load_markers(DATA_DIR)
    stale = [m.name for m in markers if not any(m.pattern in s for s in positive)]
    if stale:
        print()
        print(f"STALE: {len(stale)} shipped marker(s) not present in {ours.name}:")
        for name in stale:
            print(f"    {name}")
        return 1
    print()
    print(f"all {len(markers)} shipped markers are present in the positive sample")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("id", help="print this repository's patch series id").set_defaults(func=cmd_id)

    p_stamp = sub.add_parser("stamp", help="write provenance.json beside a build")
    p_stamp.add_argument("--dest", required=True, help="directory to write provenance.json into")
    p_stamp.add_argument("--artifact", help="optional built file to record name and size for")
    p_stamp.set_defaults(func=cmd_stamp)

    p_attr = sub.add_parser(
        "attribution", help="print the MIT attribution downstream builds must carry"
    )
    p_attr.add_argument("--dest", help="write to this file instead of stdout")
    p_attr.set_defaults(func=cmd_attribution)

    p_verify = sub.add_parser("verify", help="identify the lineage of a Godot web build")
    p_verify.add_argument("path", help="a .wasm/.js/.pck/.zip, or a directory holding a web export")
    p_verify.add_argument("--json", action="store_true", help="machine-readable report")
    p_verify.add_argument(
        "--require-attribution",
        action="store_true",
        help="exit 1 when the scanned build carries our markers (compliance check)",
    )
    p_verify.set_defaults(func=cmd_verify)

    p_cal = sub.add_parser("calibrate", help="re-derive markers from a real build vs stock Godot")
    p_cal.add_argument("--ours", required=True, help="a wasm built from this patch series")
    p_cal.add_argument(
        "--control", required=True, help="a stock Godot web template (.zip or .wasm)"
    )
    p_cal.add_argument("--limit", type=int, default=20, help="cap the backend-tier listing")
    p_cal.set_defaults(func=cmd_calibrate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ProvenanceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
