"""Characters: proportioned humanoid blockouts, armatures, skinning, animation.

Most AI-Blender tooling stops at static props because rigging is where the
context-sensitive `bpy.ops` calls live. Everything here is done through the data
API instead — bones are built by writing head/tail vectors, weights are solved
with a bone-segment distance falloff, and actions are keyframed directly onto
pose bones. No operator context, no GUI, fully deterministic.

Bone names are lowercase snake_case with `_l` / `_r` suffixes and a single
`hips` root, which satisfies the studio asset validator and imports cleanly into
Godot's `Skeleton3D` and glTF's skin joints.
"""

from __future__ import annotations

import math

import bpy
from lib import finish as finish_lib
from lib import mat as mat_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from mathutils import Matrix, Vector
from registry import OpError, op

# Proportions as fractions of total height. The classic figure-drawing ratios —
# 7.5 heads realistic, 8 heads heroic, 4 heads stylised — encoded so an agent
# gets a believable silhouette without knowing any of this.
BUILDS = {
    "realistic": {"heads": 7.5, "shoulder": 0.245, "waist": 0.145, "limb": 1.0, "bulk": 1.0},
    "heroic":    {"heads": 8.0, "shoulder": 0.285, "waist": 0.140, "limb": 1.03, "bulk": 1.18},
    "stylized":  {"heads": 5.5, "shoulder": 0.230, "waist": 0.150, "limb": 0.92, "bulk": 1.10},
    "chibi":     {"heads": 3.6, "shoulder": 0.200, "waist": 0.165, "limb": 0.80, "bulk": 1.25},
    "lithe":     {"heads": 8.2, "shoulder": 0.205, "waist": 0.120, "limb": 1.06, "bulk": 0.82},
}


def _skeleton(height, build):
    """Joint positions in metres, keyed by bone name -> (head, tail)."""
    spec = BUILDS[build]
    head_unit = height / spec["heads"]
    hip_z = height * 0.50
    shoulder_z = height - head_unit * 1.42
    shoulder_x = height * spec["shoulder"] * 0.5
    hip_x = height * spec["waist"] * 0.5
    limb = spec["limb"]

    joints = {
        "hips": ((0.0, 0.0, hip_z), (0.0, 0.0, hip_z + height * 0.075)),
        "spine": ((0.0, 0.0, hip_z + height * 0.075), (0.0, 0.0, hip_z + height * 0.155)),
        "chest": ((0.0, 0.0, hip_z + height * 0.155), (0.0, 0.0, shoulder_z)),
        "neck": ((0.0, 0.0, shoulder_z), (0.0, 0.0, shoulder_z + head_unit * 0.32)),
        "head": (
            (0.0, 0.0, shoulder_z + head_unit * 0.32),
            (0.0, 0.0, shoulder_z + head_unit * 0.32 + head_unit),
        ),
    }
    for side, sign in (("l", 1.0), ("r", -1.0)):
        arm_len = (shoulder_z - hip_z) * 0.92 * limb
        joints[f"shoulder_{side}"] = (
            (sign * height * 0.028, 0.0, shoulder_z - head_unit * 0.06),
            (sign * shoulder_x, 0.0, shoulder_z - head_unit * 0.12),
        )
        joints[f"upper_arm_{side}"] = (
            (sign * shoulder_x, 0.0, shoulder_z - head_unit * 0.12),
            (sign * shoulder_x, 0.0, shoulder_z - head_unit * 0.12 - arm_len * 0.47),
        )
        joints[f"forearm_{side}"] = (
            (sign * shoulder_x, 0.0, shoulder_z - head_unit * 0.12 - arm_len * 0.47),
            (sign * shoulder_x, 0.0, shoulder_z - head_unit * 0.12 - arm_len * 0.88),
        )
        joints[f"hand_{side}"] = (
            (sign * shoulder_x, 0.0, shoulder_z - head_unit * 0.12 - arm_len * 0.88),
            (sign * shoulder_x, 0.0, shoulder_z - head_unit * 0.12 - arm_len * 1.0),
        )
        leg_len = hip_z * limb
        joints[f"thigh_{side}"] = (
            (sign * hip_x, 0.0, hip_z),
            (sign * hip_x * 0.92, 0.0, hip_z - leg_len * 0.48),
        )
        joints[f"shin_{side}"] = (
            (sign * hip_x * 0.92, 0.0, hip_z - leg_len * 0.48),
            (sign * hip_x * 0.88, 0.0, hip_z - leg_len * 0.93),
        )
        joints[f"foot_{side}"] = (
            (sign * hip_x * 0.88, 0.0, hip_z - leg_len * 0.93),
            (sign * hip_x * 0.88, -height * 0.055, 0.0),
        )
    return joints, spec, head_unit


PARENTS = {
    "spine": "hips", "chest": "spine", "neck": "chest", "head": "neck",
    "shoulder_l": "chest", "upper_arm_l": "shoulder_l", "forearm_l": "upper_arm_l",
    "hand_l": "forearm_l",
    "shoulder_r": "chest", "upper_arm_r": "shoulder_r", "forearm_r": "upper_arm_r",
    "hand_r": "forearm_r",
    "thigh_l": "hips", "shin_l": "thigh_l", "foot_l": "shin_l",
    "thigh_r": "hips", "shin_r": "thigh_r", "foot_r": "hips",
}
PARENTS["foot_r"] = "shin_r"


