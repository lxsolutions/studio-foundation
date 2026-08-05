"""Modular building kits.

A modular kit is the highest-leverage thing you can hand a level designer: a
handful of pieces that snap to a grid and combine into unlimited buildings. The
rules that make one work are unforgiving and easy to get wrong —

* every piece's origin sits at a grid corner, never at its centre of mass
* wall thickness is symmetric about the grid line, so pieces meet flush
* one shared texel density across the whole set (uv_scale here is global)
* doorway and window openings are cut, not faked with a decal

— so these recipes enforce all four rather than exposing them as options.
"""

from __future__ import annotations

import math

import bmesh
from lib import finish as finish_lib
from lib import mat as mat_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from lib import uvs as uv_lib
from mathutils import Matrix
from registry import OpError, op

PIECES = ["floor", "wall", "wall_door", "wall_window", "wall_half", "corner", "pillar",
          "stairs", "ramp", "roof", "arch", "railing"]


def _grid_piece(bm, kind, grid, height, thickness, rng, detail):
    """Build one kit piece in local space with its origin at (0, 0, 0)."""
    half = grid * 0.5
    if kind == "floor":
        mesh_lib.add_box(bm, size=(grid, grid, thickness),
                         center=(half, half, -thickness * 0.5), bevel=thickness * 0.12)
        if detail:
            faces = [f for f in bm.faces if f.normal.z > 0.7]
            bm.edges.ensure_lookup_table()
            edges = sorted({e for f in faces for e in f.edges}, key=lambda e: e.index)
            bmesh.ops.subdivide_edges(bm, edges=edges, cuts=1, use_grid_fill=True)
    elif kind == "wall":
        mesh_lib.add_box(bm, size=(grid, thickness, height),
                         center=(half, 0.0, height * 0.5), bevel=thickness * 0.15)
    elif kind == "wall_half":
        mesh_lib.add_box(bm, size=(grid, thickness, height * 0.5),
                         center=(half, 0.0, height * 0.25), bevel=thickness * 0.15)
    elif kind == "wall_door":
        door_w = grid * 0.38
        door_h = height * 0.72
        side = (grid - door_w) * 0.5
        for sign in (-1, 1):
            mesh_lib.add_box(
                bm, size=(side, thickness, height),
                center=(half + sign * (door_w + side) * 0.5, 0.0, height * 0.5),
                bevel=thickness * 0.15,
            )
        mesh_lib.add_box(bm, size=(door_w, thickness, height - door_h),
                         center=(half, 0.0, door_h + (height - door_h) * 0.5),
                         bevel=thickness * 0.15)
    elif kind == "wall_window":
        win_w, win_h = grid * 0.4, height * 0.36
        sill = height * 0.36
        side = (grid - win_w) * 0.5
        for sign in (-1, 1):
            mesh_lib.add_box(
                bm, size=(side, thickness, height),
                center=(half + sign * (win_w + side) * 0.5, 0.0, height * 0.5),
                bevel=thickness * 0.15,
            )
        mesh_lib.add_box(bm, size=(win_w, thickness, sill),
                         center=(half, 0.0, sill * 0.5), bevel=thickness * 0.15)
        top = height - sill - win_h
        mesh_lib.add_box(bm, size=(win_w, thickness, top),
                         center=(half, 0.0, height - top * 0.5), bevel=thickness * 0.15)
    elif kind == "corner":
        mesh_lib.add_box(bm, size=(thickness, thickness, height),
                         center=(0.0, 0.0, height * 0.5), bevel=thickness * 0.15)
        mesh_lib.add_box(bm, size=(grid - thickness, thickness, height),
                         center=((grid + thickness) * 0.5 - thickness * 0.5, 0.0, height * 0.5),
                         bevel=thickness * 0.15)
        mesh_lib.add_box(bm, size=(thickness, grid - thickness, height),
                         center=(0.0, (grid + thickness) * 0.5 - thickness * 0.5, height * 0.5),
                         bevel=thickness * 0.15)
    elif kind == "pillar":
        mesh_lib.add_box(bm, size=(thickness * 2.4, thickness * 2.4, thickness * 0.5),
                         center=(0.0, 0.0, thickness * 0.25), bevel=0.015)
        mesh_lib.add_box(bm, size=(thickness * 1.7, thickness * 1.7, height - thickness),
                         center=(0.0, 0.0, height * 0.5), bevel=0.012)
        mesh_lib.add_box(bm, size=(thickness * 2.4, thickness * 2.4, thickness * 0.5),
                         center=(0.0, 0.0, height - thickness * 0.25), bevel=0.015)
    elif kind == "stairs":
        steps = max(3, int(height / 0.19))
        rise = height / steps
        run = grid / steps
        for index in range(steps):
            mesh_lib.add_box(
                bm, size=(grid, run, rise),
                center=(half, run * (index + 0.5), rise * (index + 0.5)),
                bevel=rise * 0.1,
            )
    elif kind == "ramp":
        mesh_lib.add_wedge(bm, size=(grid, grid, height))
        bmesh.ops.transform(
            bm, matrix=Matrix.Rotation(math.radians(180), 4, "Z"), verts=bm.verts[:]
        )
        bmesh.ops.translate(bm, vec=(half, half, height * 0.5), verts=bm.verts[:])
    elif kind == "roof":
        peak = height * 0.5
        verts = [
            bm.verts.new((0.0, 0.0, 0.0)), bm.verts.new((grid, 0.0, 0.0)),
            bm.verts.new((grid, grid, 0.0)), bm.verts.new((0.0, grid, 0.0)),
            bm.verts.new((0.0, half, peak)), bm.verts.new((grid, half, peak)),
        ]
        bm.faces.new((verts[0], verts[1], verts[5], verts[4]))
        bm.faces.new((verts[2], verts[3], verts[4], verts[5]))
        bm.faces.new((verts[0], verts[4], verts[3]))
        bm.faces.new((verts[1], verts[2], verts[5]))
        bm.faces.new((verts[3], verts[2], verts[1], verts[0]))
    elif kind == "arch":
        span = grid * 0.6
        side = (grid - span) * 0.5
        for sign in (-1, 1):
            mesh_lib.add_box(
                bm, size=(side, thickness, height * 0.62),
                center=(half + sign * (span + side) * 0.5, 0.0, height * 0.31),
                bevel=thickness * 0.15,
            )
        segments = 8
        for index in range(segments):
            angle0 = math.pi * index / segments
            angle1 = math.pi * (index + 1) / segments
            radius = span * 0.5
            for angle in (angle0,):
                x0 = half - math.cos(angle0) * radius
                z0 = height * 0.62 + math.sin(angle0) * radius * 0.55
                x1 = half - math.cos(angle1) * radius
                z1 = height * 0.62 + math.sin(angle1) * radius * 0.55
                mesh_lib.add_box(
                    bm,
                    size=(math.dist((x0, z0), (x1, z1)) * 1.25, thickness, height * 0.14),
                    center=((x0 + x1) * 0.5, 0.0, (z0 + z1) * 0.5),
                    bevel=thickness * 0.1,
                )
    elif kind == "railing":
        mesh_lib.add_box(bm, size=(grid, thickness * 0.5, thickness * 0.5),
                         center=(half, 0.0, height * 0.45), bevel=0.005)
        posts = max(2, int(grid / 0.3))
        for index in range(posts + 1):
            mesh_lib.add_box(
                bm, size=(thickness * 0.35, thickness * 0.35, height * 0.45),
                center=(grid * index / posts, 0.0, height * 0.225), bevel=0.004,
            )
    else:
        raise OpError(f"unknown kit piece '{kind}'. Available: {', '.join(PIECES)}")
    return bm


