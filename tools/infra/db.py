#!/usr/bin/env python3
"""Local database operations over Docker Compose (dev/test only).

db.py seed | reset | backup | restore --file F | psql [...] | test-env -- CMD...
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402

REPO = senv.repo_root()
BACKUPS = REPO / "infra" / "backups"


def compose(*args: str) -> list[str]:
    return senv.compose_argv(*args)


def pg_env() -> tuple[str, str]:
    values = senv.load_dotenv()
    return values.get("STUDIO_PG_USER", "studio"), values.get("STUDIO_PG_DB", "studio")


def run(
    cmd: list[str],
    *,
    stdin_text: str | None = None,
    stdout_path: Path | None = None,
    timeout: int = 600,
    interactive: bool = False,
) -> int:
    if interactive:
        return subprocess.call(cmd)
    stdout = open(stdout_path, "wb") if stdout_path else subprocess.PIPE
    proc = subprocess.run(
        cmd,
        input=stdin_text.encode() if stdin_text is not None else None,
        stdout=stdout,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if stdout_path:
        stdout.close()
    if proc.returncode != 0:
        sys.stderr.write((proc.stderr or b"").decode(errors="replace"))
    elif proc.stdout:
        sys.stdout.write(proc.stdout.decode(errors="replace"))
    return proc.returncode


def migrate() -> int:
    cargo = senv.find_cargo()
    if not cargo:
        print(
            "cargo not found — run scripts/bootstrap, or apply migrations via psql", file=sys.stderr
        )
        return 127
    return subprocess.call(
        [cargo, "run", "--quiet", "-p", "studio-admin-cli", "--", "migrate"],
        cwd=str(REPO / "services"),
    )


def cmd_seed() -> int:
    user, db = pg_env()
    seed_sql = (REPO / "infra" / "postgres" / "seed.sql").read_text(encoding="utf-8")
    return run(
        compose("exec", "-T", "postgres", "psql", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1"),
        stdin_text=seed_sql,
    )


def cmd_reset() -> int:
    print("resetting DEV database volume (compose down -v)…")
    if run(compose("down", "-v")) != 0:
        return 1
    if run(compose("up", "-d", "--wait", "postgres"), timeout=180) != 0:
        return 1
    code = migrate()
    if code != 0:
        return code
    return cmd_seed()


def cmd_backup() -> int:
    user, db = pg_env()
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out = BACKUPS / f"{db}_{stamp}.dump"
    code = run(
        compose("exec", "-T", "postgres", "pg_dump", "-U", user, "-d", db, "-Fc"),
        stdout_path=out,
    )
    if code == 0:
        print(f"backup -> {out.relative_to(REPO)} ({out.stat().st_size // 1024} KiB)")
    return code


def cmd_restore(file: str) -> int:
    user, db = pg_env()
    dump = Path(file)
    if not dump.is_file():
        raise SystemExit(f"backup not found: {file}")
    data = dump.read_bytes()
    proc = subprocess.run(
        compose(
            "exec", "-T", "postgres", "pg_restore", "-U", user, "-d", db, "--clean", "--if-exists"
        ),
        input=data,
        capture_output=True,
    )
    sys.stderr.write((proc.stderr or b"").decode(errors="replace"))
    print("restore complete" if proc.returncode == 0 else "restore FAILED")
    return proc.returncode


def cmd_psql(extra: list[str]) -> int:
    user, db = pg_env()
    return run(compose("exec", "postgres", "psql", "-U", user, "-d", db, *extra), interactive=True)


def ensure_test_database(user: str) -> int:
    """Create studio_test only when absent, without treating normal reuse as an error."""
    check = subprocess.run(
        compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            user,
            "-d",
            "postgres",
            "-tAc",
            "SELECT 1 FROM pg_database WHERE datname = 'studio_test'",
        ),
        capture_output=True,
    )
    if check.returncode != 0:
        sys.stderr.write((check.stderr or b"").decode(errors="replace"))
        return check.returncode
    if check.stdout.strip() == b"1":
        return 0
    return run(
        compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            user,
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "CREATE DATABASE studio_test",
        )
    )


def cmd_test_env(command: list[str]) -> int:
    """Ensure studio_test DB exists on the dev container, run CMD with
    DATABASE_URL pointed at it (used by `just test-db`)."""
    user, _ = pg_env()
    values = senv.load_dotenv()
    port = values.get("STUDIO_PG_PORT", "5432")
    password = values.get("STUDIO_PG_PASSWORD", "studio_dev_password")
    database_code = ensure_test_database(user)
    if database_code != 0:
        return database_code
    host = senv.pg_host()
    env = dict(os.environ)
    env["DATABASE_URL"] = f"postgres://{user}:{password}@{host}:{port}/studio_test"
    print(f"test env: DATABASE_URL -> studio_test on {host}:{port}")
    return subprocess.call(command, env=env, cwd=str(REPO))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    sub.add_parser("reset")
    sub.add_parser("backup")
    restore = sub.add_parser("restore")
    restore.add_argument("--file", required=True)
    psql = sub.add_parser("psql")
    psql.add_argument("extra", nargs="*")
    test_env = sub.add_parser("test-env")
    test_env.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.command == "seed":
        return cmd_seed()
    if args.command == "reset":
        return cmd_reset()
    if args.command == "backup":
        return cmd_backup()
    if args.command == "restore":
        return cmd_restore(args.file)
    if args.command == "psql":
        return cmd_psql(args.extra)
    if args.command == "test-env":
        # Strip only the leading `--` (db.py's own separator) — a later `--` is the
        # caller's own, e.g. `cargo test ... -- --ignored`, and must survive intact.
        command = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
        if not command:
            raise SystemExit("usage: db.py test-env -- <command…>")
        return cmd_test_env(command)
    return 2


if __name__ == "__main__":
    sys.exit(main())
