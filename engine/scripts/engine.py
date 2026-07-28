#!/usr/bin/env python3
"""Engine source and patch tooling: versions / fetch / build / rebase.

Single source of truth is engine/engine-lock.toml. Engine sources are cached
out-of-tree in engine/.cache (gitignored, never committed).

  python engine/scripts/engine.py versions   # print locked pins and local cache state
  python engine/scripts/engine.py fetch      # fetch official Godot + apply local patches
  python engine/scripts/engine.py build      # build pinned WebGPU export templates
  python engine/scripts/engine.py record-artifacts  # lock validated template bytes
  python engine/scripts/engine.py rebase     # test the patch series on a newer Godot ref
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
import tomllib
from pathlib import Path

from emdawn_port import EmdawnPortError, prepare_locked_emdawn_port
from patch_series import PatchSeriesError, patch_state, verified_patches
from rebase import RebaseError, cmd_rebase, rebase_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = REPO_ROOT / "engine"
CACHE_DIR = ENGINE_DIR / ".cache"
LOCK_FILE = ENGINE_DIR / "engine-lock.toml"
PATCHED_CACHE_DIR = CACHE_DIR / "studio-webgpu"
TEMPLATE_ARTIFACTS = {
    "web_webgpu_release": "godot.web.template_release.webgpu.zip",
    "web_webgpu_debug": "godot.web.template_debug.webgpu.zip",
}


def load_lock() -> dict:
    with LOCK_FILE.open("rb") as fh:
        return tomllib.load(fh)


def git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)


def fetch_repo(name: str, repo: str, commit: str, ref: str) -> Path:
    """Clone (or reuse) a source tree and check out the pinned commit."""
    dest = CACHE_DIR / name
    if not (dest / ".git").is_dir():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"[fetch] cloning {repo} -> {dest}")
        git("clone", "--filter=blob:none", "--no-checkout", repo, str(dest))
    else:
        print(f"[fetch] reusing existing clone {dest}")
        available = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=dest,
            capture_output=True,
            check=False,
        )
        if available.returncode != 0:
            print(f"[fetch] retrieving missing commit {commit}")
            git("fetch", "--filter=blob:none", "origin", commit, cwd=dest)
    print(f"[fetch] checkout {name} @ {commit} ({ref})")
    git("checkout", "--detach", commit, cwd=dest)
    return dest


def _patch_tree_fingerprint(source: Path, patches: list) -> str:
    """Hash every source path governed by the ordered patch series."""
    paths: set[str] = set()
    for patch in patches:
        for line in patch.path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^diff --git a/(.+) b/(.+)$", line)
            if match:
                paths.update(match.groups())
    digest = hashlib.sha256()
    for relative in sorted(paths):
        path = source / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_file():
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def prepare_patched_source(
    lock: dict,
    official_dir: Path,
    patches: list,
    *,
    cache_dir: Path = CACHE_DIR,
) -> Path:
    """Create or reuse the deterministic official-Godot + local-patches worktree."""
    destination = cache_dir / PATCHED_CACHE_DIR.name
    state_file = destination / ".studio-foundation-patch-state.json"
    expected_state = patch_state(lock, patches)

    if destination.exists():
        if state_file.is_file():
            try:
                current_state = json.loads(state_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PatchSeriesError(
                    f"invalid patch-state file: {state_file}"
                ) from exc
            tree_sha256 = current_state.pop("tree_sha256", None)
            if (
                current_state == expected_state
                and tree_sha256 == _patch_tree_fingerprint(destination, patches)
            ):
                print(f"[fetch] reusing verified patched source {destination}")
                return destination
        raise PatchSeriesError(
            f"{destination} exists but does not match engine-lock.toml; "
            "move this disposable cache aside and run engine-fetch again"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    base_commit = str(lock["godot"]["webgpu"]["base_commit"])
    print(f"[fetch] creating patched source from official Godot @ {base_commit}")
    git(
        "worktree",
        "add",
        "--detach",
        str(destination),
        base_commit,
        cwd=official_dir,
    )
    for patch in patches:
        print(f"[fetch] checking {patch.relative}")
        git("apply", "--check", str(patch.path), cwd=destination)
        git("apply", str(patch.path), cwd=destination)
    recorded_state = {
        **expected_state,
        "tree_sha256": _patch_tree_fingerprint(destination, patches),
    }
    state_file.write_text(
        json.dumps(recorded_state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def cmd_versions(lock: dict) -> int:
    official = lock["godot"]["official"]
    integration = lock["godot"]["webgpu"]
    toolchain = lock["toolchain"]
    print(
        f"official godot : {official['tag']} @ {official['commit'][:12]}  ({official['repo']})"
    )
    print(
        f"studio webgpu  : base {integration['base']} @ "
        f"{integration['base_commit'][:12]}  status={integration['status']}"
    )
    print(
        f"source lineage : {integration['source_lineage_commit'][:12]}  "
        f"({integration['source_lineage_repo']})"
    )
    print(
        f"toolchain      : emscripten {toolchain['emscripten']}, scons {toolchain['scons']}, "
        f"python {toolchain['python']}, rust {toolchain['rust']}"
    )
    emdawn = toolchain["emdawnwebgpu"]
    print(
        f"emdawn port    : {emdawn['version']} @ {emdawn['revision'][:12]} "
        f"(upstream fix {emdawn['upstream_fix_commit'][:12]})"
    )
    for name, key in (
        ("official", "godot-official"),
        ("patched", PATCHED_CACHE_DIR.name),
    ):
        dest = CACHE_DIR / key
        state = "cached" if (dest / ".git").exists() else "not fetched"
        print(f"cache {name:11s}: {state} ({dest})")
    patches = lock.get("patches", {}).get("series", [])
    print(f"patch series   : {len(patches)} patch(es)")
    artifacts = lock.get("artifacts", {}).get("export_templates", {})
    records = [
        value
        for value in artifacts.values()
        if isinstance(value, dict) and {"file", "bytes", "sha256"}.issubset(value)
    ]
    detail = ""
    if artifacts.get("status"):
        detail = f" ({artifacts['status']}"
        if artifacts.get("blocker"):
            detail += f": {artifacts['blocker']}"
        detail += ")"
    print(f"artifact records: {len(records)} template(s){detail}")
    return 0


def cmd_fetch(lock: dict) -> int:
    official = lock["godot"]["official"]
    try:
        patches = verified_patches(lock, ENGINE_DIR)
        official_dir = fetch_repo(
            "godot-official", official["repo"], official["commit"], official["tag"]
        )
        prepare_patched_source(lock, official_dir, patches)
    except (PatchSeriesError, OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("[fetch] done — official source and Studio WebGPU patches are ready")
    return 0


IS_WINDOWS = os.name == "nt"
# emsdk ships one activation script per platform; the emcc entry point follows suit.
EMSDK_ENV_SCRIPT = "emsdk_env.bat" if IS_WINDOWS else "emsdk_env.sh"
EMCC_NAME = "emcc.bat" if IS_WINDOWS else "emcc"


def _emsdk_root(root: Path, expected: str) -> Path | None:
    """Return `root` if it is an emsdk activated at exactly `expected`, else None."""
    env_script = root / EMSDK_ENV_SCRIPT
    version_file = root / "upstream" / "emscripten" / "emscripten-version.txt"
    if not env_script.is_file() or not version_file.is_file():
        return None
    try:
        actual = version_file.read_text(encoding="utf-8").strip().strip('"')
    except OSError:
        return None
    return root if actual == expected else None


def _find_emsdk_root(expected: str) -> Path | None:
    """Locate the exact configured emsdk, preferring an explicit EMSDK root."""
    configured = os.environ.get("EMSDK")
    if configured:
        return _emsdk_root(Path(configured), expected)

    candidates = [Path.home() / "emsdk"]
    if IS_WINDOWS:
        candidates.append(Path("C:/emsdk"))
    else:
        candidates += [Path("/opt/emsdk"), Path("/usr/local/emsdk")]
    for root in candidates:
        found = _emsdk_root(root, expected)
        if found:
            return found
    return None


def artifact_destination(
    source_dir: Path | None, engine_dir: Path = ENGINE_DIR
) -> Path:
    """Keep candidate templates separate from artifacts produced by the locked integration."""
    if source_dir:
        return engine_dir / "artifacts" / "candidates" / source_dir.name / "templates"
    return engine_dir / "artifacts" / "templates"


def artifact_record(path: Path) -> dict[str, str | int]:
    """Return the immutable metadata used to accept a built template."""
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": digest}


def record_artifacts(
    *,
    lock_path: Path = LOCK_FILE,
    artifact_dir: Path | None = None,
) -> dict[str, dict[str, str | int]]:
    """Record a complete release/debug template pair in engine-lock.toml.

    Compilation creates candidates. This separate command explicitly accepts
    exact bytes after local validation, and never records a partial pair.
    """
    artifact_dir = artifact_dir or ENGINE_DIR / "artifacts" / "templates"
    records: dict[str, dict[str, str | int]] = {}
    missing = []
    for key, filename in TEMPLATE_ARTIFACTS.items():
        path = artifact_dir / filename
        if not path.is_file():
            missing.append(str(path))
            continue
        records[key] = artifact_record(path)
    if missing:
        raise FileNotFoundError("missing required template(s): " + ", ".join(missing))

    source = lock_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^\[artifacts\.export_templates\]\r?\n.*?(?=^\[|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    if not pattern.search(source):
        raise ValueError(f"{lock_path} has no [artifacts.export_templates] table")

    lines = [
        "[artifacts.export_templates]",
        "# Generated by engine-record-artifacts after build validation.",
    ]
    for key in TEMPLATE_ARTIFACTS:
        record = records[key]
        lines.append(
            f'{key} = {{ file = "{record["file"]}", bytes = {record["bytes"]}, '
            f'sha256 = "{record["sha256"]}" }}'
        )
    replacement = "\n".join(lines) + "\n\n"
    lock_path.write_text(pattern.sub(replacement, source, count=1), encoding="utf-8")
    return records


def cmd_record_artifacts() -> int:
    try:
        records = record_artifacts()
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for key, record in records.items():
        print(
            f"[record] {key}: {record['file']} bytes={record['bytes']} "
            f"sha256={record['sha256']}"
        )
    print(f"[record] updated {LOCK_FILE.relative_to(REPO_ROOT)}")
    return 0


def cmd_build(lock: dict, source_dir: Path | None = None) -> int:
    """Build web export templates from the patched source or a candidate worktree.

    Requires: scons (tools venv `engine` group) and emsdk with the pinned
    emscripten already installed + activated (emsdk install X && emsdk activate X).
    """
    source = source_dir or PATCHED_CACHE_DIR
    artifact_dir = artifact_destination(source_dir)
    if not (source / "SConstruct").is_file():
        print(
            "error: engine source is not ready; fetch pins or prepare the selected workspace",
            file=sys.stderr,
        )
        return 2
    em_version = lock["toolchain"]["emscripten"]
    build_env = os.environ.copy()
    configured_emsdk = os.environ.get("EMSDK")
    root = _find_emsdk_root(em_version)
    if configured_emsdk or not shutil.which("emcc"):
        if not root:
            if configured_emsdk:
                print(
                    f"error: EMSDK={configured_emsdk} is not activated at exact "
                    f"Emscripten {em_version}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"error: emcc not on PATH and no exact emsdk found — "
                    f"install/activate emsdk {em_version}",
                    file=sys.stderr,
                )
            return 2
        # emsdk_env.{bat,sh} ultimately puts <root> and <root>/upstream/emscripten
        # on PATH; do that directly instead of shelling out (robust across hosts).
        em_dir = root / "upstream" / "emscripten"
        if not (em_dir / EMCC_NAME).is_file():
            print(
                f"error: {em_dir} has no {EMCC_NAME} — activate emsdk {em_version} first",
                file=sys.stderr,
            )
            return 2
        print(f"[build] using emsdk at {root}")
        sep = os.pathsep
        build_env["PATH"] = f"{em_dir}{sep}{root}{sep}" + build_env.get("PATH", "")
        build_env["EMSDK"] = str(root)
        config = root / ".emscripten"
        if config.is_file():
            build_env["EM_CONFIG"] = str(config)
        if not shutil.which("emcc", path=build_env["PATH"]):
            print("error: emcc still not found after PATH update", file=sys.stderr)
            return 2
    emcc = shutil.which("emcc", path=build_env["PATH"])
    version = subprocess.run(
        [emcc, "--version"],
        env=build_env,
        capture_output=True,
        text=True,
        check=False,
    )
    if version.returncode != 0 or em_version not in version.stdout:
        actual = version.stdout.splitlines()[0] if version.stdout else "unavailable"
        print(
            f"error: expected Emscripten {em_version}, resolved {actual}",
            file=sys.stderr,
        )
        return 2
    try:
        emdawn_port = prepare_locked_emdawn_port(
            lock,
            engine_dir=ENGINE_DIR,
            cache_dir=CACHE_DIR,
            emscripten_dir=Path(emcc).resolve().parent,
            emcc=Path(emcc),
            env=build_env,
        )
    except (EmdawnPortError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    build_env["EMDAWNWEBGPU_PORT"] = emdawn_port.resolve().as_posix()
    print(f"[build] locked Emdawn port: {build_env['EMDAWNWEBGPU_PORT']}")
    scons = [sys.executable, "-m", "SCons"]
    targets = lock["build"]["web_webgpu"]
    jobs = str(os.cpu_count() or 4)
    rc = 0
    for profile in ("target_release", "target_debug"):
        flags = targets[profile]
        print(f"[build] scons {' '.join(flags)} -j{jobs}", flush=True)
        proc = subprocess.run([*scons, *flags, f"-j{jobs}"], cwd=source, env=build_env)
        if proc.returncode != 0:
            print(f"[build] {profile} FAILED (exit {proc.returncode})", file=sys.stderr)
            rc = proc.returncode
            break
        print(f"[build] {profile} OK", flush=True)
    if rc == 0:
        _install_templates(
            source,
            artifact_dir,
            threads_enabled="threads=yes" in targets["target_release"],
        )
        _write_provenance(lock, artifact_dir)
    return rc


def _write_provenance(lock: dict, artifact_dir: Path) -> None:
    """Record what these templates were made of, next to the templates.

    Stamping is part of building, not a step someone has to remember: a template
    that ships without provenance is one nobody downstream can trace back, and
    tracing it back is the whole point.
    """
    sys.path.insert(0, str(REPO_ROOT / "tools" / "pylib"))
    try:
        from studio_tools.provenance import ProvenanceError, build_stamp
    except ImportError as exc:  # pragma: no cover - only if tools/ is absent
        print(f"[build] warning: provenance unavailable ({exc})", file=sys.stderr)
        return
    try:
        stamp = build_stamp(lock)
    except ProvenanceError as exc:
        print(f"[build] warning: could not stamp provenance: {exc}", file=sys.stderr)
        return
    artifact_dir.mkdir(parents=True, exist_ok=True)
    out = artifact_dir / "provenance.json"
    out.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    print(f"[build] provenance {stamp['series_id']} -> {out}")


def _validate_webgpu_template(archive: Path) -> None:
    """Reject mislabeled templates that do not contain the compiled backend."""
    with zipfile.ZipFile(archive) as bundle:
        try:
            loader = bundle.read("godot.js")
            runtime = bundle.read("godot.wasm")
        except KeyError as error:
            raise RuntimeError(f"incomplete Godot web template: {archive}") from error
    missing = []
    if b"importJsDevice" not in loader:
        missing.append("emdawnwebgpu loader bridge")
    if b"WebGPU: Device imported from JS successfully." not in runtime:
        missing.append("compiled WebGPU context driver")
    if missing:
        raise RuntimeError(
            f"refusing mislabeled WebGPU template {archive}: missing {', '.join(missing)}"
        )


def _install_templates(
    source: Path, dest: Path | None = None, *, threads_enabled: bool
) -> None:
    """Install the archives matching the lock's thread configuration, atomically.

    Both templates are validated and staged first, and only then moved into place.
    Copying them one at a time leaves a window -- in practice around a hundred
    seconds, because debug links long after release -- in which the directory holds
    a new release template beside the previous debug one. An export taken in that
    window silently mixes two builds, and the measurement that follows describes
    neither of them. That has already cost one wasted GPU verification round.
    """
    dest = dest or ENGINE_DIR / "artifacts" / "templates"
    dest.mkdir(parents=True, exist_ok=True)
    suffix = ".wasm32.zip" if threads_enabled else ".wasm32.nothreads.zip"

    staged: list[tuple[Path, Path, Path]] = []  # (source archive, staging, final)
    for profile in ("release", "debug"):
        archive = source / "bin" / f"godot.web.template_{profile}{suffix}"
        if not archive.is_file():
            raise RuntimeError(f"expected built WebGPU template missing: {archive}")
        target = dest / f"godot.web.template_{profile}.webgpu.zip"
        staging = target.with_suffix(".zip.incoming")
        _validate_webgpu_template(archive)
        shutil.copy2(archive, staging)
        staged.append((archive, staging, target))

    if len(staged) != 2:
        raise RuntimeError("expected release and debug WebGPU templates")

    try:
        for archive, staging, target in staged:
            os.replace(staging, target)
            shown = target.relative_to(REPO_ROOT) if target.is_relative_to(REPO_ROOT) else target
            print(f"[install] {archive.name} -> {shown}", flush=True)
    finally:
        for _, staging, _ in staged:
            staging.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "command",
        choices=["versions", "fetch", "build", "record-artifacts", "rebase"],
    )
    parser.add_argument(
        "--official-ref", default="", help="official commit/tag (default: lock pin)"
    )
    parser.add_argument("--branch", default="", help="dedicated merge branch name")
    parser.add_argument(
        "--workspace", default="", help="directory name under engine/.cache/rebases"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the plan without changing Git state",
    )
    parser.add_argument(
        "--json", action="store_true", help="machine-readable rebase result"
    )
    args = parser.parse_args()
    lock = load_lock()
    if args.command == "versions":
        return cmd_versions(lock)
    if args.command == "fetch":
        return cmd_fetch(lock)
    if args.command == "build":
        try:
            source_dir = rebase_workspace(args.workspace) if args.workspace else None
        except RebaseError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return cmd_build(lock, source_dir)
    if args.command == "record-artifacts":
        return cmd_record_artifacts()
    return cmd_rebase(lock, args)


if __name__ == "__main__":
    sys.exit(main())
