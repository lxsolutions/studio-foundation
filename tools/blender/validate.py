"""Validate a master .blend against studio conventions (ADR 0006).

Run: blender -b file.blend -P tools/blender/validate.py -- --meta=path/x.meta.json
Emits one ASSET_VALIDATE_RESULT json line; exit code 0 only when no errors.
Failure messages are written for artists AND agents: say what is wrong and how
to fix it in Blender terms.
"""

import json
import os
import re
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bpy_common import arg_value, emit, script_args  # noqa: E402

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(-col|-convcol|_lod[0-9])?$")
ALLOWED_NODES = {
    "BSDF_PRINCIPLED", "TEX_IMAGE", "NORMAL_MAP", "UVMAP", "OUTPUT_MATERIAL",
    "MIX", "MIX_RGB", "SEPARATE_COLOR", "COMBINE_COLOR", "MAPPING", "TEX_COORD",
    "VERTEX_COLOR", "ATTRIBUTE", "VALUE", "RGB",
}

checks: list[dict] = []


def check(check_id: str, ok: bool, message: str, level: str = "error") -> None:
    checks.append({
        "id": check_id,
        "level": "ok" if ok else level,
        "msg": message,
    })


def mesh_objects() -> list:
    return [o for o in bpy.data.objects if o.type == "MESH"]


def render_meshes() -> list:
    return [o for o in mesh_objects() if "-col" not in o.name and "-convcol" not in o.name]


def main() -> None:
    args = script_args()
    meta_path = arg_value(args, "meta")
    meta: dict = {}
    if meta_path and os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
    budgets = meta.get("budgets", {})

    scene = bpy.context.scene
    check(
        "units",
        scene.unit_settings.system == "METRIC" and abs(scene.unit_settings.scale_length - 1.0) < 1e-6,
        "Scene units must be Metric with Unit Scale 1.0 (Scene Properties > Units)",
    )

    for obj in bpy.data.objects:
        check(
            f"naming:{obj.name}",
            NAME_RE.match(obj.name) is not None,
            f"Object '{obj.name}' must be snake_case (optional -col/-convcol/_lodN suffix)",
        )

    for obj in mesh_objects():
        rot_zero = all(abs(a) < 1e-5 for a in obj.rotation_euler)
        scale_one = all(abs(s - 1.0) < 1e-5 for s in obj.scale)
        check(
            f"transforms:{obj.name}",
            rot_zero and scale_one,
            f"'{obj.name}' has unapplied rotation/scale — Object > Apply > Rotation & Scale",
        )

    roots = [o for o in render_meshes() if o.parent is None]
    for obj in roots:
        at_origin = all(abs(c) < 1e-4 for c in obj.location)
        check(
            f"origin:{obj.name}",
            at_origin,
            f"Root object '{obj.name}' must sit at the world origin (Alt+G)",
        )

    for obj in render_meshes():
        check(
            f"uvs:{obj.name}",
            len(obj.data.uv_layers) >= 1,
            f"'{obj.name}' has no UV map — unwrap it (UV > Smart UV Project is fine)",
        )

    material_budget = int(budgets.get("materials", 2))
    material_count = len({m.name for o in render_meshes() for m in o.data.materials if m})
    check(
        "materials",
        material_count <= material_budget,
        f"{material_count} materials exceeds budget {material_budget} (merge materials)",
    )

    tri_budget = int(budgets.get("triangles", 2000))
    triangles = 0
    for obj in render_meshes():
        mesh = obj.data
        mesh.calc_loop_triangles()
        triangles += len(mesh.loop_triangles)
    check(
        "triangles",
        triangles <= tri_budget,
        f"{triangles} triangles exceeds budget {tri_budget} (decimate or simplify)",
    )

    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    for armature in armatures:
        bone_names = [b.name for b in armature.data.bones]
        bad = [b for b in bone_names if not re.match(r"^[a-z][a-z0-9_.]*$", b)]
        check(
            f"skeleton:{armature.name}",
            not bad,
            f"Bones must be snake_case: {bad[:5]}",
        )
        root_bones = [b for b in armature.data.bones if b.parent is None]
        check(
            f"skeleton_root:{armature.name}",
            len(root_bones) == 1,
            f"Armature '{armature.name}' must have exactly one root bone (has {len(root_bones)})",
        )

    for action in bpy.data.actions:
        check(
            f"anim_naming:{action.name}",
            re.match(r"^[a-z][a-z0-9_]*$", action.name) is not None,
            f"Action '{action.name}' must be snake_case (e.g. walk_forward)",
        )

    if meta.get("collision_policy", "explicit") == "explicit":
        has_col = any("-col" in o.name or "-convcol" in o.name for o in mesh_objects())
        check(
            "collision",
            has_col,
            "collision_policy=explicit but no '<name>-col' proxy object exists",
        )

    if meta.get("lod_policy", "auto") == "explicit":
        has_lod = any(re.search(r"_lod[1-9]$", o.name) for o in mesh_objects())
        check("lods", has_lod, "lod_policy=explicit but no '*_lod1' objects exist")

    for image in bpy.data.images:
        if image.source == "FILE" and not image.packed_file:
            exists = os.path.isfile(bpy.path.abspath(image.filepath))
            check(
                f"texture:{image.name}",
                exists,
                f"Texture '{image.name}' missing on disk ({image.filepath}) — pack it (File > External Data) or fix the path",
            )

    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        bad_nodes = sorted({
            node.type for node in material.node_tree.nodes
            if node.type not in ALLOWED_NODES and node.type != "FRAME" and node.type != "REROUTE"
        })
        check(
            f"shader:{material.name}",
            not bad_nodes,
            f"Material '{material.name}' uses nodes glTF cannot export: {bad_nodes} — bake to textures first",
        )

    check(
        "provenance",
        bool(meta.get("asset_id")) and bool(meta.get("license")) and bool(meta.get("provenance")),
        "Sidecar .meta.json missing or incomplete (asset_id/license/provenance) — see shared/schemas/asset-meta.schema.json",
    )

    errors = [c for c in checks if c["level"] == "error"]
    emit(
        "ASSET_VALIDATE_RESULT",
        {
            "ok": not errors,
            "file": bpy.data.filepath,
            "triangles": triangles,
            "materials": material_count,
            "checks": checks,
        },
    )
    sys.exit(0 if not errors else 1)


main()
