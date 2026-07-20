"""Export the open .blend to GLB with studio settings.

Run: blender -b file.blend -P tools/blender/export_gltf.py -- --out=path/x.glb
Emits EXPORT_RESULT json line. Generated output only — never writes back to
the master file.
"""

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bpy_common import arg_value, emit, script_args  # noqa: E402


def main() -> None:
    args = script_args()
    out_path = arg_value(args, "out")
    if not out_path:
        emit("EXPORT_RESULT", {"ok": False, "error": "--out= required"})
        sys.exit(2)
    out_abs = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)

    try:
        bpy.ops.export_scene.gltf(
            filepath=out_abs,
            export_format="GLB",
            export_apply=True,          # apply modifiers
            export_yup=True,            # Godot expects Y-up glTF
            export_texcoords=True,
            export_normals=True,
            export_materials="EXPORT",
            export_cameras=False,
            export_lights=False,
            export_extras=True,         # custom props travel to the engine
            export_animations=True,
            export_skins=True,
        )
    except Exception as exc:  # surface the real Blender error to the artist
        emit("EXPORT_RESULT", {"ok": False, "error": str(exc)})
        sys.exit(1)

    size = os.path.getsize(out_abs) if os.path.isfile(out_abs) else 0
    emit(
        "EXPORT_RESULT",
        {"ok": size > 0, "file": out_path, "bytes": size},
    )
    sys.exit(0 if size > 0 else 1)


main()
