"""Minimal GLB structure reader (stdlib only).

Entity proofs verify the compiled artifact, not the build log: part names,
node hierarchy, and collision proxies are read back out of the binary. A
proof gate cannot let a malformed artifact look valid, so the structural
checks are strict: duplicate node names, out-of-range child indices, and
multiple parents are hard errors, not silent overwrites.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path


class GLBStructureError(ValueError):
    """The GLB's node tree is malformed (duplicate names, bad child indices,
    multiple parents)."""


def read_glb_json(path: Path) -> dict:
    """Return the glTF JSON chunk of a .glb file; truncated or malformed
    headers are controlled errors, not struct.exceptions."""
    data = Path(path).read_bytes()
    if len(data) < 20:
        raise GLBStructureError(f"{path}: truncated GLB header ({len(data)} bytes)")
    if data[:4] != b"glTF":
        raise GLBStructureError(f"{path}: not a GLB (bad magic)")
    json_length = struct.unpack_from("<I", data, 12)[0]
    if data[16:20] != b"JSON":
        raise GLBStructureError(f"{path}: first chunk is not JSON")
    if len(data) < 20 + json_length:
        raise GLBStructureError(f"{path}: truncated JSON chunk")
    try:
        return json.loads(data[20 : 20 + json_length])
    except json.JSONDecodeError as exc:
        raise GLBStructureError(f"{path}: malformed JSON chunk: {exc}") from exc


def node_index(gltf: dict) -> tuple[dict[str, int], dict[str, str]]:
    """(name -> node index, child name -> parent name) over the node tree.

    Raises GLBStructureError on duplicate names, out-of-range child indices,
    or a node with multiple parents.
    """
    nodes = gltf.get("nodes", [])
    by_name: dict[str, int] = {}
    parent_of: dict[str, str] = {}
    for i, node in enumerate(nodes):
        name = node.get("name", f"node_{i}")
        if name in by_name:
            raise GLBStructureError(f"duplicate GLB node name {name!r}")
        by_name[name] = i
        for child in node.get("children", []):
            if not isinstance(child, int) or child < 0 or child >= len(nodes):
                raise GLBStructureError(f"node {name!r} has out-of-range child index {child!r}")
            child_name = nodes[child].get("name", f"node_{child}")
            if child_name in parent_of:
                raise GLBStructureError(
                    f"node {child_name!r} has multiple parents ({parent_of[child_name]!r}, {name!r})"
                )
            parent_of[child_name] = name
    return by_name, parent_of
