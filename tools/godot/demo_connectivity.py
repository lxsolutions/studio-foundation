#!/usr/bin/env python3
"""Prove Godot -> control API -> PostgreSQL and Godot -> game server.

PostgreSQL must already be available (run just services-up). The runner owns
both Rust application processes on temporary loopback ports and always tears
them down.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402

RESULT_PREFIX = "CONNECTIVITY_RESULT "
REQUIRED_CHECKS = ("api_health", "db_roundtrip", "ws_handshake")
ERROR_MARKERS = ("SCRIPT ERROR", "Parse Error", "ERROR: Failed to load script")


class ConnectivityError(RuntimeError):
    """An actionable connectivity-demo failure."""


@dataclass
class ServerProcess:
    name: str
    process: subprocess.Popen
    log_handle: TextIO
    log_path: Path


def project_dir(game: str, root: Path | None = None) -> Path:
    root = (root or senv.repo_root()).resolve()
    game_path = (root / game).resolve()
    if not game_path.is_relative_to(root):
        raise ConnectivityError(f"game must stay inside the repository: {game}")
    project = game_path / "project" if (game_path / "project").is_dir() else game_path
    required = [
        (project / "project.godot", "project.godot"),
        (project / "tests" / "connectivity_check.gd", "tests/connectivity_check.gd"),
        (game_path / "server" / "Cargo.toml", "server/Cargo.toml"),
    ]
    for path, label in required:
        if not path.is_file():
            raise ConnectivityError(f"missing {label} under {game_path}")
    return project


def run_godot(
    binary: str, args: list[str], project: Path, timeout: int, env: dict[str, str]
) -> tuple[int, str]:
    try:
        proc = senv.run([binary, *args], timeout=timeout, cwd=project, env=env)
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") + "\n" + (exc.stderr or "")
        raise ConnectivityError(f"Godot timed out after {timeout}s\n{partial[-3000:]}") from exc
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def prepare_project(binary: str, project: Path, timeout: int, env: dict[str, str]) -> None:
    sync = senv.run(
        [sys.executable, str(senv.repo_root() / "tools" / "godot" / "sync_addons.py")],
        timeout=60,
    )
    if sync.returncode != 0:
        raise ConnectivityError(
            f"addon sync exited {sync.returncode}\n{(sync.stdout + sync.stderr)[-3000:]}"
        )
    code, output = run_godot(
        binary, ["--headless", "--path", str(project), "--import"], project, timeout, env
    )
    errors = [
        line.strip()
        for line in output.splitlines()
        if any(marker in line for marker in ERROR_MARKERS)
        and "WASAPI" not in line
        and "XAudio2" not in line
    ]
    if errors:
        raise ConnectivityError("Godot import found script errors:\n  " + "\n  ".join(errors[:40]))
    if code != 0:
        raise ConnectivityError(f"Godot import exited {code}\n{output[-3000:]}")
    print(f"import ok: {project.relative_to(senv.repo_root())}")


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def cargo_command(cargo: str, manifest: Path, package: str | None = None) -> list[str]:
    command = [cargo, "run", "--quiet", "--locked", "--manifest-path", str(manifest)]
    return [*command, "-p", package] if package else command


def start_server(
    name: str,
    cargo: str,
    manifest: Path,
    env: dict[str, str],
    log_dir: Path,
    package: str | None = None,
) -> ServerProcess:
    child_env = dict(env)
    if sys.platform == "win32" and (mingw_dir := senv.mingw_bin_dir()):
        child_env["PATH"] = mingw_dir + os.pathsep + child_env.get("PATH", "")
    log_path = log_dir / f"{name}.log"
    log_handle = log_path.open("w", encoding="utf-8")
    process_options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    try:
        process = subprocess.Popen(
            cargo_command(cargo, manifest, package),
            cwd=str(senv.repo_root()),
            env=child_env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            **process_options,
        )
    except OSError as exc:
        log_handle.close()
        raise ConnectivityError(f"could not start {name}: {exc}") from exc
    return ServerProcess(name, process, log_handle, log_path)


def server_log_tail(server: ServerProcess) -> str:
    server.log_handle.flush()
    return server.log_path.read_text(encoding="utf-8", errors="replace")[-3000:]


def wait_for_server(server: ServerProcess, port: int, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (code := server.process.poll()) is not None:
            raise ConnectivityError(
                f"{server.name} exited {code} before listening\n{server_log_tail(server)}"
            )
        if senv.port_open("127.0.0.1", port, timeout=0.2):
            print(f"{server.name} ready: 127.0.0.1:{port}")
            return
        time.sleep(0.1)
    raise ConnectivityError(
        f"{server.name} did not listen on 127.0.0.1:{port} within {timeout}s\n"
        f"{server_log_tail(server)}"
    )


def stop_server(server: ServerProcess) -> None:
    try:
        if server.process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(server.process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            else:
                os.killpg(server.process.pid, signal.SIGTERM)
            try:
                server.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    server.process.kill()
                else:
                    os.killpg(server.process.pid, signal.SIGKILL)
                server.process.wait(timeout=5)
    finally:
        server.log_handle.close()


def extract_result(output: str) -> dict[str, object]:
    lines = [line for line in output.splitlines() if line.startswith(RESULT_PREFIX)]
    if not lines:
        raise ConnectivityError("Godot did not print a CONNECTIVITY_RESULT line")
    try:
        value = json.loads(lines[-1][len(RESULT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise ConnectivityError(f"invalid CONNECTIVITY_RESULT JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ConnectivityError("CONNECTIVITY_RESULT must be a JSON object")
    return value


def result_failures(result: dict[str, object]) -> list[str]:
    failures = [name for name in REQUIRED_CHECKS if result.get(name) is not True]
    if not isinstance(result.get("session"), str) or not str(result["session"]).strip():
        failures.append("session")
    return failures


def check_client(
    binary: str, project: Path, timeout: int, env: dict[str, str]
) -> dict[str, object]:
    code, output = run_godot(
        binary,
        [
            "--headless",
            "--path",
            str(project),
            "--script",
            "res://tests/connectivity_check.gd",
        ],
        project,
        timeout,
        env,
    )
    try:
        result = extract_result(output)
    except ConnectivityError as exc:
        raise ConnectivityError(f"{exc}\n{output[-3000:]}") from exc
    failures = result_failures(result)
    if code != 0 or failures:
        detail = ", ".join(failures) if failures else f"Godot exit {code}"
        raise ConnectivityError(
            f"connectivity checks failed: {detail}\n"
            f"{RESULT_PREFIX}{json.dumps(result, sort_keys=True)}"
        )
    return result


def run_demo(game: str, timeout: int, startup_timeout: int) -> dict[str, object]:
    senv.load_dotenv()
    if not os.environ.get("DATABASE_URL", "").strip():
        raise ConnectivityError(
            "DATABASE_URL is not set; copy .env.example to .env and run just services-up"
        )
    project = project_dir(game)
    game_root = project.parent if project.name == "project" else project
    godot, cargo = senv.find_godot(), senv.find_cargo()
    if not godot:
        raise ConnectivityError("Godot not found (set GODOT_BIN or run just doctor)")
    if not cargo:
        raise ConnectivityError("Cargo not found (install Rust or run just doctor)")
    child_env = dict(os.environ)
    prepare_project(godot, project, timeout, child_env)

    api_port, ws_port = free_loopback_port(), free_loopback_port()
    while ws_port == api_port:
        ws_port = free_loopback_port()
    child_env.update(
        {
            "STUDIO_CONTROL_API_ADDR": f"127.0.0.1:{api_port}",
            "STUDIO_DEDICATED_ADDR": f"127.0.0.1:{ws_port}",
            "STUDIO_API_BASE": f"http://127.0.0.1:{api_port}",
            "STUDIO_WS_URL": f"ws://127.0.0.1:{ws_port}",
            "STUDIO_LOG": child_env.get("STUDIO_LOG", "warn"),
        }
    )
    servers: list[ServerProcess] = []
    with tempfile.TemporaryDirectory(prefix="studio-connectivity-") as temp_dir:
        try:
            specs = [
                (
                    "control-api",
                    senv.repo_root() / "services" / "Cargo.toml",
                    "studio-control-api",
                    api_port,
                ),
                ("game-server", game_root / "server" / "Cargo.toml", None, ws_port),
            ]
            for name, manifest, package, port in specs:
                server = start_server(name, cargo, manifest, child_env, Path(temp_dir), package)
                servers.append(server)
                wait_for_server(server, port, startup_timeout)
            return check_client(godot, project, timeout, child_env)
        finally:
            for server in reversed(servers):
                stop_server(server)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", default="templates/godot-game")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--startup-timeout", type=int, default=300)
    args = parser.parse_args(argv)
    if args.timeout < 1 or args.startup_timeout < 1:
        parser.error("timeouts must be positive")
    try:
        result = run_demo(args.game, args.timeout, args.startup_timeout)
    except ConnectivityError as exc:
        print(f"connectivity failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("connectivity interrupted", file=sys.stderr)
        return 130
    print(RESULT_PREFIX + json.dumps(result, sort_keys=True))
    print("connectivity ok: API + PostgreSQL round trip + WebSocket handshake")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
