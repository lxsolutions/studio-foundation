"""The finishing pass every generated asset goes through.

Centralising this is the difference between "a script that makes a mesh" and
"a pipeline that makes game assets". Any recipe that skips a step here produces
something the engine will import wrong, so recipes don't get the choice.

Order matters and is not arbitrary:

1. cleanup    — weld doubles before anything measures or projects
2. shading    — sharp-edge flags before UVs, so seams can follow them
3. UVs        — needs final topology
4. material   — needs slots to exist before UV-dependent textures
5. origin     — needs final bounds
6. transforms — applied last so nothing downstream sees a dirty matrix
"""

from __future__ import annotations

from . import mat as mat_lib
from . import mesh as mesh_lib
from . import scene as scene_lib
from . import uvs as uv_lib


def finish(
    ctx,
    obj,
    material="stone",
    color=None,
    roughness=None,
    metallic=None,
    uv="box",
    uv_scale=1.0,
    origin="bottom",
    smooth=None,
    smooth_angle=35.0,
    merge_distance=1e-5,
    apply_transforms=True,
):
    """Take raw generated geometry to engine-ready. Returns a report dict."""
    bm = mesh_lib.obj_bmesh(obj)
    mesh_lib.cleanup(bm, merge_dist=merge_distance)
    mesh_lib.write_bmesh(bm, obj)

    if smooth is True:
        mesh_lib.shade_auto_smooth(obj, smooth_angle)
    elif smooth is False:
        mesh_lib.shade_flat(obj)

    if uv and uv != "none":
        uv_lib.unwrap_for(obj, uv, scale=uv_scale)

    if material:
        if isinstance(material, str):
            applied = mat_lib.from_preset(
                material, color=color, roughness=roughness, metallic=metallic
            )
        else:
            applied = material
        mat_lib.assign(obj, applied)

    if origin:
        scene_lib.set_origin(obj, origin)
    if apply_transforms:
        scene_lib.apply_transforms(obj)

    return report(ctx, obj)


def report(ctx, obj) -> dict:
    """The result shape every generator returns, so agents can chain on it."""
    info = {
        "name": obj.name,
        "triangles": mesh_lib.tri_count(obj),
        "vertices": len(obj.data.vertices),
        "materials": [m.name for m in obj.data.materials if m],
        "bounds": mesh_lib.bounds(obj),
    }
    uv_stats = uv_lib.stats(obj)
    if uv_stats.get("has_uvs"):
        info["texel_density_px_per_m"] = uv_stats["texel_density_px_per_m"]
        info["uv_coverage"] = uv_stats["coverage"]
    return info


def budget_note(ctx, obj, budget: int) -> None:
    """Warn — but never fail — when a generator overshoots its triangle budget.

    Failing here would be wrong: the agent may legitimately want a hero asset.
    Silence would also be wrong. So: say it, and say what to do about it.
    """
    tris = mesh_lib.tri_count(obj)
    if budget and tris > budget:
        ctx.note(
            f"'{obj.name}' is {tris} triangles, over the {budget} budget for this asset class. "
            f"Run gameready.lod to generate cheaper variants, or lower the detail parameters."
        )