@op(
    "kit.piece",
    summary="One modular kit piece with its origin at the grid corner, ready to snap. Build a whole set with kit.set instead if you want more than one.",
    params={
        "kind": (f"enum:{'|'.join(PIECES)}", "wall", "Piece type"),
        "name": ("str", "", "Object name"),
        "grid": ("num", 4.0, "Grid module size in metres — use ONE value across the whole kit"),
        "height": ("num", 3.0, "Wall/storey height in metres"),
        "thickness": ("num", 0.25, "Wall thickness in metres"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "material": ("str", "stone", "Material preset"),
        "color": ("str", "", "Override colour"),
        "uv_scale": ("num", 2.0, "Metres per UV tile — MUST match across the kit"),
        "detail": ("bool", False, "Extra edge loops for later greebling"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["kit", "architecture"],
)
def kit_piece(ctx, kind, name, grid, height, thickness, location, material, color, uv_scale,
              detail, seed):
    rng = ctx.reseed(seed)
    bm = mesh_lib.new_bmesh()
    _grid_piece(bm, kind, grid, height, thickness, rng, detail)
    mesh_lib.cleanup(bm)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name or f"kit_{kind}"))
    obj.location = location
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="box", uv_scale=uv_scale,
        origin="world", smooth=False,
    )
    result["grid"] = grid
    result["snap_hint"] = (
        f"Origin is the grid corner. Place copies at multiples of {grid} m on X/Y "
        f"and {height} m on Z."
    )
    return result


