"""UV generation and measurement.

Two projections cover almost all game work:

* **box** — deterministic, no operator context needed, and the correct choice
  for anything textured with a tiling/trim material because it keeps texel
  density uniform in *world* space.
* **smart** — Blender's angle-based unwrapper, for props that need their own
  packed 0..1 layout (baked textures, atlas members).

`texel_density` is included because it is the single most useful number in a
game-art review and nobody's AI tooling reports it.
"""

from __future__ import annotations

import math
from contextlib import contextmanager

import bmesh
import bpy
from mathutils import Vector


@contextmanager
def _edit(obj):
    """Enter edit mode on exactly one object, everything selected, then leave.

    Background Blender has no window, but the UV operators only need a valid
    view layer with an active object — verified against the pinned 5.2 build.
    """
    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    previous_selection = [o for o in bpy.context.scene.objects if o.select_get()]
    for other in bpy.context.scene.objects:
        other.select_set(False)
    obj.select_set(True)
    view_layer.objects.active = obj
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        yield
    finally:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        obj.select_set(False)
        for other in previous_selection:
            if other.name in bpy.context.scene.objects:
                other.select_set(True)
        view_layer.objects.active = previous_active


def ensure_layer(obj, name="UVMap"):
    mesh = obj.data
    layer = mesh.uv_layers.get(name)
    if layer is None:
        layer = mesh.uv_layers.new(name=name)
    mesh.uv_layers.active = layer
    return layer


def box_project(obj, scale=1.0, layer_name="UVMap"):
    """Per-face planar projection along the dominant normal axis.

    `scale` is metres-per-UV-tile: 1.0 means a 1 m face spans the whole 0..1
    texture. Uniform across every object you apply it to, which is what makes
    a modular kit look like one kit instead of six.
    """
    ensure_layer(obj, layer_name)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.get(layer_name) or bm.loops.layers.uv.new(layer_name)
    inv = 1.0 / max(1e-6, scale)
    for face in bm.faces:
        normal = face.normal
        axis = max(range(3), key=lambda i: abs(normal[i]))
        for loop in face.loops:
            co = loop.vert.co
            if axis == 0:
                u, v = co.y, co.z
                if normal.x < 0:
                    u = -u
            elif axis == 1:
                u, v = co.x, co.z
                if normal.y > 0:
                    u = -u
            else:
                u, v = co.x, co.y
                if normal.z < 0:
                    v = -v
            loop[uv_layer].uv = (u * inv, v * inv)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return {"method": "box", "scale": scale}


def cylinder_project(obj, layer_name="UVMap", axis=2):
    """Angle-around-axis vs height. Barrels, columns, tree trunks, pipes."""
    ensure_layer(obj, layer_name)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.get(layer_name) or bm.loops.layers.uv.new(layer_name)
    others = [i for i in range(3) if i != axis]
    zs = [v.co[axis] for v in bm.verts] or [0.0]
    lo, hi = min(zs), max(zs)
    span = max(1e-6, hi - lo)
    for face in bm.faces:
        for loop in face.loops:
            co = loop.vert.co
            angle = math.atan2(co[others[1]], co[others[0]])
            loop[uv_layer].uv = ((angle / (2 * math.pi)) + 0.5, (co[axis] - lo) / span)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return {"method": "cylinder"}


def smart_project(obj, angle_degrees=66.0, margin=0.02, layer_name="UVMap"):
    ensure_layer(obj, layer_name)
    with _edit(obj):
        bpy.ops.uv.smart_project(
            angle_limit=math.radians(angle_degrees),
            island_margin=margin,
            correct_aspect=True,
            scale_to_bounds=False,
        )
    return {"method": "smart", "angle": angle_degrees, "margin": margin}


def pack(obj, margin=0.02, layer_name="UVMap"):
    ensure_layer(obj, layer_name)
    with _edit(obj):
        bpy.ops.uv.pack_islands(margin=margin, rotate=True)
    return {"method": "pack", "margin": margin}


def normalize_to_unit(obj, layer_name="UVMap"):
    """Squash existing UVs into 0..1 without changing relative proportions."""
    mesh = obj.data
    layer = mesh.uv_layers.get(layer_name)
    if layer is None or not len(layer.data):
        return {"normalized": False}
    us = [d.uv[0] for d in layer.data]
    vs = [d.uv[1] for d in layer.data]
    lo_u, hi_u, lo_v, hi_v = min(us), max(us), min(vs), max(vs)
    span = max(hi_u - lo_u, hi_v - lo_v, 1e-6)
    for datum in layer.data:
        datum.uv[0] = (datum.uv[0] - lo_u) / span
        datum.uv[1] = (datum.uv[1] - lo_v) / span
    mesh.update()
    return {"normalized": True, "span": round(span, 5)}


