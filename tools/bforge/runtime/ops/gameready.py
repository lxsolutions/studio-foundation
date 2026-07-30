"""The steps between "a nice mesh" and "an asset that ships".

LODs, collision proxies, platform budgets, texture atlasing and pivot hygiene.
These are unglamorous and they are exactly what separates an AI-generated model
from a usable game asset — an un-LOD'd, un-collided 40k-triangle prop is not an
asset, it is a screenshot.

Collision proxy naming follows the studio convention that the engine importer
and `tools/blender/validate.py` already understand: `<name>-col` for a concave
trimesh proxy, `<name>-convcol` for a convex one.
"""

from __future__ import annotations

import math

import bmesh
import bpy
from lib import finish as finish_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from lib import uvs as uv_lib
from mathutils import Vector
from registry import OpError, op

# Triangle ceilings per platform tier and asset class. Drawn from what actually
# ships: mobile budgets track the low end of current mid-range Android, browser
# sits between mobile and desktop because download size bites before GPU does.
PROFILES = {
    "mobile_low":    {"prop": 300,  "character": 1500,  "environment": 2000,  "hero": 3000,  "texture": 512},
    "mobile_high":   {"prop": 800,  "character": 4000,  "environment": 6000,  "hero": 9000,  "texture": 1024},
    "browser_webgl": {"prop": 900,  "character": 5000,  "environment": 8000,  "hero": 12000, "texture": 1024},
    "browser_webgpu":{"prop": 1500, "character": 9000,  "environment": 15000, "hero": 25000, "texture": 2048},
    "desktop_high":  {"prop": 5000, "character": 40000, "environment": 60000, "hero": 120000,"texture": 4096},
}


@op(
    "gameready.lod",
    summary="Generate a level-of-detail chain by decimation. Ratios are chosen so each level roughly halves the triangle count, which is what LOD switching expects. Named <object>_lod1..N to match the studio import convention.",
    params={
        "name": ("str", None, "Source object (becomes LOD0)"),
        "levels": ("int", 3, "Number of reduced levels to create"),
        "ratios": ("num[]", [], "Explicit decimation ratios, e.g. [0.5, 0.25, 0.1]. Empty auto-generates"),
        "keep_uvs": ("bool", True, "Preserve UV layout while decimating"),
        "layout": ("bool", False, "Offset each LOD along X for side-by-side review"),
    },
    tags=["gameready"],
)
def gameready_lod(ctx, name, levels, ratios, keep_uvs, layout):
    obj = _get(name)
    if obj.type != "MESH":
        raise OpError(f"'{name}' is a {obj.type}, not a mesh")
    base_tris = mesh_lib.tri_count(obj)
    if base_tris < 60:
        ctx.note(
            f"'{obj.name}' is only {base_tris} triangles — LODs will not pay for themselves "
            "below roughly 500. Consider skipping LOD for this asset."
        )
    chain = list(ratios) if ratios else [0.5 ** (i + 1) for i in range(max(1, levels))]
    width = mesh_lib.bounds(obj)["size"][0]
    made = [{"level": 0, "name": obj.name, "triangles": base_tris, "ratio": 1.0}]

    for index, ratio in enumerate(chain, start=1):
        copy = scene_lib.duplicate(obj, f"{obj.name}_lod{index}")
        scene_lib.add_decimate(copy, ratio)
        scene_lib.apply_modifiers(copy)
        if keep_uvs and not copy.data.uv_layers and obj.data.uv_layers:
            uv_lib.smart_project(copy, margin=0.02)
        if layout:
            copy.location = (
                obj.location.x + (width * 1.35) * index, obj.location.y, obj.location.z
            )
        made.append(
            {
                "level": index,
                "name": copy.name,
                "triangles": mesh_lib.tri_count(copy),
                "ratio": round(ratio, 4),
            }
        )

    return {
        "source": obj.name,
        "levels": made,
        "total_triangles": sum(m["triangles"] for m in made),
        "note": "Export all levels in one glTF; Godot picks them up as an LOD group by name suffix.",
    }


