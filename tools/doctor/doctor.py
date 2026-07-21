#!/usr/bin/env python3
"""Environment doctor: honest readiness report.

Runs on the SYSTEM Python (stdlib only) so it works before any bootstrap step.
Levels: required | optional | platform (platform-specific) | manual (needs a human
install) | na (not applicable on this OS). A platform is never reported ready just
because a config file exists — every check probes the real tool.

Usage: python tools/doctor/doctor.py [--json] [--strict]
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402


@dataclass
class Check:
    name: str
    level: str  # required | optional | platform | manual | na
    state: str  # ok | warn | missing | na
    detail: str
    fix: str = ""


def _version_of(argv: list[str], pattern_index: int = 0) -> str | None:
    try:
        proc = senv.run(argv, timeout=30)
    except Exception:
        return None
    out = (proc.stdout or proc.stderr or "").strip()
    return out.splitlines()[pattern_index] if out else None


def collect() -> list[Check]:
    senv.load_dotenv()
    checks: list[Check] = []
    add = checks.append
    is_windows = sys.platform == "win32"
    is_mac = sys.platform == "darwin"

    add(
        Check(
            "os",
            "required",
            "ok",
            f"{platform.system()} {platform.release()} ({platform.machine()})",
        )
    )
    add(
        Check(
            "python",
            "required",
            "ok" if sys.version_info >= (3, 11) else "warn",
            platform.python_version(),
            "install Python >= 3.11",
        )
    )

    # --- core CLI tools ---
    git = _version_of(["git", "--version"])
    add(Check("git", "required", "ok" if git else "missing", git or "not found", "install Git"))

    just = senv.find_just()
    just_ver = _version_of([just, "--version"]) if just else None
    add(
        Check(
            "just",
            "required",
            "ok" if just_ver else "missing",
            just_ver or "not found",
            "winget install Casey.Just | cargo install just | uv tool install rust-just",
        )
    )

    uv = _version_of(["uv", "--version"])
    add(
        Check(
            "uv",
            "required",
            "ok" if uv else "missing",
            uv or "not found",
            "https://docs.astral.sh/uv/ (winget install astral-sh.uv)",
        )
    )

    cargo = senv.find_cargo()
    cargo_ver = _version_of([cargo, "--version"]) if cargo else None
    rust_detail = cargo_ver or "not found"
    if cargo_ver and is_windows:
        host = _version_of([str(Path(cargo).parent / "rustc.exe"), "--version", "--verbose"])
        rustc_vv = None
        try:
            proc = senv.run([str(Path(cargo).parent / "rustc.exe"), "--version", "--verbose"])
            rustc_vv = proc.stdout
        except Exception:
            pass
        if rustc_vv and "pc-windows-gnu" in rustc_vv:
            rust_detail += " [windows-gnu host: OK, no MSVC needed]"
        elif rustc_vv and "pc-windows-msvc" in rustc_vv:
            rust_detail += " [msvc host: needs VS Build Tools; see ADR 0004]"
        _ = host
    add(
        Check(
            "rust",
            "required",
            "ok" if cargo_ver else "missing",
            rust_detail,
            "rustup: https://rustup.rs (Windows: --default-toolchain stable-x86_64-pc-windows-gnu)",
        )
    )

    # The windows-gnu toolchain links through a MinGW GCC. Rust ships a
    # self-contained gcc, but it cannot find the CRT startup objects
    # (dllcrt2.o, crtbegin.o, -lkernel32) unless a real MinGW bin dir is on
    # PATH. Probe for it so `cargo build` failures don't surprise contributors.
    if cargo_ver and is_windows and rustc_vv and "pc-windows-gnu" in rustc_vv:
        mingw_gcc = senv.which_any(["x86_64-w64-mingw32-gcc"])
        if not mingw_gcc:
            mingw_gcc = senv.find_mingw_gcc()
        add(
            Check(
                "mingw-linker",
                "required",
                "ok" if mingw_gcc else "missing",
                mingw_gcc or "x86_64-w64-mingw32-gcc not found",
                "winget install BrechtSanders.WinLibs.POSIX.UCRT and add its "
                "mingw64\\bin to PATH (cargo links via MinGW gcc on windows-gnu)",
            )
        )

    node = _version_of(["node", "--version"])
    add(
        Check(
            "node",
            "optional",
            "ok" if node else "missing",
            node or "not found",
            "Node 22 LTS — only needed for Playwright browser smoke tests",
        )
    )

    # --- Docker ---
    remote = senv.infra_remote()
    if remote:
        ssh_ok = False
        try:
            proc = senv.run(["ssh", remote, "docker info --format {{.ServerVersion}}"], timeout=20)
            ssh_ok = proc.returncode == 0 and bool(proc.stdout.strip())
        except Exception:
            ssh_ok = False
        add(
            Check(
                "docker",
                "manual",
                "ok" if ssh_ok else "warn",
                f"STUDIO_INFRA_REMOTE={remote}: engine "
                f"{'reachable' if ssh_ok else 'unreachable/NOT RUNNING'} over ssh "
                "(local Docker engine not required)",
                f"check `ssh {remote} docker info` and its Docker engine",
            )
        )
    else:
        docker_client = _version_of(["docker", "--version"])
        engine_ok = False
        if docker_client:
            try:
                proc = senv.run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=20)
                engine_ok = proc.returncode == 0 and bool(proc.stdout.strip())
            except Exception:
                engine_ok = False
        add(
            Check(
                "docker",
                "manual",
                "ok" if engine_ok else ("warn" if docker_client else "missing"),
                (
                    f"client {docker_client}, engine {'running' if engine_ok else 'NOT RUNNING'}"
                    if docker_client
                    else "not installed"
                ),
                "install/start Docker Desktop (Windows/macOS) or docker engine (Linux), "
                "or set STUDIO_INFRA_REMOTE to a Docker host reachable over SSH",
            )
        )

    # --- PostgreSQL (via compose) ---
    pg_host = senv.pg_host()
    pg_port = int(senv.load_dotenv().get("STUDIO_PG_PORT", "5432") or 5432)
    pg_up = senv.port_open(pg_host, pg_port)
    add(
        Check(
            "postgres",
            "optional",
            "ok" if pg_up else "missing",
            f"{pg_host}:{pg_port} {'accepting connections' if pg_up else 'not listening'}"
            + (f" (via remote Docker host '{remote}')" if remote else ""),
            "just services-up (requires Docker engine running)"
            + (f" on '{remote}'" if remote else ""),
        )
    )

    # --- Godot ---
    lock = senv.engine_lock()
    want_godot = lock["godot"]["official"]["tag"].replace("-stable", "")
    godot = senv.find_godot()
    gver = senv.godot_version(godot) if godot else None
    if gver and gver.startswith(want_godot):
        state, detail = "ok", f"{gver} at {godot}"
    elif gver:
        state, detail = "warn", f"{gver} (engine-lock pins {want_godot}) at {godot}"
    else:
        state, detail = "missing", "not found"
    add(
        Check(
            "godot",
            "required",
            state,
            detail,
            "winget install GodotEngine.GodotEngine (or set GODOT_BIN in .env)",
        )
    )

    # --- Godot web export templates (official, for WebGL2 fallback) ---
    tdir = senv.godot_templates_dir()
    web_ok = False
    tver = lock["godot"]["official"]["tag"].replace("-", ".")
    if tdir and (tdir / tver).is_dir():
        web_ok = any((tdir / tver).glob("web_*.zip"))
    add(
        Check(
            "godot-web-templates",
            "optional",
            "ok" if web_ok else "missing",
            f"{tdir / tver if tdir else '?'} {'has web templates' if web_ok else 'missing web templates'}",
            "Godot editor > Manage Export Templates, or official download; needed for export-browser-webgl",
        )
    )

    # --- WebGPU fork templates (built artifacts) ---
    fork_zip = senv.repo_root() / "engine" / "artifacts" / "templates"
    fork_built = fork_zip.is_dir() and any(fork_zip.glob("*web*webgpu*.zip"))
    add(
        Check(
            "webgpu-engine",
            "optional",
            "ok" if fork_built else "missing",
            "fork export templates built" if fork_built else "fork templates NOT built",
            "just engine-fetch && just engine-build (hours; needs scons+emsdk — see engine/README.md)",
        )
    )

    # PATH-only probe (engine builds use `uv run --group engine scons`, which
    # provisions scons on demand — do not mutate the uv env from doctor).
    scons = _version_of(["scons", "--version"], pattern_index=1)
    emcc = _version_of(["emcc", "--version"])
    add(
        Check(
            "engine-build-tools",
            "optional",
            "ok" if (scons and emcc) else "missing",
            f"scons: {'yes' if scons else 'no'}, emscripten: {'yes' if emcc else 'no'}",
            f"needed only for engine builds; emsdk {lock['toolchain']['emscripten']} pinned in engine-lock.toml",
        )
    )

    # --- Blender ---
    blender = senv.find_blender()
    bver = senv.blender_version(blender) if blender else None
    add(
        Check(
            "blender",
            "manual",
            "ok" if bver else "missing",
            f"{bver} at {blender}" if bver else "not found",
            "install Blender LTS (winget install BlenderFoundation.Blender) or set BLENDER_BIN in .env",
        )
    )

    # --- Android ---
    sdk = None
    import os as _os

    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        val = _os.environ.get(var)
        if val and Path(val).is_dir():
            sdk = val
            break
    if not sdk and is_windows:
        default = Path(_os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk"
        if default.is_dir():
            sdk = str(default)
    java = _version_of(["java", "-version"])
    android_state = "ok" if (sdk and java) else ("warn" if (sdk or java) else "missing")
    add(
        Check(
            "android",
            "platform",
            android_state,
            f"sdk: {sdk or 'not found'}; java: {'yes' if java else 'no'} - "
            + (
                "compile validation possible, signing NOT configured"
                if android_state == "ok"
                else "export unavailable"
            ),
            "install Android Studio SDK + JDK 17; configure Godot editor Android settings",
        )
    )

    # --- iOS ---
    if is_mac:
        xcode = _version_of(["xcodebuild", "-version"])
        add(
            Check(
                "ios",
                "platform",
                "ok" if xcode else "missing",
                xcode or "Xcode not found",
                "install Xcode from the App Store",
            )
        )
    else:
        add(
            Check(
                "ios",
                "na",
                "na",
                "requires macOS + Xcode; not applicable on this OS",
            )
        )

    # --- Browser testing ---
    browsers = senv.find_browsers()
    pw = (senv.repo_root() / "tests" / "browser" / "node_modules" / "playwright-core").is_dir()
    bt_state = (
        "ok" if (node and browsers and pw) else ("warn" if (node and browsers) else "missing")
    )
    add(
        Check(
            "browser-testing",
            "optional",
            bt_state,
            f"browsers: {', '.join(browsers) or 'none'}; playwright-core installed: {'yes' if pw else 'no (npm ci in tests/browser)'}",
            "cd tests/browser && npm ci  (playwright-core; drives installed Chrome/Edge, no browser downloads)",
        )
    )

    # --- MCP readiness ---
    mcp_cfg = (senv.repo_root() / ".mcp.json").is_file()
    mcp_ok = False
    try:
        proc = senv.run(
            [
                sys.executable,
                str(senv.repo_root() / "tools" / "studio-mcp" / "server.py"),
                "--self-check",
            ],
            timeout=30,
        )
        mcp_ok = proc.returncode == 0
    except Exception:
        mcp_ok = False
    add(
        Check(
            "studio-mcp",
            "optional",
            "ok" if (mcp_cfg and mcp_ok) else "warn",
            f"config: {'present' if mcp_cfg else 'missing'}; self-check: {'pass' if mcp_ok else 'fail'}",
            "see docs/agents/mcp/README.md",
        )
    )

    # --- repo hygiene ---
    envfile = (senv.repo_root() / ".env").is_file()
    add(
        Check(
            ".env",
            "optional",
            "ok" if envfile else "warn",
            "present" if envfile else "not created (defaults in use)",
            "cp .env.example .env",
        )
    )
    try:
        proc = senv.run(["git", "config", "core.hooksPath"])
        hooks = proc.stdout.strip() == ".githooks"
    except Exception:
        hooks = False
    add(
        Check(
            "git-hooks",
            "optional",
            "ok" if hooks else "warn",
            "guardrail hooks enabled" if hooks else "not enabled",
            "just hooks-install",
        )
    )

    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 if any required check is missing"
    )
    args = parser.parse_args()

    checks = collect()

    if args.json:
        print(json.dumps([asdict(c) for c in checks], indent=2))
    else:
        icon = {"ok": "[ OK ]", "warn": "[WARN]", "missing": "[MISS]", "na": "[ -- ]"}
        print(f"Studio Foundation doctor - {platform.node()}\n")
        for c in checks:
            print(f"{icon[c.state]} {c.name:<22} ({c.level:<8}) {c.detail}")
            if c.state in ("missing", "warn") and c.fix:
                print(f"       {'':<22}  fix: {c.fix}")
        req_missing = [c for c in checks if c.level == "required" and c.state == "missing"]
        opt_missing = [c for c in checks if c.level != "required" and c.state == "missing"]
        print(
            f"\nsummary: {len(checks)} checks; required missing: {len(req_missing)}; "
            f"optional/platform missing: {len(opt_missing)}"
        )
        if req_missing:
            print("required missing: " + ", ".join(c.name for c in req_missing))

    if args.strict and any(c.level == "required" and c.state == "missing" for c in checks):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
