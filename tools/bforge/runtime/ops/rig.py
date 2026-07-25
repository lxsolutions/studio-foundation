"""Generic rigging: arbitrary skeletons, skinning and keyframing.

`char.*` covers humanoids with a fixed bone set. This is the general case —
quadrupeds, birds, fish, tentacles, mechanical arms, flags, anything. You give
a bone list and keyframes; nothing here assumes a body plan.

Same constraints as the rest of the runtime: no GUI, no operator context beyond
the one unavoidable armature edit-mode switch, deterministic output.
"""

from __future__ import annotations

import math

import bpy
from lib import scene as scene_lib
from mathutils import Matrix, Vector
from registry import OpError, op


@op(
    "rig.skeleton",
    summary="Build an armature from an explicit bone list — any creature, not just humanoids. Each bone is {name, head:[x,y,z], tail:[x,y,z], parent}. Exactly one bone may be parentless, because engines and the studio validator both require a single root.",
    params={
        "name": ("str", "rig", "Armature object name"),
        "bones": ("obj[]", None, "Bones: [{\"name\": \"spine\", \"head\": [0,0,1], \"tail\": [0,0.3,1], \"parent\": \"\"}, ...]"),
        "location": ("vec3", [0.0, 0.0, 0.0], "Armature position in metres"),
    },
    tags=["rig", "char"],
)
def rig_skeleton(ctx, name, bones, location):
    if not bones:
        raise OpError("rig.skeleton needs at least one bone")

    specs = []
    seen = set()
    for entry in bones:
        bone_name = str(entry.get("name", "")).strip()
        if not bone_name:
            raise OpError(f"every bone needs a name: {entry}")
        if not scene_lib.NAME_RE.match(bone_name) and not bone_name.replace(".", "").isalnum():
            raise OpError(
                f"bone name '{bone_name}' must be snake_case (the studio validator "
                "requires ^[a-z][a-z0-9_.]*$)"
            )
        if bone_name in seen:
            raise OpError(f"duplicate bone name '{bone_name}'")
        seen.add(bone_name)
        head = entry.get("head")
        tail = entry.get("tail")
        if not (isinstance(head, (list, tuple)) and isinstance(tail, (list, tuple))):
            raise OpError(f"bone '{bone_name}' needs head and tail as [x, y, z]")
        specs.append((bone_name, [float(v) for v in head], [float(v) for v in tail],
                      str(entry.get("parent", "") or "")))

    missing = [p for _n, _h, _t, p in specs if p and p not in seen]
    if missing:
        raise OpError(f"bones name parents that do not exist: {sorted(set(missing))}")
    roots = [n for n, _h, _t, p in specs if not p]
    if len(roots) != 1:
        raise OpError(
            f"exactly one root bone is required, found {len(roots)}: {roots}. "
            "Parent the others, or engines will import a broken skeleton."
        )

    rig_name = scene_lib.unique_name(name)
    armature_data = bpy.data.armatures.new(rig_name)
    rig = bpy.data.objects.new(rig_name, armature_data)
    bpy.context.scene.collection.objects.link(rig)
    rig.location = location

    view_layer = bpy.context.view_layer
    previous = view_layer.objects.active
    view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        created = {}
        for bone_name, head, tail, _parent in specs:
            bone = armature_data.edit_bones.new(bone_name)
            bone.head = Vector(head)
            bone.tail = Vector(tail)
            if (bone.tail - bone.head).length < 1e-5:
                # A zero-length bone is silently dropped by Blender, which then
                # shows up much later as a missing joint in the exported skin.
                bone.tail = bone.head + Vector((0.0, 0.0, 0.01))
            bone.use_deform = True
            created[bone_name] = bone
        for bone_name, _head, _tail, parent in specs:
            if parent:
                created[bone_name].parent = created[parent]
                created[bone_name].use_connect = False
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    view_layer.objects.active = previous

    return {
        "armature": rig.name,
        "bones": [b.name for b in armature_data.bones],
        "bone_count": len(armature_data.bones),
        "root": roots[0],
    }


