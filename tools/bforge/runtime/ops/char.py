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
from lib import uvs as uv_lib
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

CLIPS = ["idle", "walk", "run", "attack", "jump", "death", "wave",
         "trot", "gallop", "graze"]

_HUMANOID_ONLY = {"run", "attack", "jump", "death", "wave"}
_QUADRUPED_ONLY = {"trot", "gallop", "graze"}


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

    keys_source = _clip_keys
    hexapod = "mid_upper_l" in obj.data.bones
    quadruped = not hexapod and "front_upper_l" in obj.data.bones
    if hexapod:
        if clip not in ("walk", "idle"):
            raise OpError(
                f"'{clip}' has no hexapod table — hexapod clips are walk (tripod "
                "gait) and idle. The full gait vocabulary is a quadruped feature."
            )
        keys_source = _hexapod_clip_keys
    elif quadruped and clip in _HUMANOID_ONLY:
        raise OpError(
            f"'{clip}' is a humanoid clip but '{rig}' is a quadruped rig. "
            "Quadruped gaits: walk, trot, gallop, graze, idle."
        )
    if not quadruped and clip in _QUADRUPED_ONLY:
        raise OpError(
            f"'{clip}' is a quadruped gait but '{rig}' is a humanoid rig. "
            "Humanoid clips: idle, walk, run, attack, jump, death, wave."
        )
    if quadruped:
        keys_source = _quadruped_clip_keys
    keys = keys_source(clip, length, amplitude)
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

    moved = max(abs(a - b) for a, b in zip(before, after))
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


# ---------------------------------------------------------------------------
# outfit: fitted armour and clothing for humanoids
# ---------------------------------------------------------------------------
#
# The "brown blob" lesson: a bare char.humanoid with a shield slab reads as a
# mud-coloured lump no matter how good the prompt was. Two rules are built
# into everything below, so the failure is not available to make:
#
#   1. Fit is DERIVED from the same _skeleton() proportions the body was built
#      with — never absolute metre constants — so any build/height gets
#      fitting pieces.
#   2. Materials are perceptually distinct by construction (bright metallic
#      bronze vs dark matte leather vs oxblood cloth). check.materials
#      measures pairwise ΔE; these defaults pass it by a wide margin.

OUTFIT_MATERIALS = {
    # name: (hex colour, metallic, roughness) — separated in both colour AND
    # light response, because separation in only one channel still reads as mud.
    "bronze":  ("#b08850", 1.0, 0.35),
    "iron":    ("#878d93", 1.0, 0.45),
    "leather": ("#6d4a2c", 0.0, 0.78),
    "cloth":   ("#7c2222", 0.0, 0.92),
}

_PIECE_BONE = {
    "cuirass": "chest", "pteruges": "hips", "helmet": "head",
    "greave_l": "shin_l", "greave_r": "shin_r",
    "bracer_l": "forearm_l", "bracer_r": "forearm_r",
    "shield": "forearm_l", "robe": "chest", "hood": "head",
}


def _fit(name, height, build):
    """Body measurements for fitting, derived from the skeleton proportions."""
    obj = _get(name)
    if obj.type != "MESH":
        raise OpError(f"'{name}' is a {obj.type}, not a mesh — outfit the body mesh")
    if height <= 0:
        height = mesh_lib.bounds(obj)["size"][2] or 1.8
    joints, spec, head_unit = _skeleton(height, build)
    girth = spec["bulk"]
    torso_r = height * 0.078 * girth
    upper_r = height * 0.030 * girth
    thigh_r = height * 0.043 * girth
    return obj, joints, head_unit, torso_r, upper_r, thigh_r, height


def _shell_profile(points):
    """Close a lathe profile into a shell: outer up, then straight back down
    inside, so the piece has wall thickness and no open boundaries."""
    outer = points
    inner = [(max(1e-4, r - 0.008), h) for r, h in reversed(points)]
    return outer + inner


def _canonicalize_faces(bm):
    """Return a new bmesh with faces in a stable geometric order.

    bmesh.ops.spin's seam merge (and remove_doubles on some topologies) can
    leave faces in a different order run to run even when every vertex is
    bit-identical — the export then differs only in the index buffer, which is
    still a determinism break. Vertices here are already welded and unique, so
    rebuilding with faces sorted by centroid (then vertex count) makes the
    index buffer a pure function of the geometry.
    """
    if not bm.faces:
        return bm
    ordered = sorted(
        bm.faces,
        key=lambda f: (
            round(f.calc_center_median().x, 5),
            round(f.calc_center_median().y, 5),
            round(f.calc_center_median().z, 5),
            len(f.verts),
        ),
    )
    rings = [[v.index for v in f.verts] for f in ordered]
    fresh = mesh_lib.new_bmesh()
    verts = [fresh.verts.new(v.co[:]) for v in bm.verts]
    for ring in rings:
        fresh.faces.new([verts[i] for i in ring])
    bm.free()
    return fresh


def _attach_or_parent(ctx, piece_obj, body, bone):
    """Follow the rig when there is one, in place (keep_transform), else the body."""
    rig = next(
        (m.object for m in body.modifiers if m.type == "ARMATURE" and m.object), None
    )
    if rig is not None and bone in rig.data.bones:
        char_attach(ctx, piece_obj.name, rig.name, bone, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], True)
        return f"{rig.name}:{bone}"
    piece_obj.parent = body
    piece_obj.matrix_parent_inverse = body.matrix_world.inverted()
    return f"{body.name} (no rig — parented to body)"


