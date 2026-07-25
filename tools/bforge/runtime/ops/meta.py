"""Self-description ops — how an agent discovers what bforge can do."""

from __future__ import annotations

from lib import mat as mat_lib
from registry import OPS, catalog, op


@op(
    "meta.ops",
    summary="List every available operation with its parameters. Call this first if you are unsure what exists.",
    params={
        "tag": ("str", "", "Filter by tag (session, build, prop, kit, env, char, gameready, render, export, check)"),
        "search": ("str", "", "Filter by substring in the op name or summary"),
        "detail": ("enum:names|summary|schema", "summary", "How much to return per op"),
    },
    tags=["meta"],
    mutates=False,
)
def meta_ops(ctx, tag, search, detail):
    entries = catalog()
    if tag:
        entries = [e for e in entries if tag in e["tags"]]
    if search:
        needle = search.lower()
        entries = [
            e for e in entries if needle in e["name"].lower() or needle in e["summary"].lower()
        ]
    if detail == "names":
        return {"ops": [e["name"] for e in entries], "count": len(entries)}
    if detail == "summary":
        return {
            "ops": [
                {"name": e["name"], "summary": e["summary"], "tags": e["tags"]} for e in entries
            ],
            "count": len(entries),
        }
    return {"ops": entries, "count": len(entries)}


@op(
    "meta.help",
    summary="Full parameter schema and defaults for one operation.",
    params={"name": ("str", None, "Op name, e.g. 'prop.crate'")},
    tags=["meta"],
    mutates=False,
)
def meta_help(ctx, name):
    target = OPS.get(name)
    if target is None:
        prefix = name.split(".")[0]
        near = sorted(n for n in OPS if n.startswith(prefix))
        return {
            "error": f"no op named '{name}'",
            "did_you_mean": near or sorted(OPS)[:20],
        }
    return target.describe()


@op(
    "meta.palette",
    summary="The studio colour palette and material presets. Use these names instead of inventing colours — palette discipline is what makes a set of assets look like one game.",
    params={},
    tags=["meta"],
    mutates=False,
)
def meta_palette(ctx):
    # `colors` reports LINEAR values — the same numbers a material actually gets
    # — so feeding one straight back as a colour list reproduces the named
    # colour exactly. Reporting the authored sRGB here instead would mean
    # colour=[...] and colour="name" quietly disagreed. `hex` carries the
    # human-readable form for the hex parameter.
    return {
        "colors": {
            name: [round(c, 4) for c in mat_lib.resolve_color(name)]
            for name in mat_lib.PALETTE
        },
        "hex": {name: _hex_of(rgba) for name, rgba in mat_lib.PALETTE.items()},
        "presets": mat_lib.PRESETS,
        "note": "colors are linear (pass them back verbatim); hex is sRGB (pass to a hex colour param)",
    }


def _hex_of(rgba) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgba[:3])
