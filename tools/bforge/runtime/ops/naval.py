"""Deterministic Aegean docks and ancient ships for RTS-scale naval play."""

from __future__ import annotations

import math

import bmesh
from lib import finish as finish_lib
from lib import mat as mat_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from mathutils import Matrix, Vector
from registry import op


class _Builder:
    """A material-aware mesh vocabulary shared by both naval recipes."""

    def __init__(self, bm):
        self.bm = bm
        self.parts = 0

    def mark(self, faces, slot):
        for face in faces:
            face.material_index = slot
        self.parts += 1
        return faces

    def box(self, size, center, slot, bevel=0.018, rotation=(0.0, 0.0, 0.0)):
        faces = mesh_lib.add_box(self.bm, size=size, center=(0.0, 0.0, 0.0), bevel=bevel)
        verts = list({vert for face in faces for vert in face.verts})
        rx, ry, rz = rotation
        matrix = Matrix.Translation(Vector(center))
        if rz:
            matrix = matrix @ Matrix.Rotation(rz, 4, "Z")
        if ry:
            matrix = matrix @ Matrix.Rotation(ry, 4, "Y")
        if rx:
            matrix = matrix @ Matrix.Rotation(rx, 4, "X")
        bmesh.ops.transform(self.bm, matrix=matrix, verts=verts)
        return self.mark(faces, slot)

    def cylinder(self, radius, depth, center, slot, segments=10, axis="z", radius_top=None):
        faces = mesh_lib.add_cylinder(
            self.bm,
            radius=radius,
            radius_top=radius_top,
            depth=depth,
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
        bmesh.ops.transform(self.bm, matrix=matrix, verts=verts)
        return self.mark(faces, slot)

    def beam(self, start, end, radius, slot, segments=7):
        start_vec, end_vec = Vector(start), Vector(end)
        direction = end_vec - start_vec
        if direction.length <= 1e-5:
            return []
        faces = mesh_lib.add_cylinder(
            self.bm, radius=radius, depth=direction.length, segments=segments,
            center=(0.0, 0.0, 0.0),
        )
        verts = list({vert for face in faces for vert in face.verts})
        orientation = direction.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.transform(
            self.bm,
            matrix=Matrix.Translation((start_vec + end_vec) * 0.5) @ orientation,
            verts=verts,
        )
        return self.mark(faces, slot)


def _finish(ctx, name, bm, materials, build, location, rotation, uv_scale, properties, budget):
    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    for material in materials:
        obj.data.materials.append(material)
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, math.radians(rotation))
    for key, value in properties.items():
        obj[key] = value
    obj["bforge_parts"] = build.parts
    result = finish_lib.finish(
        ctx, obj, material="", uv="box", uv_scale=max(0.1, uv_scale),
        origin="world", smooth=False,
    )
    result.update(properties)
    result["parts"] = build.parts
    finish_lib.budget_note(ctx, obj, budget)
    return result


