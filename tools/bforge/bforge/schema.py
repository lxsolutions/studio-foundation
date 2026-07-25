"""Schema export: one op registry, every function-calling dialect.

The registry lives inside Blender, so the catalogue is snapshotted to
``tools/bforge/catalog.json`` and committed. That means MCP `tools/list`, CLI
`--help` and llama.cpp schema dumps all answer instantly without starting
Blender — which matters because an MCP client calls `tools/list` at startup and
would otherwise pay a 6-second Blender boot before the user has typed anything.

Regenerate after adding or changing an op:  ``bforge catalog --refresh``
"""

from __future__ import annotations

import json
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalog.json"

# Written into MCP `initialize` so a model knows the shape of the toolset before
# it calls anything. Kept deliberately short — the details live in the catalog.
PRIMER = """\
bforge builds game-ready 3D assets in a headless Blender session. Ops are dotted
names run through bforge_run; state persists between calls, so you build an asset
up over several ops and then export it.

Namespaces:
  session.*    reset / info / save / open / snapshot   (start with session.reset)
  build.*      primitives + mesh editing (box, cylinder, lathe, extrude, greeble)
  prop.*       finished props: crate barrel chest sack rock crystal tree pillar
               torch fence furniture weapon banner debris
  kit.*        modular building kits and assembled rooms
  env.*        terrain, cliffs, water, roads, scatter, arenas
  char.*       humanoid blockouts, armatures, skinning, animation clips
  material.*   PBR presets, procedural graphs, baking to glTF-safe textures
  uv.*         unwrapping, packing, lightmap channels, texel-density reports
  gameready.*  LODs, collision proxies, budgets, atlasing, pivots, sockets
  render.*     contact sheets and turntables  -- LOOK at these, they are your eyes
  check.*      studio validation + actionable critique
  export.*     glTF/GLB, .blend masters, .meta.json sidecars

Normal workflow:
  1. session.reset
  2. one prop.*/kit.*/env.*/char.* recipe, or compose with build.*
  3. render.contact_sheet, and actually read the image
  4. check.critique, and act on the findings
  5. gameready.collision / gameready.lod
  6. export.asset

Everything is seeded and deterministic: same params + same seed = same mesh.
Sizes are metres. Use meta.palette colour names rather than inventing colours.
"""


def load_catalog() -> list[dict]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(
            f"no catalog at {CATALOG_PATH}. Run `bforge catalog --refresh` "
            "(needs Blender) to generate it."
        )
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["ops"]


def save_catalog(ops: list[dict]) -> Path:
    CATALOG_PATH.write_text(
        json.dumps({"version": 1, "ops": ops}, indent=2) + "\n", encoding="utf-8"
    )
    return CATALOG_PATH


def compact(ops: list[dict], tag: str = "", search: str = "") -> list[dict]:
    """Name + summary only — cheap enough to hand a model in full."""
    rows = ops
    if tag:
        rows = [o for o in rows if tag in o.get("tags", [])]
    if search:
        needle = search.lower()
        rows = [o for o in rows if needle in o["name"].lower() or needle in o["summary"].lower()]
    return [{"name": o["name"], "summary": o["summary"], "tags": o.get("tags", [])} for o in rows]


def to_openai(ops: list[dict], prefix: str = "bforge_") -> list[dict]:
    """OpenAI / llama.cpp / vLLM function-calling format.

    Dots are not legal in OpenAI function names, so `prop.crate` becomes
    `bforge_prop_crate`; `from_openai_name` maps it back.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": prefix + op["name"].replace(".", "_"),
                "description": op["summary"],
                "parameters": op["inputSchema"],
            },
        }
        for op in ops
    ]


def from_openai_name(name: str, prefix: str = "bforge_") -> str:
    stripped = name[len(prefix) :] if name.startswith(prefix) else name
    namespace, _, rest = stripped.partition("_")
    return f"{namespace}.{rest}" if rest else stripped


def to_anthropic(ops: list[dict]) -> list[dict]:
    """Anthropic tool-use format (name, description, input_schema)."""
    return [
        {
            "name": op["name"].replace(".", "_"),
            "description": op["summary"],
            "input_schema": op["inputSchema"],
        }
        for op in ops
    ]


def to_mcp_tools(ops: list[dict]) -> list[dict]:
    """MCP tools/list format, one entry per op (the `full` exposure mode)."""
    return [
        {
            "name": op["name"].replace(".", "_"),
            "description": op["summary"],
            "inputSchema": op["inputSchema"],
        }
        for op in ops
    ]


def markdown_reference(ops: list[dict]) -> str:
    """Human-readable reference, grouped by namespace."""
    groups: dict[str, list[dict]] = {}
    for op in ops:
        groups.setdefault(op["name"].split(".")[0], []).append(op)
    lines = ["# bforge op reference", "", f"{len(ops)} operations.", ""]
    for namespace in sorted(groups):
        lines.append(f"## `{namespace}.*`")
        lines.append("")
        for op in sorted(groups[namespace], key=lambda o: o["name"]):
            lines.append(f"### `{op['name']}`")
            lines.append("")
            lines.append(op["summary"])
            lines.append("")
            props = op["inputSchema"].get("properties", {})
            required = set(op["inputSchema"].get("required", []))
            if props:
                lines.append("| parameter | type | default | description |")
                lines.append("| --- | --- | --- | --- |")
                for key, spec in props.items():
                    kind = spec.get("type", "any")
                    if "enum" in spec:
                        kind = " \\| ".join(spec["enum"])
                    default = "**required**" if key in required else repr(spec.get("default"))
                    lines.append(
                        f"| `{key}` | {kind} | {default} | {spec.get('description', '')} |"
                    )
                lines.append("")
    return "\n".join(lines) + "\n"