@op(
    "rig.skin",
    summary="Bind a mesh to an armature using distance-to-bone falloff weights. Works on any skeleton and never fails the way Blender's bone-heat solver does on a non-watertight mesh.",
    params={
        "mesh": ("str", None, "Mesh object to bind"),
        "rig": ("str", None, "Armature object"),
        "falloff": ("num", 2.0, "Weight sharpness; higher is more rigid, lower is smoother"),
        "influences": ("int", 2, "Bones influencing each vertex (2 is right for game skins)"),
        "only_bones": ("str[]", [], "Restrict binding to these bones (empty = all deform bones)"),
    },
    tags=["rig", "char"],
)
def rig_skin(ctx, mesh, rig, falloff, influences, only_bones):
    obj = _get(mesh)
    armature = _get(rig)
    if obj.type != "MESH":
        raise OpError(f"'{mesh}' is a {obj.type}, not a mesh")
    if armature.type != "ARMATURE":
        raise OpError(f"'{rig}' is a {armature.type}, not an armature")

    bones = [b for b in armature.data.bones if not only_bones or b.name in only_bones]
    if not bones:
        raise OpError(f"no matching bones on '{rig}'")

    for group in list(obj.vertex_groups):
        obj.vertex_groups.remove(group)
    groups = {b.name: obj.vertex_groups.new(name=b.name) for b in bones}

    matrix = obj.matrix_world
    rig_matrix = armature.matrix_world
    segments = {
        b.name: (rig_matrix @ b.head_local, rig_matrix @ b.tail_local) for b in bones
    }
    limit = max(1, min(4, influences))
    weighted = 0

    for vertex in obj.data.vertices:
        world = matrix @ vertex.co
        distances = []
        for bone_name, (head, tail) in segments.items():
            axis = tail - head
            length_sq = axis.length_squared
            t = 0.0 if length_sq < 1e-9 else max(
                0.0, min(1.0, (world - head).dot(axis) / length_sq)
            )
            distances.append(((world - (head + axis * t)).length, bone_name))
        distances.sort()
        picked = distances[:limit]
        raw = [(n, 1.0 / (d + 1e-4) ** falloff) for d, n in picked]
        total = sum(w for _n, w in raw)
        if total <= 0.0:
            continue
        for bone_name, weight in raw:
            groups[bone_name].add([vertex.index], weight / total, "REPLACE")
        weighted += 1

    modifier = next((m for m in obj.modifiers if m.type == "ARMATURE"), None)
    if modifier is None:
        modifier = obj.modifiers.new("armature", "ARMATURE")
    modifier.object = armature
    modifier.use_vertex_groups = True
    obj.parent = armature
    obj.matrix_parent_inverse = armature.matrix_world.inverted()

    return {
        "mesh": obj.name,
        "rig": armature.name,
        "vertex_groups": len(obj.vertex_groups),
        "weighted_vertices": weighted,
        "influences": limit,
    }