@op(
    "char.humanoid",
    summary="Proportioned humanoid blockout using classic figure-drawing head ratios (7.5 realistic, 8 heroic, 4 chibi). ~1400 tris. Pair with char.rig and char.animate for a complete animated character.",
    params={
        "name": ("str", "character", "Object name"),
        "height": ("num", 1.8, "Total height in metres"),
        "build": ("enum:realistic|heroic|stylized|chibi|lithe", "heroic", "Body proportions"),
        "bulk": ("num", 1.0, "Extra muscle/armour thickness multiplier"),
        "detail": ("int", 8, "Limb cross-section segments (6-10 is the game range)"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "skin": ("str", "#c08a6a", "Body colour"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["char"],
)
def char_humanoid(ctx, name, height, build, bulk, detail, location, skin, seed):
    ctx.reseed(seed)
    joints, spec, head_unit = _skeleton(height, build)
    girth = spec["bulk"] * bulk
    sides = max(5, min(16, detail))
    bm = mesh_lib.new_bmesh()

    def limb(a, b, radius_a, radius_b):
        start, end = Vector(a), Vector(b)
        axis = end - start
        length = axis.length
        if length < 1e-5:
            return
        piece = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(
            piece, radius=radius_a, radius_top=radius_b, depth=length,
            segments=sides, center=(0.0, 0.0, length * 0.5),
        )
        rotation = axis.normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh_transform(piece, Matrix.Translation(start) @ rotation)
        _absorb(bm, piece)

    def blob(center, radius, squash=(1.0, 1.0, 1.0)):
        piece = mesh_lib.new_bmesh()
        mesh_lib.add_icosphere(piece, radius=radius, subdivisions=2)
        bmesh_transform(
            piece, Matrix.Translation(Vector(center)) @ Matrix.Diagonal(Vector(squash)).to_4x4()
        )
        _absorb(bm, piece)

    torso_r = height * 0.078 * girth
    # Torso as a stack so the waist actually narrows — a single capsule reads
    # as a barrel and is the classic giveaway of a generated character.
    limb(joints["hips"][0], joints["spine"][1], torso_r * 1.02, torso_r * 0.86)
    limb(joints["spine"][1], joints["chest"][1], torso_r * 0.86, torso_r * 1.16)
    limb(joints["neck"][0], joints["neck"][1], torso_r * 0.42, torso_r * 0.40)

    head_center = Vector(joints["head"][0]).lerp(Vector(joints["head"][1]), 0.5)
    blob(head_center, head_unit * 0.46, (0.88, 0.94, 1.0))

    for side in ("l", "r"):
        upper_r = height * 0.030 * girth
        shoulder_head, shoulder_tail = joints[f"shoulder_{side}"]
        limb(shoulder_head, shoulder_tail, torso_r * 0.50, upper_r * 1.0)
        # Deltoid cap. Without it the shoulder is a short, fat cone pointing
        # sideways and reads as a flat slab bolted to the torso.
        blob(shoulder_tail, upper_r * 1.18, (1.0, 1.0, 0.85))
        limb(joints[f"upper_arm_{side}"][0], joints[f"upper_arm_{side}"][1],
             upper_r * 1.05, upper_r * 0.88)
        limb(joints[f"forearm_{side}"][0], joints[f"forearm_{side}"][1],
             upper_r * 0.88, upper_r * 0.66)
        hand_center = Vector(joints[f"hand_{side}"][0]).lerp(
            Vector(joints[f"hand_{side}"][1]), 0.6
        )
        blob(hand_center, upper_r * 0.82, (0.75, 1.0, 1.15))

        thigh_r = height * 0.043 * girth
        limb(joints[f"thigh_{side}"][0], joints[f"thigh_{side}"][1], thigh_r * 1.1, thigh_r * 0.82)
        limb(joints[f"shin_{side}"][0], joints[f"shin_{side}"][1], thigh_r * 0.82, thigh_r * 0.52)
        foot_a, foot_b = joints[f"foot_{side}"]
        foot_center = Vector(foot_a).lerp(Vector(foot_b), 0.55)
        blob(
            (foot_center.x, foot_center.y - height * 0.012, height * 0.028),
            thigh_r * 0.72, (0.85, 1.75, 0.55),
        )

    mesh_lib.cleanup(bm, merge_dist=height * 0.002)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    skin_mat = mat_lib.principled(f"m_{obj.name}_skin", color=skin, roughness=0.68)
    result = finish_lib.finish(
        ctx, obj, material=skin_mat, uv="smart_packed", origin="bottom", smooth=True,
        smooth_angle=50.0,
    )
    result["build"] = build
    result["height_m"] = height
    result["head_unit_m"] = round(head_unit, 4)
    ctx.note(
        f"'{obj.name}' is a blockout. Run char.rig name='{obj.name}' to add a skinned "
        "armature, then char.animate for idle/walk/run clips."
    )
    finish_lib.budget_note(ctx, obj, 3000)
    return result


@op(
    "char.skeleton",
    summary=(
        "Build an anatomically readable bone-body on the same proportions as "
        "char.humanoid. The joined rib cage, skull, long bones and dark sockets "
        "remain compatible with char.outfit, char.rig and char.animate."
    ),
    params={
        "name": ("str", "skeleton", "Object name"),
        "height": ("num", 1.86, "Total height in metres"),
        "build": ("enum:realistic|heroic|lithe", "lithe", "Bone proportions"),
        "detail": ("int", 8, "Bone cross-section segments, 6-12"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "bone": ("str", "#b8ad92", "Aged bone colour"),
        "socket": ("str", "#171817", "Eye, nose and mouth cavity colour"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["char", "creature", "undead"],
)
def char_skeleton(ctx, name, height, build, detail, location, bone, socket, seed):
    ctx.reseed(seed)
    joints, spec, head_unit = _skeleton(height, build)
    sides = max(6, min(12, detail))
    bone_bm = mesh_lib.new_bmesh()
    socket_bm = mesh_lib.new_bmesh()

    def absorb_primitive(target, primitive, matrix=None):
        piece = mesh_lib.new_bmesh()
        primitive(piece)
        if matrix is not None:
            bmesh_transform(piece, matrix)
        _absorb(target, piece)

    def limb(a, b, radius_a, radius_b=None, *, offset=(0.0, 0.0, 0.0)):
        start = Vector(a) + Vector(offset)
        end = Vector(b) + Vector(offset)
        axis = end - start
        if axis.length < 1e-5:
            return
        top = radius_a if radius_b is None else radius_b
        matrix = (
            Matrix.Translation(start)
            @ axis.normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()
        )
        absorb_primitive(
            bone_bm,
            lambda bm: mesh_lib.add_cylinder(
                bm,
                radius=radius_a,
                radius_top=top,
                depth=axis.length,
                segments=sides,
                center=(0.0, 0.0, axis.length * 0.5),
            ),
            matrix,
        )

    def blob(target, center, radius, scale=(1.0, 1.0, 1.0), subdivisions=1):
        matrix = (
            Matrix.Translation(Vector(center))
            @ Matrix.Diagonal(Vector((*scale, 1.0)))
        )
        absorb_primitive(
            target,
            lambda bm: mesh_lib.add_icosphere(
                bm, radius=radius, subdivisions=subdivisions
            ),
            matrix,
        )

    # Spine, sternum and collar establish the torso even before the ribs are
    # visible. Bone cylinders are deliberately narrower than a living body's
    # limbs so an RTS silhouette cannot be mistaken for a recoloured human.
    limb(joints["hips"][0], joints["chest"][1], height * 0.019, height * 0.014)
    sternum_a = (0.0, -height * 0.052, height * 0.585)
    sternum_b = (0.0, -height * 0.058, height * 0.785)
    limb(sternum_a, sternum_b, height * 0.012)
    for _side, sign in (("l", 1.0), ("r", -1.0)):
        collar_end = (
            sign * height * spec["shoulder"] * 0.43,
            -height * 0.012,
            height * 0.79,
        )
        limb((0.0, 0.0, height * 0.775), collar_end, height * 0.014, height * 0.011)

    # Five elliptical rib rings retain negative space. Full rings are cheaper
    # and more legible at game distance than dozens of fragile individual arcs.
    for index in range(5):
        z = height * (0.61 + index * 0.037)
        taper = 1.0 - abs(index - 2) * 0.085
        matrix = (
            Matrix.Translation(Vector((0.0, 0.0, z)))
            @ Matrix.Diagonal(Vector((taper, 0.52, 1.0, 1.0)))
        )
        absorb_primitive(
            bone_bm,
            lambda bm, major=height * 0.112, minor=height * 0.0085: mesh_lib.add_torus(
                bm,
                major=major,
                minor=minor,
                major_segments=max(12, sides * 2),
                minor_segments=5,
            ),
            matrix,
        )

    # Pelvic ring and sacrum.
    absorb_primitive(
        bone_bm,
        lambda bm: mesh_lib.add_torus(
            bm,
            major=height * 0.075,
            minor=height * 0.014,
            major_segments=max(12, sides * 2),
            minor_segments=6,
        ),
        Matrix.Translation(Vector((0.0, 0.0, height * 0.495)))
        @ Matrix.Diagonal(Vector((1.28, 0.7, 1.0, 1.0))),
    )
    blob(bone_bm, (0.0, 0.0, height * 0.505), height * 0.035, (0.72, 0.5, 1.05))

    for side, _sign in (("l", 1.0), ("r", -1.0)):
        # Two long bones per major limb make the skeletal construction explicit.
        for bone_name, radius, separation in (
            (f"upper_arm_{side}", height * 0.013, height * 0.009),
            (f"forearm_{side}", height * 0.010, height * 0.008),
            (f"thigh_{side}", height * 0.016, height * 0.010),
            (f"shin_{side}", height * 0.012, height * 0.009),
        ):
            a, b = joints[bone_name]
            limb(a, b, radius, radius * 0.82, offset=(0.0, -separation, 0.0))
            limb(a, b, radius * 0.82, radius * 0.7, offset=(0.0, separation, 0.0))
            blob(bone_bm, a, radius * 1.65, (1.0, 0.86, 1.0))
            blob(bone_bm, b, radius * 1.45, (1.0, 0.86, 1.0))

        shoulder_a, shoulder_b = joints[f"shoulder_{side}"]
        limb(shoulder_a, shoulder_b, height * 0.014, height * 0.012)
        hand_a, hand_b = joints[f"hand_{side}"]
        hand_center = Vector(hand_a).lerp(Vector(hand_b), 0.55)
        blob(
            bone_bm,
            hand_center,
            height * 0.026,
            (0.64, 0.82, 1.18),
        )
        foot_a, foot_b = joints[f"foot_{side}"]
        foot_center = Vector(foot_a).lerp(Vector(foot_b), 0.58)
        blob(
            bone_bm,
            (foot_center.x, foot_center.y, height * 0.03),
            height * 0.029,
            (0.72, 1.6, 0.45),
        )

    # Low-poly skull, jaw and cheek bones. Dark inset meshes create actual eye
    # and nasal cavities after export instead of painted dots.
    head_center = Vector(joints["head"][0]).lerp(Vector(joints["head"][1]), 0.57)
    skull_r = head_unit * 0.43
    blob(bone_bm, head_center, skull_r, (0.83, 0.91, 1.0), subdivisions=2)
    jaw_z = head_center.z - skull_r * 0.68
    absorb_primitive(
        bone_bm,
        lambda bm: mesh_lib.add_box(
            bm,
            size=(skull_r * 1.18, skull_r * 0.78, skull_r * 0.42),
            bevel=skull_r * 0.08,
            segments=1,
        ),
        Matrix.Translation(Vector((0.0, -skull_r * 0.12, jaw_z))),
    )
    for sign in (-1.0, 1.0):
        blob(
            socket_bm,
            (
                sign * skull_r * 0.34,
                head_center.y - skull_r * 0.78,
                head_center.z + skull_r * 0.16,
            ),
            skull_r * 0.24,
            (1.08, 0.34, 0.86),
        )
    blob(
        socket_bm,
        (0.0, head_center.y - skull_r * 0.84, head_center.z - skull_r * 0.12),
        skull_r * 0.13,
        (0.72, 0.3, 1.15),
    )
    absorb_primitive(
        socket_bm,
        lambda bm: mesh_lib.add_box(
            bm,
            size=(skull_r * 0.82, skull_r * 0.08, skull_r * 0.11),
            bevel=skull_r * 0.015,
            segments=1,
        ),
        Matrix.Translation(Vector((0.0, -skull_r * 0.54, jaw_z))),
    )

    mesh_lib.cleanup(bone_bm, merge_dist=height * 0.0008)
    mesh_lib.cleanup(socket_bm, merge_dist=height * 0.0008)
    bone_obj = mesh_lib.to_object(bone_bm, scene_lib.unique_name(name))
    socket_obj = mesh_lib.to_object(socket_bm, scene_lib.unique_name(f"{name}_sockets"))
    bone_obj.location = location
    socket_obj.location = location
    bone_mat = mat_lib.principled(
        f"m_{bone_obj.name}_bone", color=bone, roughness=0.88, metallic=0.0
    )
    socket_mat = mat_lib.principled(
        f"m_{bone_obj.name}_sockets", color=socket, roughness=1.0, metallic=0.0
    )
    finish_lib.finish(
        ctx, bone_obj, material=bone_mat, uv="smart_packed", origin=None,
        smooth=True, smooth_angle=48.0,
    )
    finish_lib.finish(
        ctx, socket_obj, material=socket_mat, uv="smart_packed", origin=None,
        smooth=True, smooth_angle=48.0,
    )
    merged = scene_lib.join([bone_obj, socket_obj], bone_obj.name)
    scene_lib.set_origin(merged, "bottom")
    scene_lib.apply_transforms(merged)
    mesh_lib.shade_auto_smooth(merged, 50.0)
    result = finish_lib.report(ctx, merged)
    result["build"] = build
    result["height_m"] = height
    result["head_unit_m"] = round(head_unit, 4)
    result["anatomy"] = "joined_bone_body"
    ctx.note(
        f"'{merged.name}' is an unrigged bone-body. Add char.outfit before "
        "char.rig; use the same height and build for deterministic skinning."
    )
    finish_lib.budget_note(ctx, merged, 5000)
    return result


@op(
    "char.outfit",
    summary=(
        "Add a production-readable rigid outfit to an unrigged humanoid, then join it "
        "into the body so char.rig skins every shell. Greek delver, hoplite and "
        "peltast armour include cuirass, straps, pteruges, helmets, bracers and "
        "greaves; stalker and oracle add role-readable undead hoods, masks and robes."
    ),
    params={
        "name": ("str", None, "Unrigged humanoid mesh from char.humanoid"),
        "style": (
            "enum:greek_delver|hoplite|peltast|stalker|oracle",
            "greek_delver",
            "Outfit silhouette",
        ),
        "cloth": ("str", "#262522", "Coarse tunic/linen colour"),
        "leather": ("str", "#38261c", "Straps, belt and boot-wrap colour"),
        "metal": ("str", "#71502d", "Aged bronze armour colour"),
        "accent": ("str", "#d18a32", "Small lamp or crest accent"),
        "detail": ("int", 10, "Radial segment count, 8-16"),
    },
    tags=["char", "armour", "undead"],
)
def char_outfit(ctx, name, style, cloth, leather, metal, accent, detail):
    body = _get(name)
    if body.type != "MESH":
        raise OpError(f"'{name}' is a {body.type}, not a humanoid mesh")
    if any(modifier.type == "ARMATURE" for modifier in body.modifiers):
        raise OpError(
            f"'{name}' is already rigged. Add char.outfit before char.rig so every "
            "armour shell receives deterministic skin weights."
        )

    bounds = mesh_lib.bounds(body)
    height = bounds["size"][2] or 1.8
    sides = max(8, min(16, detail))
    origin = body.location.copy()
    parts = []

    cloth_mat = mat_lib.principled(
        "m_outfit_linen", color=cloth, roughness=0.94, metallic=0.0
    )
    leather_mat = mat_lib.principled(
        "m_outfit_leather", color=leather, roughness=0.82, metallic=0.0
    )
    metal_mat = mat_lib.principled(
        "m_outfit_bronze", color=metal, roughness=0.43, metallic=0.78
    )
    dark_metal_mat = mat_lib.principled(
        "m_outfit_dark_metal", color="#17191a", roughness=0.54, metallic=0.72
    )
    accent_mat = mat_lib.principled(
        "m_outfit_lamp", color=accent, roughness=0.4, metallic=0.15,
        emission=0.7, emission_color=accent,
    )

    def finish_part(bm, label, material, *, smooth=False):
        mesh_lib.cleanup(bm, merge_dist=height * 0.0004)
        part = mesh_lib.to_object(bm, scene_lib.unique_name(f"{body.name}_{label}"))
        part.location = origin
        finish_lib.finish(
            ctx,
            part,
            material=material,
            uv="smart_packed",
            origin=None,
            smooth=smooth,
            smooth_angle=48.0,
        )
        parts.append(part)
        return part

    def cylinder(label, radius, depth, center, material, *, scale=(1.0, 1.0, 1.0),
                 radius_top=None, smooth=True):
        bm = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(
            bm,
            radius=radius,
            radius_top=radius_top,
            depth=depth,
            segments=sides,
        )
        matrix = (
            Matrix.Translation(Vector(center))
            @ Matrix.Diagonal(Vector((*scale, 1.0)))
        )
        bmesh_transform(bm, matrix)
        return finish_part(bm, label, material, smooth=smooth)

    def ellipsoid(label, radius, center, scale, material):
        bm = mesh_lib.new_bmesh()
        mesh_lib.add_icosphere(bm, radius=radius, subdivisions=2)
        matrix = (
            Matrix.Translation(Vector(center))
            @ Matrix.Diagonal(Vector((*scale, 1.0)))
        )
        bmesh_transform(bm, matrix)
        return finish_part(bm, label, material, smooth=True)

    def box(label, size, center, material, *, rotation=(0.0, 0.0, 0.0), bevel=0.0):
        bm = mesh_lib.new_bmesh()
        mesh_lib.add_box(bm, size=size, bevel=bevel, segments=1)
        rx, ry, rz = (math.radians(value) for value in rotation)
        matrix = (
            Matrix.Translation(Vector(center))
            @ Matrix.Rotation(rz, 4, "Z")
            @ Matrix.Rotation(ry, 4, "Y")
            @ Matrix.Rotation(rx, 4, "X")
        )
        bmesh_transform(bm, matrix)
        return finish_part(bm, label, material)

    # Layered linen beneath the metal keeps the silhouette practical. Oracle
    # robes are longer and narrower; a hoplite is the only fully armoured torso.
    torso_depth = height * (0.38 if style == "oracle" else 0.31)
    torso_center = height * (0.63 if style == "oracle" else 0.665)
    cylinder(
        "cuirass",
        height * 0.128,
        torso_depth,
        (0.0, 0.0, torso_center),
        metal_mat if style == "hoplite" else cloth_mat,
        scale=(0.96 if style == "oracle" else 1.02, 0.62, 1.0),
        radius_top=height * (0.14 if style == "oracle" else 0.152),
    )
    cylinder(
        "belt",
        height * 0.163,
        height * 0.052,
        (0.0, 0.0, height * 0.505),
        leather_mat,
        scale=(1.0, 0.58, 1.0),
    )

    # Crossed straps identify the delver and stalker; the lighter peltast gets
    # one baldric. The hoplite cuirass and oracle collar are intentionally clean.
    front_y = -height * 0.092
    strap_angles = {
        "greek_delver": (-27.0, 27.0),
        "stalker": (-31.0, 31.0),
        "peltast": (-29.0,),
    }.get(style, ())
    for index, angle in enumerate(strap_angles):
        box(
            f"chest_strap_{index}",
            (height * 0.035, height * 0.018, height * 0.31),
            (0.0, front_y, height * 0.68),
            leather_mat,
            rotation=(0.0, angle, 0.0),
            bevel=height * 0.004,
        )
    if style != "oracle":
        box(
            "buckle",
            (height * 0.09, height * 0.025, height * 0.07),
            (0.0, -height * 0.101, height * 0.505),
            metal_mat,
            bevel=height * 0.006,
        )
    else:
        cylinder(
            "ritual_collar",
            height * 0.155,
            height * 0.055,
            (0.0, 0.0, height * 0.79),
            metal_mat,
            scale=(1.0, 0.64, 1.0),
            radius_top=height * 0.138,
        )

    # Separate skirt plates retain negative space while sharing the hips shell
    # after char.rig, so the legs can stride without dragging one solid cone.
    plate_count = {
        "hoplite": 12,
        "greek_delver": 10,
        "peltast": 8,
        "stalker": 10,
        "oracle": 16,
    }[style]
    plate_length = height * (0.36 if style == "oracle" else 0.205)
    plate_z = height * (0.315 if style == "oracle" else 0.405)
    plate_radius_x = height * (0.13 if style == "oracle" else 0.142)
    plate_radius_y = height * (0.075 if style == "oracle" else 0.082)
    plate_material = (
        metal_mat if style == "hoplite"
        else cloth_mat if style in {"stalker", "oracle"}
        else leather_mat
    )
    for index in range(plate_count):
        angle = math.tau * index / plate_count
        box(
            f"pteruge_{index:02d}",
            (height * 0.038, height * 0.018, plate_length),
            (
                math.cos(angle) * plate_radius_x,
                math.sin(angle) * plate_radius_y,
                plate_z,
            ),
            plate_material,
            rotation=(0.0, 0.0, math.degrees(angle)),
            bevel=height * 0.003,
        )

    # Asymmetry distinguishes a worker or light peltast from a line soldier.
    shoulders = {
        "hoplite": ("l", "r"),
        "oracle": ("l", "r"),
        "greek_delver": ("l",),
        "peltast": ("l",),
        "stalker": (),
    }[style]
    for side in shoulders:
        sign = 1.0 if side == "l" else -1.0
        ellipsoid(
            f"pauldron_{side}",
            height * (0.055 if style == "oracle" else 0.062),
            (sign * height * 0.142, 0.0, height * 0.785),
            (1.45, 0.88, 0.58),
            metal_mat,
        )

    for side, sign in (("l", 1.0), ("r", -1.0)):
        cylinder(
            f"bracer_{side}",
            height * 0.034,
            height * 0.17,
            (sign * height * 0.123, 0.0, height * 0.575),
            leather_mat if style in {"stalker", "oracle"} else metal_mat,
            scale=(1.0, 0.78, 1.0),
            radius_top=height * 0.029,
        )
        if style != "oracle":
            cylinder(
                f"greave_{side}",
                height * 0.052,
                height * 0.35,
                (sign * height * 0.072, -height * 0.004, height * 0.205),
                leather_mat if style == "stalker" else metal_mat,
                scale=(1.0, 0.72, 1.0),
                radius_top=height * 0.043,
            )
        box(
            f"boot_wrap_{side}",
            (height * 0.105, height * 0.125, height * 0.055),
            (sign * height * 0.072, -height * 0.018, height * 0.055),
            leather_mat,
            bevel=height * 0.009,
        )

    if style in {"greek_delver", "hoplite", "peltast"}:
        cylinder(
            "helmet",
            height * 0.117,
            height * 0.095,
            (0.0, 0.0, height * 0.91),
            metal_mat,
            scale=(0.92, 0.95, 1.0),
            radius_top=height * 0.078,
        )
        box(
            "helmet_brow",
            (height * 0.205, height * 0.035, height * 0.035),
            (0.0, -height * 0.092, height * 0.875),
            metal_mat,
            bevel=height * 0.005,
        )
        box(
            "helmet_spine",
            (height * 0.022, height * 0.18, height * 0.05),
            (0.0, 0.0, height * 0.965),
            dark_metal_mat,
            bevel=height * 0.004,
        )
        if style == "greek_delver":
            box(
                "lamp_cage",
                (height * 0.068, height * 0.035, height * 0.075),
                (0.0, -height * 0.113, height * 0.925),
                dark_metal_mat,
                bevel=height * 0.004,
            )
            box(
                "lamp",
                (height * 0.038, height * 0.02, height * 0.045),
                (0.0, -height * 0.132, height * 0.925),
                accent_mat,
                bevel=height * 0.003,
            )
        else:
            crest_height = height * (0.19 if style == "hoplite" else 0.11)
            box(
                "helmet_crest",
                (height * 0.035, height * 0.18, crest_height),
                (0.0, height * 0.015, height * (1.015 if style == "hoplite" else 0.985)),
                accent_mat,
                bevel=height * 0.006,
            )
    elif style == "stalker":
        cylinder(
            "hood",
            height * 0.145,
            height * 0.255,
            (0.0, height * 0.005, height * 0.895),
            cloth_mat,
            scale=(0.94, 0.83, 1.0),
            radius_top=height * 0.075,
        )
        box(
            "hood_shadow",
            (height * 0.16, height * 0.025, height * 0.09),
            (0.0, -height * 0.108, height * 0.89),
            dark_metal_mat,
            bevel=height * 0.008,
        )
        box(
            "hood_tail",
            (height * 0.15, height * 0.035, height * 0.28),
            (0.0, height * 0.10, height * 0.76),
            cloth_mat,
            rotation=(12.0, 0.0, 0.0),
            bevel=height * 0.012,
        )
    else:  # oracle
        box(
            "funerary_mask",
            (height * 0.17, height * 0.07, height * 0.23),
            (0.0, -height * 0.075, height * 0.91),
            metal_mat,
            bevel=height * 0.012,
        )
        cylinder(
            "oracle_crown",
            height * 0.105,
            height * 0.22,
            (0.0, 0.0, height * 1.045),
            metal_mat,
            scale=(0.92, 0.88, 1.0),
            radius_top=height * 0.082,
        )
        for side, sign in (("l", 1.0), ("r", -1.0)):
            box(
                f"oracle_veil_{side}",
                (height * 0.075, height * 0.025, height * 0.42),
                (sign * height * 0.105, height * 0.035, height * 0.73),
                cloth_mat,
                rotation=(4.0, 0.0, sign * 5.0),
                bevel=height * 0.007,
            )
        box(
            "oracle_glow",
            (height * 0.105, height * 0.018, height * 0.025),
            (0.0, -height * 0.118, height * 0.93),
            accent_mat,
            bevel=height * 0.003,
        )

    merged = scene_lib.join([body, *parts], body.name)
    scene_lib.set_origin(merged, "bottom")
    scene_lib.apply_transforms(merged)
    mesh_lib.shade_auto_smooth(merged, 52.0)
    result = finish_lib.report(ctx, merged)
    result["style"] = style
    result["height_m"] = round(height, 4)
    result["armour_parts"] = len(parts)
    ctx.note(
        f"'{merged.name}' now carries the {style} outfit. Run char.rig next; the "
        "joined disconnected shells let the deterministic skinner assign helmet, "
        "bracers and greaves to their nearest bones."
    )
    finish_lib.budget_note(ctx, merged, 8000)
    return result


def bmesh_transform(bm, matrix):
    import bmesh as bmesh_module

    bmesh_module.ops.transform(bm, matrix=matrix, verts=bm.verts[:])


def _absorb(target_bm, source_bm):
    temp = bpy.data.meshes.new("_absorb")
    source_bm.to_mesh(temp)
    source_bm.free()
    target_bm.from_mesh(temp)
    bpy.data.meshes.remove(temp)


@op(
    "char.rig",
    summary="Build a humanoid armature fitted to a mesh and skin it with distance-falloff weights. Single 'hips' root, snake_case bone names, glTF/Godot-compatible. No GUI needed.",
    params={
        "name": ("str", None, "Mesh object to rig"),
        "height": ("num", 0.0, "Character height; 0 measures it from the mesh bounds"),
        "build": ("enum:realistic|heroic|stylized|chibi|lithe", "heroic", "Proportions the rig assumes — match char.humanoid"),
        "falloff": ("num", 1.6, "Weight blend sharpness; higher is more rigid"),
        "armature_name": ("str", "", "Armature object name (defaults to <mesh>_rig)"),
    },
    tags=["char", "rig"],
)
def char_rig(ctx, name, height, build, falloff, armature_name):
    obj = _get(name)
    if obj.type != "MESH":
        raise OpError(f"'{name}' is a {obj.type}, not a mesh — rig the body mesh")

    bounds = mesh_lib.bounds(obj)
    measured = bounds["size"][2] or 1.8
    total_height = height if height > 0 else measured
    joints, _spec, _head_unit = _skeleton(total_height, build)

    rig_name = scene_lib.unique_name(armature_name or f"{obj.name}_rig")
    armature_data = bpy.data.armatures.new(rig_name)
    rig = bpy.data.objects.new(rig_name, armature_data)
    bpy.context.scene.collection.objects.link(rig)
    rig.location = obj.location

    # Edit-bone creation needs the armature in edit mode; this is the one place
    # a mode switch is unavoidable, and it works headless because it needs only
    # a view layer, not a window.
    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        created = {}
        for bone_name, (head, tail) in joints.items():
            bone = armature_data.edit_bones.new(bone_name)
            bone.head = Vector(head)
            bone.tail = Vector(tail)
            bone.use_deform = True
            created[bone_name] = bone
        for child, parent in PARENTS.items():
            if child in created and parent in created:
                created[child].parent = created[parent]
                created[child].use_connect = False
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    view_layer.objects.active = previous_active

    # The bones were just written in ARMATURE-LOCAL space and the armature sits
    # at the mesh's location, so the depsgraph has to catch up before _skin can
    # read matrix_world off it.
    scene_lib.sync()
    weights = _skin(obj, joints, falloff, rig)

    modifier = obj.modifiers.new("armature", "ARMATURE")
    modifier.object = rig
    modifier.use_vertex_groups = True
    obj.parent = rig
    obj.matrix_parent_inverse = rig.matrix_world.inverted()

    roots = [b for b in armature_data.bones if b.parent is None]
    return {
        "armature": rig.name,
        "mesh": obj.name,
        "bones": sorted(b.name for b in armature_data.bones),
        "bone_count": len(armature_data.bones),
        "root_bones": [b.name for b in roots],
        "vertex_groups": len(obj.vertex_groups),
        "weighted_vertices": weights,
        "height_m": round(total_height, 4),
    }


# Bone pairs that may share a vertex: a bone and its direct parent. Built from
# PARENTS so it stays correct if the skeleton ever gains bones.
_RELATED = frozenset(
    pair
    for child, parent in PARENTS.items()
    for pair in ((child, parent), (parent, child))
)


def _distance_to_segment(point, head, tail):
    axis = tail - head
    length_sq = axis.length_squared
    if length_sq < 1e-9:
        return (point - head).length
    t = max(0.0, min(1.0, (point - head).dot(axis) / length_sq))
    return (point - (head + axis * t)).length


def _components(mesh):
    """Vertex -> shell id, by union-find over the edges."""
    parent = list(range(len(mesh.vertices)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for edge in mesh.edges:
        a, b = (find(v) for v in edge.vertices)
        if a != b:
            parent[a] = b
    return [find(i) for i in range(len(mesh.vertices))]


def _skin(obj, joints, falloff, rig=None):
    """Distance-to-bone-segment weighting, normalised over the best 2 bones.

    Blender's automatic weights are a bone-heat solve that needs an operator
    context and a watertight mesh. For a blockout this simpler solve is more
    predictable and never fails with "Bone Heat Weighting: failed to find
    solution", which is the error every automated rigging attempt eventually
    hits.

    Distance alone is not enough, though. A humanoid rests with its arms at its
    sides, which runs the arm bones about 3cm from the flank of the torso while
    the spine is 19cm away — so by distance the arm owns the waist, and the
    first time the character reaches forward it drags a bat-wing of torso with
    it. The mesh knows better than the distances do: the arm is a separate
    shell from the body, so a bone is confined to the shell it lives in.
    """
    for group in list(obj.vertex_groups):
        obj.vertex_groups.remove(group)
    groups = {n: obj.vertex_groups.new(name=n) for n in joints}
    matrix = obj.matrix_world
    # BOTH SIDES OF THIS COMPARISON MUST BE IN THE SAME SPACE.
    #
    # `joints` is in armature-local space, but the armature is placed at the
    # mesh's location, and the vertices below are taken to world space. Compare
    # the two directly and every bone is displaced by exactly the character's
    # offset from the origin — so a figure built at [0, -0.92, 0.55] gets its
    # torso weighted to its head bone and its pelvis to its shins, and the
    # first pose you apply tears the mesh into flat sheets. Characters authored
    # at the origin were unaffected, which is why this survived so long.
    rig_matrix = rig.matrix_world if rig is not None else Matrix.Identity(4)
    segments = {
        n: (rig_matrix @ Vector(a), rig_matrix @ Vector(b)) for n, (a, b) in joints.items()
    }

    mesh = obj.data
    world = [matrix @ v.co for v in mesh.vertices]
    shell = _components(mesh)

    # Which shell does each bone live in? Take the vertices that bone is nearest
    # to and let them vote on their shell.
    #
    # Not "the single closest vertex" — a resting arm interpenetrates the torso,
    # so the one vertex nearest the arm bone is quite often a torso vertex, and
    # picking it hands the entire torso to the arm. The arm cylinder outvotes
    # that handful every time.
    claims = {}
    for index, point in enumerate(world):
        nearest, owner = 1e9, None
        for bone_name, (head, tail) in segments.items():
            distance = _distance_to_segment(point, head, tail)
            if distance < nearest:
                nearest, owner = distance, bone_name
        if owner is not None:
            claims.setdefault(owner, []).append(shell[index])
    bone_shell = {}
    for bone_name in segments:
        votes = claims.get(bone_name, [])
        bone_shell[bone_name] = (
            max(set(votes), key=votes.count) if votes else None
        )

    weighted = 0
    for index, point in enumerate(world):
        here = shell[index]
        candidates = [n for n in segments if bone_shell[n] == here]
        if not candidates:
            # A decorative shell no bone claims — fall back to every bone so it
            # is carried by something rather than left behind at the origin.
            candidates = list(segments)
        distances = sorted(
            (_distance_to_segment(point, *segments[n]), n) for n in candidates
        )
        best = distances[:2]
        # Within a shell a vertex may still be shared only by a bone and its
        # direct parent — that is what makes an elbow bend smoothly. Anything
        # else takes the nearest bone outright, so the two thighs cannot stretch
        # a web across the crotch.
        if len(best) == 2 and (best[0][1], best[1][1]) not in _RELATED:
            best = best[:1]
        influences = [(n, 1.0 / (d + 1e-4) ** falloff) for d, n in best]
        total = sum(w for _n, w in influences)
        if total <= 0.0:
            continue
        for bone_name, weight in influences:
            groups[bone_name].add([index], weight / total, "REPLACE")
        weighted += 1
    return weighted


# ---------------------------------------------------------------------------
# animation
# ---------------------------------------------------------------------------

CLIPS = ["idle", "walk", "run", "attack", "jump", "death", "wave"]


def action_fcurves(action):
    """Read an action's F-curves across Blender's two action layouts.

    Blender 4.4 introduced "slotted actions": `action.fcurves` is gone and the
    curves now live at action -> layers -> strips -> channelbags -> fcurves.
    Keyframe *insertion* is unchanged, so only reading needs the shim.
    """
    if hasattr(action, "fcurves"):  # legacy actions (Blender <= 4.3)
        return list(action.fcurves)
    curves = []
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for bag in getattr(strip, "channelbags", []):
                curves.extend(bag.fcurves)
    return curves


def _pose(rig, bone_name, frame, rotation_deg=None, location=None):
    bone = rig.pose.bones.get(bone_name)
    if bone is None:
        return
    bone.rotation_mode = "XYZ"
    if rotation_deg is not None:
        bone.rotation_euler = [math.radians(a) for a in rotation_deg]
        bone.keyframe_insert(data_path="rotation_euler", frame=frame)
    if location is not None:
        bone.location = Vector(location)
        bone.keyframe_insert(data_path="location", frame=frame)


def _clip_keys(clip, length, amplitude):
    """Return {frame: {bone: (rot_deg | None, loc | None)}} for one clip.

    These are hand-authored pose sets, not procedural noise. A walk cycle needs
    contact / down / passing / up poses at the right fractions of the cycle or
    it reads as a shuffle, and no amount of sine wave gets you there.
    """
    a = amplitude
    if clip == "idle":
        return {
            1:            {"spine": (0, 0, 0), "chest": (0, 0, 0),
                           "upper_arm_l": (0, 0, -6 * a), "upper_arm_r": (0, 0, 6 * a)},
            length // 2:  {"spine": (-2.2 * a, 0, 0), "chest": (1.6 * a, 0, 0),
                           "upper_arm_l": (0, 0, -8.5 * a), "upper_arm_r": (0, 0, 8.5 * a)},
            length:       {"spine": (0, 0, 0), "chest": (0, 0, 0),
                           "upper_arm_l": (0, 0, -6 * a), "upper_arm_r": (0, 0, 6 * a)},
        }
    if clip in ("walk", "run"):
        swing = (26 if clip == "walk" else 44) * a
        knee = (30 if clip == "walk" else 58) * a
        arm = (22 if clip == "walk" else 40) * a
        lift = 0.0 if clip == "walk" else 0.035 * a
        quarter = max(1, length // 4)
        return {
            1: {
                "thigh_l": (swing, 0, 0), "thigh_r": (-swing, 0, 0),
                "shin_l": (-knee * 0.25, 0, 0), "shin_r": (knee * 0.5, 0, 0),
                "upper_arm_l": (-arm, 0, -6), "upper_arm_r": (arm, 0, 6),
                "hips": None,
            },
            quarter: {
                "thigh_l": (0, 0, 0), "thigh_r": (0, 0, 0),
                "shin_l": (-knee * 0.6, 0, 0), "shin_r": (-knee * 0.1, 0, 0),
                "upper_arm_l": (0, 0, -6), "upper_arm_r": (0, 0, 6),
            },
            quarter * 2: {
                "thigh_l": (-swing, 0, 0), "thigh_r": (swing, 0, 0),
                "shin_l": (knee * 0.5, 0, 0), "shin_r": (-knee * 0.25, 0, 0),
                "upper_arm_l": (arm, 0, -6), "upper_arm_r": (-arm, 0, 6),
            },
            quarter * 3: {
                "thigh_l": (0, 0, 0), "thigh_r": (0, 0, 0),
                "shin_l": (-knee * 0.1, 0, 0), "shin_r": (-knee * 0.6, 0, 0),
                "upper_arm_l": (0, 0, -6), "upper_arm_r": (0, 0, 6),
            },
            length: {
                "thigh_l": (swing, 0, 0), "thigh_r": (-swing, 0, 0),
                "shin_l": (-knee * 0.25, 0, 0), "shin_r": (knee * 0.5, 0, 0),
                "upper_arm_l": (-arm, 0, -6), "upper_arm_r": (arm, 0, 6),
            },
        }, lift
    if clip == "attack":
        return {
            1:            {"upper_arm_r": (10, 0, 8), "chest": (0, 0, -8 * a),
                           "forearm_r": (-20, 0, 0)},
            max(2, int(length * 0.35)): {"upper_arm_r": (-95 * a, 0, 20), "chest": (0, 0, -26 * a),
                                         "forearm_r": (-58 * a, 0, 0)},
            max(3, int(length * 0.55)): {"upper_arm_r": (58 * a, 0, -6), "chest": (0, 0, 24 * a),
                                         "forearm_r": (-4, 0, 0)},
            length:       {"upper_arm_r": (10, 0, 8), "chest": (0, 0, -8 * a),
                           "forearm_r": (-20, 0, 0)},
        }
    if clip == "jump":
        return {
            1:                          {"thigh_l": (34 * a, 0, 0), "thigh_r": (34 * a, 0, 0),
                                         "shin_l": (-62 * a, 0, 0), "shin_r": (-62 * a, 0, 0),
                                         "spine": (14 * a, 0, 0)},
            max(2, int(length * 0.4)):  {"thigh_l": (-12 * a, 0, 0), "thigh_r": (-12 * a, 0, 0),
                                         "shin_l": (6 * a, 0, 0), "shin_r": (6 * a, 0, 0),
                                         "spine": (-6 * a, 0, 0),
                                         "upper_arm_l": (-110 * a, 0, -6),
                                         "upper_arm_r": (-110 * a, 0, 6)},
            length:                     {"thigh_l": (28 * a, 0, 0), "thigh_r": (28 * a, 0, 0),
                                         "shin_l": (-48 * a, 0, 0), "shin_r": (-48 * a, 0, 0),
                                         "spine": (10 * a, 0, 0)},
        }
    if clip == "death":
        return {
            1:                          {"spine": (0, 0, 0), "chest": (0, 0, 0)},
            max(2, int(length * 0.3)):  {"spine": (-22 * a, 0, 0), "chest": (-16 * a, 0, 0),
                                         "head": (18 * a, 0, 0)},
            length:                     {"spine": (-78 * a, 0, 0), "chest": (-38 * a, 0, 0),
                                         "head": (30 * a, 0, 0),
                                         "thigh_l": (48 * a, 0, 0), "thigh_r": (40 * a, 0, 0),
                                         "shin_l": (-70 * a, 0, 0), "shin_r": (-62 * a, 0, 0)},
        }
    # wave
    return {
        1:                          {"upper_arm_r": (-140 * a, 0, 12), "forearm_r": (-20, 0, 0)},
        max(2, int(length * 0.33)): {"upper_arm_r": (-150 * a, 0, 12), "forearm_r": (-46 * a, 0, 28 * a)},
        max(3, int(length * 0.66)): {"upper_arm_r": (-150 * a, 0, 12), "forearm_r": (-46 * a, 0, -22 * a)},
        length:                     {"upper_arm_r": (-140 * a, 0, 12), "forearm_r": (-20, 0, 0)},
    }


@op(
    "char.animate",
    summary="Author a keyframed animation clip on a rig: idle, walk, run, attack, jump, death or wave. Real pose-to-pose keys at contact/passing frames, not sine-wave wiggle — the difference between a walk and a shuffle.",
    params={
        "rig": ("str", None, "Armature object name (from char.rig)"),
        "clip": (f"enum:{'|'.join(CLIPS)}", "idle", "Which clip to author"),
        "length": ("int", 24, "Clip length in frames (24 frames at 30 fps = 0.8 s)"),
        "amplitude": ("num", 1.0, "Motion scale — 0.6 is subtle, 1.4 is exaggerated"),
        "loop": ("bool", True, "Match the last frame to the first so the clip cycles"),
        "action_name": ("str", "", "Action name (defaults to the clip name)"),
    },
    tags=["char", "anim"],
)
def char_animate(ctx, rig, clip, length, amplitude, loop, action_name):
    obj = _get(rig)
    if obj.type != "ARMATURE":
        raise OpError(
            f"'{rig}' is a {obj.type}, not an armature. Pass the rig object returned by "
            "char.rig (usually '<mesh>_rig')."
        )
    length = max(2, length)
    name = scene_lib.sanitize(action_name or clip)

    if obj.animation_data is None:
        obj.animation_data_create()
    action = bpy.data.actions.new(name)
    obj.animation_data.action = action

    for bone in obj.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)

    keys = _clip_keys(clip, length, amplitude)
    hip_lift = 0.0
    if isinstance(keys, tuple):
        keys, hip_lift = keys

    for frame, poses in keys.items():
        for bone_name, rotation in poses.items():
            if rotation is None:
                continue
            _pose(obj, bone_name, frame, rotation_deg=rotation)
    if hip_lift:
        for frame, height in (
            (1, 0.0), (max(2, length // 4), hip_lift), (max(3, length // 2), 0.0),
            (max(4, length * 3 // 4), hip_lift), (length, 0.0),
        ):
            _pose(obj, "hips", frame, location=(0.0, 0.0, height))

    curves = action_fcurves(action)
    if loop:
        for curve in curves:
            if len(curve.keyframe_points) >= 2:
                first = curve.keyframe_points[0].co[1]
                curve.keyframe_points[-1].co[1] = first
                curve.keyframe_points[-1].handle_left[1] = first
                curve.keyframe_points[-1].handle_right[1] = first
            curve.update()
        if hasattr(action, "use_cyclic"):
            action.use_cyclic = True

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = max(scene.frame_end, length)

    # Stash the action so a later clip does not evict it — glTF exports every
    # action it can reach, and an action with zero users gets garbage collected.
    action.use_fake_user = True

    return {
        "rig": obj.name,
        "action": action.name,
        "clip": clip,
        "frames": length,
        "fcurves": len(curves),
        "keyframes": sum(len(c.keyframe_points) for c in curves),
        "loops": loop,
        "all_actions": [a.name for a in bpy.data.actions],
    }


@op(
    "char.pose",
    summary="Set a static pose on a rig — T-pose, A-pose, sitting, or a custom per-bone rotation. Useful for reference renders and for fixing an import rest pose.",
    params={
        "rig": ("str", None, "Armature object name"),
        "preset": ("enum:rest|a_pose|t_pose|sit|crouch|custom", "a_pose", "Pose preset"),
        "bones": ("obj", None, "custom only: {\"bone_name\": [rx, ry, rz], ...} in degrees"),
    },
    tags=["char", "rig"],
)
def char_pose(ctx, rig, preset, bones):
    obj = _get(rig)
    if obj.type != "ARMATURE":
        raise OpError(f"'{rig}' is a {obj.type}, not an armature")

    presets = {
        "rest": {},
        "t_pose": {"upper_arm_l": (0, 0, -90), "upper_arm_r": (0, 0, 90)},
        "a_pose": {"upper_arm_l": (0, 0, -50), "upper_arm_r": (0, 0, 50)},
        "sit": {"thigh_l": (-88, 0, 0), "thigh_r": (-88, 0, 0),
                "shin_l": (85, 0, 0), "shin_r": (85, 0, 0), "spine": (6, 0, 0)},
        "crouch": {"thigh_l": (-62, 0, 0), "thigh_r": (-62, 0, 0),
                   "shin_l": (78, 0, 0), "shin_r": (78, 0, 0), "spine": (22, 0, 0),
                   "chest": (-8, 0, 0)},
    }
    if preset == "custom":
        if not bones:
            raise OpError("preset='custom' needs a `bones` object like {\"head\": [0,0,25]}")
        rotations = {k: tuple(v) for k, v in bones.items()}
    else:
        rotations = presets[preset]

    for bone in obj.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
    applied = []
    for bone_name, rotation in rotations.items():
        bone = obj.pose.bones.get(bone_name)
        if bone is None:
            raise OpError(
                f"no bone '{bone_name}' on '{rig}'. Bones: "
                f"{sorted(b.name for b in obj.pose.bones)}"
            )
        bone.rotation_euler = [math.radians(a) for a in rotation]
        applied.append(bone_name)
    return {"rig": obj.name, "preset": preset, "posed_bones": applied}


@op(
    "char.attach",
    summary="Parent a prop to a character bone — a sword to hand_r, a shield to hand_l, a helmet to head. Keeps the prop's own pivot, so it animates with the character.",
    params={
        "prop": ("str", None, "Object to attach"),
        "rig": ("str", None, "Armature object name"),
        "bone": ("str", "hand_r", "Bone to attach to"),
        "offset": ("vec3", [0.0, 0.0, 0.0], "Local offset in metres"),
        "rotation": ("vec3", [0.0, 0.0, 0.0], "Local rotation in degrees"),
        "keep_transform": ("bool", False, "Keep the prop exactly where it already is, ignoring offset/rotation"),
    },
    tags=["char", "rig"],
)
def char_attach(ctx, prop, rig, bone, offset, rotation, keep_transform):
    item = _get(prop)
    armature = _get(rig)
    if armature.type != "ARMATURE":
        raise OpError(f"'{rig}' is a {armature.type}, not an armature")
    target = armature.data.bones.get(bone)
    if target is None:
        raise OpError(
            f"no bone '{bone}' on '{rig}'. Bones: {sorted(b.name for b in armature.data.bones)}"
        )
    # KEEP_TRANSFORM IS FOR KIT THAT IS ALREADY IN THE RIGHT PLACE.
    #
    # Bone parenting anchors at the bone TAIL, so attaching normally THROWS AWAY
    # wherever the prop was authored and snaps it to the joint. That is right
    # for a sword you are placing into a fist, and exactly wrong for a shield, a
    # greave or an arm-guard band that was already modelled against the body —
    # re-deriving each of those as a bone-relative offset is a dozen blind
    # tuning cycles for no gain.
    #
    # With keep_transform the prop does not move at all; it simply starts
    # following the bone from where it stands.
    world = item.matrix_world.copy()
    item.parent = armature
    item.parent_type = "BONE"
    item.parent_bone = bone
    if keep_transform:
        # Assigning matrix_world after parenting makes Blender solve for the
        # local basis, bone parent and all.
        scene_lib.sync()
        item.matrix_world = world
    else:
        item.matrix_parent_inverse = Matrix.Identity(4)
        item.location = Vector(offset)
        item.rotation_euler = [math.radians(a) for a in rotation]
    return {
        "prop": item.name,
        "rig": armature.name,
        "bone": bone,
        "note": (
            "Bone parenting anchors the prop at the bone TAIL and aligns the bone's axis to "
            "local +Y, so a prop modelled pointing up (+Z) ends up pointing along the arm. "
            "For a sword held blade-up in hand_r try rotation=[-90, 0, 0] and a small "
            "negative Y offset; render.contact_sheet is the fastest way to check it."
        ),
    }


@op(
    "char.bake_pose",
    summary=(
        "Freeze a posed rig into the mesh vertices and drop the skin. Turns a "
        "char.rig + char.pose result into a plain static mesh that keeps the pose "
        "through export — for background figures, props and NPCs that never animate."
    ),
    params={
        "mesh": ("str", None, "Skinned mesh object to freeze"),
        "rig": ("str", None, "Armature to delete afterwards (default: the one deforming this mesh; pass \"\" to keep it)"),
        "keep_groups": ("bool", False, "Keep the vertex groups after baking"),
    },
    tags=["char", "rig"],
)
def char_bake_pose(ctx, mesh, rig, keep_groups):
    """Bake the armature deformation down into the mesh.

    `char.pose` only moves POSE BONES. The mesh follows in the viewport because
    of its armature modifier, but the vertices themselves never move — so a mesh
    exported without its armature comes out in the rest pose, standing to
    attention, and a mesh exported WITH its armature drags a Skeleton3D into the
    scene for a figure that was never going to animate.

    This is the third option: evaluate the deformation, write it into the
    vertices, delete the rig. What you posed is what ships.
    """
    obj = _get(mesh)
    if obj.type != "MESH":
        raise OpError(f"'{mesh}' is a {obj.type}, not a mesh")
    modifier = next((m for m in obj.modifiers if m.type == "ARMATURE"), None)
    if modifier is None:
        raise OpError(
            f"'{mesh}' has no armature modifier, so there is no pose to bake. "
            "Call char.rig on it first, then char.pose the rig."
        )

    armature = modifier.object
    if rig is None:
        target = armature
    elif rig == "":
        target = None
    else:
        target = _get(rig)

    # The pose is written straight to the data API, so the depsgraph has not
    # necessarily seen it yet. Without this the bake silently freezes the REST
    # pose and everything looks fine until you open the export.
    scene_lib.sync()
    before = _bounds(obj)
    scene_lib.apply_modifiers(obj)
    after = _bounds(obj)

    if not keep_groups:
        obj.vertex_groups.clear()
    removed = None
    if target is not None:
        removed = target.name
        scene_lib.delete(target)

    moved = max(abs(a - b) for a, b in zip(before, after, strict=False))
    return {
        "mesh": obj.name,
        "rig_removed": removed,
        "vertex_groups_kept": bool(keep_groups),
        "bounds_before": [round(v, 4) for v in before],
        "bounds_after": [round(v, 4) for v in after],
        "moved": round(moved, 4),
        "note": (
            "moved is the largest change in the bounding box, in metres. If it is "
            "0 the rig was still in its rest pose when you baked — char.pose it first."
        ),
    }


def _bounds(obj):
    """Local-space min/max of the mesh itself, not the evaluated object."""
    verts = obj.data.vertices
    if not verts:
        return (0.0,) * 6
    xs = [v.co.x for v in verts]
    ys = [v.co.y for v in verts]
    zs = [v.co.z for v in verts]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _get(name):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