@op(
    "char.outfit",
    summary="Fit an armour or clothing piece to a char.humanoid body: cuirass, pteruges skirt, greaves, bracers, helmet or round shield. Fit is derived from the body's own proportions, materials are perceptually distinct by construction (this is the anti 'brown blob' op), and pieces bone-parent to the rig when one exists so they animate with the character.",
    params={
        "name": ("str", None, "Body mesh (from char.humanoid)"),
        "piece": ("enum:cuirass|pteruges|greaves|bracers|helmet|shield|robe|hood", "cuirass", "What to fit. greaves and bracers come in pairs; robe is a full-length caster/priest garment, hood its matching cowl"),
        "height": ("num", 0.0, "Character height; 0 measures the mesh bounds"),
        "build": ("enum:realistic|heroic|stylized|chibi|lithe", "heroic", "Proportions the fit assumes — match the char.humanoid build"),
        "material": ("enum:bronze|iron|leather|cloth", "", "Material family (defaults per piece: bronze for cuirass/greaves/helmet/shield, leather for pteruges/bracers). The families are deliberately far apart in colour and response — keep them that way"),
        "color": ("colorref", "", "Override colour; stay clear of the other pieces' colours or check.materials will fail the set"),
        "crest": ("enum:none|longitudinal|transverse", "longitudinal", "helmet: crest ridge orientation"),
        "side": ("enum:l|r", "l", "shield: which forearm carries it"),
        "gap": ("num", 0.012, "Clearance between body and armour in metres; raise for bulky bodies"),
        "seed": ("int", 0, "Random seed (reserved; current pieces are fully deterministic)"),
    },
    tags=["char"],
)
def char_outfit(ctx, name, piece, height, build, material, color, crest, side, gap, seed):
    body, joints, head_unit, torso_r, upper_r, thigh_r, total_height = _fit(name, height, build)
    shoulder_z = total_height - head_unit * 1.42
    hip_z = total_height * 0.50

    default_material = "leather" if piece in ("pteruges", "bracers") else (
        "cloth" if piece in ("robe", "hood") else "bronze"
    )
    family = material or default_material
    hex_color, metallic, roughness = OUTFIT_MATERIALS[family]
    mat = mat_lib.principled(
        f"m_{body.name}_{piece}", color=color or hex_color,
        roughness=roughness, metallic=metallic,
    )

    bm = mesh_lib.new_bmesh()
    bone = _PIECE_BONE.get(piece, "chest")

    if piece == "cuirass":
        z0, z1 = hip_z + total_height * 0.02, shoulder_z + head_unit * 0.02
        outer = [
            (torso_r * 0.98 + gap, z0),
            (torso_r * 1.22 + gap, z0 + (z1 - z0) * 0.55),
            (torso_r * 1.10 + gap, z1),
            (torso_r * 0.48, z1 + 0.004),
        ]
        mesh_lib.lathe(bm, _shell_profile(outer), segments=16, cap=False)

    elif piece == "pteruges":
        straps = max(10, int(2.0 * math.pi * torso_r / (total_height * 0.02 * 1.3)))
        length = total_height * 0.14
        radius = torso_r * 0.98 + gap
        for i in range(straps):
            angle = 2.0 * math.pi * i / straps
            tilt = math.radians(8.0 if i % 2 == 0 else 14.0)
            cx, cy = radius * math.cos(angle), radius * math.sin(angle)
            piece_bm = mesh_lib.new_bmesh()
            mesh_lib.add_box(
                piece_bm,
                size=(total_height * 0.02, 0.006, length),
                center=(0.0, 0.0, -length * 0.5), bevel=0.003,
            )
            rot = (
                Matrix.Rotation(angle, 4, "Z")
                @ Matrix.Rotation(tilt, 4, "X")
            )
            bmesh_transform(piece_bm, Matrix.Translation(Vector((cx, cy, hip_z + 0.01))) @ rot)
            _absorb(bm, piece_bm)

    elif piece in ("greaves", "bracers"):
        pair = (("l", 1.0), ("r", -1.0))
        for s, sign in pair:
            if piece == "greaves":
                head, tail = joints[f"shin_{s}"]
                r0, r1 = thigh_r * 0.85 + gap, thigh_r * 0.55 + gap
                bone_name = f"shin_{s}"
            else:
                head, tail = joints[f"forearm_{s}"]
                r0, r1 = upper_r * 0.80 + gap, upper_r * 0.62 + gap
                bone_name = f"forearm_{s}"
            axis = (Vector(tail) - Vector(head))
            length = axis.length
            piece_bm = mesh_lib.new_bmesh()
            mesh_lib.lathe(
                piece_bm,
                _shell_profile([(r0, 0.0), (r1, length * 0.96)]),
                segments=12, axis=axis.normalized(), center=head, cap=False,
            )
            _absorb(bm, piece_bm)
        bone = f"{'shin' if piece == 'greaves' else 'forearm'}_l"

    elif piece == "helmet":
        head_center = Vector(joints["head"][0]).lerp(Vector(joints["head"][1]), 0.5)
        dome_r = head_unit * 0.50 + gap
        brow_z = head_center.z + head_unit * 0.06
        mesh_lib.lathe(
            bm,
            _shell_profile([
                (dome_r, 0.0),
                (dome_r * 1.01, dome_r * 0.55),
                (dome_r * 0.55, dome_r * 0.95),
                (0.012, dome_r * 1.02),
            ]),
            segments=16, center=(0.0, 0.0, brow_z), cap=False,
        )
        # Cheek guards and nose guard — the shapes that say 'helmet', not 'bowl'.
        for sign in (1.0, -1.0):
            piece_bm = mesh_lib.new_bmesh()
            mesh_lib.add_wedge(
                piece_bm,
                size=(dome_r * 0.34, dome_r * 0.42, head_unit * 0.34),
                center=(sign * dome_r * 0.72, -dome_r * 0.30, brow_z - head_unit * 0.16),
            )
            bmesh_transform(piece_bm, Matrix.Rotation(math.radians(sign * 8.0), 4, "Z"))
            _absorb(bm, piece_bm)
        piece_bm = mesh_lib.new_bmesh()
        mesh_lib.add_box(
            piece_bm,
            size=(dome_r * 0.12, dome_r * 0.10, head_unit * 0.30),
            center=(0.0, -dome_r * 0.90, brow_z - head_unit * 0.10),
        )
        _absorb(bm, piece_bm)
        if crest != "none":
            ridge = mesh_lib.new_bmesh()
            along_y = crest == "longitudinal"
            mesh_lib.add_box(
                ridge,
                size=(
                    dome_r * (0.16 if along_y else 1.5),
                    dome_r * (1.5 if along_y else 0.16),
                    dome_r * 0.42,
                ),
                center=(0.0, 0.0, brow_z + dome_r * 1.05), bevel=0.004,
            )
            _absorb(bm, ridge)

    elif piece == "shield":
        fore_head, fore_tail = joints[f"forearm_{side}"]
        sign = 1.0 if side == "l" else -1.0
        radius = total_height * 0.24
        depth = 0.025
        center = Vector(fore_head).lerp(Vector(fore_tail), 0.5)
        center.x += sign * (upper_r + radius * 0.35)
        center.y -= 0.01
        disc = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(disc, radius=radius, depth=depth, segments=20, bevel=0.004)
        bmesh_transform(
            disc, Matrix.Translation(center) @ Matrix.Rotation(math.radians(90.0), 4, "Y")
        )
        _absorb(bm, disc)
        rim = mesh_lib.new_bmesh()
        mesh_lib.add_torus(rim, major=radius * 0.97, minor=radius * 0.045,
                           major_segments=20, minor_segments=6)
        bmesh_transform(
            rim, Matrix.Translation(center) @ Matrix.Rotation(math.radians(90.0), 4, "Y")
        )
        _absorb(bm, rim)
        boss = mesh_lib.new_bmesh()
        mesh_lib.add_icosphere(boss, radius=radius * 0.16, subdivisions=2)
        bmesh_transform(
            boss,
            Matrix.Translation(center + Vector((sign * depth * 1.2, 0.0, 0.0)))
            @ Matrix.Diagonal(Vector((0.5, 1.0, 1.0))).to_4x4(),
        )
        _absorb(bm, boss)
        bone = f"forearm_{side}"

    elif piece == "robe":
        # Full-length garment: shoulders to ankles, flaring at the hem, with
        # loose sleeves suggested by a wider torso band. Lathe shell like the
        # cuirass but floor-length and cloth.
        z_top = shoulder_z + head_unit * 0.02
        z_hem = hip_z - (hip_z - 0.06 * total_height) * 0.94
        outer = [
            (torso_r * 1.12 + gap, z_top),
            (torso_r * 1.20 + gap, hip_z),
            (torso_r * 1.55 + gap, z_hem + (z_top - z_hem) * 0.35),
            (torso_r * 1.85 + gap, z_hem),
        ]
        mesh_lib.lathe(bm, _shell_profile(outer), segments=16, cap=False)
        bone = "chest"

    elif piece == "hood":
        head_center = Vector(joints["head"][0]).lerp(Vector(joints["head"][1]), 0.5)
        hood_r = head_unit * 0.56 + gap
        # Open-front cowl: lathe from brow over the crown to the shoulders,
        # face left visible (the front quarter is cut away by the profile's
        # open hem sitting forward).
        mesh_lib.lathe(
            bm,
            _shell_profile([
                (hood_r, 0.0),
                (hood_r * 1.02, hood_r * 0.6),
                (hood_r * 0.6, hood_r * 1.0),
                (0.012, hood_r * 1.08),
            ]),
            segments=16, center=(0.0, head_r * 0.1, head_center.z + head_unit * 0.02),
            cap=False,
        )
        # Shoulder drape.
        piece_bm = mesh_lib.new_bmesh()
        mesh_lib.lathe(
            piece_bm,
            _shell_profile([
                (torso_r * 0.95 + gap, 0.0),
                (torso_r * 1.05 + gap, head_unit * 0.16),
            ]),
            segments=14, center=(0.0, 0.0, shoulder_z - head_unit * 0.05), cap=False,
        )
        _absorb(bm, piece_bm)
        bone = "head"

    mesh_lib.cleanup(bm, merge_dist=total_height * 0.001)
    bm = _canonicalize_faces(bm)
    piece_obj = mesh_lib.to_object(bm, scene_lib.unique_name(f"{body.name}_{piece}"))
    result = finish_lib.finish(
        ctx, piece_obj, material=mat, uv="smart_packed", origin="world",
        smooth=True, smooth_angle=45.0,
    )
    followed = _attach_or_parent(ctx, piece_obj, body, bone)
    return {
        "piece": piece,
        "object": piece_obj.name,
        "triangles": result["triangles"],
        "material": mat.name,
        "follows": followed,
        "note": "fit another piece the same way; keep materials in different families "
                "(bronze/leather/cloth) or check.materials will fail the set at review",
    }