@op(
    "rig.keyframe",
    summary="Author an animation clip from explicit per-frame bone poses. Give the poses that define the motion and let the interpolation do the rest — this is how a real cycle is built, not by driving bones with sine waves.",
    params={
        "rig": ("str", None, "Armature object"),
        "action": ("str", "action", "Action (clip) name"),
        "keys": ("obj", None, "{\"1\": {\"spine\": [rx, ry, rz]}, \"12\": {...}} — frame -> bone -> XYZ degrees"),
        "locations": ("obj", None, "Optional {\"frame\": {\"bone\": [x, y, z]}} bone translations in metres"),
        "length": ("int", 24, "Clip length in frames"),
        "loop": ("bool", True, "Match the last frame to the first so the clip cycles seamlessly"),
        "interpolation": ("enum:BEZIER|LINEAR|CONSTANT", "BEZIER", "Keyframe interpolation"),
    },
    tags=["rig", "anim", "char"],
)
def rig_keyframe(ctx, rig, action, keys, locations, length, loop, interpolation):
    from .char import action_fcurves

    obj = _get(rig)
    if obj.type != "ARMATURE":
        raise OpError(f"'{rig}' is a {obj.type}, not an armature")
    if not keys and not locations:
        raise OpError("rig.keyframe needs `keys` and/or `locations`")

    available = {b.name for b in obj.pose.bones}
    for source in (keys or {}, locations or {}):
        for frame_poses in source.values():
            unknown = sorted(set(frame_poses) - available)
            if unknown:
                raise OpError(
                    f"no such bone(s) on '{rig}': {unknown}. Bones: {sorted(available)}"
                )

    if obj.animation_data is None:
        obj.animation_data_create()
    clip = bpy.data.actions.new(scene_lib.sanitize(action))
    obj.animation_data.action = clip

    for bone in obj.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)

    for frame_text, poses in sorted((keys or {}).items(), key=lambda kv: float(kv[0])):
        frame = int(float(frame_text))
        for bone_name, rotation in poses.items():
            bone = obj.pose.bones[bone_name]
            bone.rotation_euler = [math.radians(float(a)) for a in rotation]
            bone.keyframe_insert(data_path="rotation_euler", frame=frame)

    for frame_text, poses in sorted((locations or {}).items(), key=lambda kv: float(kv[0])):
        frame = int(float(frame_text))
        for bone_name, offset in poses.items():
            bone = obj.pose.bones[bone_name]
            bone.location = Vector([float(v) for v in offset])
            bone.keyframe_insert(data_path="location", frame=frame)

    curves = action_fcurves(clip)
    for curve in curves:
        for point in curve.keyframe_points:
            point.interpolation = interpolation
        if loop and len(curve.keyframe_points) >= 2:
            first = curve.keyframe_points[0].co[1]
            curve.keyframe_points[-1].co[1] = first
            curve.keyframe_points[-1].handle_left[1] = first
            curve.keyframe_points[-1].handle_right[1] = first
        curve.update()
    if loop and hasattr(clip, "use_cyclic"):
        clip.use_cyclic = True

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = max(scene.frame_end, length)
    clip.use_fake_user = True

    return {
        "rig": obj.name,
        "action": clip.name,
        "frames": length,
        "fcurves": len(curves),
        "keyframes": sum(len(c.keyframe_points) for c in curves),
        "loops": loop,
    }


@op(
    "rig.mirror_bones",
    summary="Duplicate a set of bones mirrored across an axis, renaming _l to _r (or vice versa). Halves the work of describing a symmetrical skeleton.",
    params={
        "bones": ("obj[]", None, "Bone specs to mirror, same shape as rig.skeleton"),
        "axis": ("enum:x|y|z", "x", "Axis to mirror across"),
        "from_suffix": ("str", "_l", "Suffix on the source bones"),
        "to_suffix": ("str", "_r", "Suffix for the mirrored copies"),
    },
    tags=["rig"],
    mutates=False,
)
def rig_mirror_bones(ctx, bones, axis, from_suffix, to_suffix):
    index = {"x": 0, "y": 1, "z": 2}[axis]
    mirrored = []
    for entry in bones:
        name = str(entry.get("name", ""))
        if not name.endswith(from_suffix):
            continue
        new_name = name[: -len(from_suffix)] + to_suffix
        parent = str(entry.get("parent", "") or "")
        if parent.endswith(from_suffix):
            parent = parent[: -len(from_suffix)] + to_suffix
        head = list(entry["head"])
        tail = list(entry["tail"])
        head[index] = -head[index]
        tail[index] = -tail[index]
        mirrored.append({"name": new_name, "head": head, "tail": tail, "parent": parent})
    return {"bones": mirrored, "count": len(mirrored)}


def _get(name):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
