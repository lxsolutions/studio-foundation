"""Arcades, colonnades and vaults — the Roman/Romanesque building vocabulary.

The arch is the single most recognisable piece of classical architecture, and
without it a stone building reads as a modern retaining wall no matter how big
you make it. A stadium bowl becomes the Colosseum the moment you stack arcades
on it.

Everything here places bays by ARC LENGTH along a path, so a colonnade around
an oval keeps even spacing instead of bunching at the turns.
"""

from __future__ import annotations

import math

import bmesh
from lib import finish as finish_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from mathutils import Matrix, Vector
from registry import OpError, op

COMMON = {
    "name": ("str", "arcade", "Object name"),
    "path": ("num[]", [], "Flat [x0,y0,z0, ...] path; leave empty and use path_shape"),
    "path_shape": ("enum:custom|oval|circle|line|arc", "oval", "Built-in path generator"),
    "straight": ("num", 40.0, "oval: length of each straight in metres"),
    "radius": ("num", 20.0, "oval/circle/arc radius in metres"),
    "length": ("num", 30.0, "line: total length in metres along X"),
    "arc_degrees": ("num", 180.0, "arc: sweep angle in degrees"),
    "resolution": ("int", 48, "Path sampling resolution"),
    "material": ("str", "stone", "Material preset"),
    "color": ("str", "", "Override colour"),
    "uv_scale": ("num", 3.0, "Metres per UV tile"),
    "z": ("num", 0.0, "Base height in metres"),
}


def _params(**extra):
    merged = dict(COMMON)
    merged.update(extra)
    return merged