@op(
    "char.face",
    summary="Give a char.humanoid head a readable face — brow ridge, nose wedge, chin — so a close-up review render reads as a person, not a box. Stylised readability, not realism. Geometry is welded into the body mesh and takes the head bone when skinned.",
    params={
        "name": ("str", None, "Body mesh (from char.humanoid)"),
        "height": ("num", 0.0, "Character height; 0 measures the mesh bounds"),
        "build": ("enum:realistic|heroic|stylized|chibi|lithe", "heroic", "Proportions — match the char.humanoid build"),
    },
    tags=["char"],
)
def char_face(ctx, name, height, build):
    body, joints, head_unit, _torso_r, _upper_r, _thigh_r, _h = _fit(name, height, build)
    head_center = Vector(joints["head"][0]).lerp(Vector(joints["head"][1]), 0.5)
    head_r = head_unit * 0.46

    bm = mesh_lib.obj_bmesh(body)
    before = len(bm.faces)

    brow = mesh_lib.new_bmesh()
    mesh_lib.add_box(
        brow,
        size=(head_r * 1.15, head_r * 0.28, head_r * 0.16),
        center=(0.0, -head_r * 0.80, head_center.z + head_unit * 0.14), bevel=0.004,
    )
    _absorb(bm, brow)

    nose = mesh_lib.new_bmesh()
    mesh_lib.add_wedge(
        nose,
        size=(head_r * 0.20, head_r * 0.26, head_r * 0.40),
        center=(0.0, -head_r * 0.86, head_center.z - head_unit * 0.04),
    )
    _absorb(bm, nose)

    chin = mesh_lib.new_bmesh()
    mesh_lib.add_icosphere(chin, radius=head_r * 0.28, subdivisions=1)
    bmesh_transform(
        chin,
        Matrix.Translation(Vector((0.0, -head_r * 0.62, head_center.z - head_r * 0.66)))
        @ Matrix.Diagonal(Vector((1.0, 0.75, 0.9))).to_4x4(),
    )
    _absorb(bm, chin)

    added = len(bm.faces) - before
    mesh_lib.write_bmesh(bm, body)
    mesh_lib.shade_auto_smooth(body, 50.0)
    return {
        "object": body.name,
        "faces_added": added,
        "note": "features share the body's skin material and weld to the head shell; "
                "the head bone owns them when char.rig skins the mesh",
    }


