"""UV ops: unwrapping, packing, lightmap channels, and measurement."""

from __future__ import annotations

from lib import scene as scene_lib
from lib import uvs as uv_lib
from registry import OpError, op


@op(
    "uv.unwrap",
    summary="Generate UVs. Use 'box' with a shared uv_scale for anything using a tiling or trim texture (keeps texel density uniform across a whole kit); use 'smart_packed' for props that need their own baked texture.",
    params={
        "object": ("str", None, "Object name"),
        "style": ("enum:box|cylinder|smart|smart_packed|none", "smart_packed", "Unwrap strategy"),
        "scale": ("num", 1.0, "box only: metres per UV tile. Use the SAME value across a kit"),
        "margin": ("num", 0.02, "smart only: island padding, prevents bleed at low mip levels"),
    },
    tags=["uv"],
)
def uv_unwrap(ctx, object, style, scale, margin):
    obj = _get(object)
    if obj.type != "MESH":
        raise OpError(f"'{object}' is a {obj.type}, not a mesh")
    try:
        result = uv_lib.unwrap_for(obj, style, scale=scale, margin=margin)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
    stats = uv_lib.stats(obj)
    overlap = uv_lib.overlap_estimate(obj)
    if style in ("box", "cylinder") and overlap > 0.05:
        ctx.note(
            f"'{obj.name}' has ~{overlap:.0%} UV overlap, which is expected and fine for tiling "
            "textures but will corrupt any baked texture or lightmap. Use style='smart_packed' "
            "if you plan to bake."
        )
    return {"object": obj.name, **result, "stats": stats, "overlap_ratio": overlap}


@op(
    "uv.pack",
    summary="Repack existing UV islands into 0..1 without re-unwrapping. Use after joining objects or editing seams.",
    params={
        "object": ("str", None, "Object name"),
        "margin": ("num", 0.02, "Island padding"),
    },
    tags=["uv"],
)
def uv_pack(ctx, object, margin):
    obj = _get(object)
    uv_lib.pack(obj, margin=margin)
    return {"object": obj.name, "stats": uv_lib.stats(obj), "overlap_ratio": uv_lib.overlap_estimate(obj)}


@op(
    "uv.lightmap",
    summary="Add a second, non-overlapping UV channel for baked lighting. Godot and Unity both require this for static lightmaps.",
    params={
        "object": ("str", None, "Object name"),
        "name": ("str", "UVLightmap", "Name of the new UV layer"),
        "margin": ("num", 0.03, "Island padding — lightmaps need more than base textures"),
    },
    tags=["uv"],
)
def uv_lightmap(ctx, object, name, margin):
    obj = _get(object)
    result = uv_lib.lightmap_uv(obj, name=name, margin=margin)
    return {"object": obj.name, **result, "layers": [layer.name for layer in obj.data.uv_layers]}


@op(
    "uv.report",
    summary="Measure UV quality: texel density, coverage, island count, overlap. Texel density is the number to match across an asset set — mismatched density is the most common reason AI-made assets look wrong together.",
    params={
        "object": ("str", None, "Object name"),
        "texture_size": ("int", 1024, "Texture resolution the density figure assumes"),
    },
    tags=["uv", "inspect"],
    mutates=False,
)
def uv_report(ctx, object, texture_size):
    obj = _get(object)
    stats = uv_lib.stats(obj, texture_size=texture_size)
    if not stats.get("has_uvs"):
        raise OpError(f"'{object}' has no UV layers — run uv.unwrap first")
    stats["islands"] = uv_lib.uv_islands(obj)
    stats["overlap_ratio"] = uv_lib.overlap_estimate(obj)
    stats["bounds"] = uv_lib.world_uv_bounds(obj)
    return {"object": obj.name, **stats}


@op(
    "uv.normalize",
    summary="Fit existing UVs into the 0..1 square, preserving proportions.",
    params={"object": ("str", None, "Object name")},
    tags=["uv"],
)
def uv_normalize(ctx, object):
    obj = _get(object)
    return {"object": obj.name, **uv_lib.normalize_to_unit(obj)}


def _get(name):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