def _path_points(path, path_shape, straight, radius, length, arc_degrees, resolution):
    if path_shape == "custom":
        if len(path) < 6 or len(path) % 3 != 0:
            raise OpError(
                "path_shape='custom' needs a flat list of at least 2 (x, y, z) points"
            )
        return [(path[i], path[i + 1], path[i + 2]) for i in range(0, len(path), 3)], False
    if path_shape == "oval":
        return mesh_lib.oval_path(straight, radius, max(6, resolution // 2)), True
    if path_shape == "circle":
        n = max(8, resolution)
        return [
            (math.cos(2 * math.pi * i / n) * radius, math.sin(2 * math.pi * i / n) * radius, 0.0)
            for i in range(n)
        ], True
    if path_shape == "arc":
        n = max(4, resolution)
        total = math.radians(arc_degrees)
        return [
            (math.cos(total * i / n) * radius, math.sin(total * i / n) * radius, 0.0)
            for i in range(n + 1)
        ], False
    n = max(2, resolution)
    return [(-length * 0.5 + length * i / n, 0.0, 0.0) for i in range(n + 1)], False


def _place(bm, block_bm, position, tangent, normal, z):
    """Drop a locally-built block onto the path with its own frame.

    Local +X runs ALONG the wall, +Y through its thickness, +Z up.
    """
    basis = Matrix((
        (tangent.x, normal.x, 0.0, 0.0),
        (tangent.y, normal.y, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    ))
    matrix = Matrix.Translation(position + Vector((0.0, 0.0, z))) @ basis
    bmesh.ops.transform(block_bm, matrix=matrix, verts=block_bm.verts[:])
    temp = mesh_lib.bpy.data.meshes.new("_arcade_block")
    block_bm.to_mesh(temp)
    block_bm.free()
    bm.from_mesh(temp)
    mesh_lib.bpy.data.meshes.remove(temp)


@op(
    "arch.arcade",
    summary="A wall of repeating arched bays following a path — THE Roman building block. Stack these to turn a stadium bowl into a colosseum, or run one along a line for an aqueduct or a cloister. Bays are spaced by arc length so an oval colonnade stays even through the turns.",
    params=_params(
        bays=("int", 32, "Number of arched openings around the path"),
        height=("num", 9.0, "Storey height in metres, plinth to cornice"),
        thickness=("num", 1.6, "Wall depth in metres"),
        opening=("num", 0.58, "Fraction of each bay that is opening rather than pier (0.3-0.75)"),
        arch_rise=("num", 0.0, "Height of the arch semicircle; 0 makes it a true semicircle (half the opening width)"),
        springing=("num", 0.42, "Height where the arch starts, as a fraction of storey height"),
        voussoirs=("int", 7, "Segments per arch — 7 reads as an arch, more is wasted at distance"),
        plinth=("num", 0.5, "Base band height in metres"),
        cornice=("num", 0.6, "Top band height in metres"),
        cornice_jut=("num", 0.35, "How far the cornice projects past the wall"),
        engaged_columns=("bool", True, "Half-columns on the piers — the Colosseum's storey articulation"),
    ),
    tags=["build", "architecture"],
)
def arch_arcade(ctx, name, path, path_shape, straight, radius, length, arc_degrees, resolution,
                bays, height, thickness, opening, arch_rise, springing, voussoirs, plinth,
                cornice, cornice_jut, engaged_columns, material, color, uv_scale, z):
    points, closed = _path_points(
        path, path_shape, straight, radius, length, arc_degrees, resolution
    )
    bays = max(2, bays)
    stations = mesh_lib.sample_path(points, bays, closed=closed)
    if len(stations) < 2:
        raise OpError("arcade needs at least two bays")

    # Bay width from actual arc length, not from the straight-line span.
    perimeter = 0.0
    for index in range(len(stations)):
        nxt = stations[(index + 1) % len(stations)]
        if index + 1 == len(stations) and not closed:
            break
        perimeter += (nxt[0] - stations[index][0]).length
    bay_width = perimeter / bays if perimeter > 0 else 1.0
    open_w = max(0.2, bay_width * max(0.2, min(0.8, opening)))
    pier_w = max(0.2, bay_width - open_w)
    spring_z = height * max(0.15, min(0.85, springing))
    rise = arch_rise if arch_rise > 0 else open_w * 0.5

    bm = mesh_lib.new_bmesh()
    half_t = thickness * 0.5

    for position, tangent, normal in stations:
        # Pier between openings.
        block = mesh_lib.new_bmesh()
        mesh_lib.add_box(
            block, size=(pier_w, thickness, height), center=(0.0, 0.0, height * 0.5)
        )
        if engaged_columns:
            mesh_lib.add_cylinder(
                block, radius=pier_w * 0.30, depth=height * 0.86, segments=8,
                center=(0.0, -half_t - pier_w * 0.16, height * 0.43),
            )
        _place(bm, block, position, tangent, normal, z)

        # Spandrel: the solid wall above the arch, up to the cornice.
        top_of_arch = spring_z + rise
        if height - top_of_arch > 0.05:
            block = mesh_lib.new_bmesh()
            mesh_lib.add_box(
                block, size=(open_w, thickness, height - top_of_arch),
                center=(bay_width * 0.5, 0.0, top_of_arch + (height - top_of_arch) * 0.5),
            )
            _place(bm, block, position, tangent, normal, z)

        # The arch itself, as voussoirs around a semicircle.
        segments = max(3, voussoirs)
        ring_thickness = max(0.18, open_w * 0.14)
        for v in range(segments):
            a0 = math.pi * v / segments
            a1 = math.pi * (v + 1) / segments
            mid = (a0 + a1) * 0.5
            cx = bay_width * 0.5 - math.cos(mid) * (open_w * 0.5)
            cz = spring_z + math.sin(mid) * rise
            span = (open_w * 0.5) * (a1 - a0) * 1.25 + ring_thickness * 0.5
            block = mesh_lib.new_bmesh()
            mesh_lib.add_box(block, size=(span, thickness, ring_thickness))
            bmesh.ops.transform(
                block,
                matrix=Matrix.Translation((cx, 0.0, cz))
                @ Matrix.Rotation(mid - math.pi * 0.5, 4, "Y"),
                verts=block.verts[:],
            )
            _place(bm, block, position, tangent, normal, z)

        # Plinth and cornice run continuously; one segment per bay closes up.
        if plinth > 0.0:
            block = mesh_lib.new_bmesh()
            mesh_lib.add_box(
                block, size=(bay_width * 1.02, thickness + cornice_jut * 0.6, plinth),
                center=(bay_width * 0.5, 0.0, plinth * 0.5),
            )
            _place(bm, block, position, tangent, normal, z)
        if cornice > 0.0:
            block = mesh_lib.new_bmesh()
            mesh_lib.add_box(
                block, size=(bay_width * 1.02, thickness + cornice_jut, cornice),
                center=(bay_width * 0.5, 0.0, height - cornice * 0.5),
            )
            _place(bm, block, position, tangent, normal, z)

    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="box", uv_scale=uv_scale,
        origin="world", smooth=False,
    )
    result.update({"bays": bays, "bay_width": round(bay_width, 3),
                   "opening_width": round(open_w, 3), "pier_width": round(pier_w, 3),
                   "storey_height": height})
    ctx.note(
        f"{bays} bays at {bay_width:.2f} m ({open_w:.2f} m openings). Stack another "
        f"storey at z={z + height:.1f} for a Colosseum-style elevation."
    )
    return result


@op(
    "arch.colonnade",
    summary="A ring or run of free-standing columns with an entablature — temple fronts, stadium rims, forum porticos. Cheaper than an arcade and the right silhouette for a top storey.",
    params=_params(
        columns=("int", 40, "Number of columns"),
        height=("num", 6.5, "Column height in metres"),
        column_radius=("num", 0.42, "Shaft radius"),
        segments=("int", 8, "Sides per column"),
        entablature=("num", 0.9, "Depth of the beam carried across the tops; 0 for none"),
        flutes=("bool", False, "Fluted shafts (costs triangles, only reads up close)"),
        statues=("bool", False, "Blocky statue silhouettes above every fourth column"),
    ),
    tags=["build", "architecture"],
)
def arch_colonnade(ctx, name, path, path_shape, straight, radius, length, arc_degrees,
                   resolution, columns, height, column_radius, segments, entablature, flutes,
                   statues, material, color, uv_scale, z):
    points, closed = _path_points(
        path, path_shape, straight, radius, length, arc_degrees, resolution
    )
    columns = max(2, columns)
    stations = mesh_lib.sample_path(points, columns, closed=closed)
    bm = mesh_lib.new_bmesh()

    for index, (position, tangent, normal) in enumerate(stations):
        block = mesh_lib.new_bmesh()
        mesh_lib.add_box(block, size=(column_radius * 2.6, column_radius * 2.6, 0.24),
                         center=(0.0, 0.0, 0.12))
        mesh_lib.add_cylinder(
            block, radius=column_radius, radius_top=column_radius * 0.86,
            depth=height - 0.5, segments=max(6, segments),
            center=(0.0, 0.0, 0.24 + (height - 0.5) * 0.5),
        )
        mesh_lib.add_box(block, size=(column_radius * 2.5, column_radius * 2.5, 0.26),
                         center=(0.0, 0.0, height - 0.13))
        if flutes:
            for vert in block.verts:
                if 0.3 < vert.co.z < height - 0.35:
                    angle = math.atan2(vert.co.y, vert.co.x)
                    dist = math.hypot(vert.co.x, vert.co.y)
                    if dist > 1e-6:
                        factor = (dist - math.cos(angle * 16) * column_radius * 0.06) / dist
                        vert.co.x *= factor
                        vert.co.y *= factor
        if statues and index % 4 == 0:
            mesh_lib.add_box(block, size=(0.42, 0.34, 1.5),
                             center=(0.0, 0.0, height + 0.75))
            mesh_lib.add_icosphere(block, radius=0.19, subdivisions=1,
                                   center=(0.0, 0.0, height + 1.62))
        _place(bm, block, position, tangent, normal, z)

    if entablature > 0.0:
        for index, (position, tangent, normal) in enumerate(stations):
            nxt = stations[(index + 1) % len(stations)]
            if index + 1 == len(stations) and not closed:
                break
            span = (nxt[0] - position).length
            block = mesh_lib.new_bmesh()
            mesh_lib.add_box(block, size=(span * 1.04, entablature, 0.55),
                             center=(span * 0.5, 0.0, height + 0.27))
            _place(bm, block, position, tangent, normal, z)

    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="box", uv_scale=uv_scale,
        origin="world", smooth=False,
    )
    result["columns"] = columns
    return result


@op(
    "arch.gateway",
    summary="A monumental arched gate — the triumphal entrance every Roman venue frames its far end with. One big central arch, optional flanking arches, an attic storey above.",
    params={
        "name": ("str", "gateway", "Object name"),
        "width": ("num", 14.0, "Overall width in metres"),
        "height": ("num", 16.0, "Overall height in metres"),
        "thickness": ("num", 3.0, "Depth in metres"),
        "side_arches": ("bool", True, "Smaller arches either side of the main opening"),
        "attic": ("num", 4.0, "Attic storey height above the cornice; 0 for none"),
        "voussoirs": ("int", 9, "Segments in the main arch"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "rotation": ("num", 0.0, "Yaw in degrees"),
        "material": ("str", "stone", "Material preset"),
        "color": ("str", "", "Override colour"),
        "uv_scale": ("num", 3.0, "Metres per UV tile"),
    },
    tags=["build", "architecture"],
)
def arch_gateway(ctx, name, width, height, thickness, side_arches, attic, voussoirs, location,
                 rotation, material, color, uv_scale):
    bm = mesh_lib.new_bmesh()
    body_h = height - attic
    main_w = width * (0.42 if side_arches else 0.60)
    spring = body_h * 0.46
    rise = main_w * 0.5

    def opening(centre_x, open_w, spring_z, segments):
        arch_rise = open_w * 0.5
        pier = (width - open_w) * 0.5
        for sign in (-1.0, 1.0):
            mesh_lib.add_box(
                bm, size=(pier, thickness, body_h),
                center=(centre_x + sign * (open_w + pier) * 0.5, 0.0, body_h * 0.5),
            )
        for v in range(segments):
            a0 = math.pi * v / segments
            a1 = math.pi * (v + 1) / segments
            mid = (a0 + a1) * 0.5
            block = mesh_lib.new_bmesh()
            span = (open_w * 0.5) * (a1 - a0) * 1.3 + 0.5
            mesh_lib.add_box(block, size=(span, thickness * 1.04, 0.9))
            bmesh.ops.transform(
                block,
                matrix=Matrix.Translation((
                    centre_x - math.cos(mid) * open_w * 0.5,
                    0.0,
                    spring_z + math.sin(mid) * arch_rise,
                ))
                @ Matrix.Rotation(mid - math.pi * 0.5, 4, "Y"),
                verts=block.verts[:],
            )
            temp = mesh_lib.bpy.data.meshes.new("_gate_v")
            block.to_mesh(temp)
            block.free()
            bm.from_mesh(temp)
            mesh_lib.bpy.data.meshes.remove(temp)

    opening(0.0, main_w, spring, max(4, voussoirs))
    if side_arches:
        side_w = width * 0.17
        for sign in (-1.0, 1.0):
            centre = sign * (main_w * 0.5 + side_w * 0.5 + width * 0.045)
            for v in range(5):
                a0 = math.pi * v / 5
                a1 = math.pi * (v + 1) / 5
                mid = (a0 + a1) * 0.5
                block = mesh_lib.new_bmesh()
                mesh_lib.add_box(block, size=((side_w * 0.5) * (a1 - a0) * 1.3 + 0.35,
                                              thickness * 1.02, 0.55))
                bmesh.ops.transform(
                    block,
                    matrix=Matrix.Translation((
                        centre - math.cos(mid) * side_w * 0.5,
                        0.0,
                        body_h * 0.30 + math.sin(mid) * side_w * 0.5,
                    ))
                    @ Matrix.Rotation(mid - math.pi * 0.5, 4, "Y"),
                    verts=block.verts[:],
                )
                temp = mesh_lib.bpy.data.meshes.new("_gate_s")
                block.to_mesh(temp)
                block.free()
                bm.from_mesh(temp)
                mesh_lib.bpy.data.meshes.remove(temp)

    mesh_lib.add_box(bm, size=(width * 1.06, thickness * 1.25, 0.9),
                     center=(0.0, 0.0, body_h - 0.45))
    if attic > 0.0:
        mesh_lib.add_box(bm, size=(width * 0.94, thickness, attic),
                         center=(0.0, 0.0, body_h + attic * 0.5))
        mesh_lib.add_box(bm, size=(width * 1.0, thickness * 1.15, 0.5),
                         center=(0.0, 0.0, body_h + attic - 0.25))

    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, math.radians(rotation))
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="box", uv_scale=uv_scale,
        origin="world", smooth=False,
    )
    result["opening_width"] = round(main_w, 2)
    return result