@op(
    "char.hands",
    summary="Upgrade a char.humanoid's block hands with readable fingers: four two-segment fingers with a relaxed curl plus a thumb, so a weapon grip or open hand reads at review distance. Welded into the body mesh; the hand bones own them when skinned.",
    params={
        "name": ("str", None, "Body mesh (from char.humanoid)"),
        "height": ("num", 0.0, "Character height; 0 measures the mesh bounds"),
        "build": ("enum:realistic|heroic|stylized|chibi|lithe", "heroic", "Proportions — match the char.humanoid build"),
        "curl": ("num", 0.35, "Finger curl in radians-ish (0 flat, 0.8 fist); a relaxed read is ~0.35"),
    },
    tags=["char"],
)
def char_hands(ctx, name, height, build, curl):
    body, joints, _head_unit, _torso_r, upper_r, _thigh_r, _h = _fit(name, height, build)
    curl = max(0.0, min(0.8, curl))

    bm = mesh_lib.obj_bmesh(body)
    before = len(bm.faces)

    for side, sign in (("l", 1.0), ("r", -1.0)):
        hand_center = Vector(joints[f"hand_{side}"][0]).lerp(
            Vector(joints[f"hand_{side}"][1]), 0.6
        )
        finger_w = upper_r * 0.18
        finger_len = upper_r * 1.15
        for f in range(4):
            x = hand_center.x + (f - 1.5) * (finger_w * 1.25)
            for segment, (seg_len, bend) in enumerate(
                ((finger_len * 0.55, curl * 0.5), (finger_len * 0.45, curl))
            ):
                piece_bm = mesh_lib.new_bmesh()
                mesh_lib.add_box(
                    piece_bm,
                    size=(finger_w, finger_w * 0.9, seg_len),
                    center=(0.0, 0.0, -seg_len * 0.5), bevel=finger_w * 0.2,
                )
                z_base = hand_center.z - upper_r * 0.45 - segment * finger_len * 0.5
                rot = Matrix.Rotation(bend, 4, "X")
                bmesh_transform(
                    piece_bm,
                    Matrix.Translation(Vector((x, hand_center.y, z_base))) @ rot,
                )
                _absorb(bm, piece_bm)
        thumb = mesh_lib.new_bmesh()
        mesh_lib.add_box(
            thumb,
            size=(finger_w, finger_w * 0.9, finger_len * 0.6),
            center=(0.0, 0.0, -finger_len * 0.3), bevel=finger_w * 0.2,
        )
        bmesh_transform(
            thumb,
            Matrix.Translation(
                Vector((hand_center.x - sign * upper_r * 0.55, hand_center.y - upper_r * 0.15,
                        hand_center.z - upper_r * 0.2))
            )
            @ Matrix.Rotation(sign * math.radians(40.0), 4, "Y")
            @ Matrix.Rotation(curl * 0.6, 4, "X"),
        )
        _absorb(bm, thumb)

    added = len(bm.faces) - before
    mesh_lib.write_bmesh(bm, body)
    mesh_lib.shade_auto_smooth(body, 50.0)
    return {
        "object": body.name,
        "faces_added": added,
        "curl": curl,
        "note": "fingers share the body's skin material; articulation needs finger "
                "bones, which the base rig does not have — pose with morph.add instead",
    }


def _get(name):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc


# ---------------------------------------------------------------------------
# creatures: quadruped bodies, rigs and gaits
# ---------------------------------------------------------------------------
#
# char.humanoid only covers the two-legged cast. Games need the other half —
# hounds, horses, stalkers — and a quadruped is not a humanoid on all fours:
# the torso is horizontal, the legs hang from a shoulder/hip at two stations,
# and its gaits are four-beat patterns, not a two-beat stride. Body plan
# ratios below follow the same figure-drawing discipline as BUILDS.

CREATURE_PLANS = {
    # leg = leg length as a fraction of shoulder height; neck rise in degrees;
    # tail as a fraction of body length; girth multiplier.
    "canine":   {"leg": 0.92, "neck_deg": 35.0, "tail": 0.42, "girth": 0.92},
    "equine":   {"leg": 1.10, "neck_deg": 55.0, "tail": 0.55, "girth": 1.05},
    "feline":   {"leg": 0.86, "neck_deg": 25.0, "tail": 0.60, "girth": 0.82},
    "generic":  {"leg": 0.95, "neck_deg": 40.0, "tail": 0.45, "girth": 1.00},
    # Hexapod (insect): a different skeleton, not a tuning of the quadruped —
    # three leg stations and a tripod gait. leg ratio is measured against the
    # thorax height; splay is how far the legs angle outward from the body.
    "insect":   {"leg": 1.05, "neck_deg": 0.0, "tail": 0.0, "girth": 1.10, "splay": 1.35},
}

_HEXAPOD_PLANS = {"insect"}


def _hexapod_skeleton(length, height, plan):
    """Joint positions for a hexapod (scarab class), standing at the origin.

    Faces -Y. Three leg stations (front/mid/rear) splay outward from the
    thorax; abdomen is the root chain (hips -> chest), head at the front.
    `length` is abdomen-tip to head; `height` is thorax height off the ground.
    """
    spec = CREATURE_PLANS[plan]
    leg_len = height * spec["leg"]
    splay = spec["splay"]
    thorax_y = -length * 0.12
    head_y = -length * 0.42
    abdomen_y = length * 0.30
    z = height

    joints = {
        "hips": ((0.0, abdomen_y, z), (0.0, abdomen_y + length * 0.16, z * 0.94)),
        "chest": ((0.0, abdomen_y * 0.4, z), (0.0, thorax_y, z)),
        "head": ((0.0, thorax_y, z), (0.0, head_y, z * 0.92)),
    }
    for side, sign in (("l", 1.0), ("r", -1.0)):
        for station, y, back in (("front", thorax_y - length * 0.10, -0.35),
                                 ("mid", thorax_y + length * 0.10, 0.0),
                                 ("rear", abdomen_y * 0.7, 0.45)):
            hip = (sign * length * 0.10, y, z * 0.9)
            knee = (sign * length * 0.10 * (1.0 + splay * 0.55), y + back * length * 0.22,
                    z * 0.9 + leg_len * 0.45)
            ankle = (sign * length * 0.10 * (1.0 + splay), y + back * length * 0.5, z * 0.16)
            foot = (sign * length * 0.10 * (1.0 + splay * 1.05), y + back * length * 0.62, 0.0)
            joints[f"{station}_upper_{side}"] = (hip, knee)
            joints[f"{station}_lower_{side}"] = (knee, ankle)
            joints[f"{station}_paw_{side}"] = (ankle, foot)
    return joints, spec


