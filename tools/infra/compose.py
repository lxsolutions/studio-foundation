#!/usr/bin/env python3
"""docker compose front door for infra/compose.yaml — local or remote (SSH) Docker host.

  compose.py <docker-compose-args...>

Local (default): runs `docker compose -f infra/compose.yaml --env-file .env <args>` here.

Remote (STUDIO_INFRA_REMOTE=<ssh host alias> set in .env): syncs infra/compose.yaml +
infra/postgres/ + .env to STUDIO_INFRA_REMOTE_DIR on that host (scp — small, static
files; no rsync dependency), then runs the same compose command over ssh there. Use
this when the local Docker engine can't run (e.g. no virtualization support) but a
Docker host is reachable over SSH/Tailscale. See infra/environments/README.md.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402

REPO = senv.repo_root()


def _remote_expr(path: str) -> str:
    """Shell-quote `path` for the remote command line without breaking a leading
    ~/ expansion (shlex.quote would wrap the whole thing in single quotes, which
    suppresses tilde expansion too — that bug once left a literal `~` dir behind)."""
    if path == "~":
        return "~"
    if path.startswith("~/"):
        return "~" + shlex.quote(path[1:])
    return shlex.quote(path)


def _sync(remote: str, remote_dir: str) -> int:
    mkdir = subprocess.call(["ssh", remote, f"mkdir -p {_remote_expr(remote_dir)}"])
    if mkdir != 0:
        return mkdir
    copy_infra = subprocess.call(
        [
            "scp",
            "-r",
            "-q",
            str(REPO / "infra" / "compose.yaml"),
            str(REPO / "infra" / "postgres"),
            f"{remote}:{remote_dir}/",
        ]
    )
    if copy_infra != 0:
        return copy_infra
    env_file = REPO / ".env"
    if env_file.is_file():
        return subprocess.call(["scp", "-q", str(env_file), f"{remote}:{remote_dir}/.env"])
    return 0


def _run_remote(remote: str, args: list[str]) -> int:
    remote_dir = senv.infra_remote_dir()
    sync_code = _sync(remote, remote_dir)
    if sync_code != 0:
        print(
            f"compose.py: sync to {remote}:{remote_dir} failed (exit {sync_code})", file=sys.stderr
        )
        return sync_code
    quoted_args = " ".join(shlex.quote(a) for a in args)
    remote_cmd = (
        f"cd {_remote_expr(remote_dir)} && "
        f"docker compose -f compose.yaml --env-file .env {quoted_args}"
    )
    return subprocess.call(["ssh", remote, remote_cmd])


def _run_local(args: list[str]) -> int:
    cmd = ["docker", "compose", "-f", str(REPO / "infra" / "compose.yaml")]
    if (REPO / ".env").is_file():
        cmd += ["--env-file", str(REPO / ".env")]
    return subprocess.call(cmd + args)


def main(argv: list[str]) -> int:
    remote = senv.infra_remote()
    return _run_remote(remote, argv) if remote else _run_local(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