@op(
    "gameready.collision",
    summary="Generate a physics collision proxy. Convex hulls are what you want for anything a character walks into; box is cheapest; simplified trimesh is for concave shapes like arenas and rooms. Named <object>-convcol / <object>-col per the studio import convention. SKIP for hulls that ride inside a moving body: Godot imports the proxy as a StaticBody3D child, and a static collider inside a CharacterBody3D blocks its own vehicle.",
    params={
        "name": ("str", None, "Source object"),
        "mode": ("enum:box|convex|simplified|cylinder|sphere|capsule", "convex", "Proxy shape"),
        "ratio": ("num", 0.12, "simplified only: decimation ratio for the trimesh proxy"),
        "inflate": ("num", 0.0, "Grow the proxy by this many metres (stops geometry poking through)"),
        "hide": ("bool", True, "Hide the proxy from rendering"),
    },
    tags=["gameready", "physics"],
)
def gameready_collision(ctx, name, mode, ratio, inflate, hide):
    obj = _get(name)
    if obj.type != "MESH":
        raise OpError(f"'{name}' is a {obj.type}, not a mesh")
    bounds = mesh_lib.bounds(obj)
    size = bounds["size"]
    centre = [(bounds["min"][i] + bounds["max"][i]) * 0.5 for i in range(3)]
    suffix = "-col" if mode == "simplified" else "-convcol"
    proxy_name = f"{obj.name}{suffix}"

    if mode == "simplified":
        proxy = scene_lib.duplicate(obj, proxy_name)
        scene_lib.add_decimate(proxy, max(0.01, ratio))
        scene_lib.apply_modifiers(proxy)
        bm = mesh_lib.obj_bmesh(proxy)
        mesh_lib.triangulate(bm)
        mesh_lib.write_bmesh(bm, proxy)
    elif mode == "convex":
        bm = mesh_lib.obj_bmesh(obj)
        result = bmesh.ops.convex_hull(bm, input=bm.verts[:])
        unused = [
            g for g in result.get("geom_unused", []) + result.get("geom_interior", [])
        ]
        if unused:
            bmesh.ops.delete(bm, geom=unused, context="VERTS")
        proxy = mesh_lib.to_object(bm, proxy_name)
        proxy.matrix_world = obj.matrix_world.copy()
    else:
        bm = mesh_lib.new_bmesh()
        if mode == "box":
            mesh_lib.add_box(bm, size=size, center=centre)
        elif mode == "sphere":
            mesh_lib.add_icosphere(bm, radius=max(size) * 0.5, subdivisions=2, center=centre)
        elif mode == "cylinder":
            mesh_lib.add_cylinder(
                bm, radius=max(size[0], size[1]) * 0.5, depth=size[2], segments=12, center=centre
            )
        else:  # capsule
            radius = max(size[0], size[1]) * 0.5
            body = max(0.01, size[2] - radius * 2.0)
            mesh_lib.add_cylinder(bm, radius=radius, depth=body, segments=12, center=centre)
            mesh_lib.add_icosphere(
                bm, radius=radius, subdivisions=2,
                center=(centre[0], centre[1], centre[2] + body * 0.5),
            )
            mesh_lib.add_icosphere(
                bm, radius=radius, subdivisions=2,
                center=(centre[0], centre[1], centre[2] - body * 0.5),
            )
            bmesh.ops.convex_hull(bm, input=bm.verts[:])
        proxy = mesh_lib.to_object(bm, proxy_name)

    if inflate > 0.0:
        bm = mesh_lib.obj_bmesh(proxy)
        pivot = Vector(centre)
        for vert in bm.verts:
            direction = (vert.co - pivot)
            if direction.length > 1e-6:
                vert.co += direction.normalized() * inflate
        mesh_lib.write_bmesh(bm, proxy)

    proxy.data.materials.clear()
    scene_lib.apply_transforms(proxy)
    if hide:
        proxy.hide_render = True
    scene_lib.parent_to(proxy, obj)

    proxy_tris = mesh_lib.tri_count(proxy)
    if mode == "simplified" and proxy_tris > 400:
        ctx.note(
            f"Collision proxy '{proxy.name}' is {proxy_tris} triangles. Concave trimesh "
            "collision is expensive — lower `ratio`, or split the object and use convex "
            "hulls per part."
        )
    return {
        "source": obj.name,
        "proxy": proxy.name,
        "mode": mode,
        "triangles": proxy_tris,
        "source_triangles": mesh_lib.tri_count(obj),
        "bounds": mesh_lib.bounds(proxy),
    }


