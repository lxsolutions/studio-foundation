"""Shape keys — glTF morph targets for damage states and expressions.

A shape key stores a per-vertex offset from the Basis shape; glTF exports it as
a morph target, and engines blend it at runtime with a 0..1 weight. That is how
a crate gets a "dented" damage state, a cartoon prop gets an inflate, or a face
gets an expression, without a second mesh or a skeleton.

All displacement here is deterministic geometry maths — no randomness — and the
keyframing idiom mirrors char.py: actions are authored directly on the shape-key
datablock, which the glTF exporter picks up as a morph-weights animation
channel.
"""

from __future__ import annotations

import bpy
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from mathutils import Vector
from registry import OpError, op


@op(
    "morph.add",
    summary="Add a shape key that displaces vertices by a deterministic rule — dent a crate for a damage state, inflate a cartoon prop, taper a tree trunk, bulge a cartoon cheek. Exports to glTF as a morph target on top of Basis.",
    params={
        "name": ("str", None, "Mesh object to add the shape key to"),
        "key": ("str", None, "Shape key name — this becomes the glTF morph target name (extras.targetNames), so make it meaningful: 'dented', 'inflate', 'blink'"),
        "rule": ("enum:inflate|dent|flatten|taper|bulge", "dent", "Displacement rule: inflate pushes verts out along their normals, dent pulls verts inside `radius` toward `center`, bulge pushes them away, flatten squashes toward the center plane along `axis`, taper scales the cross-section down along `axis`"),
        "amount": ("num", 0.1, "Displacement in metres (flatten/taper: 0..1 fraction of the way)"),
        "axis": ("enum:x|y|z", "z", "Axis for flatten and taper (z is up)"),
        "center": ("vec3", None, "Local-space point the rule acts around; omit to use the centre of the mesh's own bounds"),
        "radius": ("num", 1.0, "Reach of the effect in metres — verts beyond this from `center` are untouched (taper: full axis half-extent)"),
        "falloff": ("enum:smooth|linear", "smooth", "How the effect fades toward `radius`; smooth eases out, linear is a straight ramp"),
    },
    tags=["morph"],
)
def morph_add(ctx, name, key, rule, amount, axis, center, radius, falloff):
    obj = _get_mesh(name)
    mesh = obj.data
    if not mesh.vertices:
        raise OpError(f"'{name}' has no vertices to deform")

    keys = mesh.shape_keys
    if keys is not None and key in keys.key_blocks:
        raise OpError(
            f"shape key '{key}' already exists on '{name}' — pick another name, or "
            "use morph.set / morph.animate to drive the existing one."
        )
    if keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)

    bounds_min, bounds_max = _local_bounds(mesh)
    if center is None:
        center = [(bounds_min[i] + bounds_max[i]) * 0.5 for i in range(3)]
    center = Vector(center)
    radius = max(1e-6, radius)

    # Normals are needed by inflate; read them through bmesh (data API only —
    # bmesh is read here, never written back).
    normals = None
    if rule == "inflate":
        bm = mesh_lib.obj_bmesh(obj)
        bm.verts.ensure_lookup_table()
        bm.normal_update()
        normals = [v.normal.copy() for v in bm.verts]
        bm.free()

    axis_index = {"x": 0, "y": 1, "z": 2}[axis]
    moved = 0
    block = obj.shape_key_add(name=key, from_mix=False)
    for index, vert in enumerate(mesh.vertices):
        co = vert.co
        offset = co - center
        distance = offset.length
        delta = Vector((0.0, 0.0, 0.0))

        if rule == "taper":
            # Cross-section shrinks from 100% at center-axis to (1-amount) at
            # center+radius along the axis; radius doubles as the half-extent.
            t01 = _clamp01(0.5 + 0.5 * (co[axis_index] - center[axis_index]) / radius)
            scale = max(0.0, 1.0 - amount * t01)
            for k in range(3):
                if k != axis_index:
                    delta[k] = (center[k] + (co[k] - center[k]) * scale) - co[k]
        elif rule == "flatten":
            weight = _falloff(distance / radius, falloff)
            if weight > 0.0:
                fraction = _clamp01(amount) * weight
                delta[axis_index] = (center[axis_index] - co[axis_index]) * fraction
        else:
            weight = _falloff(distance / radius, falloff)
            if weight > 0.0:
                if rule == "inflate":
                    delta = normals[index] * (amount * weight)
                elif distance > 1e-9:
                    direction = offset / distance
                    if rule == "dent":
                        delta = -direction * (amount * weight)
                    else:  # bulge
                        delta = direction * (amount * weight)

        if delta.length > 1e-9:
            block.data[index].co = co + delta
            moved += 1

    mesh.update()
    result = {
        "name": obj.name,
        "key": key,
        "rule": rule,
        "amount": amount,
        "vertices_moved": moved,
        "keys": [k.name for k in mesh.shape_keys.key_blocks],
    }
    if moved == 0:
        result["note"] = (
            f"no vertices were affected — every vert is outside radius {radius} of "
            f"center {[round(c, 3) for c in center]}. Raise `radius`, or omit `center` "
            "to act around the mesh's own bounds centre."
        )
    return result