@op(
    "arch.dock",
    summary=(
        "A serious Aegean working harbour: stepped limestone quay, timber pier, "
        "waterline piles, bollards, cargo and a bronze-hooped loading crane. The "
        "landward apron and waterward pier read from RTS and first-person cameras."
    ),
    params={
        "name": ("str", "aegean_dock", "Object name"),
        "width": ("num", 7.5, "Shore-parallel width in metres"),
        "depth": ("num", 8.5, "Land-to-water depth in metres"),
        "height": ("num", 2.5, "Highest crane point in metres"),
        "stone_color": ("str", "#777064", "Weathered limestone quay"),
        "foundation_color": ("str", "#3b3935", "Wet foundation and shadow stone"),
        "timber_color": ("str", "#332117", "Pier, crane and cargo timber"),
        "metal_color": ("str", "#6f512e", "Bronze hoops, chain and fittings"),
        "cloth_color": ("str", "#4b2522", "Restrained painted harbour marker"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "rotation": ("num", 0.0, "Yaw in degrees; pier points toward -Y"),
        "uv_scale": ("num", 0.75, "Metres per UV tile"),
    },
    tags=["build", "architecture", "naval", "rts", "economy"],
)
def arch_dock(ctx, name, width, depth, height, stone_color, foundation_color,
              timber_color, metal_color, cloth_color, location, rotation, uv_scale):
    width = max(3.2, min(18.0, float(width)))
    depth = max(4.0, min(22.0, float(depth)))
    height = max(1.8, min(7.0, float(height)))
    materials = [
        mat_lib.principled("m_dock_stone", stone_color, roughness=0.94),
        mat_lib.principled("m_dock_foundation", foundation_color, roughness=0.98),
        mat_lib.principled("m_dock_timber", timber_color, roughness=0.87),
        mat_lib.principled("m_dock_metal", metal_color, roughness=0.48, metallic=0.66),
        mat_lib.principled("m_dock_cloth", cloth_color, roughness=0.96),
    ]
    STONE, FOUNDATION, TIMBER, METAL, CLOTH = range(5)
    bm = mesh_lib.new_bmesh()
    build = _Builder(bm)
    apron_depth = depth * 0.38
    pier_depth = depth - apron_depth
    apron_y = depth * 0.5 - apron_depth * 0.5
    quay_h = min(0.62, height * 0.24)
    course_h = quay_h * 0.34

    build.box((width, apron_depth, quay_h), (0.0, apron_y, quay_h * 0.5), FOUNDATION, 0.045)
    blocks, gap = 6, width * 0.008
    block_w = (width - gap * (blocks - 1)) / blocks
    for course in range(2):
        offset = block_w * 0.5 if course % 2 else 0.0
        for index in range(blocks + 1):
            x = -width * 0.5 + block_w * 0.5 + index * (block_w + gap) - offset
            left, right = max(-width * 0.5, x - block_w * 0.5), min(width * 0.5, x + block_w * 0.5)
            if right - left > width * 0.06:
                build.box(
                    (right - left, apron_depth * 1.02, course_h),
                    ((left + right) * 0.5, apron_y, quay_h + course_h * (course + 0.5)),
                    STONE, 0.016,
                )

    pier_w = width * 0.48
    deck_z = quay_h + course_h * 2.0 + height * 0.025
    plank_count = 11
    plank_depth = pier_depth / plank_count
    for index in range(plank_count):
        y = depth * 0.5 - apron_depth - plank_depth * (index + 0.5)
        build.box(
            (pier_w, plank_depth * 0.88, height * 0.055), (0.0, y, deck_z), TIMBER, 0.012,
            (0.0, 0.0, math.radians((-1 if index % 2 else 1) * 0.35)),
        )
    for x in (-pier_w * 0.43, pier_w * 0.43):
        build.beam((x, depth * 0.5 - apron_depth, deck_z - height * 0.08),
                   (x, -depth * 0.5, deck_z - height * 0.08), width * 0.022, TIMBER)
        for fraction in (0.05, 0.35, 0.65, 0.95):
            y = depth * 0.5 - apron_depth - pier_depth * fraction
            build.cylinder(width * 0.026, deck_z + height * 0.26,
                           (x, y, (deck_z - height * 0.26) * 0.5), TIMBER, 8)
            build.cylinder(width * 0.034, height * 0.055,
                           (x, y, deck_z + height * 0.055), METAL, 10)
    for x in (-pier_w * 0.39, pier_w * 0.39):
        for y in (-depth * 0.46, depth * 0.5 - apron_depth - pier_depth * 0.18):
            build.cylinder(width * 0.035, height * 0.18,
                           (x, y, deck_z + height * 0.09), TIMBER, 9,
                           radius_top=width * 0.045)

    crane_x, crane_y = -width * 0.27, apron_y - apron_depth * 0.10
    crane_base, crane_top = quay_h + course_h * 2.0, quay_h + course_h * 2.0 + height * 0.82
    for sx in (-1.0, 1.0):
        build.beam((crane_x + sx * width * 0.09, crane_y + apron_depth * 0.24, crane_base),
                   (crane_x, crane_y, crane_top), width * 0.024, TIMBER, 8)
    boom = (crane_x, crane_y - apron_depth * 0.76, crane_top - height * 0.08)
    build.beam((crane_x, crane_y, crane_top), boom, width * 0.025, TIMBER, 8)
    build.cylinder(width * 0.065, width * 0.15,
                   (crane_x, crane_y - apron_depth * 0.08, crane_top - height * 0.03),
                   METAL, 14, axis="x")
    hook_z = deck_z + height * 0.36
    build.beam(boom, (boom[0], boom[1], hook_z), width * 0.008, METAL, 6)
    build.beam((boom[0], boom[1], hook_z),
               (boom[0] + width * 0.045, boom[1], hook_z - height * 0.08),
               width * 0.012, METAL)
    for index, (x, y, scale) in enumerate(((0.25, 0.28, 0.17), (0.38, 0.15, 0.13), (0.18, 0.04, 0.11))):
        build.box((width * scale, width * scale * 0.82, height * scale * 0.70),
                  (x * width, apron_y + y * apron_depth, crane_base + height * scale * 0.35),
                  TIMBER if index != 1 else CLOTH, 0.025)

    properties = {
        "bforge_architecture": "aegean_harbour",
        "silhouette": "stone_quay_timber_pier_crane",
        "shore_axis": "positive_y_land_negative_y_water",
        "waterline": round(deck_z - height * 0.30, 3),
    }
    return _finish(ctx, name, bm, materials, build, location, rotation, uv_scale, properties, 12_000)


@op(
    "prop.ancient_ship",
    summary=(
        "A browser-budget ancient Greek fishing boat or war galley with a curved "
        "multi-chine hull, readable bow, oars, mast and restrained fittings. Fishing "
        "boats carry nets and amphorae; galleys carry oar banks, shields and a ram."
    ),
    params={
        "name": ("str", "ancient_ship", "Object name"),
        "style": ("enum:fishing|galley", "fishing", "Naval unit silhouette"),
        "length": ("num", 5.8, "Bow-to-stern length in metres"),
        "beam": ("num", 2.0, "Maximum hull width in metres"),
        "height": ("num", 2.8, "Keel-to-masthead height in metres"),
        "hull_color": ("str", "#3b2117", "Dark caulked hull planks"),
        "wood_color": ("str", "#6a4a2d", "Deck, mast and oars"),
        "metal_color": ("str", "#755431", "Bronze ram and fittings"),
        "cloth_color": ("str", "#5a2a25", "Muted sail or net bundle"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "rotation": ("num", 0.0, "Yaw in degrees; bow points toward -Y"),
        "uv_scale": ("num", 0.55, "Metres per UV tile"),
    },
    tags=["prop", "vehicle", "naval", "rts"],
)
def prop_ancient_ship(ctx, name, style, length, beam, height, hull_color, wood_color,
                      metal_color, cloth_color, location, rotation, uv_scale):
    length = max(3.4, min(24.0, float(length)))
    beam = max(length * 0.20, min(length * 0.46, float(beam)))
    height = max(1.8, min(length * 0.90, float(height)))
    materials = [
        mat_lib.principled("m_ship_deck", wood_color, roughness=0.88),
        mat_lib.principled("m_ship_shadow", "#211a17", roughness=0.98),
        mat_lib.principled("m_ship_hull", hull_color, roughness=0.90),
        mat_lib.principled("m_ship_metal", metal_color, roughness=0.48, metallic=0.66),
        mat_lib.principled("m_ship_cloth", cloth_color, roughness=0.96),
    ]
    DECK, _SHADOW, HULL, METAL, CLOTH = range(5)
    bm = mesh_lib.new_bmesh()
    build = _Builder(bm)

    station_count = 7 if style == "galley" else 6
    sections = []
    for index in range(station_count):
        u = index / (station_count - 1)
        y = -length * 0.5 + length * u
        curve = math.sin(math.pi * u) ** 0.58
        half = beam * (0.055 + curve * 0.445)
        end_lift = abs(u - 0.5) * 2.0
        keel_z = height * (0.055 + end_lift * 0.075)
        chine_z = height * (0.18 + end_lift * 0.025)
        gunwale_z = height * (0.30 + end_lift * 0.075)
        points = [(-half, y, gunwale_z), (-half * 0.72, y, chine_z),
                  (0.0, y, keel_z), (half * 0.72, y, chine_z),
                  (half, y, gunwale_z)]
        sections.append([bm.verts.new(point) for point in points])
    hull_faces = []
    for index in range(station_count - 1):
        current, following = sections[index], sections[index + 1]
        for strip in range(4):
            hull_faces.append(bm.faces.new((current[strip], following[strip],
                                            following[strip + 1], current[strip + 1])))
    hull_faces.extend((bm.faces.new(tuple(reversed(sections[0]))), bm.faces.new(tuple(sections[-1]))))
    build.mark(hull_faces, HULL)

    deck_z = height * 0.285
    deck_length = length * (0.72 if style == "fishing" else 0.79)
    deck_beam = beam * 0.66
    plank_count = 7 if style == "galley" else 5
    for index in range(plank_count):
        y = -deck_length * 0.5 + deck_length * (index + 0.5) / plank_count
        build.box((deck_beam, deck_length / plank_count * 0.88, height * 0.022),
                  (0.0, y, deck_z), DECK, 0.008)
    for side in (-1.0, 1.0):
        build.beam((side * beam * 0.43, -length * 0.37, deck_z + height * 0.06),
                   (side * beam * 0.43, length * 0.37, deck_z + height * 0.06),
                   beam * 0.025, METAL, 8)

    mast_y = length * (0.02 if style == "galley" else 0.08)
    mast_top = height * (0.94 if style == "galley" else 0.84)
    build.beam((0.0, mast_y, deck_z), (0.0, mast_y, mast_top), beam * 0.035, DECK, 10)
    yard_z = mast_top * (0.78 if style == "galley" else 0.72)
    yard_half = beam * (0.84 if style == "galley" else 0.63)
    build.beam((-yard_half, mast_y, yard_z), (yard_half, mast_y, yard_z), beam * 0.020, DECK, 8)
    sail_h = height * (0.43 if style == "galley" else 0.31)
    sail_w = yard_half * (1.72 if style == "galley" else 1.50)
    build.box((sail_w, height * 0.018, sail_h),
              (0.0, mast_y + height * 0.015, yard_z - sail_h * 0.52),
              CLOTH, 0.005, (0.0, math.radians(-4.0), 0.0))
    for side in (-1.0, 1.0):
        build.beam((0.0, mast_y, mast_top),
                   (side * beam * 0.40, length * 0.30, deck_z + height * 0.05),
                   beam * 0.006, METAL, 5)

    if style == "galley":
        for index in range(7):
            y = -length * 0.30 + length * 0.60 * index / 6
            for side in (-1.0, 1.0):
                build.beam((side * beam * 0.34, y, deck_z + height * 0.01),
                           (side * beam * 0.78, y + length * 0.035, height * 0.08),
                           beam * 0.014, DECK, 6)
            if index % 2 == 0:
                build.cylinder(beam * 0.075, height * 0.024,
                               (beam * 0.455, y, deck_z + height * 0.15),
                               METAL, 14, axis="x")
        build.beam((0.0, -length * 0.43, height * 0.13),
                   (0.0, -length * 0.64, height * 0.13), beam * 0.052, METAL, 10)
        build.cylinder(beam * 0.075, length * 0.18,
                       (0.0, -length * 0.66, height * 0.13), METAL, 8,
                       axis="y", radius_top=0.0)
        silhouette = "banked_oar_galley_bronze_ram"
    else:
        for side in (-1.0, 1.0):
            build.beam((side * beam * 0.23, length * 0.08, deck_z + height * 0.03),
                       (side * beam * 0.72, length * 0.18, height * 0.08),
                       beam * 0.018, DECK, 7)
        for index, x in enumerate((-0.18, 0.02, 0.20)):
            build.cylinder(beam * (0.070 if index == 1 else 0.058), height * 0.18,
                           (x * beam, length * 0.24, deck_z + height * 0.09),
                           CLOTH if index == 1 else DECK, 9,
                           radius_top=beam * 0.035)
        build.box((beam * 0.52, length * 0.13, height * 0.11),
                  (0.0, length * 0.34, deck_z + height * 0.08), CLOTH, 0.025,
                  (0.0, 0.0, math.radians(4.0)))
        silhouette = "working_fishing_boat_net_amphorae"

    properties = {
        "bforge_vehicle": "ancient_ship",
        "bforge_ship_style": style,
        "style": style,
        "silhouette": silhouette,
        "forward_axis": "negative_y",
        "waterline": round(height * 0.16, 3),
    }
    return _finish(ctx, name, bm, materials, build, location, rotation, uv_scale, properties, 10_000)