@op(
    "gameready.budget",
    summary="Check the scene against a platform triangle/texture budget and say what to do about anything over. Run this before export, every time.",
    params={
        "profile": (f"enum:{'|'.join(PROFILES)}", "browser_webgpu", "Target platform profile"),
        "asset_class": ("enum:prop|character|environment|hero", "prop", "What kind of asset this is"),
        "objects": ("str[]", [], "Objects to check (empty = every mesh in the scene)"),
    },
    tags=["gameready", "inspect"],
    mutates=False,
)
def gameready_budget(ctx, profile, asset_class, objects):
    limits = PROFILES[profile]
    ceiling = limits[asset_class]
    targets = (
        [_get(n) for n in objects] if objects
        else [o for o in scene_lib.mesh_objects() if not _is_proxy(o.name)]
    )
    rows = []
    over = []
    for obj in targets:
        if obj.type != "MESH":
            continue
        tris = mesh_lib.tri_count(obj)
        materials = len([m for m in obj.data.materials if m])
        row = {
            "name": obj.name,
            "triangles": tris,
            "budget": ceiling,
            "over_by": max(0, tris - ceiling),
            "materials": materials,
            "has_uvs": bool(obj.data.uv_layers),
            "has_collision": any(
                o.name.startswith(obj.name) and _is_proxy(o.name)
                for o in scene_lib.mesh_objects()
            ),
        }
        rows.append(row)
        if row["over_by"] > 0:
            over.append(row)

    total = sum(r["triangles"] for r in rows)
    advice = []
    for row in over:
        factor = row["budget"] / max(1, row["triangles"])
        advice.append(
            f"'{row['name']}' is {row['triangles']} tris vs {row['budget']} budget — run "
            f"gameready.lod ratios=[{factor:.2f}] or regenerate with lower detail parameters."
        )
    for row in rows:
        if not row["has_uvs"]:
            advice.append(f"'{row['name']}' has no UVs — run uv.unwrap before export.")
        if row["materials"] > 2:
            advice.append(
                f"'{row['name']}' uses {row['materials']} materials; each one is a draw call. "
                "Merge them or run gameready.atlas."
            )
    return {
        "profile": profile,
        "asset_class": asset_class,
        "triangle_budget": ceiling,
        "texture_budget": limits["texture"],
        "objects": rows,
        "total_triangles": total,
        "within_budget": not over,
        "advice": advice,
    }


def _is_proxy(name):
    return name.endswith("-col") or name.endswith("-convcol")


# Uncompressed GPU cost per texel, plus a third again for the mip chain.
_BYTES_PER_TEXEL = 4
_MIP_FACTOR = 4.0 / 3.0
# What each platform can afford to hold in texture memory at once. Browsers are
# the tight case: the WASM heap and the GPU budget share a device that is often
# running a dozen other tabs.
TEXTURE_BUDGETS_MB = {
    "mobile_low": 32,
    "mobile_high": 96,
    "browser_webgl": 96,
    "browser_webgpu": 192,
    "desktop_high": 1024,
}


