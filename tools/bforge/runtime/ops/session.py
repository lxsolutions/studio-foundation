"""Session ops: scene lifecycle, inspection, snapshots, save/open."""

from __future__ import annotations

import bpy
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from lib import uvs as uv_lib
from registry import OpError, op

_SNAPSHOTS: dict[str, bytes] = {}


def reset_scene(ctx, unit_scale=1.0):
    """Deterministic empty scene in metric units — called at daemon boot too."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = unit_scale
    scene.unit_settings.length_unit = "METERS"
    # EEVEE was renamed to EEVEE Next in Blender 4.2; pick whichever exists.
    engines = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    scene.render.engine = (
        "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    )
    scene.render.fps = 30
    scene.frame_start = 1
    scene.frame_end = 1
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.05, 0.055, 0.065, 1.0)
        background.inputs["Strength"].default_value = 1.0
    return scene


@op(
    "session.reset",
    summary="Clear the scene to a deterministic empty metric-unit state. Start every new asset with this.",
    params={"unit_scale": ("num", 1.0, "Blender unit scale; keep 1.0 = 1 metre for game engines")},
    tags=["session"],
)
def session_reset(ctx, unit_scale):
    reset_scene(ctx, unit_scale)
    return {"reset": True, "unit_scale": unit_scale}


@op(
    "session.info",
    summary="Full scene report: every object with triangle counts, materials, UVs and bounds. Cheap; call it often.",
    params={"detail": ("enum:summary|full", "summary", "'full' adds per-object UV statistics")},
    tags=["session", "inspect"],
    mutates=False,
)
def session_info(ctx, detail):
    objects = []
    total_tris = 0
    for obj in sorted(bpy.context.scene.objects, key=lambda o: o.name):
        info = scene_lib.summarize(obj)
        if obj.type == "MESH":
            total_tris += info["triangles"]
            if detail == "full":
                info["uv"] = uv_lib.stats(obj)
        objects.append(info)
    materials = sorted({m.name for o in scene_lib.mesh_objects() for m in o.data.materials if m})
    return {
        "objects": objects,
        "object_count": len(objects),
        "total_triangles": total_tris,
        "materials": materials,
        "images": [i.name for i in bpy.data.images if i.name != "Render Result"],
        "actions": [a.name for a in bpy.data.actions],
    }


@op(
    "session.snapshot",
    summary="Save an in-memory scene checkpoint you can roll back to. Take one before any risky or destructive edit.",
    params={"name": ("str", "default", "Checkpoint label")},
    tags=["session"],
)
def session_snapshot(ctx, name):
    path = ctx.out_dir / "_snapshots" / f"{scene_lib.sanitize(name)}.blend"
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True, compress=True)
    _SNAPSHOTS[name] = path.read_bytes()
    return {"snapshot": name, "bytes": len(_SNAPSHOTS[name])}


@op(
    "session.restore",
    summary="Roll the scene back to a snapshot taken earlier in this session.",
    params={"name": ("str", "default", "Checkpoint label passed to session.snapshot")},
    tags=["session"],
)
def session_restore(ctx, name):
    if name not in _SNAPSHOTS:
        raise OpError(
            f"no snapshot named '{name}'. Taken so far: {sorted(_SNAPSHOTS) or '(none)'}"
        )
    path = ctx.out_dir / "_snapshots" / f"{scene_lib.sanitize(name)}.blend"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_SNAPSHOTS[name])
    bpy.ops.wm.open_mainfile(filepath=str(path))
    return {"restored": name, "objects": len(bpy.context.scene.objects)}


@op(
    "session.save",
    summary="Write the scene to a .blend master file (the committed source of truth in ADR 0006).",
    params={
        "path": ("path", "asset.blend", "Output .blend path; relative paths land under the output dir"),
        "compress": ("bool", True, "Zstd-compress the .blend"),
    },
    tags=["session", "io"],
)
def session_save(ctx, path, compress):
    target = ctx.out_path(path, ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(target), copy=True, compress=compress)
    return {"path": str(target), "rel": ctx.rel(target), "bytes": target.stat().st_size}


@op(
    "session.open",
    summary="Load an existing .blend so you can inspect, fix or extend an asset instead of rebuilding it.",
    params={"path": ("path", None, "Path to a .blend file")},
    tags=["session", "io"],
)
def session_open(ctx, path):
    target = ctx.resolve(path)
    if not target.is_file():
        raise OpError(f"no .blend at {target}")
    bpy.ops.wm.open_mainfile(filepath=str(target))
    return {"opened": str(target), "objects": [o.name for o in bpy.context.scene.objects]}


@op(
    "session.import",
    summary="Import an existing glTF/GLB, OBJ, FBX or .blend into the current scene. Use this to inspect, critique, fix or extend assets a game already ships — not just ones you generated.",
    params={
        "path": ("path", None, "File to import (.glb/.gltf/.obj/.fbx/.blend)"),
        "prefix": ("str", "", "Rename imported objects with this prefix (keeps names snake_case)"),
        "location": ("vec3", [0.0, 0.0, 0.0], "Offset to place the import at"),
        "reset_first": ("bool", False, "Clear the scene before importing"),
    },
    tags=["session", "io"],
)
def session_import(ctx, path, prefix, location, reset_first):
    target = ctx.resolve(path)
    if not target.is_file():
        raise OpError(f"no file at {target}")
    if reset_first:
        reset_scene(ctx)

    before = {o.name for o in bpy.context.scene.objects}
    suffix = target.suffix.lower()
    try:
        if suffix in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=str(target))
        elif suffix == ".obj":
            bpy.ops.wm.obj_import(filepath=str(target))
        elif suffix == ".fbx":
            bpy.ops.import_scene.fbx(filepath=str(target))
        elif suffix == ".blend":
            # Append every object from the file's scenes rather than opening it,
            # so an import composes with whatever is already loaded.
            with bpy.data.libraries.load(str(target), link=False) as (source, dest):
                dest.objects = list(source.objects)
            for obj in dest.objects:
                if obj is not None:
                    bpy.context.scene.collection.objects.link(obj)
        else:
            raise OpError(
                f"cannot import '{suffix}' — supported: .glb .gltf .obj .fbx .blend"
            )
    except RuntimeError as exc:
        raise OpError(f"import failed for {target.name}: {exc}") from exc

    imported = [o for o in bpy.context.scene.objects if o.name not in before]
    if not imported:
        raise OpError(f"{target.name} imported no objects — the file may be empty")

    for obj in imported:
        if prefix:
            obj.name = scene_lib.unique_name(f"{prefix}_{obj.name}")
        elif not scene_lib.check_name(obj.name):
            obj.name = scene_lib.unique_name(obj.name)
        if obj.parent is None and any(location):
            obj.location = [obj.location[i] + location[i] for i in range(3)]

    meshes = [o for o in imported if o.type == "MESH"]
    return {
        "path": str(target),
        "objects": [o.name for o in imported],
        "meshes": len(meshes),
        "triangles": sum(mesh_lib.tri_count(o) for o in meshes),
        "materials": sorted({m.name for o in meshes for m in o.data.materials if m}),
        "armatures": [o.name for o in imported if o.type == "ARMATURE"],
        "actions": [a.name for a in bpy.data.actions],
    }


@op(
    "object.list",
    summary="List object names in the scene, optionally filtered by a name prefix.",
    params={"prefix": ("str", "", "Only return names starting with this")},
    tags=["inspect"],
    mutates=False,
)
def object_list(ctx, prefix):
    names = sorted(
        o.name for o in bpy.context.scene.objects if not prefix or o.name.startswith(prefix)
    )
    return {"objects": names, "count": len(names)}


@op(
    "object.inspect",
    summary="Detailed report for one object: topology, UV quality, texel density, materials, bounds.",
    params={
        "name": ("str", None, "Object name"),
        "texture_size": ("int", 1024, "Texture resolution used for the texel-density figure"),
    },
    tags=["inspect"],
    mutates=False,
)
def object_inspect(ctx, name, texture_size):
    obj = _get(name)
    info = scene_lib.summarize(obj)
    if obj.type == "MESH":
        info["uv"] = uv_lib.stats(obj, texture_size=texture_size)
        info["uv"]["islands"] = uv_lib.uv_islands(obj)
        info["uv"]["overlap_ratio"] = uv_lib.overlap_estimate(obj)
    return info


@op(
    "object.transform",
    summary="Move, rotate or scale an object. Rotation is in degrees.",
    params={
        "name": ("str", None, "Object name"),
        "location": ("vec3", None, "World position in metres"),
        "rotation": ("vec3", None, "Euler XYZ rotation in degrees"),
        "scale": ("vec3", None, "Per-axis scale multiplier"),
        "apply": ("bool", False, "Bake rotation+scale into mesh data (required before export)"),
    },
    tags=["transform"],
)
def object_transform(ctx, name, location, rotation, scale, apply):
    obj = _get(name)
    scene_lib.move(obj, location, rotation, scale)
    if apply:
        scene_lib.apply_transforms(obj)
    return scene_lib.summarize(obj)


@op(
    "object.origin",
    summary="Set an object's pivot. Use 'bottom' for floor props, 'center' for pickups, 'world' for modular kit pieces.",
    params={
        "name": ("str", None, "Object name"),
        "mode": ("enum:bottom|center|center_xy|world", "bottom", "Where the pivot goes"),
    },
    tags=["transform"],
)
def object_origin(ctx, name, mode):
    obj = _get(name)
    scene_lib.set_origin(obj, mode)
    return scene_lib.summarize(obj)


@op(
    "object.duplicate",
    summary="Copy an object, optionally placing the copy in one call.",
    params={
        "name": ("str", None, "Source object"),
        "new_name": ("str", "", "Name for the copy (auto-derived when empty)"),
        "location": ("vec3", None, "Where to put the copy"),
        "rotation": ("vec3", None, "Copy's rotation in degrees"),
    },
    tags=["transform"],
)
def object_duplicate(ctx, name, new_name, location, rotation):
    obj = _get(name)
    copy = scene_lib.duplicate(obj, new_name or None)
    scene_lib.move(copy, location, rotation, None)
    return scene_lib.summarize(copy)


@op(
    "object.join",
    summary="Merge several meshes into one object, de-duplicating material slots. Fewer objects means fewer draw calls.",
    params={
        "names": ("str[]", None, "Objects to merge (the first one's transform wins)"),
        "into": ("str", "", "Name for the merged result"),
    },
    tags=["transform"],
)
def object_join(ctx, names, into):
    objs = [_get(n) for n in names]
    result = scene_lib.join(objs, into or None)
    return scene_lib.summarize(result)


@op(
    "object.delete",
    summary="Remove objects from the scene.",
    params={"names": ("str[]", None, "Objects to delete")},
    tags=["transform"],
)
def object_delete(ctx, names):
    removed = []
    for name in names:
        obj = _get(name)
        removed.append(obj.name)
        scene_lib.delete(obj)
    return {"deleted": removed}


@op(
    "object.rename",
    summary="Rename an object, coercing the new name to the studio's snake_case convention.",
    params={"name": ("str", None, "Current name"), "to": ("str", None, "Desired name")},
    tags=["transform"],
)
def object_rename(ctx, name, to):
    obj = _get(name)
    target = scene_lib.unique_name(to)
    obj.name = target
    if obj.data is not None:
        obj.data.name = target
    return {"renamed": target}


@op(
    "object.parent",
    summary="Parent one object to another, keeping the child's world transform. Entity hierarchy is how World IR parts become a GLB node tree.",
    params={
        "name": ("str", None, "Child object"),
        "parent": ("str", None, "Parent object"),
    },
    tags=["transform"],
)
def object_parent(ctx, name, parent):
    obj = _get(name)
    par = _get(parent)
    if obj is par:
        raise OpError(f"'{name}' cannot parent itself")
    ancestor = par
    while ancestor is not None:
        if ancestor is obj:
            raise OpError(f"parenting '{name}' under '{parent}' would create a cycle")
        ancestor = ancestor.parent
    world = obj.matrix_world.copy()
    obj.parent = par
    obj.matrix_world = world
    return {"name": obj.name, "parent": par.name}


@op(
    "object.shade",
    summary="Set smooth or flat shading. Smooth shading with an angle threshold is what makes curved props read as curved.",
    params={
        "name": ("str", None, "Object name"),
        "mode": ("enum:smooth|flat", "smooth", "Shading mode"),
        "angle": ("num", 35.0, "Edges sharper than this angle (degrees) stay hard"),
    },
    tags=["shading"],
)
def object_shade(ctx, name, mode, angle):
    obj = _get(name)
    if obj.type != "MESH":
        raise OpError(f"'{name}' is a {obj.type}, not a mesh")
    if mode == "flat":
        mesh_lib.shade_flat(obj)
        return {"mode": "flat"}
    sharp = mesh_lib.shade_auto_smooth(obj, angle)
    return {"mode": "smooth", "angle": angle, "sharp_edges": sharp}


def _get(name: str):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
