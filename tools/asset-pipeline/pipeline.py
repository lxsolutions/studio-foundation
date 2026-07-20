#!/usr/bin/env python3
"""Deterministic command-line asset pipeline (ADR 0006).

  pipeline.py validate <file.blend>
  pipeline.py export   <file.blend>            # validate first, then GLB
  pipeline.py cook     --profile P [--game G]  # export all + sync into project + manifests
  pipeline.py preview  <file.blend> [--frames N]
  pipeline.py report

Sources live in assets-source/; ALL outputs land in assets-generated/ (repo
level, hash-cached) and are synced into <game>/project/assets/generated/ by
cook. Nothing here ever writes into assets-source/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402

REPO = senv.repo_root()
BLENDER_SCRIPTS = REPO / "tools" / "blender"
GENERATED = REPO / "assets-generated"
CACHE_PATH = GENERATED / ".cache.json"
REPORTS = GENERATED / "reports"
PROFILES = ["desktop_high", "browser_webgpu", "browser_webgl", "mobile_high", "mobile_low"]
RESULT_RE = re.compile(r"^(ASSET_VALIDATE_RESULT|EXPORT_RESULT|PREVIEW_RESULT|MAKE_SAMPLE_RESULT) (.+)$")


def blender_bin() -> str:
    binary = senv.find_blender()
    if not binary:
        raise SystemExit("Blender not found (set BLENDER_BIN in .env; see just doctor)")
    return binary


def run_blender(blend: Path | None, script: str, extra: list[str], timeout: int = 300) -> dict:
    argv = [blender_bin(), "-b"]
    if blend is not None:
        argv.append(str(blend))
    argv += ["-P", str(BLENDER_SCRIPTS / script), "--", *extra]
    proc = senv.run(argv, timeout=timeout)
    result: dict = {}
    for line in (proc.stdout or "").splitlines():
        match = RESULT_RE.match(line.strip())
        if match:
            try:
                result = json.loads(match.group(2))
            except json.JSONDecodeError:
                pass
    if not result:
        tail = ((proc.stdout or "") + (proc.stderr or ""))[-2500:]
        raise SystemExit(
            f"Blender produced no result marker (script {script}).\n"
            f"--- output tail ---\n{tail}"
        )
    result["_exit"] = proc.returncode
    return result


def sidecar_for(blend: Path) -> Path:
    return blend.with_name(blend.stem + ".meta.json")


def load_meta(blend: Path) -> dict:
    path = sidecar_for(blend)
    if not path.is_file():
        raise SystemExit(
            f"missing sidecar {path.name} next to {blend.name} — every master asset "
            "needs one (schema: shared/schemas/asset-meta.schema.json)"
        )
    with open(path, encoding="utf-8") as fh:
        meta = json.load(fh)
    problems = validate_meta(meta)
    if problems:
        for problem in problems:
            print(f"  meta error: {problem}", file=sys.stderr)
        raise SystemExit(f"invalid sidecar {path}")
    return meta


def validate_meta(meta: dict) -> list[str]:
    """Minimal hand-rolled checks mirroring the JSON schema (stdlib-only)."""
    problems = []
    for field in ["asset_id", "category", "license", "source", "creator", "provenance"]:
        if field not in meta:
            problems.append(f"missing required field '{field}'")
    if "asset_id" in meta and not re.match(r"^[a-z0-9_]+$", str(meta["asset_id"])):
        problems.append("asset_id must be snake_case")
    provenance = meta.get("provenance", {})
    if isinstance(provenance, dict):
        for field in ["method", "commercial_use_allowed", "modified"]:
            if field not in provenance:
                problems.append(f"provenance missing '{field}'")
        if provenance.get("method") in ("ai_generated", "ai_assisted") and "ai" not in provenance:
            problems.append("AI-produced assets must include provenance.ai block")
    return problems


def source_hash(blend: Path) -> str:
    hasher = hashlib.sha256()
    for path in [blend, sidecar_for(blend), BLENDER_SCRIPTS / "export_gltf.py"]:
        if path.is_file():
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def load_cache() -> dict:
    if CACHE_PATH.is_file():
        with open(CACHE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_cache(cache: dict) -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def generated_path_for(blend: Path) -> Path:
    relative = blend.resolve().relative_to(REPO)
    # templates/godot-game/assets-source/props/x/x.blend -> assets-generated/templates/godot-game/props/x/x.glb
    parts = [p for p in relative.parts if p != "assets-source"]
    return GENERATED.joinpath(*parts[:-1]) / (blend.stem + ".glb")


def cmd_validate(blend: Path) -> int:
    meta = load_meta(blend)
    result = run_blender(blend, "validate.py", [f"--meta={sidecar_for(blend)}"])
    REPORTS.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS / f"{meta['asset_id']}.validate.json"
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    failed = [c for c in result.get("checks", []) if c["level"] == "error"]
    for check in result.get("checks", []):
        if check["level"] != "ok":
            print(f"  [{check['level'].upper()}] {check['id']}: {check['msg']}")
    print(
        f"validate {blend.name}: {'OK' if result.get('ok') else 'FAILED'} "
        f"(tris={result.get('triangles')}, mats={result.get('materials')}, report={report_path.relative_to(REPO)})"
    )
    return 0 if result.get("ok") else 1


def cmd_export(blend: Path, force: bool = False) -> tuple[int, Path]:
    out_path = generated_path_for(blend)
    cache = load_cache()
    digest = source_hash(blend)
    key = str(out_path.relative_to(REPO)).replace("\\", "/")
    if not force and cache.get(key) == digest and out_path.is_file():
        print(f"export {blend.name}: cached ({key})")
        return 0, out_path
    code = cmd_validate(blend)
    if code != 0:
        return code, out_path
    result = run_blender(blend, "export_gltf.py", [f"--out={out_path}"])
    if not result.get("ok"):
        print(f"export {blend.name}: FAILED — {result.get('error', 'unknown')}", file=sys.stderr)
        return 1, out_path
    cache[key] = digest
    save_cache(cache)
    print(f"export {blend.name}: OK -> {key} ({result.get('bytes', 0)} bytes)")
    return 0, out_path


def game_root(game: str) -> Path:
    path = REPO / game
    if not path.is_dir():
        raise SystemExit(f"game path not found: {game}")
    return path


def cmd_cook(profile: str, game: str) -> int:
    if profile not in PROFILES:
        raise SystemExit(f"unknown profile '{profile}' (choose from {', '.join(PROFILES)})")
    root = game_root(game)
    sources = sorted((root / "assets-source").rglob("*.blend"))
    if not sources:
        print(f"cook: no source assets under {game}/assets-source")
    manifest: dict = {"schema": 1, "profile": profile, "assets": {}}
    failures = 0
    for blend in sources:
        code, out_path = cmd_export(blend)
        if code != 0:
            failures += 1
            continue
        meta = load_meta(blend)
        # Sync runtime file into the game project (generated dir, gitignored).
        relative = out_path.relative_to(GENERATED)
        parts = [p for p in relative.parts if p not in Path(game).parts]
        dest = root / "project" / "assets" / "generated" / Path(*parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(out_path.read_bytes())
        manifest["assets"][meta["asset_id"]] = {
            "file": str(Path(*parts)).replace("\\", "/"),
            "category": meta.get("category", "prop"),
            "source_hash": source_hash(blend),
            "texture_policy": meta.get("texture_policy", "compressed"),
            # Texture conversion hook: per-profile KTX2/Basis + platform compression
            # lands here when texture-bearing assets arrive (tracked in docs/asset-pipeline).
        }
    manifest_path = root / "project" / "assets" / "generated" / "asset_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    content_path = root / "project" / "content_manifest.json"
    content_path.write_text(
        json.dumps(
            {"schema": 1, "packs": {"base": {"version": "0.1.0", "profile": profile}}},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"cook: {len(sources) - failures}/{len(sources)} assets for profile {profile} -> {game}")
    return 1 if failures else 0


def cmd_preview(blend: Path, frames: int) -> int:
    meta = load_meta(blend)
    out_path = GENERATED / "previews" / f"{meta['asset_id']}.png"
    result = run_blender(blend, "render_preview.py", [f"--out={out_path}", f"--frames={frames}"])
    print(f"preview {blend.name}: {'OK' if result.get('ok') else 'FAILED'} -> {result.get('files')}")
    return 0 if result.get("ok") else 1


def cmd_report() -> int:
    reports = sorted(REPORTS.glob("*.validate.json")) if REPORTS.is_dir() else []
    summary = []
    for report_path in reports:
        with open(report_path, encoding="utf-8") as fh:
            data = json.load(fh)
        errors = [c for c in data.get("checks", []) if c["level"] == "error"]
        warns = [c for c in data.get("checks", []) if c["level"] == "warn"]
        summary.append({
            "asset": report_path.name.replace(".validate.json", ""),
            "ok": data.get("ok", False),
            "triangles": data.get("triangles"),
            "materials": data.get("materials"),
            "errors": len(errors),
            "warnings": len(warns),
        })
        print(
            f"{report_path.name.replace('.validate.json', ''):<24} "
            f"{'OK  ' if data.get('ok') else 'FAIL'} tris={data.get('triangles')} "
            f"mats={data.get('materials')} errors={len(errors)} warns={len(warns)}"
        )
    GENERATED.mkdir(parents=True, exist_ok=True)
    (REPORTS / "summary.json").parent.mkdir(parents=True, exist_ok=True)
    (REPORTS / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"{len(summary)} report(s); summary -> {(REPORTS / 'summary.json').relative_to(REPO)}")
    return 0


def main() -> int:
    senv.load_dotenv()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "export", "preview"):
        cmd = sub.add_parser(name)
        cmd.add_argument("file")
        if name == "preview":
            cmd.add_argument("--frames", type=int, default=1)
        if name == "export":
            cmd.add_argument("--force", action="store_true")
    cook = sub.add_parser("cook")
    cook.add_argument("--profile", required=True)
    cook.add_argument("--game", default="templates/godot-game")
    sub.add_parser("report")
    args = parser.parse_args()

    if args.command == "report":
        return cmd_report()
    if args.command == "cook":
        return cmd_cook(args.profile, args.game)
    blend = Path(args.file).resolve()
    if not blend.is_file():
        raise SystemExit(f"not found: {blend}")
    if args.command == "validate":
        return cmd_validate(blend)
    if args.command == "export":
        return cmd_export(blend, force=args.force)[0]
    if args.command == "preview":
        return cmd_preview(blend, args.frames)
    return 2


if __name__ == "__main__":
    sys.exit(main())
