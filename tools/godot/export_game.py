#!/usr/bin/env python3
"""Export a game project with a named preset, with honest readiness checks.

  python tools/godot/export_game.py --game templates/godot-game --preset web-webgl

Presets (export_presets.cfg): web-webgl | web-webgpu | android | ios.
Stamps build_info.json (version/git/date) into the project before export and
verifies expected outputs exist afterwards. Never fakes readiness: missing
templates/SDKs fail with precise instructions, not half-exports.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402

REPO = senv.repo_root()


def check_readiness(preset: str) -> str | None:
    """Return an error message if this machine cannot run the preset."""
    lock = senv.engine_lock()
    if preset == "web-webgl":
        tdir = senv.godot_templates_dir()
        version = lock["godot"]["official"]["tag"].replace("-", ".")
        if not tdir or not any((tdir / version).glob("web_*.zip")):
            return (
                f"official web export templates for {version} not installed.\n"
                "Fix: open the Godot editor > Editor > Manage Export Templates > Download,\n"
                "or download the tpz from godotengine.org and install it."
            )
        return None
    if preset == "web-webgpu":
        artifacts = REPO / "engine" / "artifacts" / "templates"
        if not artifacts.is_dir() or not any(artifacts.glob("*web*.zip")):
            return (
                "Studio WebGPU export templates are not built on this machine.\n"
                "Fix: just engine-fetch && just engine-build   (hours; needs scons + emsdk "
                f"{lock['toolchain']['emscripten']} — see engine/README.md).\n"
                "Until then, use the always-green fallback: just export-browser-webgl"
            )
        return None
    if preset == "android":
        import os

        sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        if not sdk:
            return (
                "Android SDK not found (ANDROID_HOME unset).\n"
                "Fix: install Android Studio + SDK + JDK 17, configure Godot editor "
                "Android settings, and set a debug keystore. See docs/runbooks/android-export.md"
            )
        return None
    if preset == "ios":
        if sys.platform != "darwin":
            return "iOS export requires macOS + Xcode; not possible on this OS (doctor reports the same)."
        return None
    return f"unknown preset {preset}"


def git_describe() -> tuple[str, str]:
    sha = senv.run(["git", "rev-parse", "--short=12", "HEAD"]).stdout.strip() or "unknown"
    dirty = bool(senv.run(["git", "status", "--porcelain"]).stdout.strip())
    return sha + ("-dirty" if dirty else ""), "0.1.0"


def stamp_build_info(project: Path, preset: str) -> None:
    sha, version = git_describe()
    info = {
        "version": f"{version}+{sha}",
        "git_commit": sha,
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "channel": preset,
    }
    (project / "build_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")


def expected_outputs(project: Path, preset: str) -> list[Path]:
    if preset.startswith("web"):
        base = project / "exports" / preset
        return [base / "index.html", base / "index.wasm", base / "index.pck"]
    if preset == "android":
        return [project / "exports" / "android" / "game.apk"]
    if preset == "ios":
        return [project / "exports" / "ios"]
    return []


def configure_web_renderer(export_html: Path, preset: str) -> None:
    """Bind the generated shell and engine CLI to the preset's real renderer.

    Exports use the official editor with Studio's custom runtime templates. The
    official editor does not know Studio's WebGPU-only HTML configuration field,
    so make that handoff explicit after export and preserve all existing args.
    """
    if preset not in {"web-webgl", "web-webgpu"}:
        return
    source = export_html.read_text(encoding="utf-8")
    match = re.search(r"const GODOT_CONFIG = (\{[^\n]+\});", source)
    if not match:
        raise RuntimeError(f"generated Godot config not found in {export_html}")
    config = json.loads(match.group(1))
    args = config.get("args", [])
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise RuntimeError(f"generated Godot args are invalid in {export_html}")

    if preset == "web-webgpu":
        renderer_args = [
            "--rendering-method",
            "mobile",
            "--rendering-driver",
            "webgpu",
        ]
        config["renderingDriver"] = "webgpu"
    else:
        renderer_args = [
            "--rendering-method",
            "gl_compatibility",
            "--rendering-driver",
            "opengl3",
        ]
        config["renderingDriver"] = "opengl3"

    config["args"] = [*args, *renderer_args]
    serialized = json.dumps(config, separators=(",", ":"), sort_keys=True)
    updated = source[: match.start(1)] + serialized + source[match.end(1) :]
    export_html.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default="templates/godot-game")
    parser.add_argument(
        "--preset", required=True, choices=["web-webgl", "web-webgpu", "android", "ios"]
    )
    parser.add_argument("--debug", action="store_true", help="export debug build")
    args = parser.parse_args()
    senv.load_dotenv()

    problem = check_readiness(args.preset)
    if problem:
        print(f"NOT READY for preset '{args.preset}':\n{problem}", file=sys.stderr)
        return 3

    game_root = REPO / args.game
    project = game_root / "project" if (game_root / "project").is_dir() else game_root
    if not (project / "project.godot").is_file():
        raise SystemExit(f"no project.godot under {game_root}")

    godot = senv.find_godot()
    if not godot:
        raise SystemExit("Godot not found (just doctor)")

    # Fresh import + build stamp, then export.
    stamp_build_info(project, args.preset)
    for output in expected_outputs(project, args.preset):
        output.parent.mkdir(parents=True, exist_ok=True)

    sync = senv.run([sys.executable, str(Path(__file__).with_name("sync_addons.py"))], timeout=60)
    if sync.returncode != 0:
        print(sync.stdout + sync.stderr, file=sys.stderr)
        return 1

    mode = "--export-debug" if args.debug else "--export-release"
    try:
        proc = senv.run([godot, "--headless", "--path", str(project), "--import"], timeout=300)
        proc = senv.run(
            [godot, "--headless", "--path", str(project), mode, args.preset], timeout=900
        )
    except subprocess.TimeoutExpired as error:
        raise SystemExit("godot export timed out") from error
    web_html = project / "exports" / args.preset / "index.html"
    if proc.returncode == 0 and web_html.is_file() and args.preset.startswith("web"):
        configure_web_renderer(web_html, args.preset)

    output_text = (proc.stdout or "") + (proc.stderr or "")

    missing = [p for p in expected_outputs(project, args.preset) if not p.exists()]
    if proc.returncode != 0 or missing:
        print(output_text[-4000:], file=sys.stderr)
        if missing:
            print(f"missing expected outputs: {[str(m) for m in missing]}", file=sys.stderr)
        return proc.returncode or 1

    total = 0
    for output in expected_outputs(project, args.preset):
        if output.is_file():
            size = output.stat().st_size
            total += size
            print(f"  {output.relative_to(project)}  {size / 1024:.0f} KiB")
    print(
        f"export '{args.preset}' OK -> {project / 'exports' / args.preset}  (total {total / 1048576:.1f} MiB)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