def lightmap_uv(obj, name="UVLightmap", margin=0.03):
    """Second, non-overlapping UV set. Godot/Unity lightmappers require this."""
    mesh = obj.data
    if len(mesh.uv_layers) >= 8:
        return {"created": False, "reason": "uv layer limit reached"}
    layer = mesh.uv_layers.get(name) or mesh.uv_layers.new(name=name)
    mesh.uv_layers.active = layer
    with _edit(obj):
        bpy.ops.uv.lightmap_pack(PREF_CONTEXT="ALL_FACES", PREF_MARGIN_DIV=1.0 / max(margin, 1e-3))
    if mesh.uv_layers:
        mesh.uv_layers.active = mesh.uv_layers[0]
    return {"created": True, "name": name}


# ---------------------------------------------------------------------------
# measurement — the numbers a game-art review actually asks for
# ---------------------------------------------------------------------------


def stats(obj, texture_size=1024, layer_name="UVMap") -> dict:
    mesh = obj.data
    layer = mesh.uv_layers.get(layer_name) or (mesh.uv_layers[0] if mesh.uv_layers else None)
    if layer is None:
        return {"has_uvs": False}

    uv_area = 0.0
    world_area = 0.0
    out_of_bounds = 0
    matrix = obj.matrix_world
    for polygon in mesh.polygons:
        loops = list(polygon.loop_indices)
        coords = [layer.data[i].uv for i in loops]
        for uv in coords:
            if uv[0] < -1e-4 or uv[0] > 1.0001 or uv[1] < -1e-4 or uv[1] > 1.0001:
                out_of_bounds += 1
                break
        for i in range(1, len(coords) - 1):
            a, b, c = coords[0], coords[i], coords[i + 1]
            uv_area += abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) * 0.5
        verts = [matrix @ mesh.vertices[mesh.loops[i].vertex_index].co for i in loops]
        for i in range(1, len(verts) - 1):
            world_area += (verts[i] - verts[0]).cross(verts[i + 1] - verts[0]).length * 0.5

    density = 0.0
    if world_area > 1e-9 and uv_area > 1e-12:
        density = math.sqrt(uv_area / world_area) * texture_size

    return {
        "has_uvs": True,
        "layers": [layer_item.name for layer_item in mesh.uv_layers],
        "uv_area": round(uv_area, 5),
        "world_area_m2": round(world_area, 5),
        "coverage": round(min(uv_area, 1.0), 4),
        "texel_density_px_per_m": round(density, 1),
        "faces_outside_0_1": out_of_bounds,
    }


def overlap_estimate(obj, layer_name="UVMap", grid=64) -> float:
    """Cheap occupancy-grid overlap check: >0 means islands share texture space.

    Exact island intersection is expensive and rarely worth it; a stochastic
    grid tells an agent 'you have overlap, repack' which is the actionable bit.
    """
    mesh = obj.data
    layer = mesh.uv_layers.get(layer_name) or (mesh.uv_layers[0] if mesh.uv_layers else None)
    if layer is None:
        return 0.0
    hits: dict[tuple[int, int], int] = {}
    for polygon in mesh.polygons:
        cells = set()
        for i in polygon.loop_indices:
            uv = layer.data[i].uv
            cells.add(
                (
                    max(0, min(grid - 1, int(uv[0] * grid))),
                    max(0, min(grid - 1, int(uv[1] * grid))),
                )
            )
        for cell in cells:
            hits[cell] = hits.get(cell, 0) + 1
    if not hits:
        return 0.0
    overlapped = sum(1 for count in hits.values() if count > 1)
    return round(overlapped / len(hits), 4)


def world_uv_bounds(obj, layer_name="UVMap") -> dict:
    mesh = obj.data
    layer = mesh.uv_layers.get(layer_name) or (mesh.uv_layers[0] if mesh.uv_layers else None)
    if layer is None:
        return {}
    us = [d.uv[0] for d in layer.data] or [0.0]
    vs = [d.uv[1] for d in layer.data] or [0.0]
    return {
        "u": [round(min(us), 4), round(max(us), 4)],
        "v": [round(min(vs), 4), round(max(vs), 4)],
    }


def unwrap_for(obj, style: str, scale=1.0, margin=0.02):
    """Style-driven dispatch so recipes state intent, not method."""
    if style == "box":
        return box_project(obj, scale=scale)
    if style == "cylinder":
        return cylinder_project(obj)
    if style == "smart":
        return smart_project(obj, margin=margin)
    if style == "smart_packed":
        smart_project(obj, margin=margin)
        return pack(obj, margin=margin)
    if style == "none":
        return {"method": "none"}
    raise ValueError(f"unknown uv style: {style}")


def uv_islands(obj, layer_name="UVMap") -> int:
    """Island count — a proxy for how badly a mesh will seam under lighting."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.get(layer_name)
    if uv_layer is None:
        bm.free()
        return 0
    seen: set = set()
    islands = 0
    for face in bm.faces:
        if face in seen:
            continue
        islands += 1
        stack = [face]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for loop in current.loops:
                uv = Vector(loop[uv_layer].uv)
                for other in loop.edge.link_faces:
                    if other in seen:
                        continue
                    for other_loop in other.loops:
                        if (Vector(other_loop[uv_layer].uv) - uv).length < 1e-5:
                            stack.append(other)
                            break
    bm.free()
    return islands
