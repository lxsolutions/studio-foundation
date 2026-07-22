"""Generate The Deep's master asset set headlessly (ADR 0006).

Whitelisted studio script — the ONLY supported way scripts create/modify
.blend files headlessly. Produces convention-correct props for the mining
cavern: metric units, applied transforms, origin at base, single material per
prop, and an explicit -col collision proxy each.

Set: deep_ore_boulder, deep_crystal, deep_pillar.

Run: blender -b -P tools/blender/make_deep_assets.py -- --out=path/
"""

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


def mat(name: str, color: tuple, emission: float = 0.0) -> bpy.types.Material:
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.85
    if emission > 0.0:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission
    return m


def finish(obj: bpy.types.Object, name: str, material: bpy.types.Material) -> None:
    obj.name = name
    obj.data.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if material:
        obj.data.materials.append(material)
    # Collision proxy: a slightly-shrunk duplicate marked -col (studio convention).
    bpy.ops.object.duplicate()
    col = bpy.context.active_object
    col.name = name + "-col"
    col.data = obj.data.copy()
    col.scale = (0.95, 0.95, 0.95)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    col.display_type = "WIRE"
    col.hide_render = True
    # Re-select the visual as active for the next op.
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    col.select_set(False)


def make_ore_boulder(material: bpy.types.Material) -> None:
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.7)
    ob = bpy.context.active_object
    # Flatten the base so it sits on the cavern floor (origin at base).
    ob.scale = (1.0, 1.0, 0.8)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    ob.location.z = 0.0
    finish(ob, "deep_ore_boulder", material)


def make_crystal(material: bpy.types.Material) -> None:
    bpy.ops.mesh.primitive_cone_add(vertices=6, radius1=0.3, radius2=0.05, depth=1.4)
    ob = bpy.context.active_object
    ob.location.z = 0.7  # origin at base
    finish(ob, "deep_crystal", material)


def make_pillar(material: bpy.types.Material) -> None:
    bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=0.35, depth=3.0)
    ob = bpy.context.active_object
    ob.location.z = 1.5  # origin at base
    # Bevel the top/bottom edges so it reads as worked stone, not a raw primitive.
    bevel = ob.modifiers.new("bevel", "BEVEL")
    bevel.width = 0.05
    bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    finish(ob, "deep_pillar", material)


def main() -> None:
    args = script_args()
    out_dir = arg_value(args, "out", os.getcwd())
    os.makedirs(out_dir, exist_ok=True)

    made = []
    # Materials are created AFTER each clean_scene() (the reset would free them).
    for name, fn, spec in [
        ("deep_ore_boulder", make_ore_boulder, ("deep_ore", (0.85, 0.55, 0.15), 0.6)),
        ("deep_crystal", make_crystal, ("deep_crystal", (0.35, 0.6, 0.95), 1.2)),
        ("deep_pillar", make_pillar, ("deep_stone", (0.28, 0.26, 0.3), 0.0)),
    ]:
        clean_scene()
        m = mat(spec[0], spec[1], emission=spec[2])
        fn(m)
        path = os.path.join(out_dir, name + ".blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        made.append(path)
        emit("MAKE_SAMPLE_RESULT", f"{name} -> {path}")

    emit("MAKE_SAMPLE_RESULT", f"set complete: {len(made)} assets in {out_dir}")


if __name__ == "__main__":
    main()
