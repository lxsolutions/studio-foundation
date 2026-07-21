"""studio-mcp tool registry: narrow, allowlisted, schema-validated operations.

Every tool is a fixed argv template + validated arguments. There is NO generic
shell/eval surface, and long/destructive operations return guidance instead of
executing (ADR 0009).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from studio_tools import env as senv
from studio_tools.mcp import security
from studio_tools.mcp.security import ToolArgError

REPO = senv.repo_root()
RUN_DIR = REPO / ".mcp-run"
LOG_PATH = REPO / ".mcp-log" / "studio-mcp.log"

GAME_ARG = {
    "type": "string",
    "pattern": r"^[A-Za-z0-9_\-/]+$",
    "default": "templates/godot-game",
    "description": "Repo-relative game root (templates/godot-game or games/<name>)",
}
BLEND_ARG = {"type": "string", "description": "Repo-relative path to a .blend master"}


def _audit(tool: str, args: dict, exit_code: int, ms: int) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts_ms": int(time.time() * 1000),
        "tool": tool,
        "args": security.redact(args),
        "exit": exit_code,
        "duration_ms": ms,
    }
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _run(
    argv: list[str], timeout: int = security.DEFAULT_TIMEOUT, cwd: Path = REPO
) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError as exc:
        return 127, f"tool binary not found: {exc}"
    return proc.returncode, security.cap_output((proc.stdout or "") + (proc.stderr or ""))


def _py() -> str:
    return sys.executable or "python"


def _compose_psql(statements: list[str], timeout: int = 30) -> tuple[int, str]:
    argv = senv.compose_argv(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "studio_ro",
        "-d",
        os.environ.get("STUDIO_PG_DB", "studio"),
        "-v",
        "ON_ERROR_STOP=1",
        "-P",
        "pager=off",
    )
    for statement in statements:
        argv += ["-c", statement]
    return _run(argv, timeout=timeout)


# --------------------------------------------------------------------- tools


def tool_studio_get_status(args: dict) -> tuple[int, str]:
    return _run([_py(), str(REPO / "tools" / "doctor" / "doctor.py"), "--json"], timeout=90)


def tool_studio_list_projects(args: dict) -> tuple[int, str]:
    projects = [{"id": "template", "path": "templates/godot-game"}]
    games = REPO / "games"
    if games.is_dir():
        for game in sorted(games.iterdir()):
            if (game / "project" / "project.godot").is_file():
                projects.append({"id": game.name, "path": f"games/{game.name}"})
    return 0, json.dumps(projects, indent=2)


def tool_studio_create_game_from_template(args: dict) -> tuple[int, str]:
    return _run(
        [
            _py(),
            str(REPO / "tools" / "build" / "new_game.py"),
            "--name",
            args["name"],
            "--display-name",
            args.get("display_name", args["name"]),
        ],
        timeout=180,
    )


def _game_path(args: dict) -> str:
    path = security.repo_relative_path(args.get("game", "templates/godot-game"), must_exist=True)
    return str(path.relative_to(REPO)).replace("\\", "/")


def tool_godot_validate_project(args: dict) -> tuple[int, str]:
    return _run(
        [
            _py(),
            str(REPO / "tools" / "godot" / "run_godot.py"),
            "--game",
            _game_path(args),
            "--import-only",
        ],
        timeout=300,
    )


def tool_godot_run_tests(args: dict) -> tuple[int, str]:
    return _run(
        [
            _py(),
            str(REPO / "tools" / "godot" / "run_godot.py"),
            "--game",
            _game_path(args),
            "--tests",
        ],
        timeout=420,
    )


def tool_godot_export(args: dict) -> tuple[int, str]:
    return _run(
        [
            _py(),
            str(REPO / "tools" / "godot" / "export_game.py"),
            "--game",
            _game_path(args),
            "--preset",
            args["preset"],
        ],
        timeout=600,
    )


def tool_godot_collect_logs(args: dict) -> tuple[int, str]:
    project = security.repo_relative_path(args.get("game", "templates/godot-game"), must_exist=True)
    name = None
    project_file = project / "project" / "project.godot"
    if project_file.is_file():
        for line in project_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("config/name="):
                name = line.split("=", 1)[1].strip().strip('"')
    if not name:
        return 1, "could not determine project name"
    if os.name == "nt":
        log_dir = Path(os.environ.get("APPDATA", "")) / "Godot" / "app_userdata" / name / "logs"
    else:
        log_dir = Path.home() / ".local/share/godot/app_userdata" / name / "logs"
    if not log_dir.is_dir():
        return 0, f"no logs yet at {log_dir}"
    logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return 0, "log directory empty"
    return 0, security.cap_output(logs[0].read_text(encoding="utf-8", errors="replace"))


def tool_godot_capture_screenshot(args: dict) -> tuple[int, str]:
    return _run(
        [
            _py(),
            str(REPO / "tools" / "screenshots" / "visual_regression.py"),
            "capture",
            "--game",
            _game_path(args),
        ],
        timeout=300,
    )


def tool_godot_run_benchmark(args: dict) -> tuple[int, str]:
    return _run(
        [_py(), str(REPO / "tools" / "benchmark" / "run_benchmark.py"), "--game", _game_path(args)],
        timeout=600,
    )


def tool_engine_show_versions(args: dict) -> tuple[int, str]:
    return _run([_py(), str(REPO / "engine" / "scripts" / "engine.py"), "versions"], timeout=60)


def tool_engine_fetch(args: dict) -> tuple[int, str]:
    return _run([_py(), str(REPO / "engine" / "scripts" / "engine.py"), "fetch"], timeout=1800)


def tool_engine_build(args: dict) -> tuple[int, str]:
    return 1, (
        "engine_build is deliberately not runnable through MCP: it is an hours-long "
        "compile. Run `just engine-build` in a terminal (see docs/runbooks/engine-rebuild.md)."
    )


def tool_engine_classify_conflicts(args: dict) -> tuple[int, str]:
    return _run(
        [_py(), str(REPO / "engine" / "scripts" / "classify_conflicts.py"), "--json"],
        timeout=300,
    )


def tool_engine_build_status(args: dict) -> tuple[int, str]:
    """Report built template artifacts + whether they match the engine-lock pin."""
    artifacts = REPO / "engine" / "artifacts" / "templates"
    lock = senv.engine_lock()
    pinned = lock.get("godot", {}).get("webgpu_fork", {})
    zips = []
    if artifacts.is_dir():
        for z in sorted(artifacts.glob("*.zip")):
            zips.append({"file": z.name, "bytes": z.stat().st_size})
    return 0, json.dumps(
        {
            "pinned_branch": pinned.get("branch"),
            "pinned_base": pinned.get("base"),
            "pinned_commit": pinned.get("commit"),
            "templates": zips,
            "built": len(zips) > 0,
        },
        indent=2,
    )


def tool_godot_capture_web(args: dict) -> tuple[int, str]:
    argv = [
        _py(),
        str(REPO / "tools" / "screenshots" / "capture_web.py"),
        "--game",
        _game_path(args),
        "--preset",
        args.get("preset", "web-webgl"),
    ]
    if args.get("out"):
        argv += ["--out", args["out"]]
    if args.get("wait"):
        argv += ["--wait", str(args["wait"])]
    return _run(argv, timeout=300)


def tool_godot_compare_screenshots(args: dict) -> tuple[int, str]:
    baseline = security.repo_relative_path(args["baseline"], must_exist=True, suffix=".png")
    candidate = security.repo_relative_path(args["candidate"], must_exist=True, suffix=".png")
    argv = [
        _py(),
        str(REPO / "tools" / "screenshots" / "compare_screenshots.py"),
        str(baseline),
        str(candidate),
    ]
    if args.get("max_diff_ratio") is not None:
        argv += ["--max-diff-ratio", str(args["max_diff_ratio"])]
    if args.get("channel_tolerance") is not None:
        argv += ["--channel-tolerance", str(args["channel_tolerance"])]
    return _run(argv, timeout=120)


def _blend(args: dict) -> str:
    path = security.repo_relative_path(args["file"], must_exist=True, suffix=".blend")
    return str(path)


def tool_blender_validate_asset(args: dict) -> tuple[int, str]:
    return _run(
        [_py(), str(REPO / "tools" / "asset-pipeline" / "pipeline.py"), "validate", _blend(args)],
        timeout=300,
    )


def tool_blender_export_asset(args: dict) -> tuple[int, str]:
    return _run(
        [_py(), str(REPO / "tools" / "asset-pipeline" / "pipeline.py"), "export", _blend(args)],
        timeout=600,
    )


def tool_blender_render_preview(args: dict) -> tuple[int, str]:
    return _run(
        [
            _py(),
            str(REPO / "tools" / "asset-pipeline" / "pipeline.py"),
            "preview",
            _blend(args),
            "--frames",
            str(args.get("frames", 1)),
        ],
        timeout=600,
    )


def tool_asset_get_metadata(args: dict) -> tuple[int, str]:
    path = security.repo_relative_path(args["file"], must_exist=True)
    if path.suffix == ".blend":
        path = path.with_name(path.stem + ".meta.json")
    if path.suffix != ".json" or not path.is_file():
        raise ToolArgError("no .meta.json sidecar found for that path")
    return 0, path.read_text(encoding="utf-8")


def tool_asset_search_catalog(args: dict) -> tuple[int, str]:
    query = args.get("query", "").lower()
    hits = []
    for meta_path in REPO.rglob("*.meta.json"):
        if any(
            part in ("assets-generated", "node_modules", "target", ".git")
            for part in meta_path.parts
        ):
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        haystack = " ".join(
            str(meta.get(field, "")) for field in ("asset_id", "category", "license", "creator")
        ).lower()
        if query in haystack:
            hits.append(
                {
                    "asset_id": meta.get("asset_id"),
                    "category": meta.get("category"),
                    "license": meta.get("license"),
                    "path": str(meta_path.relative_to(REPO)).replace("\\", "/"),
                }
            )
    return 0, json.dumps(hits, indent=2)


def tool_asset_cook_profile(args: dict) -> tuple[int, str]:
    return _run(
        [
            _py(),
            str(REPO / "tools" / "asset-pipeline" / "pipeline.py"),
            "cook",
            "--profile",
            args["profile"],
            "--game",
            _game_path(args),
        ],
        timeout=1800,
    )


def tool_postgres_schema_summary(args: dict) -> tuple[int, str]:
    return _compose_psql(
        [
            "SET default_transaction_read_only = on",
            r"\dn",
            r"\dt platform.*",
        ]
    )


def tool_postgres_migration_status(args: dict) -> tuple[int, str]:
    migrations_dir = REPO / "services" / "control-api" / "migrations"
    on_disk = sorted(p.name for p in migrations_dir.glob("*.sql"))
    code, output = _compose_psql(
        [
            "SET default_transaction_read_only = on",
            "SELECT version, description, success FROM _sqlx_migrations ORDER BY version",
        ]
    )
    summary = {
        "on_disk": on_disk,
        "database": output if code == 0 else f"(db unavailable: {output.strip()})",
    }
    return 0, json.dumps(summary, indent=2)


def tool_postgres_query_readonly(args: dict) -> tuple[int, str]:
    statement = security.validate_readonly_sql(args["query"])
    security.assert_local_database(
        os.environ.get("DATABASE_URL", "postgres://studio@127.0.0.1/studio"),
        extra_allowed_host=senv.pg_host(),
    )
    return _compose_psql(["SET default_transaction_read_only = on", statement])


def tool_server_run_tests(args: dict) -> tuple[int, str]:
    return _run(
        [str(senv.find_cargo() or "cargo"), "test", "--workspace"],
        timeout=900,
        cwd=REPO / "services",
    )


def _pidfile(service: str) -> Path:
    return RUN_DIR / f"{service}.pid"


def tool_server_start_local(args: dict) -> tuple[int, str]:
    service = args["service"]
    package = {"control-api": "studio-control-api", "dedicated-server": "studio-dedicated-server"}[
        service
    ]
    RUN_DIR.mkdir(exist_ok=True)
    if _pidfile(service).is_file():
        return 1, f"{service} already started by studio-mcp (stop it first)"
    cargo = senv.find_cargo() or "cargo"
    log_file = open(RUN_DIR / f"{service}.log", "a", encoding="utf-8")
    proc = subprocess.Popen(
        [cargo, "run", "--quiet", "-p", package],
        cwd=str(REPO / "services"),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    _pidfile(service).write_text(str(proc.pid), encoding="utf-8")
    return 0, f"{service} starting (pid {proc.pid}); logs: .mcp-run/{service}.log"


def tool_server_stop_local(args: dict) -> tuple[int, str]:
    service = args["service"]
    pidfile = _pidfile(service)
    if not pidfile.is_file():
        return 1, f"{service} was not started by studio-mcp; refusing to touch other processes"
    pid = int(pidfile.read_text(encoding="utf-8").strip())
    pidfile.unlink()
    if os.name == "nt":
        return _run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=30)
    os.kill(pid, 15)
    return 0, f"sent SIGTERM to {service} (pid {pid})"


def tool_ci_run_local(args: dict) -> tuple[int, str]:
    return _run(
        [_py(), str(REPO / "scripts" / "ci" / "run_all.py"), "--stage", args.get("stage", "pr")],
        timeout=1800,
    )


def tool_release_validate(args: dict) -> tuple[int, str]:
    return _run([_py(), str(REPO / "tools" / "release" / "release_validate.py")], timeout=300)


REGISTRY: dict[str, dict] = {
    "studio_get_status": {
        "fn": tool_studio_get_status,
        "description": "Doctor report: tool/platform readiness as JSON",
        "schema": {"type": "object", "properties": {}},
    },
    "studio_list_projects": {
        "fn": tool_studio_list_projects,
        "description": "List game projects (template + games/*)",
        "schema": {"type": "object", "properties": {}},
    },
    "studio_create_game_from_template": {
        "fn": tool_studio_create_game_from_template,
        "description": "Generate a new game under games/<name> from the template",
        "schema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{2,29}$"},
                "display_name": {"type": "string", "maxLength": 60},
            },
        },
    },
    "godot_validate_project": {
        "fn": tool_godot_validate_project,
        "description": "Headless import of a game project; fails on script errors",
        "schema": {"type": "object", "properties": {"game": GAME_ARG}},
    },
    "godot_run_tests": {
        "fn": tool_godot_run_tests,
        "description": "Run a project's headless GDScript test suite",
        "schema": {"type": "object", "properties": {"game": GAME_ARG}},
    },
    "godot_export": {
        "fn": tool_godot_export,
        "description": "Export a game with a named preset (web-webgl, web-webgpu, android, ios)",
        "schema": {
            "type": "object",
            "required": ["preset"],
            "properties": {
                "game": GAME_ARG,
                "preset": {"type": "string", "enum": ["web-webgl", "web-webgpu", "android", "ios"]},
            },
        },
    },
    "godot_collect_logs": {
        "fn": tool_godot_collect_logs,
        "description": "Read the most recent Godot user log for a project (read-only)",
        "schema": {"type": "object", "properties": {"game": GAME_ARG}},
    },
    "godot_capture_screenshot": {
        "fn": tool_godot_capture_screenshot,
        "description": "Capture the deterministic screenshot scene for a project",
        "schema": {"type": "object", "properties": {"game": GAME_ARG}},
    },
    "godot_run_benchmark": {
        "fn": tool_godot_run_benchmark,
        "description": "Run the benchmark scene and return structured metrics",
        "schema": {"type": "object", "properties": {"game": GAME_ARG}},
    },
    "engine_show_versions": {
        "fn": tool_engine_show_versions,
        "description": "Show pinned engine/toolchain versions vs local state",
        "schema": {"type": "object", "properties": {}},
    },
    "engine_fetch": {
        "fn": tool_engine_fetch,
        "description": "Fetch pinned engine sources into the local cache (network, minutes)",
        "schema": {"type": "object", "properties": {}},
    },
    "engine_build": {
        "fn": tool_engine_build,
        "description": "DISABLED: engine builds run only via `just engine-build` in a terminal",
        "schema": {"type": "object", "properties": {}},
    },
    "engine_build_status": {
        "fn": tool_engine_build_status,
        "description": "Report built WebGPU template artifacts vs the engine-lock pin (read-only)",
        "schema": {"type": "object", "properties": {}},
    },
    "engine_classify_conflicts": {
        "fn": tool_engine_classify_conflicts,
        "description": "Classify Godot-fork merge conflicts (mechanical/base-lag/fork-touched) as JSON",
        "schema": {"type": "object", "properties": {}},
    },
    "godot_capture_web": {
        "fn": tool_godot_capture_web,
        "description": "Real-GPU browser screenshot of a web export via Playwright (CI capture path)",
        "schema": {
            "type": "object",
            "properties": {
                "game": GAME_ARG,
                "preset": {"type": "string", "enum": ["web-webgl", "web-webgpu"]},
                "out": {"type": "string", "maxLength": 200},
                "wait": {"type": "integer", "minimum": 0, "maximum": 60000},
            },
        },
    },
    "godot_compare_screenshots": {
        "fn": tool_godot_compare_screenshots,
        "description": "Visual-regression gate: compare two PNGs with tolerance (exit 1 on divergence)",
        "schema": {
            "type": "object",
            "required": ["baseline", "candidate"],
            "properties": {
                "baseline": {"type": "string", "maxLength": 400},
                "candidate": {"type": "string", "maxLength": 400},
                "max_diff_ratio": {"type": "number", "minimum": 0, "maximum": 1},
                "channel_tolerance": {"type": "integer", "minimum": 0, "maximum": 255},
            },
        },
    },
    "blender_validate_asset": {
        "fn": tool_blender_validate_asset,
        "description": "Validate a .blend master against studio conventions",
        "schema": {"type": "object", "required": ["file"], "properties": {"file": BLEND_ARG}},
    },
    "blender_export_asset": {
        "fn": tool_blender_export_asset,
        "description": "Validate + export a .blend master to GLB (hash-cached)",
        "schema": {"type": "object", "required": ["file"], "properties": {"file": BLEND_ARG}},
    },
    "blender_render_preview": {
        "fn": tool_blender_render_preview,
        "description": "Render a thumbnail/turntable preview of a .blend master",
        "schema": {
            "type": "object",
            "required": ["file"],
            "properties": {
                "file": BLEND_ARG,
                "frames": {"type": "integer", "minimum": 1, "maximum": 16, "default": 1},
            },
        },
    },
    "asset_get_metadata": {
        "fn": tool_asset_get_metadata,
        "description": "Read the .meta.json sidecar for an asset",
        "schema": {
            "type": "object",
            "required": ["file"],
            "properties": {"file": {"type": "string"}},
        },
    },
    "asset_search_catalog": {
        "fn": tool_asset_search_catalog,
        "description": "Search asset sidecars by id/category/license/creator substring",
        "schema": {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string", "maxLength": 100}},
        },
    },
    "asset_cook_profile": {
        "fn": tool_asset_cook_profile,
        "description": "Cook all of a game's assets for a quality profile",
        "schema": {
            "type": "object",
            "required": ["profile"],
            "properties": {
                "game": GAME_ARG,
                "profile": {
                    "type": "string",
                    "enum": [
                        "desktop_high",
                        "browser_webgpu",
                        "browser_webgl",
                        "mobile_high",
                        "mobile_low",
                    ],
                },
            },
        },
    },
    "postgres_schema_summary": {
        "fn": tool_postgres_schema_summary,
        "description": "Schemas + platform tables via the read-only role (local dev DB only)",
        "schema": {"type": "object", "properties": {}},
    },
    "postgres_migration_status": {
        "fn": tool_postgres_migration_status,
        "description": "Migrations on disk vs applied in the local dev database",
        "schema": {"type": "object", "properties": {}},
    },
    "postgres_query_readonly": {
        "fn": tool_postgres_query_readonly,
        "description": "Single read-only SQL statement against the LOCAL dev database (studio_ro role)",
        "schema": {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string", "maxLength": 4000}},
        },
    },
    "server_run_tests": {
        "fn": tool_server_run_tests,
        "description": "cargo test --workspace for the Rust services",
        "schema": {"type": "object", "properties": {}},
    },
    "server_start_local": {
        "fn": tool_server_start_local,
        "description": "Start control-api or dedicated-server locally (pid-tracked)",
        "schema": {
            "type": "object",
            "required": ["service"],
            "properties": {
                "service": {"type": "string", "enum": ["control-api", "dedicated-server"]}
            },
        },
    },
    "server_stop_local": {
        "fn": tool_server_stop_local,
        "description": "Stop a service previously started by studio-mcp (only those)",
        "schema": {
            "type": "object",
            "required": ["service"],
            "properties": {
                "service": {"type": "string", "enum": ["control-api", "dedicated-server"]}
            },
        },
    },
    "ci_run_local": {
        "fn": tool_ci_run_local,
        "description": "Run the same checks CI runs (stage: pr|nightly)",
        "schema": {
            "type": "object",
            "properties": {"stage": {"type": "string", "enum": ["pr", "nightly"], "default": "pr"}},
        },
    },
    "release_validate": {
        "fn": tool_release_validate,
        "description": "Validate release readiness (clean tree, pins, licenses, manifests)",
        "schema": {"type": "object", "properties": {}},
    },
}


def list_tools() -> list[dict]:
    return [
        {
            "name": name,
            "description": entry["description"],
            "inputSchema": {**entry["schema"], "additionalProperties": False},
        }
        for name, entry in sorted(REGISTRY.items())
    ]


def call_tool(name: str, args: dict) -> tuple[bool, str]:
    """Returns (is_error, text). Validation errors never execute anything."""
    entry = REGISTRY.get(name)
    if entry is None:
        return True, f"unknown tool: {name}"
    started = time.monotonic()
    try:
        cleaned = security.validate_args(entry["schema"], args or {})
        code, output = entry["fn"](cleaned)
    except ToolArgError as exc:
        _audit(name, args or {}, -1, int((time.monotonic() - started) * 1000))
        return True, f"invalid arguments: {exc}"
    except Exception as exc:  # defense: never crash the server on a tool bug
        _audit(name, args or {}, -2, int((time.monotonic() - started) * 1000))
        return True, f"tool crashed: {type(exc).__name__}: {exc}"
    _audit(name, args or {}, code, int((time.monotonic() - started) * 1000))
    return code != 0, security.cap_output(output)