@op(
    "morph.set",
    summary="Set a shape key's slider value (0..1) for review renders — pose the dent at 60% before render.contact_sheet so the still shows the damaged state.",
    params={
        "name": ("str", None, "Mesh object with the shape key"),
        "key": ("str", None, "Shape key name (from morph.add or morph.list)"),
        "value": ("num", 1.0, "Slider weight, clamped to 0..1: 0 is Basis, 1 is the full morph"),
    },
    tags=["morph"],
)
def morph_set(ctx, name, key, value):
    block = _get_key(name, key)
    block.value = _clamp01(value)
    return {"name": name, "key": key, "value": block.value}


@op(
    "morph.animate",
    summary="Keyframe a shape key's weight over time so glTF exports a morph-target animation channel — a crate denting on impact, a chest lid swell, a pulsing crystal. Follows the same action idiom as char.animate.",
    params={
        "name": ("str", None, "Mesh object with the shape key"),
        "key": ("str", None, "Shape key name to animate"),
        "frames": ("num[]", None, "Frame numbers, e.g. [1, 12, 24]; must be the same length as `values`"),
        "values": ("num[]", None, "Weight at each frame (0..1), e.g. [0, 1, 0] pops the morph and settles back"),
    },
    tags=["morph", "anim"],
)
def morph_animate(ctx, name, key, frames, values):
    block = _get_key(name, key)
    if len(frames) != len(values):
        raise OpError(
            f"frames ({len(frames)}) and values ({len(values)}) must be the same length, "
            "e.g. frames=[1, 12, 24], values=[0, 1, 0]"
        )
    if not frames:
        raise OpError("frames must not be empty — give at least one (frame, value) key")

    obj = _get_mesh(name)
    keys = obj.data.shape_keys
    if keys.animation_data is None:
        keys.animation_data_create()
    action = bpy.data.actions.new(scene_lib.sanitize(f"{obj.name}_{key}"))
    keys.animation_data.action = action

    for frame, value in zip(frames, values, strict=True):
        block.value = _clamp01(value)
        block.keyframe_insert(data_path="value", frame=frame)

    scene = bpy.context.scene
    scene.frame_start = min(scene.frame_start, int(min(frames)))
    scene.frame_end = max(scene.frame_end, int(max(frames)))

    # Keep the action reachable even after a later animate call replaces it —
    # glTF exports every action it can reach, and a zero-user action is garbage
    # collected. Same trick char.animate relies on.
    action.use_fake_user = True

    return {
        "name": obj.name,
        "key": key,
        "action": action.name,
        "keyframes": len(frames),
        "all_actions": [a.name for a in bpy.data.actions],
    }


@op(
    "morph.list",
    summary="Report an object's shape keys: names, slider ranges and current values. Check this before morph.animate — the key name must match exactly.",
    params={
        "name": ("str", None, "Mesh object to inspect"),
    },
    tags=["morph", "inspect"],
    mutates=False,
)
def morph_list(ctx, name):
    obj = _get_mesh(name)
    keys = obj.data.shape_keys
    if keys is None:
        ctx.note(f"'{name}' has no shape keys — morph.add creates them.")
        return {"name": obj.name, "keys": [], "count": 0}
    entries = [
        {
            "key": block.name,
            "value": round(block.value, 4),
            "slider_min": block.slider_min,
            "slider_max": block.slider_max,
            "muted": block.mute,
        }
        for block in keys.key_blocks
    ]
    return {"name": obj.name, "keys": entries, "count": len(entries)}


def _falloff(t01, falloff):
    """Weight at a normalised distance: 1 at the centre, 0 at the radius."""
    if t01 >= 1.0:
        return 0.0
    t01 = max(0.0, t01)
    if falloff == "linear":
        return 1.0 - t01
    return 1.0 - t01 * t01 * (3.0 - 2.0 * t01)  # smoothstep-shaped ease-out


def _clamp01(value):
    return max(0.0, min(1.0, value))


def _local_bounds(mesh):
    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _get_mesh(name):
    try:
        obj = scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
    if obj.type != "MESH":
        raise OpError(f"'{name}' is a {obj.type}, not a mesh — shape keys live on meshes")
    return obj


def _get_key(name, key):
    obj = _get_mesh(name)
    keys = obj.data.shape_keys
    if keys is None or key not in keys.key_blocks:
        available = [] if keys is None else [k.name for k in keys.key_blocks]
        raise OpError(
            f"no shape key '{key}' on '{name}'. Keys: {available or '(none)'} "
            "— morph.add creates one, morph.list shows what exists."
        )
    return keys.key_blocks[key]
