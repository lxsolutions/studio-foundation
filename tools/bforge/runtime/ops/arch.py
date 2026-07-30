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
from lib import mat as mat_lib
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
            raise OpError("path_shape='custom' needs a flat list of at least 2 (x, y, z) points")
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
    basis = Matrix(
        (
            (tangent.x, normal.x, 0.0, 0.0),
            (tangent.y, normal.y, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
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
        arch_rise=(
            "num",
            0.0,
            "Height of the arch semicircle; 0 makes it a true semicircle (half the opening width)",
        ),
        springing=("num", 0.42, "Height where the arch starts, as a fraction of storey height"),
        voussoirs=("int", 7, "Segments per arch — 7 reads as an arch, more is wasted at distance"),
        plinth=("num", 0.5, "Base band height in metres"),
        cornice=("num", 0.6, "Top band height in metres"),
        cornice_jut=("num", 0.35, "How far the cornice projects past the wall"),
        engaged_columns=(
            "bool",
            True,
            "Half-columns on the piers — the Colosseum's storey articulation",
        ),
    ),
    tags=["build", "architecture"],
)
def arch_arcade(
    ctx,
    name,
    path,
    path_shape,
    straight,
    radius,
    length,
    arc_degrees,
    resolution,
    bays,
    height,
    thickness,
    opening,
    arch_rise,
    springing,
    voussoirs,
    plinth,
    cornice,
    cornice_jut,
    engaged_columns,
    material,
    color,
    uv_scale,
    z,
):
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
        mesh_lib.add_box(block, size=(pier_w, thickness, height), center=(0.0, 0.0, height * 0.5))
        if engaged_columns:
            mesh_lib.add_cylinder(
                block,
                radius=pier_w * 0.30,
                depth=height * 0.86,
                segments=8,
                center=(0.0, -half_t - pier_w * 0.16, height * 0.43),
            )
        _place(bm, block, position, tangent, normal, z)

        # Spandrel: the solid wall above the arch, up to the cornice.
        top_of_arch = spring_z + rise
        if height - top_of_arch > 0.05:
            block = mesh_lib.new_bmesh()
            mesh_lib.add_box(
                block,
                size=(open_w, thickness, height - top_of_arch),
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
                block,
                size=(bay_width * 1.02, thickness + cornice_jut * 0.6, plinth),
                center=(bay_width * 0.5, 0.0, plinth * 0.5),
            )
            _place(bm, block, position, tangent, normal, z)
        if cornice > 0.0:
            block = mesh_lib.new_bmesh()
            mesh_lib.add_box(
                block,
                size=(bay_width * 1.02, thickness + cornice_jut, cornice),
                center=(bay_width * 0.5, 0.0, height - cornice * 0.5),
            )
            _place(bm, block, position, tangent, normal, z)

    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    result = finish_lib.finish(
        ctx,
        obj,
        material=material,
        color=color or None,
        uv="box",
        uv_scale=uv_scale,
        origin="world",
        smooth=False,
    )
    result.update(
        {
            "bays": bays,
            "bay_width": round(bay_width, 3),
            "opening_width": round(open_w, 3),
            "pier_width": round(pier_w, 3),
            "storey_height": height,
        }
    )
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
def arch_colonnade(
    ctx,
    name,
    path,
    path_shape,
    straight,
    radius,
    length,
    arc_degrees,
    resolution,
    columns,
    height,
    column_radius,
    segments,
    entablature,
    flutes,
    statues,
    material,
    color,
    uv_scale,
    z,
):
    points, closed = _path_points(
        path, path_shape, straight, radius, length, arc_degrees, resolution
    )
    columns = max(2, columns)
    stations = mesh_lib.sample_path(points, columns, closed=closed)
    bm = mesh_lib.new_bmesh()

    for index, (position, tangent, normal) in enumerate(stations):
        block = mesh_lib.new_bmesh()
        mesh_lib.add_box(
            block, size=(column_radius * 2.6, column_radius * 2.6, 0.24), center=(0.0, 0.0, 0.12)
        )
        mesh_lib.add_cylinder(
            block,
            radius=column_radius,
            radius_top=column_radius * 0.86,
            depth=height - 0.5,
            segments=max(6, segments),
            center=(0.0, 0.0, 0.24 + (height - 0.5) * 0.5),
        )
        mesh_lib.add_box(
            block,
            size=(column_radius * 2.5, column_radius * 2.5, 0.26),
            center=(0.0, 0.0, height - 0.13),
        )
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
            mesh_lib.add_box(block, size=(0.42, 0.34, 1.5), center=(0.0, 0.0, height + 0.75))
            mesh_lib.add_icosphere(
                block, radius=0.19, subdivisions=1, center=(0.0, 0.0, height + 1.62)
            )
        _place(bm, block, position, tangent, normal, z)

    if entablature > 0.0:
        for index, (position, tangent, normal) in enumerate(stations):
            nxt = stations[(index + 1) % len(stations)]
            if index + 1 == len(stations) and not closed:
                break
            span = (nxt[0] - position).length
            block = mesh_lib.new_bmesh()
            mesh_lib.add_box(
                block,
                size=(span * 1.04, entablature, 0.55),
                center=(span * 0.5, 0.0, height + 0.27),
            )
            _place(bm, block, position, tangent, normal, z)

    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    result = finish_lib.finish(
        ctx,
        obj,
        material=material,
        color=color or None,
        uv="box",
        uv_scale=uv_scale,
        origin="world",
        smooth=False,
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
def arch_gateway(
    ctx,
    name,
    width,
    height,
    thickness,
    side_arches,
    attic,
    voussoirs,
    location,
    rotation,
    material,
    color,
    uv_scale,
):
    bm = mesh_lib.new_bmesh()
    body_h = height - attic
    main_w = width * (0.42 if side_arches else 0.60)
    spring = body_h * 0.46

    def opening(centre_x, open_w, spring_z, segments):
        arch_rise = open_w * 0.5
        pier = (width - open_w) * 0.5
        for sign in (-1.0, 1.0):
            mesh_lib.add_box(
                bm,
                size=(pier, thickness, body_h),
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
                matrix=Matrix.Translation(
                    (
                        centre_x - math.cos(mid) * open_w * 0.5,
                        0.0,
                        spring_z + math.sin(mid) * arch_rise,
                    )
                )
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
                mesh_lib.add_box(
                    block, size=((side_w * 0.5) * (a1 - a0) * 1.3 + 0.35, thickness * 1.02, 0.55)
                )
                bmesh.ops.transform(
                    block,
                    matrix=Matrix.Translation(
                        (
                            centre - math.cos(mid) * side_w * 0.5,
                            0.0,
                            body_h * 0.30 + math.sin(mid) * side_w * 0.5,
                        )
                    )
                    @ Matrix.Rotation(mid - math.pi * 0.5, 4, "Y"),
                    verts=block.verts[:],
                )
                temp = mesh_lib.bpy.data.meshes.new("_gate_s")
                block.to_mesh(temp)
                block.free()
                bm.from_mesh(temp)
                mesh_lib.bpy.data.meshes.remove(temp)

    mesh_lib.add_box(
        bm, size=(width * 1.06, thickness * 1.25, 0.9), center=(0.0, 0.0, body_h - 0.45)
    )
    if attic > 0.0:
        mesh_lib.add_box(
            bm, size=(width * 0.94, thickness, attic), center=(0.0, 0.0, body_h + attic * 0.5)
        )
        mesh_lib.add_box(
            bm, size=(width * 1.0, thickness * 1.15, 0.5), center=(0.0, 0.0, body_h + attic - 0.25)
        )

    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, math.radians(rotation))
    result = finish_lib.finish(
        ctx,
        obj,
        material=material,
        color=color or None,
        uv="box",
        uv_scale=uv_scale,
        origin="world",
        smooth=False,
    )
    result["opening_width"] = round(main_w, 2)
    return result


@op(
    "arch.civic_hall",
    summary=(
        "A complete classical town centre in one joined, material-disciplined asset: "
        "stepped masonry masses, pedimented portico, tiled gable roofs, buttresses, "
        "windows and faction banner. The greek_mine style adds an arched shaft mouth "
        "and working timber headframe/hoist, making an RTS civic centre that is also "
        "credible at first-person distance."
    ),
    params={
        "name": ("str", "civic_hall", "Object name"),
        "style": ("enum:greek_mine|greek_polis", "greek_mine", "Architecture programme"),
        "width": ("num", 10.4, "Overall facade width in metres"),
        "depth": ("num", 8.4, "Overall building depth in metres"),
        "height": ("num", 6.8, "Height to the upper roof eaves"),
        "columns": ("int", 6, "Doric columns across the front portico"),
        "tile_rows": ("int", 7, "Raised tile bands across each major roof"),
        "mine_portal": ("bool", True, "Add an arched mine mouth through the facade"),
        "hoist": ("bool", True, "Add the timber headframe, wheel, spokes, axle and rope"),
        "stone_color": ("str", "#817765", "Primary weathered masonry"),
        "foundation_color": ("str", "#4c4841", "Podium, courses and buttress stone"),
        "roof_color": ("str", "#552c24", "Dark terracotta tile"),
        "timber_color": ("str", "#2b1d16", "Mine framing and doors"),
        "metal_color": ("str", "#61441f", "Bronze/iron fittings"),
        "cloth_color": ("str", "#4a2024", "Faction banner"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "rotation": ("num", 0.0, "Yaw in degrees"),
        "uv_scale": ("num", 1.4, "Metres per UV tile"),
    },
    tags=["build", "architecture", "rts"],
)
def arch_civic_hall(
    ctx,
    name,
    style,
    width,
    depth,
    height,
    columns,
    tile_rows,
    mine_portal,
    hoist,
    stone_color,
    foundation_color,
    roof_color,
    timber_color,
    metal_color,
    cloth_color,
    location,
    rotation,
    uv_scale,
):
    width = max(6.0, float(width))
    depth = max(5.0, float(depth))
    height = max(4.5, float(height))
    columns = max(4, min(10, int(columns)))
    if columns % 2:
        columns += 1
    tile_rows = max(0, min(12, int(tile_rows)))
    if style == "greek_polis":
        mine_portal = False
        hoist = False

    # One mesh and seven shared slots. The old production recipe made every
    # differently-coloured primitive create another material, reaching 17 draw
    # materials before the building even had real roof or facade articulation.
    materials = [
        mat_lib.principled("m_civic_stone", stone_color, roughness=0.88),
        mat_lib.principled("m_civic_foundation", foundation_color, roughness=0.94),
        mat_lib.principled("m_civic_roof", roof_color, roughness=0.9),
        mat_lib.principled("m_civic_timber", timber_color, roughness=0.82),
        mat_lib.principled("m_civic_metal", metal_color, roughness=0.38, metallic=0.82),
        mat_lib.principled("m_civic_cloth", cloth_color, roughness=0.97),
        mat_lib.principled("m_civic_void", "#050607", roughness=1.0),
    ]
    STONE, FOUNDATION, ROOF, TIMBER, METAL, CLOTH, VOID = range(len(materials))
    bm = mesh_lib.new_bmesh()
    parts = 0

    def mark(faces, slot):
        nonlocal parts
        for face in faces:
            face.material_index = slot
        parts += 1
        return faces

    def box(size, center, slot, bevel=0.025):
        return mark(mesh_lib.add_box(bm, size=size, center=center, bevel=bevel), slot)

    def rotated_box(size, center, slot, rotation_y=0.0, bevel=0.015):
        faces = mesh_lib.add_box(bm, size=size, center=(0.0, 0.0, 0.0), bevel=bevel)
        verts = list({vert for face in faces for vert in face.verts})
        matrix = Matrix.Translation(Vector(center))
        if rotation_y:
            matrix = matrix @ Matrix.Rotation(rotation_y, 4, "Y")
        bmesh.ops.transform(bm, matrix=matrix, verts=verts)
        return mark(faces, slot)

    def oriented_cylinder(radius, depth_value, segments, center, slot, rotation_x=0.0):
        faces = mesh_lib.add_cylinder(
            bm,
            radius=radius,
            depth=depth_value,
            segments=segments,
            center=(0.0, 0.0, 0.0),
        )
        verts = list({vert for face in faces for vert in face.verts})
        matrix = Matrix.Translation(Vector(center))
        if rotation_x:
            matrix = matrix @ Matrix.Rotation(rotation_x, 4, "X")
        bmesh.ops.transform(bm, matrix=matrix, verts=verts)
        return mark(faces, slot)

    def gable_prism(span, prism_depth, base_z, rise, center_x, center_y, slot):
        nonlocal parts
        hx, hy = span * 0.5, prism_depth * 0.5
        verts = [
            bm.verts.new((center_x - hx, center_y - hy, base_z)),
            bm.verts.new((center_x + hx, center_y - hy, base_z)),
            bm.verts.new((center_x, center_y - hy, base_z + rise)),
            bm.verts.new((center_x - hx, center_y + hy, base_z)),
            bm.verts.new((center_x + hx, center_y + hy, base_z)),
            bm.verts.new((center_x, center_y + hy, base_z + rise)),
        ]
        faces = [
            bm.faces.new((verts[0], verts[2], verts[1])),
            bm.faces.new((verts[3], verts[4], verts[5])),
            bm.faces.new((verts[0], verts[3], verts[5], verts[2])),
            bm.faces.new((verts[2], verts[5], verts[4], verts[1])),
            bm.faces.new((verts[0], verts[1], verts[4], verts[3])),
        ]
        for face in faces:
            face.material_index = slot
        parts += 1
        return faces

    def tile_bands(span, roof_depth, base_z, rise, center_x, center_y, rows):
        if rows <= 0:
            return
        half = span * 0.5
        slope = math.atan2(rise, half)
        length = math.hypot(half, rise) + 0.08
        for row in range(rows):
            y = center_y - roof_depth * 0.46 + roof_depth * 0.92 * row / max(1, rows - 1)
            rotated_box(
                (length, 0.055, 0.055),
                (center_x - span * 0.25, y, base_z + rise * 0.5 + 0.055),
                ROOF,
                rotation_y=-slope,
                bevel=0.008,
            )
            rotated_box(
                (length, 0.055, 0.055),
                (center_x + span * 0.25, y, base_z + rise * 0.5 + 0.055),
                ROOF,
                rotation_y=slope,
                bevel=0.008,
            )
        box(
            (0.13, roof_depth * 1.04, 0.14),
            (center_x, center_y, base_z + rise + 0.045),
            ROOF,
            bevel=0.025,
        )

    # --- stepped civic massing -------------------------------------------------
    podium_z = 0.24
    box((width, depth, 0.48), (0.0, 0.0, podium_z), FOUNDATION, bevel=0.08)
    for step in range(3):
        step_width = width * (0.76 + step * 0.06)
        step_depth = 0.48 + step * 0.22
        box(
            (step_width, step_depth, 0.17),
            (0.0, -depth * 0.5 - 0.18 - step * 0.18, 0.16 + step * 0.13),
            FOUNDATION,
            bevel=0.025,
        )

    body_base = 0.48
    hall_h = height * 0.58
    wing_h = height * 0.43
    hall_w = width * 0.62
    hall_d = depth * 0.72
    box((hall_w, hall_d, hall_h), (0.0, depth * 0.055, body_base + hall_h * 0.5), STONE, 0.055)
    wing_w = width * 0.23
    wing_d = depth * 0.62
    for sign in (-1.0, 1.0):
        x = sign * width * 0.385
        box((wing_w, wing_d, wing_h), (x, depth * 0.02, body_base + wing_h * 0.5), STONE, 0.045)
        # Heavy corner buttresses produce an RTS-readable footprint without
        # turning the hall into a castle.
        for y in (-depth * 0.31, depth * 0.29):
            box(
                (width * 0.075, depth * 0.115, wing_h * 0.92),
                (sign * width * 0.47, y, body_base + wing_h * 0.46),
                FOUNDATION,
                0.035,
            )

    tower_w = width * 0.36
    tower_d = depth * 0.43
    tower_h = height * 0.86
    box(
        (tower_w, tower_d, tower_h - hall_h * 0.42),
        (0.0, depth * 0.16, body_base + hall_h * 0.42 + (tower_h - hall_h * 0.42) * 0.5),
        STONE,
        0.045,
    )
    # Continuous string courses break the giant wall slabs at both camera
    # scales and share the darker foundation material.
    for z in (body_base + hall_h * 0.33, body_base + hall_h * 0.69):
        box((width * 0.96, depth * 0.73, 0.13), (0.0, depth * 0.04, z), FOUNDATION, 0.02)

    # --- roofs and readable terracotta tile rhythm ----------------------------
    hall_roof_z = body_base + hall_h
    hall_roof_w = hall_w * 1.1
    hall_roof_d = hall_d * 1.12
    hall_rise = height * 0.17
    gable_prism(hall_roof_w, hall_roof_d, hall_roof_z, hall_rise, 0.0, depth * 0.055, ROOF)
    tile_bands(hall_roof_w, hall_roof_d, hall_roof_z, hall_rise, 0.0, depth * 0.055, tile_rows)

    for sign in (-1.0, 1.0):
        x = sign * width * 0.385
        roof_w = wing_w * 1.18
        roof_d = wing_d * 1.12
        roof_z = body_base + wing_h
        rise = height * 0.105
        gable_prism(roof_w, roof_d, roof_z, rise, x, depth * 0.02, ROOF)
        tile_bands(roof_w, roof_d, roof_z, rise, x, depth * 0.02, max(3, tile_rows - 2))

    tower_roof_z = body_base + tower_h
    tower_roof_w = tower_w * 1.14
    tower_roof_d = tower_d * 1.16
    tower_rise = height * 0.13
    gable_prism(tower_roof_w, tower_roof_d, tower_roof_z, tower_rise, 0.0, depth * 0.16, ROOF)
    tile_bands(
        tower_roof_w,
        tower_roof_d,
        tower_roof_z,
        tower_rise,
        0.0,
        depth * 0.16,
        max(4, tile_rows - 1),
    )

    # --- Doric portico and pediment -------------------------------------------
    facade_y = -depth * 0.5 - 0.34
    column_h = height * 0.39
    column_r = width * 0.025
    column_span = width * 0.82
    for index in range(columns):
        x = -column_span * 0.5 + column_span * index / max(1, columns - 1)
        box((column_r * 2.7, column_r * 2.7, 0.16), (x, facade_y, body_base + 0.08), STONE, 0.015)
        faces = mesh_lib.add_cylinder(
            bm,
            radius=column_r,
            radius_top=column_r * 0.84,
            depth=column_h,
            segments=12,
            center=(x, facade_y, body_base + 0.16 + column_h * 0.5),
            bevel=0.015,
        )
        mark(faces, STONE)
        box(
            (column_r * 2.55, column_r * 2.55, 0.19),
            (x, facade_y, body_base + column_h + 0.205),
            STONE,
            0.018,
        )

    entablature_z = body_base + column_h + 0.36
    box((width * 0.94, 0.72, 0.42), (0.0, facade_y, entablature_z), STONE, 0.035)
    box((width, 0.82, 0.16), (0.0, facade_y, entablature_z + 0.29), FOUNDATION, 0.025)
    pediment_base = entablature_z + 0.37
    gable_prism(width * 0.91, 0.52, pediment_base, height * 0.13, 0.0, facade_y, STONE)
    # Oxblood tympanum inset: faction identity without a bright toy-like banner.
    gable_prism(
        width * 0.47, 0.055, pediment_base + 0.12, height * 0.065, 0.0, facade_y - 0.29, CLOTH
    )

    # --- mine mouth, windows and working hoist --------------------------------
    portal_width = width * 0.225
    portal_radius = portal_width * 0.5
    portal_base = body_base + 0.08
    portal_spring = portal_base + height * 0.245
    portal_y = facade_y - 0.42
    if mine_portal:
        box(
            (portal_width, 0.10, portal_spring - portal_base),
            (0.0, portal_y, portal_base + (portal_spring - portal_base) * 0.5),
            VOID,
            0.01,
        )
        oriented_cylinder(
            portal_radius,
            0.11,
            24,
            (0.0, portal_y, portal_spring),
            VOID,
            rotation_x=math.pi * 0.5,
        )
        jamb_w = width * 0.038
        for sign in (-1.0, 1.0):
            box(
                (jamb_w, 0.58, portal_spring - portal_base + 0.22),
                (
                    sign * (portal_radius + jamb_w * 0.5),
                    portal_y + 0.06,
                    portal_base + (portal_spring - portal_base) * 0.5,
                ),
                FOUNDATION,
                0.022,
            )
        for index in range(11):
            a0 = math.pi * index / 11
            a1 = math.pi * (index + 1) / 11
            mid = (a0 + a1) * 0.5
            ring = portal_radius + jamb_w * 0.48
            x = -math.cos(mid) * ring
            z = portal_spring + math.sin(mid) * ring
            span = portal_radius * (a1 - a0) * 1.22 + jamb_w * 0.32
            rotated_box(
                (span, 0.62, jamb_w * 0.92),
                (x, portal_y + 0.06, z),
                FOUNDATION,
                rotation_y=mid - math.pi * 0.5,
                bevel=0.012,
            )
        # Substantial timber lintel and doors sit inside the stone arch.
        box((portal_width * 0.96, 0.16, 0.18), (0.0, portal_y - 0.08, portal_spring), TIMBER, 0.018)
        for sign in (-1.0, 1.0):
            box(
                (0.16, 0.16, portal_spring - portal_base),
                (
                    sign * portal_width * 0.42,
                    portal_y - 0.08,
                    portal_base + (portal_spring - portal_base) * 0.5,
                ),
                TIMBER,
                0.018,
            )

    # Deep-set windows and bronze lintels turn blank wall into a civic facade.
    for sign in (-1.0, 1.0):
        x = sign * width * 0.29
        box(
            (width * 0.075, 0.08, height * 0.145),
            (x, portal_y + 0.32, body_base + height * 0.32),
            VOID,
            0.015,
        )
        box(
            (width * 0.095, 0.11, 0.10),
            (x, portal_y + 0.27, body_base + height * 0.405),
            METAL,
            0.012,
        )
    for sign in (-1.0, 0.0, 1.0):
        box(
            (width * 0.035, 0.07, height * 0.12),
            (
                sign * tower_w * 0.27,
                -tower_d * 0.5 + depth * 0.16 - 0.045,
                body_base + height * 0.68,
            ),
            VOID,
            0.01,
        )

    if hoist:
        wheel_x = width * 0.36
        wheel_y = portal_y - 0.62
        wheel_z = body_base + height * 0.33
        frame_h = height * 0.48
        frame_span = width * 0.155
        for sign in (-1.0, 1.0):
            rotated_box(
                (0.23, 0.27, frame_h),
                (wheel_x + sign * frame_span * 0.5, wheel_y + 0.18, body_base + frame_h * 0.5),
                TIMBER,
                rotation_y=math.radians(-sign * 7.0),
                bevel=0.018,
            )
        box(
            (frame_span * 1.35, 0.32, 0.24),
            (wheel_x, wheel_y + 0.18, body_base + frame_h),
            TIMBER,
            0.022,
        )

        wheel_faces = mesh_lib.add_torus(
            bm,
            major=width * 0.068,
            minor=width * 0.009,
            major_segments=24,
            minor_segments=7,
            center=(0.0, 0.0, 0.0),
        )
        wheel_verts = list({vert for face in wheel_faces for vert in face.verts})
        bmesh.ops.transform(
            bm,
            matrix=Matrix.Translation((wheel_x, wheel_y, wheel_z))
            @ Matrix.Rotation(math.pi * 0.5, 4, "X"),
            verts=wheel_verts,
        )
        mark(wheel_faces, METAL)
        for spoke in range(8):
            rotated_box(
                (width * 0.125, 0.055, 0.055),
                (wheel_x, wheel_y, wheel_z),
                METAL,
                rotation_y=spoke * math.pi / 4,
                bevel=0.006,
            )
        oriented_cylinder(
            width * 0.025,
            0.52,
            12,
            (wheel_x, wheel_y, wheel_z),
            METAL,
            rotation_x=math.pi * 0.5,
        )
        box(
            (0.055, 0.055, wheel_z - portal_base),
            (wheel_x, wheel_y, portal_base + (wheel_z - portal_base) * 0.5),
            TIMBER,
            0.006,
        )

    # Upper civic banner completes the mine-town identity. Loose ore piles are
    # deliberately omitted: the game already owns mineable boulders, and baked
    # decorative rocks at the portal read as collision blockers in first person.
    box(
        (tower_w * 0.34, 0.055, height * 0.25),
        (0.0, -tower_d * 0.5 + depth * 0.16 - 0.09, body_base + height * 0.66),
        CLOTH,
        0.012,
    )
    box(
        (tower_w * 0.40, 0.085, 0.10),
        (0.0, -tower_d * 0.5 + depth * 0.16 - 0.11, body_base + height * 0.80),
        METAL,
        0.01,
    )
    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    for material in materials:
        obj.data.materials.append(material)
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, math.radians(rotation))
    obj["bforge_architecture"] = style
    obj["bforge_parts"] = parts
    result = finish_lib.finish(
        ctx,
        obj,
        material="",
        uv="box",
        uv_scale=max(0.1, uv_scale),
        origin="world",
        smooth=False,
    )
    result.update(
        {
            "style": style,
            "parts": parts,
            "columns": columns,
            "tile_rows": tile_rows,
            "mine_portal": bool(mine_portal),
            "hoist": bool(hoist),
            "portal_width": round(portal_width, 3) if mine_portal else 0.0,
        }
    )
    finish_lib.budget_note(ctx, obj, 18_000)
    return result


@op(
    "arch.defense_tower",
    summary=(
        "A browser-budget classical Greek defense tower with one disciplined material set "
        "and three gameplay-readable silhouettes: an elevated arrow crown, a horizontal "
        "torsion ballista, or a vertical bronze storm conductor. All variants share stepped "
        "weathered masonry, battered buttresses, string courses and oxblood faction cloth."
    ),
    params={
        "name": ("str", "defense_tower", "Object name"),
        "style": ("enum:arrow|ballista|storm", "arrow", "Weapon and crown silhouette"),
        "width": ("num", 3.0, "Overall masonry footprint width in metres"),
        "height": ("num", 5.2, "Overall structure height before the weapon crown"),
        "stone_color": ("str", "#777064", "Primary weathered limestone"),
        "foundation_color": ("str", "#403e3a", "Podium, buttress and course stone"),
        "timber_color": ("str", "#2a1c14", "Weapon frame, canopy and rails"),
        "metal_color": ("str", "#72502a", "Bronze and dark iron fittings"),
        "cloth_color": ("str", "#491c20", "Oxblood faction cloth"),
        "energy_color": ("str", "#7e9ca3", "Restrained storm conductor emission"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "rotation": ("num", 0.0, "Yaw in degrees"),
        "uv_scale": ("num", 0.9, "Metres per UV tile"),
    },
    tags=["build", "architecture", "rts", "tower-defense"],
)
def arch_defense_tower(
    ctx,
    name,
    style,
    width,
    height,
    stone_color,
    foundation_color,
    timber_color,
    metal_color,
    cloth_color,
    energy_color,
    location,
    rotation,
    uv_scale,
):
    """Forge a serious, low-draw-call tower family for Spike and other RTS games."""
    width = max(2.2, min(5.0, float(width)))
    height = max(3.6, min(8.0, float(height)))
    materials = [
        mat_lib.principled("m_defense_stone", stone_color, roughness=0.9),
        mat_lib.principled("m_defense_foundation", foundation_color, roughness=0.96),
        mat_lib.principled("m_defense_timber", timber_color, roughness=0.84),
        mat_lib.principled("m_defense_metal", metal_color, roughness=0.42, metallic=0.76),
        mat_lib.principled("m_defense_cloth", cloth_color, roughness=0.98),
        mat_lib.principled(
            "m_defense_energy",
            energy_color,
            roughness=0.28,
            metallic=0.18,
            emission=0.75,
            emission_color=energy_color,
        ),
    ]
    STONE, FOUNDATION, TIMBER, METAL, CLOTH, ENERGY = range(len(materials))
    bm = mesh_lib.new_bmesh()
    parts = 0

    def mark(faces, slot):
        nonlocal parts
        for face in faces:
            face.material_index = slot
        parts += 1
        return faces

    def box(size, center, slot, bevel=0.025, rotation_xyz=(0.0, 0.0, 0.0)):
        faces = mesh_lib.add_box(
            bm,
            size=size,
            center=(0.0, 0.0, 0.0),
            bevel=bevel,
        )
        verts = list({vert for face in faces for vert in face.verts})
        rx, ry, rz = rotation_xyz
        matrix = Matrix.Translation(Vector(center))
        if rz:
            matrix = matrix @ Matrix.Rotation(rz, 4, "Z")
        if ry:
            matrix = matrix @ Matrix.Rotation(ry, 4, "Y")
        if rx:
            matrix = matrix @ Matrix.Rotation(rx, 4, "X")
        bmesh.ops.transform(bm, matrix=matrix, verts=verts)
        return mark(faces, slot)

    def cylinder(radius, depth_value, center, slot, segments=12, axis="z", radius_top=None):
        faces = mesh_lib.add_cylinder(
            bm,
            radius=radius,
            radius_top=radius_top,
            depth=depth_value,
            segments=segments,
            center=(0.0, 0.0, 0.0),
            bevel=min(radius * 0.12, 0.025),
        )
        verts = list({vert for face in faces for vert in face.verts})
        matrix = Matrix.Translation(Vector(center))
        if axis == "x":
            matrix = matrix @ Matrix.Rotation(math.pi * 0.5, 4, "Y")
        elif axis == "y":
            matrix = matrix @ Matrix.Rotation(math.pi * 0.5, 4, "X")
        bmesh.ops.transform(bm, matrix=matrix, verts=verts)
        return mark(faces, slot)

    def beam(start, end, radius, slot, segments=8):
        start_vec, end_vec = Vector(start), Vector(end)
        direction = end_vec - start_vec
        if direction.length <= 1e-5:
            return []
        faces = mesh_lib.add_cylinder(
            bm,
            radius=radius,
            depth=direction.length,
            segments=segments,
            center=(0.0, 0.0, 0.0),
        )
        verts = list({vert for face in faces for vert in face.verts})
        orientation = direction.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.transform(
            bm,
            matrix=Matrix.Translation((start_vec + end_vec) * 0.5) @ orientation,
            verts=verts,
        )
        return mark(faces, slot)

    def torus(major, minor, center, slot, axis="z"):
        faces = mesh_lib.add_torus(
            bm,
            major=major,
            minor=minor,
            major_segments=20,
            minor_segments=6,
            center=(0.0, 0.0, 0.0),
        )
        verts = list({vert for face in faces for vert in face.verts})
        matrix = Matrix.Translation(Vector(center))
        if axis == "x":
            matrix = matrix @ Matrix.Rotation(math.pi * 0.5, 4, "Y")
        elif axis == "y":
            matrix = matrix @ Matrix.Rotation(math.pi * 0.5, 4, "X")
        bmesh.ops.transform(bm, matrix=matrix, verts=verts)
        return mark(faces, slot)

    # Shared military architecture: wide base, subtly tapered shaft, battered
    # buttresses and dark stone courses. It reads as Greek field engineering
    # instead of a toy castle at either tactical or first-person distance.
    base_h = height * 0.09
    box((width * 1.08, width * 1.08, base_h), (0.0, 0.0, base_h * 0.5), FOUNDATION, 0.07)
    box(
        (width * 0.94, width * 0.94, base_h * 0.42),
        (0.0, 0.0, base_h * 1.21),
        STONE,
        0.035,
    )
    shaft_base = base_h * 1.42
    shaft_h = height * (0.45 if style == "ballista" else 0.30 if style == "storm" else 0.46)
    shaft_w = width * (0.74 if style == "storm" else 0.79)
    box(
        (shaft_w, shaft_w, shaft_h),
        (0.0, 0.0, shaft_base + shaft_h * 0.5),
        STONE,
        0.055,
    )
    buttress_w = width * 0.14
    buttress_h = shaft_h * 0.83
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            box(
                (buttress_w, buttress_w, buttress_h),
                (
                    sx * shaft_w * 0.49,
                    sy * shaft_w * 0.49,
                    shaft_base + buttress_h * 0.5,
                ),
                FOUNDATION,
                0.035,
                (0.0, math.radians(-sx * sy * 2.5), 0.0),
            )
    for fraction in (0.31, 0.67):
        box(
            (shaft_w * 1.07, shaft_w * 1.07, height * 0.028),
            (0.0, 0.0, shaft_base + shaft_h * fraction),
            FOUNDATION,
            0.018,
        )

    # Recessed arrow slits and a front access door use deep bronze/cloth insets;
    # they articulate the silhouette without adding another transparent material.
    front_y = -shaft_w * 0.505
    for z_fraction in (0.36, 0.62):
        box(
            (width * 0.055, 0.035, height * 0.115),
            (0.0, front_y - 0.018, shaft_base + shaft_h * z_fraction),
            METAL,
            0.006,
        )
    box(
        (width * 0.22, 0.045, height * 0.23),
        (0.0, front_y - 0.024, shaft_base + height * 0.115),
        TIMBER,
        0.012,
    )
    crown_z = shaft_base + shaft_h

    if style == "arrow":
        platform_w = width * 1.04
        box((platform_w, platform_w, height * 0.065), (0.0, 0.0, crown_z), FOUNDATION, 0.045)
        parapet_z = crown_z + height * 0.08
        # Alternating merlons create the elevated archer crown at RTS scale.
        for side in (-1.0, 1.0):
            for offset in (-0.31, 0.0, 0.31):
                box(
                    (width * 0.22, width * 0.16, height * 0.22),
                    (offset * width, side * platform_w * 0.45, parapet_z),
                    STONE,
                    0.025,
                )
                box(
                    (width * 0.16, width * 0.22, height * 0.22),
                    (side * platform_w * 0.45, offset * width, parapet_z),
                    STONE,
                    0.025,
                )
        canopy_z = crown_z + height * 0.28
        post_span = width * 0.27
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                beam(
                    (sx * post_span, sy * post_span, crown_z + height * 0.04),
                    (sx * post_span, sy * post_span, canopy_z),
                    width * 0.025,
                    TIMBER,
                )
        # Dark pitched field roof and iron arrow finial.
        roof_pitch = math.radians(26.0)
        for sx in (-1.0, 1.0):
            box(
                (width * 0.52, width * 0.78, height * 0.055),
                (sx * width * 0.13, 0.0, canopy_z + height * 0.035),
                TIMBER,
                0.018,
                (0.0, sx * roof_pitch, 0.0),
            )
        beam(
            (0.0, 0.0, canopy_z + height * 0.03),
            (0.0, 0.0, canopy_z + height * 0.13),
            width * 0.018,
            METAL,
        )
        box(
            (width * 0.20, 0.035, height * 0.28),
            (0.0, -post_span - 0.06, crown_z + height * 0.16),
            CLOTH,
            0.006,
        )
        weapon_height = canopy_z + height * 0.13
        silhouette = "elevated_archer_crown"

    elif style == "ballista":
        platform_w = width * 1.18
        box((platform_w, platform_w, height * 0.085), (0.0, 0.0, crown_z), FOUNDATION, 0.055)
        # Low stone breastwork leaves the torsion engine unmistakable.
        rail_z = crown_z + height * 0.09
        for side in (-1.0, 1.0):
            box(
                (platform_w, width * 0.12, height * 0.12),
                (0.0, side * platform_w * 0.45, rail_z),
                STONE,
                0.025,
            )
        engine_z = crown_z + height * 0.21
        box(
            (width * 0.18, width * 1.10, height * 0.10),
            (0.0, -width * 0.08, engine_z),
            TIMBER,
            0.025,
        )
        for sx in (-1.0, 1.0):
            cylinder(
                width * 0.10,
                height * 0.22,
                (sx * width * 0.31, 0.0, engine_z),
                METAL,
                12,
            )
            beam(
                (sx * width * 0.28, 0.02, engine_z + height * 0.04),
                (sx * width * 0.63, -width * 0.15, engine_z + height * 0.16),
                width * 0.035,
                TIMBER,
            )
            beam(
                (sx * width * 0.63, -width * 0.15, engine_z + height * 0.16),
                (0.0, -width * 0.68, engine_z + height * 0.06),
                width * 0.012,
                METAL,
                6,
            )
        # Heavy bolt and bronze point along the visual front (-Y).
        beam(
            (0.0, width * 0.42, engine_z + height * 0.06),
            (0.0, -width * 0.76, engine_z + height * 0.06),
            width * 0.018,
            METAL,
            8,
        )
        cylinder(
            width * 0.055,
            width * 0.20,
            (0.0, -width * 0.83, engine_z + height * 0.06),
            METAL,
            8,
            axis="y",
            radius_top=0.0,
        )
        box(
            (width * 0.22, 0.035, height * 0.24),
            (platform_w * 0.42, -platform_w * 0.30, crown_z + height * 0.16),
            CLOTH,
            0.006,
        )
        weapon_height = engine_z + height * 0.18
        silhouette = "horizontal_torsion_engine"

    else:
        # A tapered four-sided stone pylon turns the ward into a vertical
        # lightning rod, not a fantasy glowing mushroom.
        pedestal_z = crown_z + height * 0.04
        box(
            (width * 0.90, width * 0.90, height * 0.08),
            (0.0, 0.0, pedestal_z),
            FOUNDATION,
            0.035,
        )
        pylon_h = height * 0.23
        pylon_faces = mesh_lib.add_cylinder(
            bm,
            radius=width * 0.28,
            radius_top=width * 0.12,
            depth=pylon_h,
            segments=4,
            center=(0.0, 0.0, crown_z + height * 0.08 + pylon_h * 0.5),
        )
        mark(pylon_faces, STONE)
        for fraction in (0.23, 0.55, 0.83):
            torus(
                width * (0.29 - fraction * 0.10),
                width * 0.025,
                (0.0, 0.0, crown_z + height * 0.08 + pylon_h * fraction),
                METAL,
            )
        conductor_z = crown_z + height * 0.08 + pylon_h
        cylinder(width * 0.045, height * 0.22, (0.0, 0.0, conductor_z + height * 0.10), METAL, 10)
        core_faces = mesh_lib.add_icosphere(
            bm,
            radius=width * 0.12,
            subdivisions=2,
            center=(0.0, 0.0, conductor_z + height * 0.12),
        )
        mark(core_faces, ENERGY)
        for angle in (0.0, math.pi * 0.5, math.pi, math.pi * 1.5):
            start = (
                math.cos(angle) * width * 0.07,
                math.sin(angle) * width * 0.07,
                conductor_z + height * 0.17,
            )
            end = (
                math.cos(angle) * width * 0.27,
                math.sin(angle) * width * 0.27,
                conductor_z + height * 0.28,
            )
            beam(start, end, width * 0.024, METAL, 8)
        box(
            (width * 0.19, 0.035, height * 0.26),
            (0.0, -shaft_w * 0.54, crown_z - height * 0.10),
            CLOTH,
            0.006,
        )
        weapon_height = conductor_z + height * 0.28
        silhouette = "vertical_bronze_conductor"

    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    for material in materials:
        obj.data.materials.append(material)
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, math.radians(rotation))
    obj["bforge_architecture"] = "greek_defense"
    obj["bforge_tower_style"] = style
    obj["bforge_parts"] = parts
    result = finish_lib.finish(
        ctx,
        obj,
        material="",
        uv="box",
        uv_scale=max(0.1, uv_scale),
        origin="world",
        smooth=False,
    )
    result.update(
        {
            "style": style,
            "silhouette": silhouette,
            "parts": parts,
            "weapon_height": round(weapon_height, 3),
        }
    )
    finish_lib.budget_note(ctx, obj, 9_000)
    return result


@op(
    "arch.field_building",
    summary=(
        "A browser-budget Greek settlement family for the structures surrounding a civic "
        "hall: a furrowed farmstead, strategos campaign tent, hoplite barracks, modular "
        "ashlar wall, weathered road stele, courtyard house, stoa-fronted emporium, or "
        "mining survey lattice. Variants share restrained limestone, timber, cloth, "
        "terracotta, bronze and crop materials while keeping silhouettes readable from "
        "an RTS camera."
    ),
    params={
        "name": ("str", "field_building", "Object name"),
        "style": (
            "enum:farm|camp|barracks|wall|waymarker|house|emporium|lattice",
            "farm",
            "Settlement structure silhouette",
        ),
        "width": ("num", 3.4, "Overall footprint width in metres"),
        "depth": ("num", 3.4, "Overall footprint depth in metres"),
        "height": ("num", 2.2, "Authored visual height in metres"),
        "stone_color": ("str", "#777064", "Primary weathered limestone"),
        "foundation_color": ("str", "#403e3a", "Podium, earth and shadow stone"),
        "timber_color": ("str", "#2a1c14", "Posts, doors, racks and tools"),
        "roof_color": ("str", "#552c24", "Muted terracotta roof and painted details"),
        "metal_color": ("str", "#72502a", "Bronze and dark iron fittings"),
        "crop_color": ("str", "#525632", "Olive, grain and restrained field growth"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "rotation": ("num", 0.0, "Yaw in degrees"),
        "uv_scale": ("num", 0.7, "Metres per UV tile"),
    },
    tags=["build", "architecture", "rts", "economy"],
)
def arch_field_building(
    ctx,
    name,
    style,
    width,
    depth,
    height,
    stone_color,
    foundation_color,
    timber_color,
    roof_color,
    metal_color,
    crop_color,
    location,
    rotation,
    uv_scale,
):
    """Forge the low-rise structures that make a Greek RTS settlement coherent."""
    width = max(0.9, min(8.0, float(width)))
    depth = max(0.45, min(8.0, float(depth)))
    height = max(0.8, min(6.0, float(height)))
    materials = [
        mat_lib.principled("m_field_stone", stone_color, roughness=0.92),
        mat_lib.principled("m_field_foundation", foundation_color, roughness=0.98),
        mat_lib.principled("m_field_timber", timber_color, roughness=0.86),
        mat_lib.principled("m_field_roof", roof_color, roughness=0.94),
        mat_lib.principled("m_field_metal", metal_color, roughness=0.46, metallic=0.68),
        mat_lib.principled("m_field_crop", crop_color, roughness=1.0),
    ]
    STONE, FOUNDATION, TIMBER, ROOF, METAL, CROP = range(len(materials))
    bm = mesh_lib.new_bmesh()
    parts = 0

    def mark(faces, slot):
        nonlocal parts
        for face in faces:
            face.material_index = slot
        parts += 1
        return faces

    def box(size, center, slot, bevel=0.018, rotation_xyz=(0.0, 0.0, 0.0)):
        faces = mesh_lib.add_box(
            bm,
            size=size,
            center=(0.0, 0.0, 0.0),
            bevel=bevel,
        )
        verts = list({vert for face in faces for vert in face.verts})
        rx, ry, rz = rotation_xyz
        matrix = Matrix.Translation(Vector(center))
        if rz:
            matrix = matrix @ Matrix.Rotation(rz, 4, "Z")
        if ry:
            matrix = matrix @ Matrix.Rotation(ry, 4, "Y")
        if rx:
            matrix = matrix @ Matrix.Rotation(rx, 4, "X")
        bmesh.ops.transform(bm, matrix=matrix, verts=verts)
        return mark(faces, slot)

    def cylinder(
        radius,
        depth_value,
        center,
        slot,
        segments=10,
        axis="z",
        radius_top=None,
    ):
        faces = mesh_lib.add_cylinder(
            bm,
            radius=radius,
            radius_top=radius_top,
            depth=depth_value,
            segments=segments,
            center=(0.0, 0.0, 0.0),
            bevel=min(radius * 0.12, 0.018),
        )
        verts = list({vert for face in faces for vert in face.verts})
        matrix = Matrix.Translation(Vector(center))
        if axis == "x":
            matrix = matrix @ Matrix.Rotation(math.pi * 0.5, 4, "Y")
        elif axis == "y":
            matrix = matrix @ Matrix.Rotation(math.pi * 0.5, 4, "X")
        bmesh.ops.transform(bm, matrix=matrix, verts=verts)
        return mark(faces, slot)

    def beam(start, end, radius, slot, segments=7):
        start_vec, end_vec = Vector(start), Vector(end)
        direction = end_vec - start_vec
        if direction.length <= 1e-5:
            return []
        faces = mesh_lib.add_cylinder(
            bm,
            radius=radius,
            depth=direction.length,
            segments=segments,
            center=(0.0, 0.0, 0.0),
        )
        verts = list({vert for face in faces for vert in face.verts})
        orientation = direction.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.transform(
            bm,
            matrix=Matrix.Translation((start_vec + end_vec) * 0.5) @ orientation,
            verts=verts,
        )
        return mark(faces, slot)

    if style == "farm":
        # Dry-stone boundary, alternating dark earth and restrained crop rows,
        # and a rear threshing shelter. It reads as an economy plot without the
        # neon-green carpet and oversized vegetables common to cartoon RTS art.
        border_h = max(0.12, height * 0.09)
        border_w = min(0.22, width * 0.07)
        box((width, border_w, border_h), (0.0, -depth * 0.5, border_h * 0.5), STONE)
        box((width, border_w, border_h), (0.0, depth * 0.5, border_h * 0.5), STONE)
        box((border_w, depth, border_h), (-width * 0.5, 0.0, border_h * 0.5), STONE)
        box((border_w, depth, border_h), (width * 0.5, 0.0, border_h * 0.5), STONE)
        row_count = 6
        usable_w = width - border_w * 2.8
        row_depth = max(0.10, (depth * 0.64) / (row_count * 2 - 1))
        start_y = -depth * 0.34
        for row in range(row_count):
            y = start_y + row * row_depth * 2.0
            box(
                (usable_w, row_depth * 1.05, border_h * 0.48),
                (0.0, y, border_h * 0.46),
                FOUNDATION,
                0.01,
            )
            box(
                (usable_w * 0.94, row_depth * 0.52, border_h * 0.30),
                (0.0, y, border_h * 0.82),
                CROP,
                0.008,
            )
        shelter_y = depth * 0.34
        post_h = height * 0.62
        post_span = width * 0.27
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                beam(
                    (
                        sx * post_span,
                        shelter_y + sy * depth * 0.11,
                        border_h,
                    ),
                    (
                        sx * post_span,
                        shelter_y + sy * depth * 0.11,
                        post_h,
                    ),
                    width * 0.018,
                    TIMBER,
                )
        roof_pitch = math.radians(17.0)
        box(
            (width * 0.72, depth * 0.34, height * 0.045),
            (0.0, shelter_y, post_h + height * 0.04),
            ROOF,
            0.015,
            (roof_pitch, 0.0, 0.0),
        )
        cylinder(
            width * 0.075,
            height * 0.24,
            (post_span * 0.48, shelter_y, border_h + height * 0.12),
            ROOF,
            10,
            radius_top=width * 0.055,
        )
        for sx in (-1.0, 1.0):
            trunk_x = sx * width * 0.39
            trunk_y = depth * 0.28
            trunk_top = border_h + height * 0.48
            cylinder(
                width * 0.025,
                height * 0.48,
                (trunk_x, trunk_y, border_h + height * 0.24),
                TIMBER,
                7,
            )
            # A forked trunk and several low, flattened leaf masses keep the
            # tree legible as an olive rather than a single toy-like green gem.
            crown_offsets = (
                (-0.075, -0.020, 0.010, 0.090),
                (0.070, -0.025, 0.030, 0.082),
                (-0.028, 0.055, 0.055, 0.084),
                (0.035, 0.045, -0.018, 0.078),
                (0.000, -0.055, 0.068, 0.074),
            )
            for ox, oy, oz, radius_scale in crown_offsets:
                tip = (
                    trunk_x + width * ox,
                    trunk_y + width * oy,
                    trunk_top + height * (0.10 + oz),
                )
                beam(
                    (trunk_x, trunk_y, trunk_top - height * 0.08),
                    tip,
                    width * 0.010,
                    TIMBER,
                )
                crown_faces = mesh_lib.add_icosphere(
                    bm,
                    radius=width * radius_scale,
                    subdivisions=1,
                    center=tip,
                )
                crown_verts = {vertex for face in crown_faces for vertex in face.verts}
                for vertex in crown_verts:
                    vertex.co.z = tip[2] + (vertex.co.z - tip[2]) * 0.58
                mark(crown_faces, CROP)
        silhouette = "furrowed_olive_plot"

    elif style == "camp":
        # A strategos' campaign tent: a real ridge-and-eave timber frame under
        # separate weathered cloth planes, with split entrance flaps, guy ropes,
        # pegs, a command shield and spear bundle. The silhouette remains a
        # grounded low shelter instead of the three-sided cone/party hat that
        # survived in Spike's old unversioned camp pack.
        floor_h = height * 0.045
        eave_z = height * 0.54
        ridge_z = height * 0.91
        box(
            (width * 0.96, depth * 0.90, floor_h),
            (0.0, 0.0, floor_h * 0.5),
            FOUNDATION,
            0.035,
        )

        # Four eave posts and two ridge standards expose enough frame to read
        # as field construction instead of a solid cloth pyramid.
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                beam(
                    (
                        sx * width * 0.43,
                        sy * depth * 0.40,
                        floor_h,
                    ),
                    (
                        sx * width * 0.43,
                        sy * depth * 0.40,
                        eave_z,
                    ),
                    width * 0.018,
                    TIMBER,
                )
            beam(
                (sx * width * 0.43, 0.0, floor_h),
                (sx * width * 0.43, 0.0, ridge_z),
                width * 0.021,
                TIMBER,
            )
        beam(
            (-width * 0.52, 0.0, ridge_z),
            (width * 0.52, 0.0, ridge_z),
            width * 0.020,
            TIMBER,
        )
        for sy in (-1.0, 1.0):
            beam(
                (-width * 0.48, sy * depth * 0.42, eave_z),
                (width * 0.48, sy * depth * 0.42, eave_z),
                width * 0.016,
                TIMBER,
            )

        # Two pitched cloth panels meet at the ridge. Thin volume rather than a
        # one-sided plane keeps them glTF-safe and readable from first person.
        rise = ridge_z - eave_z
        run = depth * 0.48
        roof_slope = math.hypot(run, rise)
        roof_pitch = math.atan2(rise, run)
        for sy in (-1.0, 1.0):
            box(
                (width * 1.08, roof_slope, height * 0.030),
                (0.0, sy * depth * 0.24, (eave_z + ridge_z) * 0.5),
                ROOF,
                0.012,
                (-sy * roof_pitch, 0.0, 0.0),
            )

        # Back curtain and side skirts give the shelter weight. The front stays
        # open around two folded flaps so it has a legible entrance.
        cloth_h = eave_z - floor_h
        box(
            (width * 0.92, depth * 0.025, cloth_h),
            (0.0, depth * 0.405, floor_h + cloth_h * 0.5),
            ROOF,
            0.010,
        )
        for sx in (-1.0, 1.0):
            box(
                (width * 0.025, depth * 0.76, cloth_h * 0.90),
                (
                    sx * width * 0.445,
                    depth * 0.02,
                    floor_h + cloth_h * 0.45,
                ),
                ROOF,
                0.010,
            )
        flap_w = width * 0.29
        for sx in (-1.0, 1.0):
            box(
                (flap_w, depth * 0.024, cloth_h * 0.92),
                (
                    sx * width * 0.305,
                    -depth * 0.408,
                    floor_h + cloth_h * 0.46,
                ),
                ROOF,
                0.010,
                (0.0, math.radians(-sx * 9.0), 0.0),
            )
        cylinder(
            width * 0.035,
            width * 0.34,
            (0.0, -depth * 0.43, eave_z * 0.92),
            ROOF,
            9,
            axis="x",
        )

        # Ropes, iron pegs and command kit identify a working military camp at
        # RTS distance without resorting to flags, glowing banners or giant
        # cartoon supplies.
        for sx in (-1.0, 1.0):
            rope_top = (sx * width * 0.50, 0.0, ridge_z * 0.98)
            rope_foot = (sx * width * 0.66, 0.0, floor_h * 0.25)
            beam(rope_top, rope_foot, width * 0.006, TIMBER, 5)
            cylinder(
                width * 0.018,
                height * 0.16,
                (rope_foot[0], rope_foot[1], height * 0.095),
                METAL,
                6,
            )
        for sy in (-1.0, 1.0):
            for sx in (-1.0, 1.0):
                rope_top = (sx * width * 0.44, sy * depth * 0.40, eave_z)
                rope_foot = (
                    sx * width * 0.52,
                    sy * depth * 0.57,
                    floor_h * 0.25,
                )
                beam(rope_top, rope_foot, width * 0.005, TIMBER, 5)
                cylinder(
                    width * 0.014,
                    height * 0.13,
                    (rope_foot[0], rope_foot[1], height * 0.080),
                    METAL,
                    6,
                )
        cylinder(
            width * 0.105,
            depth * 0.040,
            (width * 0.29, -depth * 0.435, eave_z * 0.56),
            METAL,
            16,
            axis="y",
        )
        for index, sx in enumerate((-0.34, -0.29, -0.24)):
            beam(
                (sx * width, -depth * 0.46, floor_h),
                (
                    (sx - 0.025) * width,
                    -depth * 0.46,
                    eave_z + height * (0.13 + index * 0.018),
                ),
                width * 0.010,
                TIMBER,
                6,
            )
        box(
            (width * 0.28, depth * 0.23, height * 0.18),
            (width * 0.28, depth * 0.25, floor_h + height * 0.09),
            TIMBER,
            0.018,
            (0.0, 0.0, math.radians(-4.0)),
        )
        silhouette = "strategos_campaign_tent"

    elif style == "barracks":
        # A low hoplite hall: masonry cella, real front portico, terracotta
        # pitched roof, shield rack and spear bundle. The military identity is
        # readable before any unit walks out of it.
        podium_h = height * 0.08
        wall_h = height * 0.60
        wall_t = max(0.12, min(width, depth) * 0.065)
        box((width * 1.04, depth * 1.05, podium_h), (0.0, 0.0, podium_h * 0.5), FOUNDATION, 0.04)
        wall_z = podium_h + wall_h * 0.5
        box((width, wall_t, wall_h), (0.0, depth * 0.5 - wall_t * 0.5, wall_z), STONE, 0.025)
        box((wall_t, depth, wall_h), (-width * 0.5 + wall_t * 0.5, 0.0, wall_z), STONE, 0.025)
        box((wall_t, depth, wall_h), (width * 0.5 - wall_t * 0.5, 0.0, wall_z), STONE, 0.025)
        door_w = width * 0.28
        front_piece = (width - door_w) * 0.5
        for sx in (-1.0, 1.0):
            box(
                (front_piece, wall_t, wall_h),
                (
                    sx * (door_w * 0.5 + front_piece * 0.5),
                    -depth * 0.5 + wall_t * 0.5,
                    wall_z,
                ),
                STONE,
                0.025,
            )
        box(
            (door_w * 0.86, wall_t * 0.48, wall_h * 0.78),
            (0.0, -depth * 0.5 - wall_t * 0.04, podium_h + wall_h * 0.39),
            TIMBER,
            0.012,
        )
        portico_y = -depth * 0.5 - depth * 0.11
        column_h = wall_h * 0.88
        for sx in (-0.34, 0.34):
            cylinder(
                width * 0.045,
                column_h,
                (sx * width, portico_y, podium_h + column_h * 0.5),
                STONE,
                10,
                radius_top=width * 0.038,
            )
            box(
                (width * 0.13, width * 0.12, podium_h * 0.55),
                (sx * width, portico_y, podium_h + column_h + podium_h * 0.25),
                FOUNDATION,
                0.012,
            )
        box(
            (width * 0.88, wall_t * 1.4, podium_h * 0.55),
            (0.0, portico_y, podium_h + column_h + podium_h * 0.53),
            FOUNDATION,
            0.018,
        )
        roof_base = podium_h + wall_h
        roof_pitch = math.radians(27.0)
        roof_span = width * 0.57
        for sx in (-1.0, 1.0):
            box(
                (roof_span, depth * 1.17, height * 0.055),
                (sx * width * 0.245, 0.0, roof_base + height * 0.13),
                ROOF,
                0.018,
                (0.0, sx * roof_pitch, 0.0),
            )
        beam(
            (0.0, -depth * 0.59, roof_base + height * 0.31),
            (0.0, depth * 0.59, roof_base + height * 0.31),
            width * 0.018,
            METAL,
        )
        # Three bronze-faced shields make the barracks role legible from the
        # front, while the adjacent spear bundle keeps the shapes historical.
        for index, sx in enumerate((-0.27, 0.0, 0.27)):
            cylinder(
                width * 0.09,
                wall_t * 0.30,
                (sx * width, -depth * 0.5 - wall_t * 0.18, podium_h + wall_h * 0.46),
                METAL if index != 1 else ROOF,
                16,
                axis="y",
            )
        for sx in (0.40, 0.44, 0.48):
            beam(
                (sx * width, -depth * 0.58, podium_h),
                (sx * width - width * 0.03, -depth * 0.58, roof_base + height * 0.16),
                width * 0.012,
                TIMBER,
                6,
            )
        silhouette = "hoplite_training_hall"

    elif style == "house":
        # A compact miner household around a paved forecourt. The offset roof,
        # chimney, porch and storage jars stop it reading as a generic RTS box.
        podium_h = height * 0.07
        body_h = height * 0.56
        wall_t = min(width, depth) * 0.055
        court_d = depth * 0.31
        body_d = depth - court_d
        body_y = court_d * 0.5
        box(
            (width * 1.03, depth * 1.03, podium_h),
            (0.0, 0.0, podium_h * 0.5),
            FOUNDATION,
            0.035,
        )
        wall_z = podium_h + body_h * 0.5
        # Rear and side masonry define a real cella rather than a solid block.
        box((width, wall_t, body_h), (0.0, depth * 0.5 - wall_t * 0.5, wall_z), STONE, 0.025)
        for sx in (-1.0, 1.0):
            box(
                (wall_t, body_d, body_h),
                (sx * (width * 0.5 - wall_t * 0.5), body_y, wall_z),
                STONE,
                0.025,
            )
        door_w = width * 0.25
        front_y = -depth * 0.5 + court_d
        side_w = (width - door_w) * 0.5
        for sx in (-1.0, 1.0):
            box(
                (side_w, wall_t, body_h),
                (sx * (door_w * 0.5 + side_w * 0.5), front_y, wall_z),
                STONE,
                0.025,
            )
        box(
            (door_w * 0.82, wall_t * 0.55, body_h * 0.78),
            (0.0, front_y - wall_t * 0.18, podium_h + body_h * 0.39),
            TIMBER,
            0.012,
        )
        # Small porch and bench make the front readable from the Hero camera.
        porch_y = -depth * 0.42
        porch_h = body_h * 0.72
        for sx in (-0.30, 0.30):
            cylinder(
                width * 0.034,
                porch_h,
                (sx * width, porch_y, podium_h + porch_h * 0.5),
                TIMBER,
                7,
            )
        box(
            (width * 0.78, depth * 0.22, height * 0.045),
            (0.0, porch_y, podium_h + porch_h + height * 0.025),
            ROOF,
            0.014,
            (math.radians(8.0), 0.0, 0.0),
        )
        box(
            (width * 0.32, depth * 0.11, height * 0.09),
            (-width * 0.24, -depth * 0.42, podium_h + height * 0.045),
            TIMBER,
            0.012,
        )
        # Asymmetric terracotta roof with a dark hearth chimney.
        roof_z = podium_h + body_h
        roof_pitch = math.radians(24.0)
        for sx in (-1.0, 1.0):
            box(
                (width * 0.57, body_d * 1.08, height * 0.052),
                (sx * width * 0.245, body_y, roof_z + height * 0.12),
                ROOF,
                0.016,
                (0.0, sx * roof_pitch, 0.0),
            )
        box(
            (width * 0.13, depth * 0.13, height * 0.40),
            (width * 0.28, depth * 0.30, roof_z + height * 0.25),
            FOUNDATION,
            0.015,
        )
        # Two amphorae are small vertical accents, not oversized toy props.
        for index, sx in enumerate((0.32, 0.41)):
            cylinder(
                width * (0.055 if index == 0 else 0.047),
                height * (0.24 if index == 0 else 0.20),
                (sx * width, -depth * 0.35, podium_h + height * (0.12 if index == 0 else 0.10)),
                ROOF,
                10,
                radius_top=width * 0.032,
            )
        silhouette = "courtyard_delver_house"

    elif style == "emporium":
        # A merchant stoa: deep shop cell, four-post limestone frontage,
        # oxblood awning, counter and restrained bronze trade goods.
        podium_h = height * 0.08
        body_h = height * 0.57
        shop_d = depth * 0.64
        rear_y = depth * 0.18
        wall_t = min(width, depth) * 0.06
        box(
            (width * 1.07, depth * 1.08, podium_h),
            (0.0, 0.0, podium_h * 0.5),
            FOUNDATION,
            0.04,
        )
        wall_z = podium_h + body_h * 0.5
        box((width, wall_t, body_h), (0.0, depth * 0.5 - wall_t * 0.5, wall_z), STONE, 0.025)
        for sx in (-1.0, 1.0):
            box(
                (wall_t, shop_d, body_h),
                (sx * (width * 0.5 - wall_t * 0.5), rear_y, wall_z),
                STONE,
                0.025,
            )
        # The recess is intentionally dark timber so the open frontage reads.
        box(
            (width * 0.82, wall_t * 0.55, body_h * 0.82),
            (0.0, -depth * 0.14, podium_h + body_h * 0.41),
            TIMBER,
            0.010,
        )
        counter_y = -depth * 0.27
        box(
            (width * 0.72, depth * 0.18, height * 0.24),
            (0.0, counter_y, podium_h + height * 0.12),
            TIMBER,
            0.018,
        )
        portico_y = -depth * 0.46
        column_h = height * 0.56
        for sx in (-0.43, -0.14, 0.14, 0.43):
            cylinder(
                width * 0.030,
                column_h,
                (sx * width, portico_y, podium_h + column_h * 0.5),
                STONE,
                10,
                radius_top=width * 0.026,
            )
        box(
            (width * 1.0, depth * 0.13, height * 0.08),
            (0.0, portico_y, podium_h + column_h + height * 0.04),
            FOUNDATION,
            0.018,
        )
        awning_z = podium_h + column_h * 0.75
        box(
            (width * 0.88, depth * 0.36, height * 0.035),
            (0.0, -depth * 0.36, awning_z),
            ROOF,
            0.012,
            (math.radians(14.0), 0.0, 0.0),
        )
        roof_z = podium_h + body_h
        for sx in (-1.0, 1.0):
            box(
                (width * 0.57, shop_d * 1.12, height * 0.052),
                (sx * width * 0.245, rear_y, roof_z + height * 0.12),
                ROOF,
                0.016,
                (0.0, sx * math.radians(23.0), 0.0),
            )
        # Scales and three small amphorae establish commerce at RTS distance.
        beam(
            (0.0, counter_y - depth * 0.11, podium_h + height * 0.24),
            (0.0, counter_y - depth * 0.11, podium_h + height * 0.52),
            width * 0.010,
            METAL,
            7,
        )
        beam(
            (-width * 0.13, counter_y - depth * 0.11, podium_h + height * 0.48),
            (width * 0.13, counter_y - depth * 0.11, podium_h + height * 0.48),
            width * 0.009,
            METAL,
            7,
        )
        for index, sx in enumerate((-0.33, 0.28, 0.38)):
            cylinder(
                width * (0.045 + index * 0.004),
                height * (0.16 + index * 0.025),
                (sx * width, counter_y - depth * 0.12, podium_h + height * (0.08 + index * 0.012)),
                METAL if index == 1 else ROOF,
                9,
                radius_top=width * 0.027,
            )
        silhouette = "stoa_fronted_emporium"

    elif style == "lattice":
        # A tall mining survey/hoist lattice: four raked timber standards,
        # X-bracing, limestone footings, bronze crown wheel and plumb line.
        base_h = height * 0.055
        base_w = width * 0.86
        base_d = depth * 0.86
        box((width, depth, base_h), (0.0, 0.0, base_h * 0.5), FOUNDATION, 0.035)
        leg_bottom_x = base_w * 0.42
        leg_bottom_y = base_d * 0.42
        leg_top_x = base_w * 0.24
        leg_top_y = base_d * 0.24
        leg_top_z = height * 0.78
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                box(
                    (width * 0.17, depth * 0.17, base_h * 1.3),
                    (sx * leg_bottom_x, sy * leg_bottom_y, base_h * 0.65),
                    STONE,
                    0.02,
                )
                beam(
                    (sx * leg_bottom_x, sy * leg_bottom_y, base_h),
                    (sx * leg_top_x, sy * leg_top_y, leg_top_z),
                    width * 0.030,
                    TIMBER,
                    8,
                )
        # Bracing on all four faces produces the lattice silhouette.
        brace_low = height * 0.23
        brace_high = height * 0.58
        for sy in (-1.0, 1.0):
            beam(
                (-leg_bottom_x * 0.92, sy * leg_bottom_y, brace_low),
                (leg_top_x, sy * leg_top_y, brace_high),
                width * 0.014,
                TIMBER,
                7,
            )
            beam(
                (leg_bottom_x * 0.92, sy * leg_bottom_y, brace_low),
                (-leg_top_x, sy * leg_top_y, brace_high),
                width * 0.014,
                TIMBER,
                7,
            )
        for sx in (-1.0, 1.0):
            beam(
                (sx * leg_bottom_x, -leg_bottom_y * 0.92, brace_low),
                (sx * leg_top_x, leg_top_y, brace_high),
                width * 0.014,
                TIMBER,
                7,
            )
            beam(
                (sx * leg_bottom_x, leg_bottom_y * 0.92, brace_low),
                (sx * leg_top_x, -leg_top_y, brace_high),
                width * 0.014,
                TIMBER,
                7,
            )
        deck_z = leg_top_z
        box(
            (base_w * 0.72, base_d * 0.72, height * 0.045),
            (0.0, 0.0, deck_z),
            TIMBER,
            0.018,
        )
        for sx in (-1.0, 1.0):
            beam(
                (sx * base_w * 0.28, 0.0, deck_z),
                (sx * base_w * 0.28, 0.0, height * 0.92),
                width * 0.022,
                TIMBER,
                7,
            )
        beam(
            (-base_w * 0.34, 0.0, height * 0.92),
            (base_w * 0.34, 0.0, height * 0.92),
            width * 0.020,
            TIMBER,
            7,
        )
        cylinder(
            width * 0.16,
            depth * 0.055,
            (0.0, -depth * 0.03, height * 0.86),
            METAL,
            18,
            axis="y",
        )
        for angle in (0.0, math.pi * 0.5):
            beam(
                (
                    -math.cos(angle) * width * 0.15,
                    -depth * 0.06,
                    height * 0.86 - math.sin(angle) * width * 0.15,
                ),
                (
                    math.cos(angle) * width * 0.15,
                    -depth * 0.06,
                    height * 0.86 + math.sin(angle) * width * 0.15,
                ),
                width * 0.009,
                METAL,
                6,
            )
        beam(
            (0.0, 0.0, height * 0.86),
            (0.0, 0.0, base_h + height * 0.08),
            width * 0.006,
            METAL,
            5,
        )
        cylinder(
            width * 0.07,
            height * 0.12,
            (0.0, 0.0, base_h + height * 0.06),
            METAL,
            10,
            radius_top=0.0,
        )
        silhouette = "mining_survey_lattice"

    elif style == "wall":
        # Individually blocked courses and end pilasters give a modular wall
        # enough real construction detail at first-person distance without
        # breaking its clean RTS footprint or end-to-end tiling.
        base_h = height * 0.09
        box((width, depth * 1.12, base_h), (0.0, 0.0, base_h * 0.5), FOUNDATION, 0.025)
        course_count = 4
        course_h = height * 0.15
        blocks = 4
        block_gap = width * 0.012
        block_w = (width - block_gap * (blocks - 1)) / blocks
        for course in range(course_count):
            offset = block_w * 0.5 if course % 2 else 0.0
            for block_index in range(blocks + 1):
                x = -width * 0.5 + block_w * 0.5 + block_index * (block_w + block_gap) - offset
                left = max(-width * 0.5, x - block_w * 0.5)
                right = min(width * 0.5, x + block_w * 0.5)
                clipped_w = right - left
                if clipped_w <= width * 0.08:
                    continue
                box(
                    (clipped_w, depth, course_h),
                    (
                        (left + right) * 0.5,
                        0.0,
                        base_h + course_h * (course + 0.5),
                    ),
                    STONE,
                    0.012,
                )
        wall_top = base_h + course_h * course_count
        box((width, depth * 1.10, height * 0.07), (0.0, 0.0, wall_top), FOUNDATION, 0.018)
        pier_w = width * 0.12
        for sx in (-1.0, 1.0):
            box(
                (pier_w, depth * 1.18, wall_top + height * 0.11),
                (
                    sx * (width * 0.5 - pier_w * 0.5),
                    0.0,
                    (wall_top + height * 0.11) * 0.5,
                ),
                FOUNDATION,
                0.02,
            )
        merlon_count = 4
        merlon_w = width * 0.15
        for merlon in range(merlon_count):
            x = -width * 0.36 + merlon * width * 0.24
            box(
                (merlon_w, depth * 0.92, height * 0.22),
                (x, 0.0, wall_top + height * 0.145),
                STONE,
                0.018,
            )
        silhouette = "ashlar_parapet_segment"

    else:
        # A road stele rather than a pristine white column: dark rubble plinth,
        # tapered limestone marker, bronze inscription panel and chipped cap.
        # It can be scattered as an archaeological landmark without looking
        # like editor test geometry.
        marker_w = min(width, depth)
        base_h = height * 0.11
        box((marker_w, marker_w * 0.88, base_h), (0.0, 0.0, base_h * 0.5), FOUNDATION, 0.035)
        box(
            (marker_w * 0.74, marker_w * 0.70, base_h * 0.52),
            (0.0, 0.0, base_h * 1.23),
            STONE,
            0.022,
        )
        shaft_h = height * 0.60
        shaft = mesh_lib.add_cylinder(
            bm,
            radius=marker_w * 0.25,
            radius_top=marker_w * 0.19,
            depth=shaft_h,
            segments=4,
            center=(0.0, 0.0, base_h * 1.49 + shaft_h * 0.5),
        )
        mark(shaft, STONE)
        box(
            (marker_w * 0.28, marker_w * 0.035, shaft_h * 0.42),
            (0.0, -marker_w * 0.255, base_h * 1.42 + shaft_h * 0.53),
            METAL,
            0.008,
        )
        cap_z = base_h * 1.48 + shaft_h
        box(
            (marker_w * 0.68, marker_w * 0.58, height * 0.07),
            (0.0, 0.0, cap_z),
            FOUNDATION,
            0.022,
            (0.0, math.radians(3.5), math.radians(-2.0)),
        )
        box(
            (marker_w * 0.50, marker_w * 0.44, height * 0.055),
            (marker_w * 0.025, 0.0, cap_z + height * 0.06),
            STONE,
            0.018,
            (0.0, math.radians(-4.0), math.radians(2.5)),
        )
        for sx, sy, scale in (
            (-0.38, 0.30, 0.13),
            (0.34, 0.28, 0.11),
            (-0.29, -0.32, 0.09),
        ):
            rubble = mesh_lib.add_icosphere(
                bm,
                radius=marker_w * scale,
                subdivisions=1,
                center=(
                    sx * marker_w,
                    sy * marker_w,
                    marker_w * scale,
                ),
            )
            mark(rubble, FOUNDATION)
        beam(
            (-marker_w * 0.34, marker_w * 0.28, base_h * 0.35),
            (-marker_w * 0.20, marker_w * 0.22, base_h + height * 0.20),
            marker_w * 0.022,
            TIMBER,
            6,
        )
        silhouette = "weathered_road_stele"

    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    for material in materials:
        obj.data.materials.append(material)
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, math.radians(rotation))
    obj["bforge_architecture"] = "greek_field_building"
    obj["bforge_field_style"] = style
    obj["bforge_parts"] = parts
    result = finish_lib.finish(
        ctx,
        obj,
        material="",
        uv="box",
        uv_scale=max(0.1, uv_scale),
        origin="world",
        smooth=False,
    )
    result.update(
        {
            "style": style,
            "silhouette": silhouette,
            "parts": parts,
        }
    )
    finish_lib.budget_note(ctx, obj, 6_000)
    return result


@op(
    "arch.hellenic_ruin",
    summary=(
        "A grounded archaeological Greek landmark authored as a ruined Doric shrine, "
        "broken colonnade, or hero tomb. Broad podiums, uneven standing columns, fallen "
        "drums, displaced lintels, pediment fragments and restrained bronze votives "
        "produce serious navigation silhouettes from FPS through RTS distance."
    ),
    params={
        "name": ("str", "hellenic_ruin", "Object name"),
        "style": (
            "enum:shrine|colonnade|tomb",
            "shrine",
            "Archaeological landmark silhouette",
        ),
        "width": ("num", 5.2, "Overall footprint width in metres"),
        "depth": ("num", 3.8, "Overall footprint depth in metres"),
        "height": ("num", 4.2, "Tallest surviving architectural extent"),
        "weathering": (
            "num",
            0.65,
            "Damage strength from restrained wear to heavily displaced remains",
        ),
        "seed": ("int", 0, "Deterministic fracture and rubble seed"),
        "stone_color": ("str", "#8b8374", "Weathered Attic limestone"),
        "foundation_color": ("str", "#46433d", "Dark podium, crevice and buried stone"),
        "patina_color": ("str", "#52645b", "Tarnished bronze votive and inscription colour"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "rotation": ("num", 0.0, "Yaw in degrees"),
        "uv_scale": ("num", 0.8, "Metres per UV tile"),
    },
    tags=["build", "architecture", "environment", "landmark", "greek"],
)
def arch_hellenic_ruin(
    ctx,
    name,
    style,
    width,
    depth,
    height,
    weathering,
    seed,
    stone_color,
    foundation_color,
    patina_color,
    location,
    rotation,
    uv_scale,
):
    """Forge a one-draw-mesh ruin whose damage is authored into its silhouette."""
    rng = ctx.reseed(seed)
    width = max(2.4, min(12.0, float(width)))
    depth = max(1.8, min(10.0, float(depth)))
    height = max(2.0, min(9.0, float(height)))
    damage = max(0.0, min(1.0, float(weathering)))
    materials = [
        mat_lib.principled("m_ruin_limestone", stone_color, roughness=0.93),
        mat_lib.principled("m_ruin_foundation", foundation_color, roughness=0.98),
        mat_lib.principled(
            "m_ruin_patina",
            patina_color,
            roughness=0.56,
            metallic=0.58,
        ),
    ]
    STONE, FOUNDATION, PATINA = range(len(materials))
    bm = mesh_lib.new_bmesh()
    parts = 0

    def mark(faces, slot):
        nonlocal parts
        for face in faces:
            face.material_index = slot
        parts += 1
        return faces

    def box(size, center, slot, bevel=0.025, rotation_xyz=(0.0, 0.0, 0.0)):
        faces = mesh_lib.add_box(
            bm,
            size=size,
            center=(0.0, 0.0, 0.0),
            bevel=max(0.0, bevel),
        )
        verts = list({vert for face in faces for vert in face.verts})
        rx, ry, rz = rotation_xyz
        matrix = (
            Matrix.Translation(Vector(center))
            @ Matrix.Rotation(rz, 4, "Z")
            @ Matrix.Rotation(ry, 4, "Y")
            @ Matrix.Rotation(rx, 4, "X")
        )
        bmesh.ops.transform(bm, matrix=matrix, verts=verts)
        return mark(faces, slot)

    def cylinder(radius, depth_value, center, slot, segments=12, axis="z", radius_top=None):
        faces = mesh_lib.add_cylinder(
            bm,
            radius=radius,
            radius_top=radius_top,
            depth=depth_value,
            segments=segments,
            center=(0.0, 0.0, 0.0),
            bevel=min(radius * 0.09, 0.022),
        )
        verts = list({vert for face in faces for vert in face.verts})
        matrix = Matrix.Translation(Vector(center))
        if axis == "x":
            matrix = matrix @ Matrix.Rotation(math.pi * 0.5, 4, "Y")
        elif axis == "y":
            matrix = matrix @ Matrix.Rotation(math.pi * 0.5, 4, "X")
        bmesh.ops.transform(bm, matrix=matrix, verts=verts)
        return mark(faces, slot)

    def column(x, y, surviving_height, broken=False, lean=0.0):
        radius = width * 0.052
        base_h = height * 0.045
        box(
            (radius * 2.8, radius * 2.8, base_h),
            (x, y, base_h * 0.5 + height * 0.09),
            FOUNDATION,
            0.018,
            (0.0, lean * 0.3, lean * 0.18),
        )
        shaft_h = max(height * 0.24, surviving_height - height * 0.13)
        cylinder(
            radius,
            shaft_h,
            (x, y, height * 0.09 + base_h + shaft_h * 0.5),
            STONE,
            14,
            radius_top=radius * 0.82,
        )
        if not broken:
            cap_z = height * 0.09 + base_h + shaft_h
            box((radius * 2.55, radius * 2.35, height * 0.055), (x, y, cap_z), STONE, 0.018)
            box(
                (radius * 3.05, radius * 2.65, height * 0.045),
                (x, y, cap_z + height * 0.047),
                STONE,
                0.014,
                (0.0, lean * 0.22, lean * 0.12),
            )

    def pediment(width_value, depth_value, base_z, rise, center_x=0.0):
        half_w = width_value * 0.5
        half_d = depth_value * 0.5
        verts = [
            bm.verts.new((center_x - half_w, -half_d, base_z)),
            bm.verts.new((center_x + half_w, -half_d, base_z)),
            bm.verts.new((center_x, -half_d, base_z + rise)),
            bm.verts.new((center_x - half_w, half_d, base_z)),
            bm.verts.new((center_x + half_w, half_d, base_z)),
            bm.verts.new((center_x, half_d, base_z + rise)),
        ]
        faces = [
            bm.faces.new((verts[0], verts[1], verts[2])),
            bm.faces.new((verts[5], verts[4], verts[3])),
            bm.faces.new((verts[0], verts[3], verts[4], verts[1])),
            bm.faces.new((verts[1], verts[4], verts[5], verts[2])),
            bm.faces.new((verts[2], verts[5], verts[3], verts[0])),
        ]
        return mark(faces, STONE)

    # Every variant shares a partially buried two-step stereobate. Uneven slabs
    # and a missing corner prevent the perfect white wedding-cake look.
    podium_h = height * 0.09
    box(
        (width, depth, podium_h),
        (0.0, 0.0, podium_h * 0.5),
        FOUNDATION,
        0.045,
        (0.0, 0.0, math.radians(rng.uniform(-1.2, 1.2) * damage)),
    )
    box(
        (width * 0.86, depth * 0.82, podium_h * 0.72),
        (-width * 0.025, depth * 0.015, podium_h * 1.32),
        STONE,
        0.035,
        (0.0, math.radians(rng.uniform(-1.0, 1.0) * damage), 0.0),
    )

    if style == "shrine":
        column_h = height * 0.72
        column(-width * 0.25, -depth * 0.22, column_h, broken=False, lean=-0.018 * damage)
        column(width * 0.25, -depth * 0.22, column_h * (0.54 + damage * 0.08), broken=True)
        column(-width * 0.25, depth * 0.22, column_h * 0.82, broken=False, lean=0.024 * damage)
        column(width * 0.25, depth * 0.22, column_h * 0.42, broken=True)
        lintel_z = height * 0.91
        box(
            (width * 0.68, depth * 0.18, height * 0.095),
            (-width * 0.04, -depth * 0.22, lintel_z),
            STONE,
            0.028,
            (0.0, math.radians(-2.8 * damage), math.radians(1.8 * damage)),
        )
        pediment(width * 0.66, depth * 0.16, lintel_z + height * 0.052, height * 0.18)
        box(
            (width * 0.28, depth * 0.24, height * 0.28),
            (0.0, depth * 0.1, podium_h * 2.1),
            FOUNDATION,
            0.03,
        )
        box(
            (width * 0.2, depth * 0.018, height * 0.18),
            (0.0, depth * 0.1 - depth * 0.13, podium_h * 2.45),
            PATINA,
            0.008,
        )
        silhouette = "ruined_doric_shrine"

    elif style == "colonnade":
        for index, x in enumerate((-width * 0.33, 0.0, width * 0.33)):
            surviving = height * (0.72 if index == 0 else 0.48 if index == 1 else 0.84)
            column(
                x,
                0.0,
                surviving,
                broken=index == 1,
                lean=(index - 1) * 0.022 * damage,
            )
        box(
            (width * 0.62, depth * 0.22, height * 0.1),
            (width * 0.12, 0.0, height * 0.88),
            STONE,
            0.03,
            (0.0, math.radians(3.5 * damage), math.radians(-2.2 * damage)),
        )
        box(
            (width * 0.46, depth * 0.20, height * 0.085),
            (-width * 0.22, depth * 0.26, podium_h * 2.3),
            STONE,
            0.025,
            (math.radians(7.0), math.radians(-5.0), math.radians(18.0)),
        )
        silhouette = "broken_processional_colonnade"

    else:
        # A compact naiskos/heroon: heavy tomb core, two surviving antae and a
        # bronze name plate. It remains unmistakable even when the camera is too
        # far away to resolve individual column drums.
        core_w = width * 0.54
        core_d = depth * 0.58
        core_h = height * 0.48
        box(
            (core_w, core_d, core_h),
            (0.0, depth * 0.08, podium_h * 1.7 + core_h * 0.5),
            FOUNDATION,
            0.04,
        )
        column(-width * 0.29, -depth * 0.24, height * 0.72, broken=False)
        column(width * 0.29, -depth * 0.24, height * 0.55, broken=True)
        lintel_z = height * 0.80
        box(
            (width * 0.74, depth * 0.18, height * 0.10),
            (-width * 0.02, -depth * 0.24, lintel_z),
            STONE,
            0.026,
            (0.0, math.radians(-2.0 * damage), math.radians(1.5 * damage)),
        )
        pediment(width * 0.71, depth * 0.16, lintel_z + height * 0.055, height * 0.19)
        box(
            (core_w * 0.54, depth * 0.025, core_h * 0.33),
            (0.0, -core_d * 0.51 + depth * 0.08, podium_h * 1.7 + core_h * 0.55),
            PATINA,
            0.009,
        )
        silhouette = "weathered_hero_tomb"

    # Fallen drums and cap fragments tell the damage story at ground level.
    drum_radius = width * 0.052
    for index in range(3 if style != "colonnade" else 4):
        side = -1.0 if index % 2 == 0 else 1.0
        x = side * width * (0.27 + index * 0.045)
        y = depth * (-0.33 + index * 0.22)
        cylinder(
            drum_radius * (0.92 + rng.uniform(-0.08, 0.08)),
            width * (0.15 + rng.uniform(-0.025, 0.035)),
            (x, y, podium_h * 1.88 + drum_radius),
            STONE,
            12,
            axis="x" if index % 2 == 0 else "y",
        )
    for index in range(5):
        angle = rng.uniform(0.0, math.tau)
        distance = rng.uniform(width * 0.32, width * 0.54)
        scale = rng.uniform(width * 0.035, width * 0.07)
        rubble = mesh_lib.add_icosphere(
            bm,
            radius=scale,
            subdivisions=1,
            center=(
                math.cos(angle) * distance,
                math.sin(angle) * distance * depth / width,
                podium_h + scale * 0.65,
            ),
        )
        mark(rubble, FOUNDATION if index % 2 else STONE)

    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    for material in materials:
        obj.data.materials.append(material)
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, math.radians(rotation))
    obj["bforge_architecture"] = "hellenic_ruin"
    obj["bforge_ruin_style"] = style
    obj["bforge_parts"] = parts
    result = finish_lib.finish(
        ctx,
        obj,
        material="",
        uv="box",
        uv_scale=max(0.1, float(uv_scale)),
        origin="world",
        smooth=False,
    )
    result.update(
        {
            "style": style,
            "silhouette": silhouette,
            "parts": parts,
            "weathering": round(damage, 3),
        }
    )
    finish_lib.budget_note(ctx, obj, 7_500)
    return result
