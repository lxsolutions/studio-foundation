"""Scene-graph plumbing: naming, transforms, modifiers, collections.

Everything here is background-mode safe. Where `bpy.ops` has a data-API
equivalent we use the data API — `object.transform_apply` and
`modifier_apply` in particular are context-sensitive operators that fail or
silently no-op headless, and the depsgraph route below is both faster and
deterministic.
"""

from __future__ import annotations

import re

import bmesh
import bpy
from mathutils import Matrix, Vector

# Matches the studio asset validator (tools/blender/validate.py) so anything
# bforge generates passes `just asset-validate` without a rename pass.
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(-col|-convcol|_lod[0-9])?$")


SUFFIX_RE = re.compile(r"(-col|-convcol|_lod[0-9])$")


def sanitize(name: str) -> str:
    """Coerce any string into the studio's snake_case object-name convention.

    The `-col` / `-convcol` / `_lodN` suffixes are meaningful to the engine
    importer, so they survive: a naive slug turns `crate-col` into `crate_col`
    and the collision proxy silently stops being recognised as one.
    """
    raw = str(name)
    suffix_match = SUFFIX_RE.search(raw)
    suffix = suffix_match.group(0) if suffix_match else ""
    body = raw[: -len(suffix)] if suffix else raw

    text = re.sub(r"[^a-zA-Z0-9]+", "_", body).strip("_").lower()
    text = re.sub(r"_+", "_", text)
    if not text:
        text = "asset"
    if not text[0].isalpha():
        text = f"a_{text}"
    return text + suffix


def check_name(name: str) -> bool:
    return NAME_RE.match(name) is not None


def unique_name(name: str) -> str:
    """Blender appends '.001' on collision, which breaks the naming rule."""
    base = sanitize(name)
    if base not in bpy.data.objects:
        return base
    index = 1
    while f"{base}_{index}" in bpy.data.objects:
        index += 1
    return f"{base}_{index}"


def get_object(name: str):
    # Guard before touching bpy: bpy_prop_collection.get(None) raises a raw
    # SystemError from C, which surfaces as an inscrutable daemon error
    # instead of the helpful message below (found via Riftline's asset pack,
    # where an op reached here with a missing name argument).
    if not isinstance(name, str) or not name:
        raise ValueError(f"object name must be a non-empty string, got {name!r}")
    obj = bpy.data.objects.get(name)
    if obj is None:
        available = sorted(o.name for o in bpy.context.scene.objects)[:25]
        raise ValueError(
            f"no object named '{name}'. In the scene: {available or '(scene is empty)'}"
        )
    return obj


def mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def select_only(objs):
    view_layer = bpy.context.view_layer
    for other in bpy.context.scene.objects:
        other.select_set(False)
    for obj in objs:
        obj.select_set(True)
    if objs:
        view_layer.objects.active = objs[0]
    return objs


# ---------------------------------------------------------------------------
# transforms
# ---------------------------------------------------------------------------


def sync():
    """Force the depsgraph to recompute object matrices.

    `obj.matrix_world` is only refreshed when the depsgraph evaluates. Set
    `obj.location` and read `obj.matrix_world` on the next line and you get the
    PREVIOUS matrix, silently. Anything that reads a world matrix after moving
    something must call this first.
    """
    bpy.context.view_layer.update()


def apply_transforms(obj, location=False, rotation=True, scale=True):
    """Bake the object's own transform into mesh data.

    Game engines import rotation/scale as-is, so an unapplied 0.01 scale becomes
    a centimetre-scaled prop in Godot. The studio validator rejects it; this
    makes it impossible to emit.

    Built from `location`/`rotation_euler`/`scale` rather than `matrix_world` on
    purpose — see `sync()`. Reading a stale matrix here used to collapse every
    object in a multi-part assembly back onto the origin.
    """
    if obj.type != "MESH":
        return False
    keep_translation = obj.location.copy()
    basis = Matrix.Identity(4)
    if rotation:
        basis = obj.rotation_euler.to_matrix().to_4x4() @ basis
    if scale:
        basis = basis @ Matrix.Diagonal(obj.scale).to_4x4()
    if location:
        basis = Matrix.Translation(keep_translation) @ basis

    obj.data.transform(basis)
    obj.data.update()

    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    obj.location = (0.0, 0.0, 0.0) if location else keep_translation
    return True