@op(
    "gameready.texture_budget",
    summary="Measure what the textures actually cost in GPU memory and flag any over the platform's resolution cap. Triangle budgets are half the story — a scene can be trivially cheap to draw and still fail to load because its textures do not fit in VRAM.",
    params={
        "profile": (f"enum:{'|'.join(PROFILES)}", "browser_webgpu", "Target platform profile"),
        "assume_compressed": ("bool", False, "Report cost after KTX2/Basis transcoding (~8:1) instead of raw RGBA. Only set this once the cook step actually compresses, or the number is fiction"),
    },
    tags=["gameready", "inspect"],
    mutates=False,
)
def gameready_texture_budget(ctx, profile, assume_compressed):
    cap = PROFILES[profile]["texture"]
    budget_mb = TEXTURE_BUDGETS_MB[profile]
    ratio = 8.0 if assume_compressed else 1.0

    rows = []
    total_bytes = 0.0
    oversized = []
    for image in bpy.data.images:
        if image.name == "Render Result":
            continue
        width, height = image.size
        if width == 0 or height == 0:
            continue
        cost = (width * height * _BYTES_PER_TEXEL * _MIP_FACTOR) / ratio
        total_bytes += cost
        row = {
            "name": image.name,
            "size": [width, height],
            "mb": round(cost / (1024 * 1024), 3),
            "over_cap": max(width, height) > cap,
        }
        rows.append(row)
        if row["over_cap"]:
            oversized.append(row)

    total_mb = total_bytes / (1024 * 1024)
    advice = [
        f"'{row['name']}' is {row['size'][0]}x{row['size'][1]} against a {cap} cap for "
        f"{profile} — re-bake at size={cap}."
        for row in oversized
    ]
    if total_mb > budget_mb:
        advice.append(
            f"{total_mb:.1f} MB of texture memory against a {budget_mb} MB budget for "
            f"{profile}. Lower resolutions, share one tiling map across surfaces "
            "(material.tileable with reuse=true), or atlas."
        )
    if rows and not assume_compressed:
        # The sidecars this pipeline writes declare texture_policy=compressed.
        # Until the cook step actually runs KTX2/Basis that claim is aspirational,
        # and the honest number is the uncompressed one reported here.
        ctx.note(
            f"Measured as UNCOMPRESSED RGBA ({total_mb:.1f} MB). Assets declaring "
            "texture_policy=compressed are not compressed until the cook step runs "
            f"KTX2/Basis; with it this set would cost about {total_mb / 8.0:.1f} MB."
        )

    return {
        "profile": profile,
        "textures": rows,
        "count": len(rows),
        "total_mb": round(total_mb, 2),
        "budget_mb": budget_mb,
        "resolution_cap": cap,
        "compressed": assume_compressed,
        "within_budget": total_mb <= budget_mb and not oversized,
        "advice": advice,
    }


@op(
    "gameready.atlas",
    summary="Merge several objects into one mesh with one shared material and a repacked UV atlas. The most effective draw-call reduction available — a room of 20 props becomes 1 draw call.",
    params={
        "objects": ("str[]", None, "Objects to atlas together"),
        "name": ("str", "atlas_group", "Name for the merged object"),
        "margin": ("num", 0.015, "UV island padding"),
        "material": ("str", "stone", "Material preset for the merged result"),
        "color": ("str", "", "Override colour"),
    },
    tags=["gameready"],
)
def gameready_atlas(ctx, objects, name, margin, material, color):
    from lib import mat as mat_lib

    if len(objects) < 2:
        raise OpError("gameready.atlas needs at least two objects to merge")
    targets = [_get(n) for n in objects]
    before_materials = sorted(
        {m.name for o in targets if o.type == "MESH" for m in o.data.materials if m}
    )
    before_tris = sum(mesh_lib.tri_count(o) for o in targets if o.type == "MESH")

    merged = scene_lib.join(targets, scene_lib.sanitize(name))
    merged.data.materials.clear()
    mat_lib.assign(merged, mat_lib.from_preset(material, color=color or None))
    uv_lib.smart_project(merged, margin=margin)
    uv_lib.pack(merged, margin=margin)
    scene_lib.apply_transforms(merged)

    result = finish_lib.report(ctx, merged)
    result.update(
        {
            "merged_from": objects,
            "materials_before": before_materials,
            "materials_after": [m.name for m in merged.data.materials if m],
            "draw_calls_saved": max(0, len(before_materials) - 1),
            "triangles_before": before_tris,
        }
    )
    ctx.note(
        f"Atlased {len(objects)} objects into '{merged.name}': "
        f"{len(before_materials)} materials -> 1. Bake a texture "
        f"(material.bake) if the originals had different colours, or they will all "
        "come out the same shade."
    )
    return result


