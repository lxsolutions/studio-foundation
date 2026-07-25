"""Small, dependency-free GLB v2 and runtime node-contract validation."""

from __future__ import annotations

import json
import struct
from collections.abc import Iterable
from pathlib import Path

GLB_MAGIC = b"glTF"
GLB_VERSION = 2
JSON_CHUNK = b"JSON"
HEADER = struct.Struct("<4sII")
CHUNK_HEADER = struct.Struct("<I4s")


class GlbContractError(ValueError):
    """A GLB cannot satisfy the runtime contract expected by the game."""


def read_glb_json(path: Path) -> dict:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise GlbContractError(f"cannot read GLB candidate {path}: {exc}") from exc

    minimum_size = HEADER.size + CHUNK_HEADER.size
    if len(payload) < minimum_size:
        raise GlbContractError(
            f"invalid GLB header: expected at least {minimum_size} bytes, found {len(payload)}"
        )

    magic, version, declared_length = HEADER.unpack_from(payload)
    if magic != GLB_MAGIC:
        raise GlbContractError(f"invalid GLB magic: expected 'glTF', found {magic!r}")
    if version != GLB_VERSION:
        raise GlbContractError(f"unsupported GLB version {version}: expected {GLB_VERSION}")
    if declared_length != len(payload):
        raise GlbContractError(
            f"invalid GLB length: header declares {declared_length} bytes, found {len(payload)}"
        )

    chunk_length, chunk_type = CHUNK_HEADER.unpack_from(payload, HEADER.size)
    if chunk_type != JSON_CHUNK:
        raise GlbContractError(f"invalid first GLB chunk: expected JSON, found {chunk_type!r}")
    if chunk_length % 4 != 0:
        raise GlbContractError(
            f"invalid GLB JSON chunk length {chunk_length}: chunks must be 4-byte aligned"
        )
    chunk_start = HEADER.size + CHUNK_HEADER.size
    chunk_end = chunk_start + chunk_length
    if chunk_end > declared_length:
        raise GlbContractError(
            f"truncated GLB JSON chunk: needs {chunk_end} bytes, file has {declared_length}"
        )

    try:
        document = json.loads(payload[chunk_start:chunk_end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GlbContractError(f"invalid GLB JSON chunk: {exc}") from exc
    if not isinstance(document, dict):
        raise GlbContractError("invalid GLB JSON chunk: root must be an object")
    return document


def validate_glb_contract(path: Path, required_nodes: Iterable[str] = ()) -> set[str]:
    document = read_glb_json(path)
    node_entries = document.get("nodes", [])
    if not isinstance(node_entries, list):
        raise GlbContractError("invalid GLB JSON chunk: 'nodes' must be an array")

    node_names = {
        entry["name"]
        for entry in node_entries
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    required = tuple(dict.fromkeys(required_nodes))
    missing = [name for name in required if name not in node_names]
    if missing:
        expected = ", ".join(missing)
        found = ", ".join(sorted(node_names)) or "<none>"
        raise GlbContractError(f"GLB missing required node(s): {expected}; exported nodes: {found}")
    return node_names
