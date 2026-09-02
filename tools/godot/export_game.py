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


def _webgpu_template_identity_problem(artifacts: Path, lock: dict) -> str | None:
    """Refuse to export against templates that are not this patch series.

    Exporting is where a stale or foreign template becomes an invisible problem:
    the export succeeds, the browser runs *something*, and every measurement taken
    afterwards describes a build nobody meant to test. Checking the stamp here
    turns that into a message instead of a wrong number.

    A missing stamp is a warning, not a failure — templates built before stamping
    existed are still usable, they just cannot be identified.
    """
    sys.path.insert(0, str(REPO / "tools" / "pylib"))
    try:
        from studio_tools.provenance import ProvenanceError, series_from_lock, series_id
    except ImportError:
        return None

    stamp_file = artifacts / "provenance.json"
    if not stamp_file.is_file():
        print(
            f"warning: {stamp_file.relative_to(REPO)} is missing — these templates "
            "cannot be identified. Rebuild with `just engine-build` to stamp them.",
            file=sys.stderr,
        )
        return None
    try:
        stamped = json.loads(stamp_file.read_text(encoding="utf-8")).get("series_id")
        expected = series_id(*series_from_lock(lock))
    except (OSError, json.JSONDecodeError, ProvenanceError) as exc:
        print(f"warning: could not read template provenance: {exc}", file=sys.stderr)
        return None

    if stamped != expected:
        return (
            "Installed WebGPU templates are from a different patch series.\n"
            f"  templates: {stamped}\n"
            f"  this repo: {expected}\n"
            "Fix: just engine-fetch && just engine-build"
        )
    return None


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
        return _webgpu_template_identity_problem(artifacts, lock)
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


def dotnet_signals(project: Path) -> list[str]:
    """Evidence that this project is a C#/.NET Godot project, named individually."""
    signals: list[str] = []
    for pattern in ("*.csproj", "*.sln"):
        for found in sorted(project.glob(pattern)):
            signals.append(found.name)
    try:
        settings = (project / "project.godot").read_text(encoding="utf-8", errors="replace")
    except OSError:
        settings = ""
    if "[dotnet]" in settings or "dotnet/project/assembly_name" in settings:
        signals.append("project.godot declares a [dotnet] assembly")
    scripts = sorted(p.relative_to(project).as_posix() for p in project.rglob("*.cs"))
    scripts = [s for s in scripts if not s.startswith((".godot/", "obj/", "bin/"))]
    if scripts:
        preview = ", ".join(scripts[:3]) + (
            f", +{len(scripts) - 3} more" if len(scripts) > 3 else ""
        )
        signals.append(f"{len(scripts)} C# script(s): {preview}")
    return signals


