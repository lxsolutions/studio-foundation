"""Ingest & finish: take an external mesh (neural image-to-3D output, a scan,
a download) to game-ready inside the enforced loop.

Neural generators (TRELLIS, Hunyuan3D, Tripo) produce dense, textured
triangle soup. Soup does not ship: it rigs badly, skins worse, and blows
budgets. The finishing line is retopo (quads at a target face count) ->
fresh UVs -> bake the source's textures and detail across -> the same
quality gate every bforge asset passes. The generator can change next
month; the finishing line is generator-agnostic on purpose.
"""

from __future__ import annotations

import bpy
from lib import mat as mat_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from lib import uvs as uv_lib
from registry import OpError, op


def _get(name):
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH":
        raise OpError(f"no mesh object named '{name}'")
    return obj


def _activate(obj, select_others=()):
    view_layer = bpy.context.view_layer
    previous = view_layer.objects.active
    for other in bpy.context.scene.objects:
        other.select_set(other in select_others or other is obj)
    view_layer.objects.active = obj
    return previous


@op(
    "mesh.retopo",
    summary="Rebuild a dense triangle soup (neural/scan import) as a clean all-quad mesh via voxel remesh, in place. Robust on any input — open seams, overlapping shells, interior garbage all get swallowed by the voxel grid. Destroys UVs and skin weights (unwrap again after; re-rig if it had a rig). Pair with bake.transfer to move the source's textures and detail across.",
    params={
        "name": ("str", None, "Mesh object to retopologize (modified in place)"),
        "voxel_size": ("num", 0.0, "Voxel edge in metres — 0 picks it from the bounds (~1/120 of the longest side). Smaller keeps more detail at more quads"),
        "adaptivity": ("num", 0.02, "Quad adaptivity 0..0.2 — higher spends quads only where curvature demands"),
        "strip_rig": ("bool", True, "Retopo destroys skin weights: unparent, drop armature modifiers, and apply transforms first (neural/scan inputs arrive unrigged anyway)"),
    },
    tags=["mesh"],
)
def mesh_retopo(ctx, name, voxel_size, adaptivity, strip_rig):
    obj = _get(name)
    before_tris = mesh_lib.tri_count(obj)

    rigged = bool(obj.find_armature()) or any(m.type == "ARMATURE" for m in obj.modifiers)
    if rigged and not strip_rig:
        raise OpError(
            f"'{name}' is rigged — retopo destroys skin weights. Pass strip_rig=True "
            "to unparent, strip the armature modifier, and apply transforms first."
        )
    if rigged or obj.parent or obj.modifiers:
        world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = world
        obj.modifiers.clear()
        scene_lib.apply_transforms(obj)

    if not voxel_size:
        longest = max(obj.dimensions) or 1.0
        voxel_size = longest / 120.0
    data = obj.data
    data.remesh_voxel_size = float(voxel_size)
    data.remesh_voxel_adaptivity = max(0.0, min(0.2, float(adaptivity)))
    data.use_remesh_fix_poles = True

    previous = _activate(obj)
    bpy.ops.object.voxel_remesh()
    if previous:
        bpy.context.view_layer.objects.active = previous
    for other in bpy.context.scene.objects:
        other.select_set(False)

    after_tris = mesh_lib.tri_count(obj)
    ctx.note(
        f"'{name}' voxel-retopologized {before_tris} -> {after_tris} tris at "
        f"{voxel_size * 1000:.0f}mm voxels. UVs and weights were destroyed: "
        "run uv.unwrap, then bake.transfer to bring the source's textures across."
    )
    return {
        "object": obj.name,
        "triangles_before": before_tris,
        "triangles_after": after_tris,
        "voxel_size_m": round(voxel_size, 4),
        "quads": True,
    }


@op(
    "bake.transfer",
    summary="Bake textures from a source mesh (the neural soup, the high-poly sculpt) onto a target mesh (the retopo'd game mesh) via selected-to-active projection: base colour and tangent-space normal map. This is the AAA high->low transfer step — the game mesh keeps the source's surface richness at a fraction of the triangles.",
    params={
        "source": ("str", None, "Source mesh object (textured / high-poly)"),
        "target": ("str", None, "Target mesh object (retopo'd, with fresh UVs)"),
        "maps": ("str[]", ["base_color", "normal"], "Which maps to bake: base_color, normal"),
        "size": ("int", 1024, "Bake resolution (square)"),
        "ray_distance": ("num", 0.05, "Projection ray length in metres — raise if the bake misses recessed detail, lower if it picks up neighbouring parts"),
        "samples": ("int", 16, "Cycles samples per texel"),
    },
    tags=["material", "mesh"],
)
def bake_transfer(ctx, source, target, maps, size, ray_distance, samples):
    src = _get(source)
    dst = _get(target)
    if not dst.data.uv_layers:
        raise OpError(f"'{target}' has no UVs — unwrap it first (uv.unwrap)")

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = max(1, int(samples))
    scene.render.bake.use_selected_to_active = True
    scene.render.bake.max_ray_distance = float(ray_distance)

    mat = dst.data.materials[0] if dst.data.materials else None
    if mat is None:
        mat = mat_lib.principled(f"m_{dst.name}_transfer", color="#808080")
        dst.data.materials.append(mat)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    principled = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)

    baked = []
    for kind in maps:
        image = bpy.data.images.new(
            f"{dst.name}_{kind}", width=int(size), height=int(size), alpha=False,
            float_buffer=False,
        )
        image.colorspace_settings.name = "Non-Color" if kind == "normal" else "sRGB"
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = image
        nodes.active = tex_node
        tex_node.select = True

        previous = _activate(dst, select_others=(src,))
        if kind == "base_color":
            scene.render.bake.use_pass_direct = False
            scene.render.bake.use_pass_indirect = False
            scene.render.bake.use_pass_color = True
            bpy.ops.object.bake(type="DIFFUSE")
            if principled:
                links.new(tex_node.outputs["Color"], principled.inputs["Base Color"])
        elif kind == "normal":
            bpy.ops.object.bake(type="NORMAL")
            if principled:
                normal_node = nodes.new("ShaderNodeNormalMap")
                links.new(tex_node.outputs["Color"], normal_node.inputs["Color"])
                links.new(normal_node.outputs["Normal"], principled.inputs["Normal"])
        else:
            raise OpError(f"unknown bake map '{kind}' (base_color | normal)")
        tex_node.select = False
        baked.append(kind)

    # Pack every baked image so the GLB carries the textures self-contained,
    # then drop the source-node selection state back.
    for image in bpy.data.images:
        if image.name.startswith(f"{dst.name}_") and not image.packed_file:
            image.pack()
    for other in bpy.context.scene.objects:
        other.select_set(False)

    ctx.note(
        f"baked {', '.join(baked)} from '{source}' onto '{target}' at {size}px. "
        "Hide or delete the source before export (session.delete), or export "
        f"objects=['{target}'] explicitly."
    )
    return {"object": dst.name, "baked": baked, "size": int(size)}
