"""Generate the bootstrap sample master asset (crate_a.blend).

Whitelisted studio script — the ONLY supported way scripts create/modify
.blend files headlessly (ADR 0006). Produces a clean, convention-correct prop:
metric units, applied transforms, origin at base, UVs, single material,
explicit -col collision proxy.

Run: blender -b -P tools/blender/make_sample_asset.py -- --out=path/crate_a.blend
"""

import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bpy_common import arg_value, emit, script_args  # noqa: E402


def clean_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


def make_crate() -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    crate = bpy.context.active_object
    crate.name = "crate_a"
    crate.data.name = "crate_a"
    crate.scale = (0.5, 0.5, 0.4)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # Bevel for non-trivial geometry (still far under budget).
    bevel = crate.modifiers.new("bevel", "BEVEL")
    bevel.width = 0.03
    bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)

    # Origin at base center, object at world origin.
    min_z = min(v.co.z for v in crate.data.vertices)
    for vertex in crate.data.vertices:
        vertex.co.z -= min_z
    crate.location = (0.0, 0.0, 0.0)

    # UVs.
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")

    material = bpy.data.materials.new("crate_wood")
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.42, 0.27, 0.13, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.82
    crate.data.materials.append(material)
    return crate


def make_collision(crate: bpy.types.Object) -> None:
    # Godot glTF convention: a sibling named <name>-col imports as collision.
    dims = crate.dimensions
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    col = bpy.context.active_object
    col.name = "crate_a-col"
    col.data.name = "crate_a-col"
    col.scale = (dims.x / 2.0, dims.y / 2.0, dims.z / 2.0)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    min_z = min(v.co.z for v in col.data.vertices)
    for vertex in col.data.vertices:
        vertex.co.z -= min_z
    col.location = (0.0, 0.0, 0.0)
    col.display_type = "WIRE"


def main() -> None:
    args = script_args()
    out_path = arg_value(args, "out")
    if not out_path:
        emit("MAKE_SAMPLE_RESULT", {"ok": False, "error": "--out= required"})
        sys.exit(2)
    clean_scene()
    crate = make_crate()
    make_collision(crate)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out_path), compress=True)
    emit(
        "MAKE_SAMPLE_RESULT",
        {
            "ok": True,
            "file": out_path,
            "objects": sorted(o.name for o in bpy.data.objects),
            "triangles": sum(len(p.vertices) - 2 for p in crate.data.polygons),
        },
    )


main()