def set_origin(obj, mode="bottom"):
    """Origin placement is a gameplay decision, not a modelling detail.

    bottom  — props that sit on the floor (crates, trees, characters)
    center  — pickups and anything that spins
    world   — modular kit pieces that must snap to a grid

    Unlike Blender's "Set Origin" menu item, this does NOT compensate the
    object's transform to keep the geometry where it was. It moves the mesh so
    the chosen pivot lands on the object's location. That is what a generator
    wants: after `origin="bottom"`, placing the object at z=0 puts it *on* the
    ground rather than half-buried in it.
    """
    if obj.type != "MESH":
        return False
    mesh = obj.data
    coords = [v.co for v in mesh.vertices]
    if not coords:
        return False
    if mode == "world":
        offset = Vector((0.0, 0.0, 0.0)) - obj.location
        mesh.transform(Matrix.Translation(offset))
        obj.location = (0.0, 0.0, 0.0)
        mesh.update()
        return True
    xs = [c.x for c in coords]
    ys = [c.y for c in coords]
    zs = [c.z for c in coords]
    if mode == "bottom":
        pivot = Vector(((min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5, min(zs)))
    elif mode == "center":
        pivot = Vector((
            (min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5, (min(zs) + max(zs)) * 0.5
        ))
    elif mode == "center_xy":
        pivot = Vector(((min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5, 0.0))
    else:
        raise ValueError(f"unknown origin mode '{mode}' (bottom|center|center_xy|world)")
    mesh.transform(Matrix.Translation(-pivot))
    mesh.update()
    return True


def move(obj, location=None, rotation_deg=None, scale=None):
    import math

    if location is not None:
        obj.location = Vector(location)
    if rotation_deg is not None:
        obj.rotation_euler = [math.radians(a) for a in rotation_deg]
    if scale is not None:
        obj.scale = Vector(scale) if isinstance(scale, (list, tuple)) else Vector((scale,) * 3)
    return obj


# ---------------------------------------------------------------------------
# modifiers
# ---------------------------------------------------------------------------


def apply_modifiers(obj, keep=()):
    """Evaluate the modifier stack via the depsgraph and swap in the result.

    `bpy.ops.object.modifier_apply` needs an active object and a real window;
    this does not, and gives byte-identical results run to run.
    """
    if obj.type != "MESH" or not obj.modifiers:
        return 0
    keep_set = set(keep)
    disabled = []
    for modifier in obj.modifiers:
        if modifier.name in keep_set and modifier.show_viewport:
            modifier.show_viewport = False
            disabled.append(modifier)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    new_mesh = bpy.data.meshes.new_from_object(
        evaluated, preserve_all_data_layers=True, depsgraph=depsgraph
    )
    old_mesh = obj.data
    new_mesh.name = old_mesh.name
    obj.data = new_mesh

    applied = 0
    for modifier in list(obj.modifiers):
        if modifier.name in keep_set:
            continue
        obj.modifiers.remove(modifier)
        applied += 1
    for modifier in disabled:
        modifier.show_viewport = True
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    return applied


def add_decimate(obj, ratio, name="lod_decimate"):
    modifier = obj.modifiers.new(name, "DECIMATE")
    modifier.decimate_type = "COLLAPSE"
    modifier.ratio = max(0.01, min(1.0, ratio))
    modifier.use_collapse_triangulate = True
    return modifier


def add_array(obj, count, offset, name="array"):
    modifier = obj.modifiers.new(name, "ARRAY")
    modifier.count = max(1, count)
    modifier.use_relative_offset = False
    modifier.use_constant_offset = True
    modifier.constant_offset_displace = Vector(offset)
    return modifier


def add_mirror(obj, axis=(True, False, False), name="mirror"):
    modifier = obj.modifiers.new(name, "MIRROR")
    modifier.use_axis = axis
    modifier.use_clip = True
    return modifier


def add_bevel(obj, width=0.01, segments=2, angle_deg=40.0, name="bevel"):
    import math

    modifier = obj.modifiers.new(name, "BEVEL")
    modifier.width = width
    modifier.segments = segments
    modifier.limit_method = "ANGLE"
    modifier.angle_limit = math.radians(angle_deg)
    modifier.harden_normals = False
    return modifier


def add_solidify(obj, thickness=0.02, name="solidify"):
    modifier = obj.modifiers.new(name, "SOLIDIFY")
    modifier.thickness = thickness
    modifier.offset = 0.0
    return modifier


def add_weld(obj, distance=1e-4, name="weld"):
    modifier = obj.modifiers.new(name, "WELD")
    modifier.merge_threshold = distance
    return modifier


# ---------------------------------------------------------------------------
# combining
# ---------------------------------------------------------------------------


def join(objs, name=None):
    """Merge meshes into one object without bpy.ops.object.join.

    Material slots are remapped rather than duplicated, which keeps a joined
    modular kit inside its material budget.
    """
    meshes = [o for o in objs if o.type == "MESH"]
    if not meshes:
        raise ValueError("join needs at least one mesh object")
    if len(meshes) == 1 and name is None:
        return meshes[0]
    sync()  # world matrices are read below; they must be current

    requested = sanitize(name or meshes[0].name)
    # Anchor the result on the first source's location and store geometry
    # RELATIVE to it, rather than dumping world coordinates into a mesh on an
    # object sitting at the origin. Otherwise the merged object's transform is a
    # lie, and any later set_origin drags the geometry back to (0,0,0).
    anchor = meshes[0].location.copy()
    to_local = Matrix.Translation(-anchor)
    combined = bmesh.new()
    materials: list = []
    layer_names: list[str] = []
    for source in meshes:
        for layer in source.data.uv_layers:
            if layer.name not in layer_names:
                layer_names.append(layer.name)

    for source in meshes:
        temp = bmesh.new()
        temp.from_mesh(source.data)
        for layer_name in layer_names:
            if temp.loops.layers.uv.get(layer_name) is None:
                temp.loops.layers.uv.new(layer_name)
        remap: dict[int, int] = {}
        for index, material in enumerate(source.data.materials):
            if material is None:
                remap[index] = 0
                continue
            if material not in materials:
                materials.append(material)
            remap[index] = materials.index(material)
        temp.transform(to_local @ source.matrix_world)
        for face in temp.faces:
            face.material_index = remap.get(face.material_index, 0)
        mesh_copy = bpy.data.meshes.new("_bforge_join_tmp")
        temp.to_mesh(mesh_copy)
        temp.free()
        combined.from_mesh(mesh_copy)
        bpy.data.meshes.remove(mesh_copy)

    # Free the source objects BEFORE naming the result. Otherwise the inputs
    # still hold the requested name, unique_name() dodges the collision, and a
    # recipe that asked for "sword" silently hands back "sword_1".
    for source in meshes:
        data = source.data
        bpy.data.objects.remove(source, do_unlink=True)
        if data.users == 0:
            bpy.data.meshes.remove(data)

    target_name = unique_name(requested)
    mesh = bpy.data.meshes.new(target_name)
    combined.to_mesh(mesh)
    combined.free()
    for material in materials:
        mesh.materials.append(material)
    result = bpy.data.objects.new(target_name, mesh)
    result.location = anchor
    bpy.context.scene.collection.objects.link(result)
    return result


def duplicate(obj, name=None, linked=False):
    copy = obj.copy()
    if not linked and obj.data is not None:
        copy.data = obj.data.copy()
    copy.name = unique_name(name or f"{obj.name}_copy")
    if copy.data is not None:
        copy.data.name = copy.name
    bpy.context.scene.collection.objects.link(copy)
    return copy


def delete(obj):
    data = obj.data
    is_mesh = obj.type == "MESH"
    bpy.data.objects.remove(obj, do_unlink=True)
    if is_mesh and data is not None and data.users == 0:
        bpy.data.meshes.remove(data)


def collection(name: str):
    existing = bpy.data.collections.get(name)
    if existing is None:
        existing = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(existing)
    return existing


def move_to_collection(obj, target):
    for parent in list(obj.users_collection):
        parent.objects.unlink(obj)
    target.objects.link(obj)
    return obj


def parent_to(child, parent, keep_transform=True):
    sync()
    world = child.matrix_world.copy()
    child.parent = parent
    if keep_transform:
        child.matrix_parent_inverse = parent.matrix_world.inverted()
        child.matrix_world = world
    return child


def summarize(obj) -> dict:
    from . import mesh as mesh_lib

    info = {
        "name": obj.name,
        "type": obj.type,
        "location": [round(v, 5) for v in obj.location],
        "rotation_deg": [round(a * 57.2957795, 3) for a in obj.rotation_euler],
        "scale": [round(v, 5) for v in obj.scale],
    }
    if obj.type == "MESH":
        info.update(
            {
                "triangles": mesh_lib.tri_count(obj),
                "vertices": len(obj.data.vertices),
                "faces": len(obj.data.polygons),
                "materials": [m.name for m in obj.data.materials if m],
                "uv_layers": [layer.name for layer in obj.data.uv_layers],
                "bounds": mesh_lib.bounds(obj),
                "modifiers": [m.type for m in obj.modifiers],
            }
        )
    elif obj.type == "ARMATURE":
        info["bones"] = [b.name for b in obj.data.bones]
    return info
