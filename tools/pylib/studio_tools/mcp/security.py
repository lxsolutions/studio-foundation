"""Security primitives for studio-mcp. Every tool argument passes through here.

Rules (ADR 0009):
- repository-relative paths only; resolved result must stay inside the repo
- explicit per-argument schemas (type, enum, regex, range) — reject extras
- read-only SQL only, single statement, localhost databases only
- execution timeouts and output caps on every subprocess
- no shell=True anywhere in this package
"""

from __future__ import annotations

import re
from pathlib import Path

from studio_tools import env as senv

MAX_OUTPUT_BYTES = 64 * 1024
DEFAULT_TIMEOUT = 120

GAME_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,29}$")
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SQL_FORBIDDEN = re.compile(
    r"(?i)\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|vacuum|do|call|merge|comment|security|reset|set\s+role)\b"
)


class ToolArgError(ValueError):
    """Raised when tool input fails validation; returned to the client as a
    tool error, never executed."""


def repo_relative_path(raw: str, *, must_exist: bool = False, suffix: str | None = None) -> Path:
    """Validate a repository-relative path. Rejects absolute paths, drive
    letters, parent-escapes, and (via resolve) symlink escapes."""
    if not isinstance(raw, str) or not raw.strip():
        raise ToolArgError("path must be a non-empty string")
    raw = raw.strip().replace("\\", "/")
    if raw.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", raw):
        raise ToolArgError("absolute paths are not allowed; use repository-relative paths")
    if any(part == ".." for part in raw.split("/")):
        raise ToolArgError("path traversal ('..') is not allowed")
    root = senv.repo_root().resolve()
    candidate = (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise ToolArgError("path escapes the repository")
    if suffix and candidate.suffix != suffix:
        raise ToolArgError(f"path must end with {suffix}")
    if must_exist and not candidate.exists():
        raise ToolArgError(f"path does not exist: {raw}")
    return candidate


def validate_args(schema: dict, args: dict) -> dict:
    """Validate args against a minimal JSON-Schema subset (type/enum/pattern/
    minimum/maximum/required/additionalProperties=false semantics)."""
    if not isinstance(args, dict):
        raise ToolArgError("arguments must be an object")
    properties: dict = schema.get("properties", {})
    unknown = set(args) - set(properties)
    if unknown:
        raise ToolArgError(f"unknown argument(s): {sorted(unknown)}")
    for name in schema.get("required", []):
        if name not in args:
            raise ToolArgError(f"missing required argument: {name}")
    cleaned: dict = {}
    for name, spec in properties.items():
        if name not in args:
            if "default" in spec:
                cleaned[name] = spec["default"]
            continue
        value = args[name]
        expected = spec.get("type", "string")
        if expected == "string":
            if not isinstance(value, str):
                raise ToolArgError(f"{name} must be a string")
            if "enum" in spec and value not in spec["enum"]:
                raise ToolArgError(f"{name} must be one of {spec['enum']}")
            if "pattern" in spec and not re.match(spec["pattern"], value):
                raise ToolArgError(f"{name} does not match required pattern {spec['pattern']}")
            if len(value) > int(spec.get("maxLength", 4096)):
                raise ToolArgError(f"{name} too long")
        elif expected == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ToolArgError(f"{name} must be an integer")
            if value < spec.get("minimum", -(2**31)) or value > spec.get("maximum", 2**31):
                raise ToolArgError(f"{name} out of range")
        elif expected == "boolean":
            if not isinstance(value, bool):
                raise ToolArgError(f"{name} must be a boolean")
        cleaned[name] = value
    return cleaned


def validate_readonly_sql(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ToolArgError("query must be a non-empty string")
    statement = query.strip().rstrip(";").strip()
    if ";" in statement:
        raise ToolArgError("exactly one SQL statement is allowed")
    if not re.match(r"(?i)^(select|explain|show|with)\b", statement):
        raise ToolArgError("only SELECT/EXPLAIN/SHOW/WITH read queries are allowed")
    if SQL_FORBIDDEN.search(statement):
        raise ToolArgError("statement contains a forbidden keyword (read-only access)")
    if len(statement) > 4000:
        raise ToolArgError("query too long")
    return statement


def assert_local_database(url: str, *, extra_allowed_host: str | None = None) -> None:
    """Refuse anything but this machine's own dev database.

    extra_allowed_host lets a caller also allow the STUDIO_PG_HOST configured in
    THIS machine's own .env (e.g. a remote Docker host's Tailscale address, when
    STUDIO_INFRA_REMOTE is set — see infra/environments/README.md). That's still
    local trust: the value comes from a gitignored local file, never from request
    input, so this isn't a general remote-database allowance.
    """
    match = re.match(r"^postgres(?:ql)?://[^@]*@([^/:]+)", url or "")
    host = match.group(1) if match else ""
    allowed = {"127.0.0.1", "localhost", "::1"}
    if extra_allowed_host:
        allowed.add(extra_allowed_host)
    if host not in allowed:
        raise ToolArgError(
            f"studio-mcp only queries local development databases ({', '.join(sorted(allowed))}); "
            "production database access is disabled by design"
        )


REDACT_RE = re.compile(r"(?i)(password|secret|token|key|authorization)")


def redact(args: dict) -> dict:
    return {key: ("<redacted>" if REDACT_RE.search(key) else value) for key, value in args.items()}


def cap_output(text: str) -> str:
    data = text.encode("utf-8", errors="replace")
    if len(data) <= MAX_OUTPUT_BYTES:
        return text
    return (
        data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        + f"\n…[truncated {len(data) - MAX_OUTPUT_BYTES} bytes]"
    )