@op(
    "gameready.pivot",
    summary="Fix pivots and transforms across many objects at once — the two things engines get wrong on import and nobody notices until a prop spins about its ankle.",
    params={
        "objects": ("str[]", [], "Objects to fix (empty = every mesh)"),
        "origin": ("enum:bottom|center|center_xy|world|none", "bottom", "Pivot placement"),
        "apply_transforms": ("bool", True, "Bake rotation and scale into the mesh"),
        "snap_to_ground": ("bool", False, "Move each object so its lowest point sits at Z=0"),
        "to_origin": ("bool", False, "Also move the object itself to (0,0,0). Required for a single-asset master file — the studio validator rejects a root object that is not at the world origin"),
    },
    tags=["gameready", "transform"],
)
def gameready_pivot(ctx, objects, origin, apply_transforms, snap_to_ground, to_origin):
    targets = [_get(n) for n in objects] if objects else scene_lib.mesh_objects()
    fixed = []
    for obj in targets:
        if obj.type != "MESH":
            continue
        if origin != "none":
            scene_lib.set_origin(obj, origin)
        if apply_transforms:
            scene_lib.apply_transforms(obj)
        if to_origin and obj.parent is None:
            obj.location = (0.0, 0.0, 0.0)
        if snap_to_ground:
            low = mesh_lib.bounds(obj)["min"][2]
            obj.location.z -= low
        fixed.append({"name": obj.name, "location": [round(v, 5) for v in obj.location]})
    return {"fixed": fixed, "count": len(fixed), "origin": origin, "moved_to_origin": to_origin}


@op(
    "gameready.optimize",
    summary="One-call cleanup pass: weld doubles, drop degenerate faces, recalculate normals, and report what it saved. Safe to run on anything.",
    params={
        "objects": ("str[]", [], "Objects to optimise (empty = every mesh)"),
        "merge_distance": ("num", 0.0001, "Vertex weld threshold in metres"),
        "dissolve_flat": ("bool", False, "Merge coplanar faces — cuts triangles but can create n-gons"),
        "triangulate": ("bool", False, "Triangulate (engines do this anyway; useful for exact counts)"),
    },
    tags=["gameready", "polish"],
)
def gameready_optimize(ctx, objects, merge_distance, dissolve_flat, triangulate):
    targets = [_get(n) for n in objects] if objects else scene_lib.mesh_objects()
    rows = []
    saved = 0
    for obj in targets:
        if obj.type != "MESH":
            continue
        before = mesh_lib.tri_count(obj)
        before_verts = len(obj.data.vertices)
        bm = mesh_lib.obj_bmesh(obj)
        mesh_lib.cleanup(bm, merge_dist=merge_distance, limited_dissolve=dissolve_flat)
        degenerate = [f for f in bm.faces if f.calc_area() < 1e-9]
        if degenerate:
            bmesh.ops.delete(bm, geom=degenerate, context="FACES")
        if triangulate:
            mesh_lib.triangulate(bm)
        mesh_lib.write_bmesh(bm, obj)
        after = mesh_lib.tri_count(obj)
        saved += max(0, before - after)
        rows.append(
            {
                "name": obj.name,
                "triangles": after,
                "triangles_before": before,
                "vertices": len(obj.data.vertices),
                "vertices_before": before_verts,
                "degenerate_removed": len(degenerate),
            }
        )
    return {"objects": rows, "triangles_saved": saved, "count": len(rows)}


@op(
    "gameready.socket",
    summary="Add a named empty as an attachment socket — muzzle points, hardpoints, spawn markers, VFX anchors. Engines import empties as nodes you can query by name.",
    params={
        "name": ("str", None, "Socket name (prefix it, e.g. 'socket_muzzle')"),
        "parent": ("str", "", "Object to parent the socket to"),
        "location": ("vec3", [0.0, 0.0, 0.0], "Position in metres"),
        "rotation": ("vec3", [0.0, 0.0, 0.0], "Rotation in degrees"),
        "size": ("num", 0.1, "Display size of the empty"),
    },
    tags=["gameready"],
)
def gameready_socket(ctx, name, parent, location, rotation, size):
    import bpy

    socket_name = scene_lib.unique_name(name)
    empty = bpy.data.objects.new(socket_name, None)
    empty.empty_display_type = "ARROWS"
    empty.empty_display_size = size
    empty.location = location
    empty.rotation_euler = [math.radians(a) for a in rotation]
    bpy.context.scene.collection.objects.link(empty)
    if parent:
        scene_lib.parent_to(empty, _get(parent))
    return {
        "socket": socket_name,
        "parent": parent or None,
        "location": [round(v, 5) for v in location],
        "note": "glTF exports this as an empty node; Godot imports it as a Node3D you can find by name.",
    }