@op(
    "kit.set",
    summary="Generate a complete, texel-consistent modular kit in one call — floor, walls, door, window, corner, pillar, stairs, roof. This is the fastest path from nothing to a level a designer can actually build with.",
    params={
        "prefix": ("str", "kit", "Name prefix for every piece"),
        "pieces": ("str[]", ["floor", "wall", "wall_door", "wall_window", "corner", "pillar", "stairs", "roof"], "Which pieces to generate"),
        "grid": ("num", 4.0, "Grid module size in metres"),
        "height": ("num", 3.0, "Storey height in metres"),
        "thickness": ("num", 0.25, "Wall thickness in metres"),
        "material": ("str", "stone", "Shared material preset"),
        "color": ("str", "", "Override colour"),
        "uv_scale": ("num", 2.0, "Shared metres-per-UV-tile across the whole set"),
        "layout": ("bool", True, "Lay the pieces out in a row for review rendering"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["kit", "architecture"],
)
def kit_set(ctx, prefix, pieces, grid, height, thickness, material, color, uv_scale, layout, seed):
    unknown = [p for p in pieces if p not in PIECES]
    if unknown:
        raise OpError(f"unknown piece(s) {unknown}. Available: {', '.join(PIECES)}")
    shared = mat_lib.from_preset(material, name=f"m_{prefix}_{material}", color=color or None)
    made = []
    total = 0
    for index, kind in enumerate(pieces):
        rng = ctx.reseed(seed + index)
        bm = mesh_lib.new_bmesh()
        _grid_piece(bm, kind, grid, height, thickness, rng, False)
        mesh_lib.cleanup(bm)
        obj = mesh_lib.to_object(bm, scene_lib.unique_name(f"{prefix}_{kind}"))
        if layout:
            obj.location = (index * (grid + 1.5), 0.0, 0.0)
        mat_lib.assign(obj, shared)
        uv_lib.box_project(obj, scale=uv_scale)
        scene_lib.set_origin(obj, "world")
        scene_lib.apply_transforms(obj)
        report = finish_lib.report(ctx, obj)
        total += report["triangles"]
        made.append(report)
    ctx.note(
        f"All {len(made)} pieces share material '{shared.name}' and uv_scale={uv_scale} — "
        "that shared texel density is what makes them read as one kit. Keep it if you add more."
    )
    return {
        "prefix": prefix, "grid": grid, "height": height, "pieces": made,
        "total_triangles": total, "material": shared.name,
    }


@op(
    "kit.room",
    summary="Assemble a closed room from kit pieces: floor, four walls with a door and windows, optional pillars and roof. Produces a playable space, not just parts.",
    params={
        "name": ("str", "room", "Name for the assembled room"),
        "size": ("int[]", [3, 3], "Room size in grid modules [x, y]"),
        "grid": ("num", 4.0, "Grid module size in metres"),
        "height": ("num", 3.0, "Wall height in metres"),
        "thickness": ("num", 0.25, "Wall thickness in metres"),
        "doors": ("int", 1, "Number of doorway modules to cut into the walls"),
        "windows": ("int", 2, "Number of window modules"),
        "pillars": ("bool", True, "Corner pillars"),
        "roof": ("bool", False, "Add a pitched roof"),
        "material": ("str", "stone", "Material preset"),
        "color": ("str", "", "Override colour"),
        "uv_scale": ("num", 2.0, "Metres per UV tile"),
        "join": ("bool", True, "Merge into one mesh (recommended — one draw call)"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["kit", "architecture"],
)
def kit_room(ctx, name, size, grid, height, thickness, doors, windows, pillars, roof, material,
             color, uv_scale, join, seed):
    rng = ctx.reseed(seed)
    cells_x, cells_y = (list(size) + [3])[:2]
    cells_x, cells_y = max(1, cells_x), max(1, cells_y)
    shared = mat_lib.from_preset(material, name=f"m_{scene_lib.sanitize(name)}", color=color or None)
    parts = []

    def place(kind, x, y, rotation_deg):
        bm = mesh_lib.new_bmesh()
        _grid_piece(bm, kind, grid, height, thickness, rng, False)
        mesh_lib.cleanup(bm)
        obj = mesh_lib.to_object(bm, scene_lib.unique_name(f"{name}_{kind}"))
        obj.location = (x, y, 0.0)
        obj.rotation_euler = (0.0, 0.0, math.radians(rotation_deg))
        mat_lib.assign(obj, shared)
        parts.append(obj)
        return obj

    for ix in range(cells_x):
        for iy in range(cells_y):
            place("floor", ix * grid, iy * grid, 0)

    # Wall slots around the perimeter, then spend the door/window budget on them.
    slots = []
    for ix in range(cells_x):
        slots.append(("south", ix * grid, 0.0, 0))
        slots.append(("north", ix * grid, cells_y * grid, 0))
    for iy in range(cells_y):
        # +90, not -90: a wall's local geometry runs from x=0 to x=+grid, so a
        # -90 turn sends it into -Y and off the footprint entirely.
        slots.append(("west", 0.0, iy * grid, 90))
        slots.append(("east", cells_x * grid, iy * grid, 90))

    openings = {}
    order = list(range(len(slots)))
    rng.shuffle(order)
    for index in order[: max(0, doors)]:
        openings[index] = "wall_door"
    for index in order[max(0, doors) : max(0, doors) + max(0, windows)]:
        openings[index] = "wall_window"

    for index, (_side, x, y, rotation) in enumerate(slots):
        place(openings.get(index, "wall"), x, y, rotation)

    if pillars:
        for ix in (0, cells_x):
            for iy in (0, cells_y):
                place("pillar", ix * grid, iy * grid, 0)
    if roof:
        for ix in range(cells_x):
            for iy in range(cells_y):
                obj = place("roof", ix * grid, iy * grid, 0)
                obj.location = (ix * grid, iy * grid, height)

    for part in parts:
        scene_lib.apply_transforms(part, rotation=True, scale=True)
        uv_lib.box_project(part, scale=uv_scale)

    if join:
        merged = scene_lib.join(parts, scene_lib.sanitize(name))
        scene_lib.set_origin(merged, "world")
        scene_lib.apply_transforms(merged)
        result = finish_lib.report(ctx, merged)
        result["interior_size_m"] = [
            round(cells_x * grid - thickness, 3), round(cells_y * grid - thickness, 3),
            round(height, 3),
        ]
        result["doors"] = doors
        result["windows"] = windows
        finish_lib.budget_note(ctx, merged, cells_x * cells_y * 1500)
        return result
    return {"objects": [p.name for p in parts], "count": len(parts)}