HEXAPOD_PARENTS = {
    "chest": "hips", "head": "chest",
    "front_upper_l": "chest", "front_lower_l": "front_upper_l", "front_paw_l": "front_lower_l",
    "front_upper_r": "chest", "front_lower_r": "front_upper_r", "front_paw_r": "front_lower_r",
    "mid_upper_l": "chest", "mid_lower_l": "mid_upper_l", "mid_paw_l": "mid_lower_l",
    "mid_upper_r": "chest", "mid_lower_r": "mid_upper_r", "mid_paw_r": "mid_lower_r",
    "rear_upper_l": "hips", "rear_lower_l": "rear_upper_l", "rear_paw_l": "rear_lower_l",
    "rear_upper_r": "hips", "rear_lower_r": "rear_upper_r", "rear_paw_r": "rear_lower_r",
}

_RELATED = _RELATED | frozenset(
    pair
    for child, parent in HEXAPOD_PARENTS.items()
    for pair in ((child, parent), (parent, child))
)


def _hexapod_clip_keys(clip, length, amplitude):
    """Tripod gait and idle for the hexapod skeleton.

    Insects walk on alternating TRIPODS — front+rear of one side with the
    middle of the other — which is what makes six legs read as six. Bobbing
    all legs together reads as a toy car.
    """
    a = amplitude
    half = max(1, length // 2)
    swing, knee = 16 * a, 14 * a
    tripod_a = (("front", "l"), ("mid", "r"), ("rear", "l"))
    tripod_b = (("front", "r"), ("mid", "l"), ("rear", "r"))

    if clip == "walk":
        keys = {1: {}, half: {}, length: {}}
        for frame, forward in ((1, tripod_a), (half, tripod_b), (length, tripod_a)):
            for station, side in forward:
                keys[frame][f"{station}_upper_{side}"] = (swing, 0, 0)
                keys[frame][f"{station}_lower_{side}"] = (-knee * 0.6, 0, 0)
            for station, side in (tripod_b if forward is tripod_a else tripod_a):
                keys[frame][f"{station}_upper_{side}"] = (-swing, 0, 0)
                keys[frame][f"{station}_lower_{side}"] = (-knee * 0.15, 0, 0)
        return keys, 0.012 * a

    # idle: antennae/head wobble and a slow abdomen breath.
    return {
        1:      {"head": (0, 0, 0), "hips": (0, 0, 0), "chest": (0, 0, 0)},
        half:   {"head": (4 * a, 0, 6 * a), "hips": (1.5 * a, 0, 0), "chest": (0, 0, 0)},
        length: {"head": (0, 0, 0), "hips": (0, 0, 0), "chest": (0, 0, 0)},
    }



def _quadruped_skeleton(length, shoulder, plan):
    """Joint positions in metres for a quadruped standing at the origin.

    Faces -Y (the studio forward), spine horizontal, legs at two stations.
    `length` is chest-to-hip body length; `shoulder` is shoulder height.
    """
    spec = CREATURE_PLANS[plan]
    leg_len = shoulder * spec["leg"]
    body_z = leg_len
    chest_y = -length * 0.5
    hip_y = length * 0.5
    leg_x = length * 0.11 * spec["girth"]
    neck_len = shoulder * 0.42
    neck_rad = math.radians(spec["neck_deg"])

    joints = {
        "hips": ((0.0, hip_y, body_z), (0.0, hip_y, body_z + length * 0.10)),
        "spine": ((0.0, hip_y, body_z), (0.0, length * 0.08, body_z + length * 0.045)),
        "chest": ((0.0, length * 0.08, body_z + length * 0.045), (0.0, chest_y, body_z + length * 0.03)),
        "neck": (
            (0.0, chest_y, body_z + length * 0.03),
            (0.0, chest_y - math.cos(neck_rad) * neck_len, body_z + length * 0.03 + math.sin(neck_rad) * neck_len),
        ),
        "head": (
            (0.0, chest_y - math.cos(neck_rad) * neck_len, body_z + length * 0.03 + math.sin(neck_rad) * neck_len),
            (0.0, chest_y - math.cos(neck_rad) * neck_len - length * 0.16,
             body_z + length * 0.03 + math.sin(neck_rad) * neck_len + length * 0.02),
        ),
        "tail_1": ((0.0, hip_y, body_z), (0.0, hip_y + length * spec["tail"] * 0.55, body_z + length * 0.04)),
        "tail_2": (
            (0.0, hip_y + length * spec["tail"] * 0.55, body_z + length * 0.04),
            (0.0, hip_y + length * spec["tail"], body_z - length * 0.06),
        ),
    }
    for side, sign in (("l", 1.0), ("r", -1.0)):
        for station, y in (("front", chest_y), ("rear", hip_y)):
            joints[f"{station}_upper_{side}"] = (
                (sign * leg_x, y, body_z),
                (sign * leg_x * 1.05, y, body_z - leg_len * 0.52),
            )
            joints[f"{station}_lower_{side}"] = (
                (sign * leg_x * 1.05, y, body_z - leg_len * 0.52),
                (sign * leg_x * 1.08, y, body_z - leg_len * 0.88),
            )
            joints[f"{station}_paw_{side}"] = (
                (sign * leg_x * 1.08, y, body_z - leg_len * 0.88),
                (sign * leg_x * 1.08, y - length * 0.045, max(0.0, body_z - leg_len)),
            )
    return joints, spec


QUADRUPED_PARENTS = {
    "spine": "hips", "chest": "spine", "neck": "chest", "head": "neck",
    "tail_1": "hips", "tail_2": "tail_1",
    "front_upper_l": "chest", "front_lower_l": "front_upper_l", "front_paw_l": "front_lower_l",
    "front_upper_r": "chest", "front_lower_r": "front_upper_r", "front_paw_r": "front_lower_r",
    "rear_upper_l": "hips", "rear_lower_l": "rear_upper_l", "rear_paw_l": "rear_lower_l",
    "rear_upper_r": "hips", "rear_lower_r": "rear_upper_r", "rear_paw_r": "rear_lower_r",
}

# The two-bone elbow/knee blend in _skin applies to a bone and its direct
# parent, on either body plan.
_RELATED = _RELATED | frozenset(
    pair
    for child, parent in QUADRUPED_PARENTS.items()
    for pair in ((child, parent), (parent, child))
)


def _creature_hexapod_body(ctx, name, length, height, plan, bulk, detail, location, skin, seed):
    """Scarab-class body: segmented abdomen, thorax, dorsal shell, mandibles,
    six splayed legs. Separate from the quadruped assembly on purpose."""
    ctx.reseed(seed)
    joints, spec = _hexapod_skeleton(length, height, plan)
    sides = max(5, min(16, detail))
    girth = spec["girth"] * bulk
    body_r = length * 0.15 * girth
    bm = mesh_lib.new_bmesh()

    def limb(a, b, radius_a, radius_b):
        start, end = Vector(a), Vector(b)
        axis = end - start
        if axis.length < 1e-5:
            return
        piece = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(
            piece, radius=radius_a, radius_top=radius_b, depth=axis.length,
            segments=sides, center=(0.0, 0.0, axis.length * 0.5),
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

    hips_a, hips_b = joints["hips"]
    # Segmented abdomen: three overlapping blobs shrinking rearward.
    for i, factor in enumerate((1.0, 0.82, 0.58)):
        t = i / 2.0
        center = Vector(hips_a).lerp(Vector(hips_b), t)
        blob((center.x, center.y + i * length * 0.05, center.z - i * length * 0.015),
             body_r * factor, (0.95, 1.1, 0.9))
    blob(joints["chest"][1], body_r * 0.9, (1.0, 1.15, 0.95))
    # Dorsal shell (elytra) — the scarab signature. One squashed dome over the back.
    shell_center = Vector(hips_a).lerp(Vector(joints["chest"][1]), 0.4)
    blob((shell_center.x, shell_center.y, shell_center.z + body_r * 0.28),
         body_r * 1.12, (0.95, 1.45, 0.5))
    head_center = Vector(joints["head"][0]).lerp(Vector(joints["head"][1]), 0.6)
    blob(head_center, body_r * 0.5, (0.9, 1.0, 0.85))
    for sign in (1.0, -1.0):
        mandible = mesh_lib.new_bmesh()
        mesh_lib.add_wedge(
            mandible, size=(body_r * 0.16, body_r * 0.45, body_r * 0.12),
            center=(sign * body_r * 0.2, head_center.y - body_r * 0.5, head_center.z - body_r * 0.1),
        )
        _absorb(bm, mandible)

    leg_r = body_r * 0.16
    for side in ("l", "r"):
        for station in ("front", "mid", "rear"):
            upper_a, upper_b = joints[f"{station}_upper_{side}"]
            lower_a, lower_b = joints[f"{station}_lower_{side}"]
            paw_a, paw_b = joints[f"{station}_paw_{side}"]
            limb(upper_a, upper_b, leg_r * 1.2, leg_r * 0.9)
            limb(lower_a, lower_b, leg_r * 0.9, leg_r * 0.65)
            limb(paw_a, paw_b, leg_r * 0.65, leg_r * 0.4)

    mesh_lib.cleanup(bm, merge_dist=length * 0.002)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    skin_mat = mat_lib.principled(f"m_{obj.name}_skin", color=skin, roughness=0.55, metallic=0.15)
    result = finish_lib.finish(
        ctx, obj, material=skin_mat, uv="smart_packed", origin="bottom", smooth=True,
        smooth_angle=50.0,
    )
    result["plan"] = plan
    result["length_m"] = length
    ctx.note(
        f"'{obj.name}' is a hexapod body. char.creature_rig plan='{plan}' rigs it; "
        "char.animate clip='walk' uses the tripod gait table."
    )
    return result


@op(
    "char.creature",
    summary="Proportioned quadruped body (canine/equine/feline/generic) or hexapod (insect: scarab class, three leg stations). Pair with char.creature_rig and char.animate — walk/trot/gallop/graze for quadrupeds, tripod-gait walk for hexapods. Deterministic, data-API only, metres.",
    params={
        "name": ("str", "creature", "Object name"),
        "length": ("num", 1.4, "Body length in metres (chest-to-hip; abdomen-tip to head for insect)"),
        "shoulder": ("num", 0.9, "Shoulder height in metres (thorax height for insect)"),
        "plan": ("enum:canine|equine|feline|generic|insect", "canine", "Body plan — quadruped proportions or the hexapod scarab class"),
        "bulk": ("num", 1.0, "Extra girth multiplier"),
        "detail": ("int", 8, "Limb cross-section segments"),
        "location": ("vec3", [0.0, 0.0, 0.0], "World position"),
        "skin": ("str", "#7a6248", "Body colour"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["char"],
)
def char_creature(ctx, name, length, shoulder, plan, bulk, detail, location, skin, seed):
    if plan in _HEXAPOD_PLANS:
        return _creature_hexapod_body(ctx, name, length, shoulder, plan, bulk, detail,
                                      location, skin, seed)
    ctx.reseed(seed)
    joints, spec = _quadruped_skeleton(length, shoulder, plan)
    sides = max(5, min(16, detail))
    girth = spec["girth"] * bulk
    body_r = length * 0.115 * girth
    bm = mesh_lib.new_bmesh()

    def limb(a, b, radius_a, radius_b):
        start, end = Vector(a), Vector(b)
        axis = end - start
        if axis.length < 1e-5:
            return
        piece = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(
            piece, radius=radius_a, radius_top=radius_b, depth=axis.length,
            segments=sides, center=(0.0, 0.0, axis.length * 0.5),
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

    # Torso: chest -> spine -> hips as two overlapping capsules so the belly
    # sags slightly between the stations instead of reading as a pipe.
    limb(joints["chest"][1], joints["spine"][0], body_r * 1.05, body_r * 0.92)
    limb(joints["spine"][0], joints["hips"][0], body_r * 0.92, body_r * 0.82)
    blob(joints["chest"][1], body_r * 1.08, (0.9, 1.05, 1.0))
    blob(joints["hips"][0], body_r * 0.95, (0.85, 1.0, 0.95))

    limb(joints["neck"][0], joints["neck"][1], body_r * 0.55, body_r * 0.42)
    head_center = Vector(joints["head"][0]).lerp(Vector(joints["head"][1]), 0.55)
    blob(head_center, body_r * 0.62, (0.85, 1.35, 0.95))
    # Muzzle — the feature that stops a quadruped head reading as a ball.
    muzzle = Vector(joints["head"][1])
    blob((muzzle.x, muzzle.y - length * 0.015, muzzle.z - length * 0.01),
         body_r * 0.34, (0.7, 1.5, 0.8))

    limb(joints["tail_1"][0], joints["tail_1"][1], body_r * 0.30, body_r * 0.22)
    limb(joints["tail_2"][0], joints["tail_2"][1], body_r * 0.22, body_r * 0.08)

    leg_r = body_r * 0.30
    for side in ("l", "r"):
        for station in ("front", "rear"):
            upper_a, upper_b = joints[f"{station}_upper_{side}"]
            lower_a, lower_b = joints[f"{station}_lower_{side}"]
            paw_a, paw_b = joints[f"{station}_paw_{side}"]
            limb(upper_a, upper_b, leg_r * 1.15, leg_r * 0.85)
            limb(lower_a, lower_b, leg_r * 0.85, leg_r * 0.60)
            paw_center = Vector(paw_a).lerp(Vector(paw_b), 0.5)
            blob(paw_center, leg_r * 0.75, (1.0, 1.4, 0.75))

    mesh_lib.cleanup(bm, merge_dist=length * 0.002)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    skin_mat = mat_lib.principled(f"m_{obj.name}_skin", color=skin, roughness=0.72)
    result = finish_lib.finish(
        ctx, obj, material=skin_mat, uv="smart_packed", origin="bottom", smooth=True,
        smooth_angle=50.0,
    )
    result["plan"] = plan
    result["length_m"] = length
    ctx.note(
        f"'{obj.name}' is a body. Run char.creature_rig name='{obj.name}' for the "
        "armature, then char.animate clip='trot' (or walk/gallop/graze/idle)."
    )
    return result


@op(
    "char.creature_rig",
    summary="Build a quadruped armature (hips root, spine chain, neck/head, 2-segment tail, 3-bone legs at both stations) fitted to a char.creature body, and skin it with the same shell-constrained distance-falloff solve as char.rig.",
    params={
        "name": ("str", None, "Creature mesh object (from char.creature)"),
        "length": ("num", 0.0, "Chest-to-hip length; 0 measures from the mesh bounds Y extent"),
        "shoulder": ("num", 0.0, "Shoulder height; 0 measures from the mesh bounds Z extent"),
        "plan": ("enum:canine|equine|feline|generic|insect", "canine", "Body plan the rig assumes — match char.creature"),
        "falloff": ("num", 1.6, "Weight blend sharpness; higher is more rigid"),
        "armature_name": ("str", "", "Armature object name (defaults to <mesh>_rig)"),
    },
    tags=["char", "rig"],
)
def char_creature_rig(ctx, name, length, shoulder, plan, falloff, armature_name):
    obj = _get(name)
    if obj.type != "MESH":
        raise OpError(f"'{name}' is a {obj.type}, not a mesh — rig the body mesh")
    bounds = mesh_lib.bounds(obj)
    hexapod = plan in _HEXAPOD_PLANS
    if length <= 0:
        length = (bounds["size"][1] * (0.8 if hexapod else 0.55)) or 1.4
    if shoulder <= 0:
        shoulder = (bounds["size"][2] * (0.5 if hexapod else 0.75)) or 0.9
    if hexapod:
        joints, _spec = _hexapod_skeleton(length, shoulder, plan)
        parents = HEXAPOD_PARENTS
    else:
        joints, _spec = _quadruped_skeleton(length, shoulder, plan)
        parents = QUADRUPED_PARENTS

    rig_name = scene_lib.unique_name(armature_name or f"{obj.name}_rig")
    armature_data = bpy.data.armatures.new(rig_name)
    rig = bpy.data.objects.new(rig_name, armature_data)
    bpy.context.scene.collection.objects.link(rig)
    rig.location = obj.location

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
        for child, parent in parents.items():
            if child in created and parent in created:
                created[child].parent = created[parent]
                created[child].use_connect = False
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    view_layer.objects.active = previous_active

    scene_lib.sync()
    weights = _skin(obj, joints, falloff, rig)

    modifier = obj.modifiers.new("armature", "ARMATURE")
    modifier.object = rig
    modifier.use_vertex_groups = True
    obj.parent = rig
    obj.matrix_parent_inverse = rig.matrix_world.inverted()

    return {
        "armature": rig.name,
        "mesh": obj.name,
        "bones": sorted(b.name for b in armature_data.bones),
        "bone_count": len(armature_data.bones),
        "vertex_groups": len(obj.vertex_groups),
        "weighted_vertices": weights,
        "note": "gaits live in char.animate: clip='walk'|'trot'|'gallop'|'graze'|'idle' "
                "— the quadruped tables are chosen automatically from these bones",
    }


def _quadruped_clip_keys(clip, length, amplitude):
    """Gait pose tables for the quadruped skeleton.

    Real quadruped gaits are footfall SEQUENCES, and the silhouette of each
    beat is what reads: a walk is a four-beat lateral sequence (LH, LF, RH,
    RF), a trot is two-beat diagonal pairs, a gallop is front-pair reach then
    rear-pair drive with the spine flexing between. Sine waves on all four
    legs at once is how you get a rocking horse, not an animal.
    """
    a = amplitude
    quarter = max(1, length // 4)

    if clip == "walk":
        swing, knee = 15 * a, 12 * a
        phases = {
            1:            (("rear", "l", swing), ("front", "l", -swing * 0.4),
                           ("rear", "r", -swing * 0.4), ("front", "r", swing * 0.6)),
            quarter:      (("rear", "l", swing * 0.4), ("front", "l", swing),
                           ("rear", "r", -swing), ("front", "r", -swing * 0.4)),
            quarter * 2:  (("rear", "l", -swing * 0.4), ("front", "l", swing * 0.6),
                           ("rear", "r", swing), ("front", "r", -swing * 0.4)),
            quarter * 3:  (("rear", "l", -swing), ("front", "l", -swing * 0.4),
                           ("rear", "r", swing * 0.4), ("front", "r", swing)),
            length:       (("rear", "l", swing), ("front", "l", -swing * 0.4),
                           ("rear", "r", -swing * 0.4), ("front", "r", swing * 0.6)),
        }
        keys = {}
        for frame, beats in phases.items():
            pose = {}
            for station, side, angle in beats:
                pose[f"{station}_upper_{side}"] = (angle, 0, 0)
                pose[f"{station}_lower_{side}"] = (-knee * (0.4 if angle > 0 else 0.1), 0, 0)
            keys[frame] = pose
        return keys

    if clip == "trot":
        swing, knee = 20 * a, 18 * a
        keys = {
            1: {}, quarter: {}, quarter * 2: {}, quarter * 3: {}, length: {},
        }
        diagonal_a = (("front", "l"), ("rear", "r"))
        diagonal_b = (("front", "r"), ("rear", "l"))
        for frame, forward in ((1, diagonal_a), (quarter * 2, diagonal_b), (length, diagonal_a)):
            for station, side in forward:
                keys[frame][f"{station}_upper_{side}"] = (swing, 0, 0)
                keys[frame][f"{station}_lower_{side}"] = (-knee * 0.5, 0, 0)
            for station, side in (diagonal_b if forward is diagonal_a else diagonal_a):
                keys[frame][f"{station}_upper_{side}"] = (-swing, 0, 0)
                keys[frame][f"{station}_lower_{side}"] = (-knee * 0.15, 0, 0)
        for frame in (quarter, quarter * 3):
            for station in ("front", "rear"):
                for side in ("l", "r"):
                    keys[frame][f"{station}_upper_{side}"] = (0, 0, 0)
                    keys[frame][f"{station}_lower_{side}"] = (-knee * 0.25, 0, 0)
        return keys, 0.02 * a

    if clip == "gallop":
        reach, drive, flex = 30 * a, 34 * a, 10 * a
        keys = {
            1: {
                "chest": (-flex * 0.5, 0, 0), "spine": (flex * 0.5, 0, 0),
                "front_upper_l": (reach, 0, 0), "front_upper_r": (reach * 0.9, 0, 0),
                "front_lower_l": (-reach * 0.7, 0, 0), "front_lower_r": (-reach * 0.6, 0, 0),
                "rear_upper_l": (-drive, 0, 0), "rear_upper_r": (-drive * 0.9, 0, 0),
                "rear_lower_l": (drive * 0.5, 0, 0), "rear_lower_r": (drive * 0.45, 0, 0),
                "neck": (-6 * a, 0, 0),
            },
            quarter: {
                "chest": (flex, 0, 0), "spine": (-flex, 0, 0),
                "front_upper_l": (-reach * 0.4, 0, 0), "front_upper_r": (-reach * 0.35, 0, 0),
                "front_lower_l": (-reach * 0.2, 0, 0), "front_lower_r": (-reach * 0.2, 0, 0),
                "rear_upper_l": (drive * 0.6, 0, 0), "rear_upper_r": (drive * 0.55, 0, 0),
                "rear_lower_l": (-drive * 0.6, 0, 0), "rear_lower_r": (-drive * 0.55, 0, 0),
                "neck": (4 * a, 0, 0),
            },
            quarter * 2: {
                "chest": (flex * 0.6, 0, 0), "spine": (-flex * 0.6, 0, 0),
                "front_upper_l": (reach * 0.3, 0, 0), "front_upper_r": (reach * 0.35, 0, 0),
                "front_lower_l": (-reach * 0.3, 0, 0), "front_lower_r": (-reach * 0.3, 0, 0),
                "rear_upper_l": (drive * 0.2, 0, 0), "rear_upper_r": (drive * 0.25, 0, 0),
                "rear_lower_l": (-drive * 0.3, 0, 0), "rear_lower_r": (-drive * 0.3, 0, 0),
                "neck": (2 * a, 0, 0),
            },
            length: {
                "chest": (-flex * 0.5, 0, 0), "spine": (flex * 0.5, 0, 0),
                "front_upper_l": (reach, 0, 0), "front_upper_r": (reach * 0.9, 0, 0),
                "front_lower_l": (-reach * 0.7, 0, 0), "front_lower_r": (-reach * 0.6, 0, 0),
                "rear_upper_l": (-drive, 0, 0), "rear_upper_r": (-drive * 0.9, 0, 0),
                "rear_lower_l": (drive * 0.5, 0, 0), "rear_lower_r": (drive * 0.45, 0, 0),
                "neck": (-6 * a, 0, 0),
            },
        }
        return keys, 0.04 * a

    if clip == "graze":
        drop = 38 * a
        return {
            1:            {"neck": (0, 0, 0), "head": (0, 0, 0)},
            quarter:      {"neck": (drop, 0, 0), "head": (drop * 0.4, 0, 0)},
            quarter * 2:  {"neck": (drop * 1.05, 0, 0), "head": (drop * 0.45, 0, 0),
                           "tail_1": (0, 0, 8 * a)},
            quarter * 3:  {"neck": (drop * 0.9, 0, 0), "head": (drop * 0.35, 0, 0)},
            length:       {"neck": (0, 0, 0), "head": (0, 0, 0)},
        }

    # idle: weight shift, tail sway, ear-flick stand-in on the head.
    return {
        1:            {"chest": (0, 0, 0), "tail_1": (0, 0, 0), "head": (0, 0, 0)},
        quarter:      {"chest": (1.5 * a, 0, 1.5 * a), "tail_1": (0, 0, 10 * a),
                       "head": (3 * a, 0, 0)},
        quarter * 2:  {"chest": (0, 0, 0), "tail_1": (0, 0, -4 * a), "head": (0, 0, 0)},
        quarter * 3:  {"chest": (1.5 * a, 0, -1.5 * a), "tail_1": (0, 0, -10 * a),
                       "head": (-2 * a, 0, 0)},
        length:       {"chest": (0, 0, 0), "tail_1": (0, 0, 0), "head": (0, 0, 0)},
    }