def _get(name):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc


@op(
    "gameready.vertex_ao",
    summary=(
        "Bake ambient occlusion into VERTEX COLOURS. Costs nothing at runtime — no texture, "
        "no extra pass, no shadow map — and it is what makes an object read as sitting on the "
        "ground rather than pasted in front of it. The cheapest contact-shadow cue there is, and "
        "the right one for low-poly assets where vertices are already dense relative to detail. "
        "Exports as COLOR_0 in glTF; enable vertex colours on the material in-engine "
        "(Babylon useVertexColors, three vertexColors, Godot vertex_color_use_as_albedo)."
    ),
    params={
        "name": ("str", None, "Object to bake into"),
        "samples": ("int", 32, "Hemisphere rays per vertex. 32 is clean; 64 for hero assets"),
        "distance": ("num", 0.6, "Occlusion search radius in metres. Roughly the scale of the crevices you want to darken"),
        "strength": ("num", 0.8, "How dark full occlusion goes, 0..1"),
        "floor": ("num", 0.25, "Darkest value a vertex may reach. Stops creases going to pure black"),
        "self_only": ("bool", True, "Occlude against this object only. False also tests every other mesh in the scene"),
    },
    tags=["gameready", "material"],
)
def gameready_vertex_ao(ctx, name, samples, distance, strength, floor, self_only):
    from mathutils.bvhtree import BVHTree

    obj = scene_lib.get_object(name)
    mesh = obj.data
    if not mesh.vertices:
        raise OpError(f"gameready.vertex_ao: '{name}' has no geometry")

    samples = max(4, min(256, int(samples)))

    # Everything the rays can hit, in this object's local space. Building one
    # tree per source and transforming ray origins is cheaper than merging.
    trees = []
    bm_self = bmesh.new()
    bm_self.from_mesh(mesh)
    bmesh.ops.triangulate(bm_self, faces=bm_self.faces[:])
    trees.append((BVHTree.FromBMesh(bm_self), obj.matrix_world.copy()))
    others = []
    if not self_only:
        for other in scene_lib.mesh_objects():
            if other is obj or not other.data.vertices:
                continue
            bm_o = bmesh.new()
            bm_o.from_mesh(other.data)
            bmesh.ops.triangulate(bm_o, faces=bm_o.faces[:])
            trees.append((BVHTree.FromBMesh(bm_o), other.matrix_world.copy()))
            others.append(bm_o)

    # Deterministic hemisphere sampling. A Fibonacci spiral gives near-uniform
    # coverage with no RNG at all, which matters because every bforge op has to
    # produce the same bytes for the same input, forever.
    golden = math.pi * (3.0 - math.sqrt(5.0))
    directions = []
    for i in range(samples):
        z = (i + 0.5) / samples          # 0..1 → upper hemisphere only
        r = math.sqrt(max(0.0, 1.0 - z * z))
        theta = golden * i
        directions.append(Vector((math.cos(theta) * r, math.sin(theta) * r, z)))

    world = obj.matrix_world
    # Nudge each ray origin off the surface, or every ray instantly hits the
    # face it started on and the whole mesh bakes black.
    epsilon = max(1e-5, distance * 0.005)

    values = []
    for vert in mesh.vertices:
        origin_local = vert.co
        normal = vert.normal
        if normal.length_squared < 1e-12:
            values.append(1.0)
            continue
        normal = normal.normalized()
        # Basis with `normal` as up, so the hemisphere points out of the surface.
        helper = Vector((0.0, 0.0, 1.0)) if abs(normal.z) < 0.9 else Vector((1.0, 0.0, 0.0))
        tangent = normal.cross(helper).normalized()
        bitangent = normal.cross(tangent)

        origin_world = world @ origin_local
        hits = 0
        for d in directions:
            ray = (tangent * d.x) + (bitangent * d.y) + (normal * d.z)
            start = origin_world + ray * epsilon
            for tree, tree_world in trees:
                inv = tree_world.inverted_safe()
                local_start = inv @ start
                local_dir = (inv.to_3x3() @ ray).normalized()
                loc, _nrm, _idx, dist = tree.ray_cast(local_start, local_dir, distance)
                if loc is not None and dist is not None and dist <= distance:
                    hits += 1
                    break
        occlusion = hits / float(samples)
        values.append(max(floor, 1.0 - strength * occlusion))

    bm_self.free()
    for bm_o in others:
        bm_o.free()

    # Clear out informationless colour layers first, or AO does not reach the
    # engine.
    #
    # Measured, not assumed: the first working bake produced correct values and
    # shipped a USELESS glTF. Blender already carried an all-white colour
    # attribute from mesh creation, so the export wrote that as COLOR_0 and put
    # the AO in COLOR_1 -- and every engine reads COLOR_0. The op reported
    # mean 0.74 while the asset on disk was uniformly white.
    #
    # A colour layer with no variation carries nothing, so dropping it is safe.
    # A layer that DOES vary is somebody's data and is left alone, with the AO
    # slot reported so the caller can see where it actually landed.
    for existing in list(mesh.color_attributes):
        if existing.name == "AO":
            continue
        try:
            channels = [tuple(px.color)[:3] for px in existing.data]
        except (AttributeError, TypeError):
            continue
        if channels and all(
            abs(c - channels[0][i]) < 1e-4 for px in channels for i, c in enumerate(px)
        ):
            mesh.color_attributes.remove(existing)

    layer = mesh.color_attributes.get("AO")
    if layer is None:
        layer = mesh.color_attributes.new(name="AO", type="FLOAT_COLOR", domain="POINT")
    for i, v in enumerate(values):
        layer.data[i].color = (v, v, v, 1.0)
    # Index-based, not name-based: `default_color` is not settable and the
    # name-based accessors moved between Blender versions. Both indices matter --
    # active is what the viewport shows, render is what the glTF exporter picks
    # up as COLOR_0, and setting only the first exports nothing.
    try:
        idx = list(mesh.color_attributes).index(layer)
        mesh.color_attributes.active_color_index = idx
        mesh.color_attributes.render_color_index = idx
    except (ValueError, AttributeError) as exc:
        raise OpError(
            f"gameready.vertex_ao: baked {len(values)} vertices but could not mark the "
            f"colour layer for export ({exc}). The data is on the mesh; the glTF would "
            f"ship without COLOR_0."
        ) from exc
    mesh.update()

    result = finish_lib.report(ctx, obj)
    darkest = min(values) if values else 1.0
    mean = sum(values) / len(values) if values else 1.0
    occluded = sum(1 for v in values if v < 0.995) / max(1, len(values))
    slot = list(mesh.color_attributes).index(layer)
    result["ao"] = {
        "vertices": len(values),
        "samples": samples,
        "mean": round(mean, 4),
        "darkest": round(darkest, 4),
        "occluded_fraction": round(occluded, 4),
        # Which glTF COLOR_n this becomes. Engines read COLOR_0; anything else
        # is data the runtime will not look at, so say the number rather than
        # letting the caller assume.
        "gltf_slot": f"COLOR_{slot}",
        "colour_layers": [a.name for a in mesh.color_attributes],
    }
    # A bake that darkened nothing is a no-op wearing a success message.
    if occluded < 0.01:
        raise OpError(
            f"gameready.vertex_ao: baked '{name}' but nothing was occluded "
            f"(mean {mean:.3f}). Raise `distance` above {distance} -- it is smaller than "
            f"the gaps in this mesh -- or check the object is not a single flat plane."
        )
    if slot != 0:
        raise OpError(
            f"gameready.vertex_ao: AO landed in COLOR_{slot}, not COLOR_0, because "
            f"{[a.name for a in mesh.color_attributes]} share the mesh. Engines read "
            f"COLOR_0, so this asset would ship its AO where nothing reads it. Remove the "
            f"competing colour layer first."
        )
    return result