def dotnet_web_problem(project: Path, preset: str) -> str | None:
    """Refuse a C#/.NET web export in the terms of the blocker that actually applies.

    Godot's own answer here is `export failed: cannot combine Mono runtime with the
    web platform`, which reads like a missing feature, a bad setting, or a template
    that someone forgot to download. It is none of those, and the difference decides
    what a team does next — so say the real thing before Godot says the cryptic one.

    A web export is one WebAssembly *main module*: the module that owns runtime
    initialization, the linear memory, and the JS glue the page boots. Godot's
    Emscripten build is that module. The .NET runtime is built to be that module too.
    Two candidates, one slot. No export preset, export template, or rendering backend
    changes that arithmetic, which is why this repository's WebGPU patch series does
    not help and structurally cannot: it replaces what Godot draws with, not what
    initializes the WebAssembly binary (ADR 0019).

    The way past it is not to win the slot. It is to stop needing it — compiled
    gameplay logic ships as a zero-import reactor module that any runtime can
    instantiate, and the Godot client stays GDScript. That path is real, checked, and
    documented, so point at it rather than leaving a team to rediscover the ceiling.
    """
    if not preset.startswith("web"):
        return None  # desktop and mobile presets export C# fine; only web has the conflict
    signals = dotnet_signals(project)
    if not signals:
        return None
    found = "\n".join(f"    - {signal}" for signal in signals)
    return (
        "this is a C#/.NET project, and .NET cannot be exported to the browser.\n"
        f"  Detected:\n{found}\n"
        "\n"
        "  Why (not a missing template, and not something this repo can patch):\n"
        "    A web export has exactly one WebAssembly main module -- the module that\n"
        "    owns runtime init, linear memory, and the JS glue the page boots. Godot's\n"
        "    Emscripten build is that module; the .NET runtime is built to be that\n"
        "    module too. Two runtimes, one slot. Godot reports this as\n"
        "      export failed: cannot combine Mono runtime with the web platform\n"
        "    Studio Foundation's WebGPU series changes what Godot DRAWS with, never\n"
        "    what initializes the binary, so it does not affect this at all.\n"
        "\n"
        "  What to do instead (docs/adr/0019-compiled-gameplay-on-the-web.md):\n"
        "    - Keep C# for desktop/mobile/server presets -- they are unaffected.\n"
        "    - For the browser, move the logic C# was carrying into the deterministic\n"
        "      sim kernel (services/sim-kernel): compiled Rust, one shared rule set for\n"
        "      client and server, verified identical across hosts by `just sim-parity`.\n"
        "      It compiles to a zero-import reactor module, so it needs no main-module\n"
        "      slot and loads from inside a Godot web export. `just sim-host-abi`\n"
        "      enforces that.\n"
        "    - Keep the Godot client itself in GDScript (ADR 0003), with StudioSimKernel\n"
        "      as its view onto the kernel's state.\n"
        "    - Or export web with the WebGL 2 / WebGPU presets from a GDScript project\n"
        "      and leave C# out of the browser target entirely."
    )


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


WEBGPU_RENDERING_METHODS = ("mobile", "forward_plus")


def configure_web_renderer(
    export_html: Path, preset: str, rendering_method: str = "mobile"
) -> None:
    """Bind the generated shell and engine CLI to the preset's real renderer.

    Exports use the official editor with Studio's custom runtime templates. The
    official editor does not know Studio's WebGPU-only HTML configuration field,
    so make that handoff explicit after export and preserve all existing args.

    `rendering_method` only applies to `web-webgpu`. It stays "mobile" by default
    because that is the configuration that has been verified on hardware, but
    Forward Mobile hard-disables the entire high-end feature set -- it returns
    false from `_render_buffers_can_be_storage`, `is_dynamic_gi_supported`, and
    `is_volumetric_supported`, so SSAO, SSIL, SSR, SDFGI, VoxelGI and volumetric
    fog are all unavailable no matter what a project asks for. "forward_plus"
    selects the clustered renderer, which is compiled into the same template and
    is a legal `rendering_method.web` value, so a Forward+ build can be produced
    and tested without editing this file.
    """
    if preset not in {"web-webgl", "web-webgpu"}:
        return
    if preset == "web-webgpu" and rendering_method not in WEBGPU_RENDERING_METHODS:
        raise RuntimeError(
            f"unsupported rendering method {rendering_method!r} for web-webgpu; "
            f"expected one of {', '.join(WEBGPU_RENDERING_METHODS)}"
        )
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
            rendering_method,
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
    parser.add_argument(
        "--rendering-method",
        default="mobile",
        choices=list(WEBGPU_RENDERING_METHODS),
        help=(
            "renderer for the web-webgpu preset (ignored by other presets). "
            "'mobile' is the hardware-verified default; 'forward_plus' enables the "
            "clustered renderer, which is the only one that can do SSAO/SSIL/SSR/"
            "SDFGI/VoxelGI/volumetric fog"
        ),
    )
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

    dotnet_problem = dotnet_web_problem(project, args.preset)
    if dotnet_problem:
        print(f"CANNOT EXPORT '{args.preset}': {dotnet_problem}", file=sys.stderr)
        return 3

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
        configure_web_renderer(web_html, args.preset, args.rendering_method)

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
