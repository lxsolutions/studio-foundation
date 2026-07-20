"""Render a deterministic thumbnail/turntable preview of the open .blend.

Run: blender -b file.blend -P tools/blender/render_preview.py -- --out=x.png [--frames=1]
Uses the Workbench engine (CPU-stable, no GPU context needed headless).
--frames=8 renders a turntable sequence x_000.png … x_007.png.
"""

import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bpy_common import arg_value, emit, script_args  # noqa: E402


def frame_bounds() -> tuple:
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and "-col" not in o.name]
    if not meshes:
        return ((0, 0, 0), 1.0)
    from mathutils import Vector

    minimum = Vector((1e9, 1e9, 1e9))
    maximum = Vector((-1e9, -1e9, -1e9))
    for obj in meshes:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            minimum = Vector(map(min, minimum, world))
            maximum = Vector(map(max, maximum, world))
    center = (minimum + maximum) / 2
    radius = max((maximum - minimum).length / 2, 0.5)
    return (center, radius)


def main() -> None:
    args = script_args()
    out_path = arg_value(args, "out")
    frames = int(arg_value(args, "frames", "1"))
    if not out_path:
        emit("PREVIEW_RESULT", {"ok": False, "error": "--out= required"})
        sys.exit(2)
    out_abs = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.film_transparent = True

    center, radius = frame_bounds()
    camera_data = bpy.data.cameras.new("preview_cam")
    camera = bpy.data.objects.new("preview_cam", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera

    written = []
    for index in range(max(frames, 1)):
        angle = (index / max(frames, 1)) * math.tau + math.radians(35)
        distance = radius * 2.6
        camera.location = (
            center[0] + distance * math.cos(angle),
            center[1] + distance * math.sin(angle),
            center[2] + radius * 1.1,
        )
        direction = (
            center[0] - camera.location[0],
            center[1] - camera.location[1],
            center[2] - camera.location[2],
        )
        from mathutils import Vector

        camera.rotation_euler = Vector(direction).to_track_quat("-Z", "Y").to_euler()
        if frames > 1:
            base, ext = os.path.splitext(out_abs)
            target = f"{base}_{index:03d}{ext}"
        else:
            target = out_abs
        scene.render.filepath = target
        bpy.ops.render.render(write_still=True)
        written.append(os.path.basename(target))

    emit("PREVIEW_RESULT", {"ok": bool(written), "files": written})


main()
