"""Deterministic non-humanoid creature bases for production game assets.

These are deliberately anatomy-first rather than collections of decorative
primitives.  Their silhouettes must survive an RTS camera, while the joined
multi-material mesh remains suitable for ``rig.skeleton`` + ``rig.skin`` when
animation is needed.
"""

from __future__ import annotations

import math

import bpy
from lib import finish as finish_lib
from lib import mat as mat_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from mathutils import Matrix, Vector
from registry import op


def _transform_primitive(target, create, matrix=None):
    piece = mesh_lib.new_bmesh()
    create(piece)
    if matrix is not None:
        import bmesh

        bmesh.ops.transform(piece, matrix=matrix, verts=piece.verts[:])
    temp = bpy.data.meshes.new("_creature_piece")
    piece.to_mesh(temp)
    piece.free()
    target.from_mesh(temp)
    bpy.data.meshes.remove(temp)


def _finish_material_mesh(ctx, bm, name, material, location):
    mesh_lib.cleanup(bm, merge_dist=0.0005)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    finish_lib.finish(
        ctx,
        obj,
        material=material,
        uv="smart_packed",
        origin=None,
        smooth=True,
        smooth_angle=48.0,
    )
    return obj


def _ellipsoid(bm, center, radius, scale, subdivisions=2):
    _transform_primitive(
        bm,
        lambda piece: mesh_lib.add_icosphere(
            piece, radius=radius, subdivisions=subdivisions
        ),
        Matrix.Translation(Vector(center))
        @ Matrix.Diagonal(Vector((*scale, 1.0))),
    )


def _segment(bm, start, end, radius, radius_top, sides):
    a = Vector(start)
    b = Vector(end)
    axis = b - a
    if axis.length < 1e-5:
        return
    matrix = (
        Matrix.Translation(a)
        @ axis.normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()
    )
    _transform_primitive(
        bm,
        lambda piece: mesh_lib.add_cylinder(
            piece,
            radius=radius,
            radius_top=radius_top,
            depth=axis.length,
            segments=sides,
            center=(0.0, 0.0, axis.length * 0.5),
        ),
        matrix,
    )


def _box(bm, center, size, rotation=(0.0, 0.0, 0.0), bevel=0.0):
    rx, ry, rz = (math.radians(value) for value in rotation)
    matrix = (
        Matrix.Translation(Vector(center))
        @ Matrix.Rotation(rz, 4, "Z")
        @ Matrix.Rotation(ry, 4, "Y")
        @ Matrix.Rotation(rx, 4, "X")
    )
    _transform_primitive(
        bm,
        lambda piece: mesh_lib.add_box(
            piece, size=size, bevel=bevel, segments=1
        ),
        matrix,
    )


def _torus(bm, center, major, minor, scale, rotation=(0.0, 0.0, 0.0), detail=10):
    rx, ry, rz = (math.radians(value) for value in rotation)
    matrix = (
        Matrix.Translation(Vector(center))
        @ Matrix.Rotation(rz, 4, "Z")
        @ Matrix.Rotation(ry, 4, "Y")
        @ Matrix.Rotation(rx, 4, "X")
        @ Matrix.Diagonal(Vector((*scale, 1.0)))
    )
    _transform_primitive(
        bm,
        lambda piece: mesh_lib.add_torus(
            piece,
            major=major,
            minor=minor,
            major_segments=max(12, detail * 2),
            minor_segments=5,
        ),
        matrix,
    )


@op(
    "creature.hound",
    summary=(
        "Build a gaunt game-ready war hound with readable canine anatomy, bent "
        "legs, muzzle, ears, segmented tail and a separate bronze collar. The "
        "joined mesh can be exported static or bound to a custom quadruped rig."
    ),
    params={
        "name": ("str", "war_hound", "Object name"),
        "length": ("num", 1.75, "Nose-to-rump length in metres"),
        "shoulder_height": ("num", 1.0, "Ground-to-shoulder height"),
        "bulk": ("num", 1.0, "Torso and limb thickness multiplier"),
        "detail": ("int", 8, "Radial segment count, 6-12"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "hide": ("str", "#25231f", "Dark hide colour"),
        "leather": ("str", "#3b241c", "Collar leather colour"),
        "metal": ("str", "#6f4d2b", "Collar and spike metal colour"),
        "eyes": ("str", "#9b5428", "Eye colour"),
    },
    tags=["creature", "quadruped", "game"],
)
def creature_hound(
    ctx, name, length, shoulder_height, bulk, detail, location,
    hide, leather, metal, eyes,
):
    sides = max(6, min(12, detail))
    unit = length
    hide_bm = mesh_lib.new_bmesh()
    leather_bm = mesh_lib.new_bmesh()
    metal_bm = mesh_lib.new_bmesh()
    eye_bm = mesh_lib.new_bmesh()

    chest = (0.0, -unit * 0.12, shoulder_height * 0.72)
    rump = (0.0, unit * 0.23, shoulder_height * 0.66)
    _ellipsoid(
        hide_bm, chest, unit * 0.245 * bulk, (0.9, 1.0, 1.15)
    )
    _ellipsoid(
        hide_bm, rump, unit * 0.25 * bulk, (1.02, 1.08, 0.96)
    )
    _segment(
        hide_bm,
        (0.0, -unit * 0.27, shoulder_height * 0.75),
        (0.0, -unit * 0.47, shoulder_height * 0.94),
        unit * 0.14 * bulk,
        unit * 0.115 * bulk,
        sides,
    )
    _ellipsoid(
        hide_bm,
        (0.0, -unit * 0.55, shoulder_height * 1.02),
        unit * 0.16 * bulk,
        (0.78, 1.1, 0.8),
    )
    _ellipsoid(
        hide_bm,
        (0.0, -unit * 0.72, shoulder_height * 0.96),
        unit * 0.11 * bulk,
        (0.72, 1.35, 0.58),
        subdivisions=1,
    )
    _box(
        hide_bm,
        (0.0, -unit * 0.69, shoulder_height * 0.87),
        (unit * 0.15, unit * 0.23, unit * 0.065),
        rotation=(4.0, 0.0, 0.0),
        bevel=unit * 0.018,
    )

    # Tall triangular ears and brow give the predatory silhouette without an
    # oversized cartoon head.
    for sign in (-1.0, 1.0):
        _segment(
            hide_bm,
            (
                sign * unit * 0.085,
                -unit * 0.56,
                shoulder_height * 1.10,
            ),
            (
                sign * unit * 0.115,
                -unit * 0.54,
                shoulder_height * 1.32,
            ),
            unit * 0.06,
            0.0,
            sides,
        )
        _ellipsoid(
            eye_bm,
            (
                sign * unit * 0.062,
                -unit * 0.685,
                shoulder_height * 1.05,
            ),
            unit * 0.018,
            (1.0, 0.45, 0.72),
            subdivisions=1,
        )

    # Canine legs bend at a visible hock instead of reading as four table legs.
    leg_specs = (
        (-unit * 0.27, -unit * 0.18, -unit * 0.30, "front"),
        (unit * 0.27, -unit * 0.18, -unit * 0.30, "front"),
        (-unit * 0.29, unit * 0.28, unit * 0.35, "hind"),
        (unit * 0.29, unit * 0.28, unit * 0.35, "hind"),
    )
    for x, y, hock_y, kind in leg_specs:
        hip_z = shoulder_height * (0.78 if kind == "front" else 0.68)
        knee_y = y - unit * 0.055 if kind == "front" else y + unit * 0.08
        knee = (x, knee_y, shoulder_height * 0.39)
        hock = (x, hock_y, shoulder_height * 0.16)
        _segment(
            hide_bm, (x, y, hip_z), knee,
            unit * 0.052 * bulk, unit * 0.039 * bulk, sides,
        )
        _ellipsoid(
            hide_bm, knee, unit * 0.052 * bulk, (0.85, 0.85, 1.0),
            subdivisions=1,
        )
        _segment(
            hide_bm, knee, hock,
            unit * 0.038 * bulk, unit * 0.026 * bulk, sides,
        )
        paw_y = hock[1] - unit * 0.08
        _segment(
            hide_bm, hock, (x, paw_y, shoulder_height * 0.055),
            unit * 0.027 * bulk, unit * 0.021 * bulk, sides,
        )
        _ellipsoid(
            hide_bm,
            (x, paw_y - unit * 0.035, shoulder_height * 0.045),
            unit * 0.045 * bulk,
            (0.75, 1.45, 0.42),
            subdivisions=1,
        )

    tail_points = (
        (0.0, unit * 0.43, shoulder_height * 0.72),
        (0.0, unit * 0.61, shoulder_height * 0.84),
        (unit * 0.06, unit * 0.77, shoulder_height * 0.82),
        (unit * 0.12, unit * 0.90, shoulder_height * 0.70),
    )
    for index in range(len(tail_points) - 1):
        _segment(
            hide_bm,
            tail_points[index],
            tail_points[index + 1],
            unit * (0.052 - index * 0.011) * bulk,
            unit * (0.041 - index * 0.011) * bulk,
            sides,
        )

    # Separate materials survive joining and make the collar readable even
    # after sober runtime grading.
    _torus(
        leather_bm,
        (0.0, -unit * 0.43, shoulder_height * 0.90),
        unit * 0.14,
        unit * 0.026,
        (1.0, 0.78, 1.0),
        rotation=(66.0, 0.0, 0.0),
        detail=sides,
    )
    for sign in (-1.0, 0.0, 1.0):
        _segment(
            metal_bm,
            (
                sign * unit * 0.09,
                -unit * 0.49,
                shoulder_height * 1.00,
            ),
            (
                sign * unit * 0.12,
                -unit * 0.53,
                shoulder_height * 1.10,
            ),
            unit * 0.018,
            0.0,
            6,
        )

    mats = (
        mat_lib.principled("m_hound_hide", color=hide, roughness=0.92),
        mat_lib.principled("m_hound_leather", color=leather, roughness=0.86),
        mat_lib.principled(
            "m_hound_bronze", color=metal, roughness=0.48, metallic=0.72
        ),
        mat_lib.principled(
            "m_hound_eyes",
            color=eyes,
            roughness=0.28,
            emission=0.32,
            emission_color=eyes,
        ),
    )
    objects = [
        _finish_material_mesh(ctx, bm, f"{name}_{label}", material, location)
        for bm, label, material in zip(
            (hide_bm, leather_bm, metal_bm, eye_bm),
            ("hide", "leather", "bronze", "eyes"),
            mats,
            strict=True,
        )
    ]
    merged = scene_lib.join(objects, scene_lib.unique_name(name))
    scene_lib.set_origin(merged, "bottom")
    scene_lib.apply_transforms(merged)
    mesh_lib.shade_auto_smooth(merged, 52.0)
    result = finish_lib.report(ctx, merged)
    result["creature"] = "hound"
    result["length_m"] = length
    result["shoulder_height_m"] = shoulder_height
    ctx.note(
        f"'{merged.name}' is a joined four-material hound base. Export it static, "
        "or add a custom quadruped rig with rig.skeleton + rig.skin."
    )
    finish_lib.budget_note(ctx, merged, 5000)
    return result


@op(
    "creature.scarab",
    summary=(
        "Build a low, wide carrion scarab with layered segmented shell plates, "
        "six bent legs, hooked forelimbs and mandibles. The joined multi-material "
        "mesh is readable from an isometric camera and ready for a custom rig."
    ),
    params={
        "name": ("str", "carrion_scarab", "Object name"),
        "length": ("num", 1.55, "Mandible-to-abdomen length in metres"),
        "width": ("num", 0.95, "Maximum shell width"),
        "height": ("num", 0.62, "Maximum shell height"),
        "detail": ("int", 8, "Radial segment count, 6-12"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "shell": ("str", "#4e3925", "Aged shell colour"),
        "edge": ("str", "#84603a", "Raised shell-edge colour"),
        "body": ("str", "#171715", "Underside and leg colour"),
        "eyes": ("str", "#8d3f22", "Eye colour"),
    },
    tags=["creature", "arthropod", "game"],
)
def creature_scarab(
    ctx, name, length, width, height, detail, location,
    shell, edge, body, eyes,
):
    sides = max(6, min(12, detail))
    shell_bm = mesh_lib.new_bmesh()
    edge_bm = mesh_lib.new_bmesh()
    body_bm = mesh_lib.new_bmesh()
    eye_bm = mesh_lib.new_bmesh()

    _ellipsoid(body_bm, (0.0, 0.0, height * 0.42), width * 0.34, (1.0, 1.45, 0.58))
    _ellipsoid(shell_bm, (0.0, length * 0.12, height * 0.68), width * 0.46, (1.0, 1.28, 0.72))
    _ellipsoid(shell_bm, (0.0, -length * 0.26, height * 0.62), width * 0.37, (0.95, 0.82, 0.66))
    _ellipsoid(body_bm, (0.0, -length * 0.50, height * 0.42), width * 0.27, (0.9, 0.72, 0.62))

    # Three raised bands break the abdomen into unmistakable armor segments.
    for index, y in enumerate((length * 0.34, length * 0.12, -length * 0.08)):
        _torus(
            edge_bm,
            (0.0, y, height * (0.72 - index * 0.025)),
            width * (0.35 - index * 0.015),
            width * 0.022,
            (1.0, 0.68, 1.0),
            rotation=(0.0, 0.0, 0.0),
            detail=sides,
        )
    _box(
        edge_bm,
        (0.0, length * 0.13, height * 0.83),
        (width * 0.035, length * 0.62, height * 0.055),
        bevel=width * 0.009,
    )

    # Six legs, each with two strong angled segments and a hooked terminal.
    for pair, y in enumerate((-length * 0.25, 0.0, length * 0.27)):
        for sign in (-1.0, 1.0):
            hip = (sign * width * 0.31, y, height * 0.43)
            knee = (
                sign * width * (0.58 + pair * 0.04),
                y - length * (0.06 - pair * 0.01),
                height * 0.26,
            )
            foot = (
                sign * width * (0.73 + pair * 0.035),
                y - length * (0.16 - pair * 0.015),
                height * 0.055,
            )
            _segment(body_bm, hip, knee, width * 0.055, width * 0.039, sides)
            _segment(body_bm, knee, foot, width * 0.041, width * 0.022, sides)
            _segment(
                edge_bm,
                foot,
                (
                    sign * width * (0.79 + pair * 0.03),
                    foot[1] - length * 0.055,
                    height * 0.025,
                ),
                width * 0.018,
                0.0,
                6,
            )

    for sign in (-1.0, 1.0):
        _segment(
            edge_bm,
            (sign * width * 0.13, -length * 0.57, height * 0.42),
            (sign * width * 0.25, -length * 0.78, height * 0.18),
            width * 0.035,
            width * 0.012,
            sides,
        )
        _ellipsoid(
            eye_bm,
            (sign * width * 0.15, -length * 0.60, height * 0.53),
            width * 0.027,
            (1.0, 0.5, 0.8),
            subdivisions=1,
        )

    mats = (
        mat_lib.principled(
            "m_scarab_shell", color=shell, roughness=0.52, metallic=0.26
        ),
        mat_lib.principled(
            "m_scarab_edges", color=edge, roughness=0.46, metallic=0.48
        ),
        mat_lib.principled("m_scarab_body", color=body, roughness=0.9),
        mat_lib.principled(
            "m_scarab_eyes",
            color=eyes,
            roughness=0.3,
            emission=0.28,
            emission_color=eyes,
        ),
    )
    objects = [
        _finish_material_mesh(ctx, bm, f"{name}_{label}", material, location)
        for bm, label, material in zip(
            (shell_bm, edge_bm, body_bm, eye_bm),
            ("shell", "edges", "body", "eyes"),
            mats,
            strict=True,
        )
    ]
    merged = scene_lib.join(objects, scene_lib.unique_name(name))
    scene_lib.set_origin(merged, "bottom")
    scene_lib.apply_transforms(merged)
    mesh_lib.shade_auto_smooth(merged, 50.0)
    result = finish_lib.report(ctx, merged)
    result["creature"] = "scarab"
    result["length_m"] = length
    result["width_m"] = width
    result["height_m"] = height
    ctx.note(
        f"'{merged.name}' is a joined four-material scarab base. Export it "
        "static, or add a custom arthropod rig with rig.skeleton + rig.skin."
    )
    finish_lib.budget_note(ctx, merged, 5000)
    return result
