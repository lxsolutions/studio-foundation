"""Material ops: PBR presets, procedural graphs, and baking to glTF-safe textures."""

from __future__ import annotations

import bpy
from lib import mat as mat_lib
from lib import scene as scene_lib
from lib import uvs as uv_lib
from registry import OpError, op


@op(
    "material.set",
    summary="Create and assign a PBR material. Prefer a preset name (stone, wood, metal, gold, crystal...) — the presets have physically sane roughness/metallic values.",
    params={
        "object": ("str", None, "Object to assign to"),
        "preset": ("str", "stone", "Material preset; see meta.palette for the list"),
        "name": ("str", "", "Material name (defaults to m_<preset>)"),
        "color": ("colorref", "", "Override colour: palette name, #rrggbb, or a linear [r,g,b] triple"),
        "roughness": ("num", -1.0, "Override roughness 0..1; -1 keeps the preset value"),
        "metallic": ("num", -1.0, "Override metallic 0..1; -1 keeps the preset value"),
        "emission": ("num", -1.0, "Emission strength; -1 keeps the preset value"),
        "slot": ("int", 0, "Material slot index"),
    },
    tags=["material"],
)
def material_set(ctx, object, preset, name, color, roughness, metallic, emission, slot):
    obj = _get(object)
    try:
        if emission >= 0.0:
            spec = mat_lib.PRESETS.get(preset, {})
            material = mat_lib.principled(
                name or f"m_{preset}",
                color=color or spec.get("color", "stone_grey"),
                roughness=spec.get("roughness", 0.6) if roughness < 0 else roughness,
                metallic=spec.get("metallic", 0.0) if metallic < 0 else metallic,
                emission=emission,
            )
        else:
            material = mat_lib.from_preset(
                preset,
                name=name or None,
                color=color or None,
                roughness=None if roughness < 0 else roughness,
                metallic=None if metallic < 0 else metallic,
            )
    except ValueError as exc:
        raise OpError(str(exc)) from exc
    mat_lib.assign(obj, material, slot)
    return {"object": obj.name, "material": material.name, "slot": slot}


@op(
    "material.procedural",
    summary="Build a noise/voronoi/wave/gradient material. Gives surfaces real variation instead of flat colour — but it must be baked (material.bake) before it can export to glTF.",
    params={
        "object": ("str", None, "Object to assign to"),
        "kind": ("enum:noise|voronoi|wave|gradient|checker", "noise", "Pattern type: noise=rock/dirt, voronoi=cracked stone/scales, wave=wood grain/strata, gradient=vertical fade, checker=UV debug"),
        "name": ("str", "", "Material name"),
        "color_a": ("str", "stone_grey", "Low colour: palette name or #rrggbb"),
        "color_b": ("str", "stone_warm", "High colour: palette name or #rrggbb"),
        "scale": ("num", 5.0, "Pattern scale — higher is finer"),
        "detail": ("num", 2.0, "Fractal detail levels"),
        "roughness": ("num", 0.7, "Base roughness; the pattern modulates around it"),
        "metallic": ("num", 0.0, "Metallic 0..1"),
        "distortion": ("num", 0.0, "Warps the pattern; makes wood grain and marble believable"),
    },
    tags=["material"],
)
def material_procedural(ctx, object, kind, name, color_a, color_b, scale, detail, roughness,
                        metallic, distortion):
    obj = _get(object)
    try:
        material = mat_lib.procedural(
            name or f"m_{kind}_{scene_lib.sanitize(obj.name)}",
            kind, color_a, color_b, scale=scale, detail=detail,
            roughness=roughness, metallic=metallic, distortion=distortion,
        )
    except ValueError as exc:
        raise OpError(str(exc)) from exc
    mat_lib.assign(obj, material)
    ctx.note(
        f"'{material.name}' is procedural and cannot export to glTF as-is. "
        f"Run material.bake on '{obj.name}' before export.gltf, or the surface will "
        f"arrive in-engine as flat grey."
    )
    return {"object": obj.name, "material": material.name, "gltf_safe": False}


@op(
    "material.pbr",
    summary="Apply a layered AAA-grade surface: base albedo, curvature-driven EDGE WEAR, ambient-occlusion-driven CAVITY DIRT, two octaves of micro-detail and non-constant roughness. This is the single biggest jump in perceived quality — flat-coloured geometry never reads as AAA no matter how good the silhouette. Bake it with material.bake_pbr before export.",
    params={
        "object": ("str", None, "Object to surface"),
        "base_color": ("colorref", "stone_grey", "Base albedo: palette name or #rrggbb"),
        "roughness": ("num", 0.75, "Mid roughness; the layers vary around it"),
        "metallic": ("num", 0.0, "Metallic 0..1"),
        "detail_scale": ("num", 14.0, "Micro-detail frequency — higher is finer grain"),
        "grain": ("num", 0.55, "How strongly the noise tints the albedo"),
        "edge_wear": ("num", 0.55, "Abrasion on convex edges (0..1). Real objects are worn where they stick out"),
        "edge_color": ("colorref", "", "Colour of worn edges; defaults to a lighter base"),
        "cavity_dirt": ("num", 0.5, "Grime settled in crevices (0..1)"),
        "dirt_color": ("colorref", "#2b2118", "Colour of the grime"),
        "bump": ("num", 0.35, "Surface relief strength"),
        "name": ("str", "", "Material name"),
        "seed": ("int", 0, "Random seed for the noise"),
    },
    tags=["material", "pbr"],
)
def material_pbr(ctx, object, base_color, roughness, metallic, detail_scale, grain, edge_wear,
                 edge_color, cavity_dirt, dirt_color, bump, name, seed):
    obj = _get(object)
    if obj.type != "MESH":
        raise OpError(f"'{object}' is a {obj.type}, not a mesh")
    try:
        material = mat_lib.layered_pbr(
            name or f"m_pbr_{scene_lib.sanitize(obj.name)}",
            base_color, roughness=roughness, metallic=metallic,
            detail_scale=detail_scale, grain=grain, edge_wear=edge_wear,
            edge_color=edge_color or None, cavity_dirt=cavity_dirt,
            dirt_color=dirt_color, bump=bump, seed=seed,
        )
    except ValueError as exc:
        raise OpError(str(exc)) from exc
    obj.data.materials.clear()
    mat_lib.assign(obj, material)
    ctx.note(
        f"'{material.name}' is a Cycles layer stack and cannot export as-is. Run "
        f"material.bake_pbr object='{obj.name}' to turn it into real PBR maps."
    )
    return {"object": obj.name, "material": material.name, "gltf_safe": False,
            "layers": ["base", "micro-detail", "edge wear", "cavity dirt"]}


@op(
    "material.tileable",
    summary="Bake a SEAMLESS PBR texture set and apply it repeating across a surface. This is how architecture gets textured: a unique bake for a 725 m stadium works out to ~3 px/m, which is no texture at all, whereas one 1k tiling map gives real surface detail everywhere. Noise is sampled through a torus mapping so it tiles perfectly with no visible seam.",
    params={
        "object": ("str", None, "Object to texture"),
        "base_color": ("colorref", "stone_grey", "Base albedo"),
        "roughness": ("num", 0.78, "Mid roughness"),
        "metallic": ("num", 0.0, "Metallic 0..1"),
        "detail_scale": ("num", 6.0, "Feature size in the baked map — higher is finer"),
        "dirt": ("num", 0.35, "Grime settled in the low spots (0..1)"),
        "dirt_color": ("colorref", "#2b2118", "Grime colour"),
        "bump": ("num", 0.4, "Surface relief strength"),
        "tiles": ("num", 6.0, "How many times the map repeats across the object's UVs"),
        "uv_scale": ("num", 0.0, "Metres per UV tile for box projection; 0 keeps existing UVs"),
        "size": ("int", 1024, "Texture resolution"),
        "samples": ("int", 16, "Cycles samples for the bake"),
        "stem": ("str", "", "Filename stem (defaults to the object name)"),
        "out_dir": ("path", "textures", "Directory for the PNGs"),
        "reuse": ("bool", True, "If this stem was already baked, assign the existing material instead of baking again. Bake once, apply to every stone surface in a building — same texture, one set of maps, one draw call"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["material", "bake", "pbr"],
)
def material_tileable(ctx, object, base_color, roughness, metallic, detail_scale, dirt,
                      dirt_color, bump, tiles, uv_scale, size, samples, stem, out_dir,
                      reuse, seed):
    obj = _get(object)
    if obj.type != "MESH":
        raise OpError(f"'{object}' is a {obj.type}, not a mesh")

    existing = bpy.data.materials.get(f"m_{scene_lib.sanitize(stem or obj.name)}")
    if reuse and existing is not None:
        if uv_scale > 0.0:
            uv_lib.box_project(obj, scale=uv_scale)
        obj.data.materials.clear()
        mat_lib.assign(obj, existing)
        return {
            "object": obj.name, "material": existing.name, "reused": True,
            "tiles": tiles, "uv_scale": uv_scale or None, "gltf_safe": True,
        }

    if uv_scale > 0.0:
        # Box projection at a fixed metres-per-tile keeps texel density uniform
        # across every surface of the building, which is what makes a kit read
        # as one kit rather than a pile of separately-textured parts.
        uv_lib.box_project(obj, scale=uv_scale)
    elif not obj.data.uv_layers:
        raise OpError(
            f"'{object}' has no UVs. Pass uv_scale (metres per tile) to box-project, "
            "or run uv.unwrap first."
        )

    label = scene_lib.sanitize(stem or obj.name)
    source = mat_lib.tileable_pbr(
        f"m_tileable_{label}", base_color, roughness=roughness, metallic=metallic,
        detail_scale=detail_scale, dirt_color=dirt_color, dirt=dirt, bump=bump, seed=seed,
    )
    directory = ctx.out_path(f"{out_dir}/{label}.png", ".png").parent
    try:
        produced = mat_lib.bake_tileable_set(
            source, str(directory), label, size=size, samples=samples,
        )
    except (RuntimeError, ValueError) as exc:
        raise OpError(f"tileable bake failed: {exc}") from exc
    if not produced:
        raise OpError("no maps were baked")

    applied = mat_lib.tiled_material(f"m_{label}", produced, tiles=tiles)
    obj.data.materials.clear()
    mat_lib.assign(obj, applied)
    bpy.data.materials.remove(source)

    return {
        "object": obj.name,
        "material": applied.name,
        "maps": {k: ctx.rel(v[1]) for k, v in produced.items()},
        "size": size,
        "tiles": tiles,
        "uv_scale": uv_scale or None,
        "reused": False,
        "gltf_safe": True,
    }


@op(
    "material.bake_pbr",
    summary="Bake a layered material into a real PBR texture set (base colour, normal, roughness, AO) and rewire it as glTF-safe image textures. This is the step that makes a procedurally-surfaced asset actually shippable.",
    params={
        "object": ("str", None, "Object to bake"),
        "stem": ("str", "", "Filename stem (defaults to the object name)"),
        "out_dir": ("path", "textures", "Directory for the PNGs"),
        "size": ("int", 1024, "Texture resolution per map"),
        "samples": ("int", 24, "Cycles samples; AO and normal want more than base colour"),
        "maps": ("str[]", ["base_color", "normal", "roughness", "ao"], "Which maps to bake"),
        "unwrap": ("bool", True, "Auto-unwrap first — baking needs non-overlapping UVs"),
        "margin": ("int", 10, "Bake margin in pixels; prevents seams at low mips"),
    },
    tags=["material", "bake", "pbr"],
)
def material_bake_pbr(ctx, object, stem, out_dir, size, samples, maps, unwrap, margin):
    obj = _get(object)
    if obj.type != "MESH":
        raise OpError(f"'{object}' is a {obj.type}, not a mesh")
    if not obj.data.materials or all(m is None for m in obj.data.materials):
        raise OpError(f"'{object}' has no material — run material.pbr first")

    if unwrap:
        uv_lib.smart_project(obj, margin=0.02)
        uv_lib.pack(obj, margin=0.02)
    overlap = uv_lib.overlap_estimate(obj)
    if overlap > 0.02:
        ctx.note(
            f"UV overlap is {overlap:.0%} on '{obj.name}'; baked texels will fight. "
            "Re-run with unwrap=true."
        )

    label = scene_lib.sanitize(stem or obj.name)
    directory = ctx.out_path(f"{out_dir}/{label}.png", ".png").parent
    try:
        produced = mat_lib.bake_pbr_set(
            obj, str(directory), label, size=size, samples=samples, margin=margin,
            maps=tuple(maps),
        )
    except (RuntimeError, ValueError) as exc:
        raise OpError(f"PBR bake failed: {exc}") from exc
    if not produced:
        raise OpError(f"no maps baked — check `maps` ({maps})")
    wired = mat_lib.wire_pbr_set(obj, produced)

    return {
        "object": obj.name,
        "maps": {k: ctx.rel(v[1]) for k, v in produced.items()},
        "size": size,
        "materials": wired,
        "uv_overlap_ratio": overlap,
        "gltf_safe": True,
    }


@op(
    "material.bake",
    summary="Bake procedural shading down to an image texture and rewire the material to use it. This is what makes procedural materials shippable.",
    params={
        "object": ("str", None, "Object to bake"),
        "pass_name": ("enum:base_color|normal|roughness|ao|emit|combined", "base_color", "Which channel to bake"),
        "size": ("int", 1024, "Texture resolution in pixels"),
        "samples": ("int", 16, "Cycles samples; 16 is plenty for base colour, raise for AO"),
        "out": ("path", "", "PNG output path (defaults to textures/<object>_<pass>.png)"),
        "unwrap": ("bool", True, "Auto-unwrap first — baking needs non-overlapping UVs"),
        "rewire": ("bool", True, "Replace the procedural graph with the baked texture"),
    },
    tags=["material", "bake"],
)
def material_bake(ctx, object, pass_name, size, samples, out, unwrap, rewire):
    obj = _get(object)
    if obj.type != "MESH":
        raise OpError(f"'{object}' is a {obj.type}, not a mesh")
    if unwrap:
        uv_lib.smart_project(obj, margin=0.02)
        uv_lib.pack(obj, margin=0.02)
    overlap = uv_lib.overlap_estimate(obj)
    if overlap > 0.02:
        ctx.note(
            f"UV overlap is {overlap:.0%} on '{obj.name}' — baked texels will fight each other. "
            "Re-run with unwrap=true, or call uv.unwrap style='smart_packed'."
        )
    target = ctx.out_path(out or f"textures/{obj.name}_{pass_name}.png", ".png")
    try:
        result = mat_lib.bake_material(
            obj, target, size=size, pass_name=pass_name, samples=samples
        )
    except ValueError as exc:
        raise OpError(str(exc)) from exc
    rewired = []
    if rewire:
        rewired = mat_lib.rewire_baked(obj, result["image"], pass_name)
    return {
        "object": obj.name,
        "pass": pass_name,
        "texture": str(target),
        "rel": ctx.rel(target),
        "size": size,
        "rewired_materials": rewired,
        "uv_overlap_ratio": overlap,
    }


@op(
    "material.bake_detail",
    summary=(
        "Bake high-poly detail onto a low-poly mesh as a tangent-space normal (or AO) map. "
        "This is what makes a cheap mesh read as an expensive one: the silhouette stays low-poly "
        "but the surface gets its detail back. Use this instead of material.bake when the detail "
        "lives in a separate dense mesh -- material.bake bakes an object onto itself, so its "
        "normal pass just reproduces the low-poly's own flat normals."
    ),
    params={
        "low": ("str", None, "Low-poly object that receives the texture (needs UVs)"),
        "high": ("str[]", None, "High-poly source object(s) the detail is projected from"),
        "pass_name": ("enum:normal|ao|base_color", "normal", "Which channel to transfer"),
        "size": ("int", 2048, "Texture resolution in pixels"),
        "samples": ("int", 32, "Cycles samples; raise for AO, 32 is plenty for normals"),
        "cage_extrusion": ("num", 0.02, "Metres to push the low-poly out before casting rays"),
        "max_ray_distance": ("num", 0.05, "Metres to search for the high-poly surface"),
        "out": ("path", "", "PNG output path (defaults to textures/<low>_<pass>_detail.png)"),
        "attach": ("bool", True, "Link the baked map into the low-poly's existing material"),
    },
    tags=["material", "bake"],
)
def material_bake_detail(
    ctx, low, high, pass_name, size, samples, cage_extrusion, max_ray_distance, out, attach
):
    low_obj = _get(low)
    if low_obj.type != "MESH":
        raise OpError(f"'{low}' is a {low_obj.type}, not a mesh")
    high_objs = [_get(name) for name in high]
    for obj in high_objs:
        if obj.type != "MESH":
            raise OpError(f"high-poly source '{obj.name}' is a {obj.type}, not a mesh")

    low_tris = len(low_obj.data.loop_triangles) or len(low_obj.data.polygons)
    high_tris = sum(len(o.data.loop_triangles) or len(o.data.polygons) for o in high_objs)
    if high_tris <= low_tris:
        ctx.note(
            f"high-poly total ({high_tris} faces) is not denser than '{low_obj.name}' "
            f"({low_tris} faces) — a detail bake can only transfer detail the source "
            "actually has, so this will produce a flat map."
        )

    target = ctx.out_path(out or f"textures/{low_obj.name}_{pass_name}_detail.png", ".png")
    try:
        result = mat_lib.bake_detail(
            low_obj, high_objs, target, pass_name=pass_name, size=size,
            samples=samples, cage_extrusion=cage_extrusion,
            max_ray_distance=max_ray_distance,
        )
    except ValueError as exc:
        raise OpError(str(exc)) from exc

    attached = []
    if attach:
        attached = mat_lib.attach_baked_map(low_obj, result["image"], pass_name)
    return {
        "low": low_obj.name,
        "high": [o.name for o in high_objs],
        "pass": pass_name,
        "texture": str(target),
        "rel": ctx.rel(target),
        "size": size,
        "low_faces": low_tris,
        "high_faces": high_tris,
        "attached_materials": attached,
    }


@op(
    "material.consolidate",
    summary="Merge materials that render identically into one shared material. Composing a scene from many prop recipes leaves a pile of near-duplicate materials, and every distinct material is a draw call — this collapses them without changing how anything looks.",
    params={
        "tolerance": ("num", 0.02, "How close two materials' colour/roughness/metallic must be to count as the same"),
        "objects": ("str[]", [], "Limit to these objects (empty = whole scene)"),
        "dry_run": ("bool", False, "Report what would merge without changing anything"),
    },
    tags=["material", "gameready"],
)
def material_consolidate(ctx, tolerance, objects, dry_run):
    targets = (
        [_get(n) for n in objects] if objects
        else [o for o in bpy.context.scene.objects if o.type == "MESH"]
    )
    if not targets:
        raise OpError("no mesh objects to consolidate")

    used: list = []
    for obj in targets:
        for material in obj.data.materials:
            if material is not None and material not in used:
                used.append(material)

    # Group by rendered appearance, not by name. Two materials called
    # m_flame_torch_0 and m_flame_torch_7 with the same inputs are one material
    # as far as the GPU is concerned.
    groups: list[tuple[tuple, list]] = []
    for material in used:
        key = _appearance(material)
        if key is None:
            continue  # procedural/unresolvable — never merge, it may differ
        for existing_key, members in groups:
            if _close(existing_key, key, tolerance):
                members.append(material)
                break
        else:
            groups.append((key, [material]))

    merges = {}
    for _key, members in groups:
        if len(members) < 2:
            continue
        # Keep the shortest name: it is almost always the generic one
        # (m_stone) rather than a per-instance variant (m_stone_torch_12).
        keeper = min(members, key=lambda m: (len(m.name), m.name))
        for member in members:
            if member is not keeper:
                merges[member.name] = keeper.name

    if not dry_run and merges:
        for obj in targets:
            for index, material in enumerate(obj.data.materials):
                if material is not None and material.name in merges:
                    obj.data.materials[index] = bpy.data.materials[merges[material.name]]
        # Drop the now-unused datablocks so material.list stays honest.
        for name in list(merges):
            leftover = bpy.data.materials.get(name)
            if leftover is not None and leftover.users == 0:
                bpy.data.materials.remove(leftover)

    remaining = sorted(
        {m.name for o in targets for m in o.data.materials if m is not None}
    )
    return {
        "merged": merges,
        "materials_before": len(used),
        "materials_after": len(remaining),
        "draw_calls_saved": max(0, len(used) - len(remaining)),
        "remaining": remaining,
        "dry_run": dry_run,
    }


def _appearance(material):
    """A comparable tuple of what actually reaches the GPU, or None if unknown."""
    if not material.use_nodes:
        return ("flat", tuple(round(c, 4) for c in material.diffuse_color))
    tree = material.node_tree
    if any(n.type not in
           ("BSDF_PRINCIPLED", "OUTPUT_MATERIAL", "FRAME", "REROUTE") for n in tree.nodes):
        return None  # textured or procedural: appearance is not just its sockets
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return None
    values = []
    for socket_name in ("Base Color", "Roughness", "Metallic", "Alpha",
                        "Emission Color", "Emission Strength", "IOR"):
        socket = bsdf.inputs.get(socket_name)
        if socket is None:
            values.append(0.0)
        elif socket.is_linked:
            return None
        else:
            value = socket.default_value
            try:
                values.extend(float(v) for v in value)
            except TypeError:
                values.append(float(value))
    return ("principled", tuple(values))


def _close(left, right, tolerance):
    if left[0] != right[0] or len(left[1]) != len(right[1]):
        return False
    return all(abs(a - b) <= tolerance for a, b in zip(left[1], right[1], strict=True))


@op(
    "material.list",
    summary="List materials in the file and flag any that glTF cannot export.",
    params={},
    tags=["material", "inspect"],
    mutates=False,
)
def material_list(ctx):
    entries = []
    for material in bpy.data.materials:
        safe, offenders = mat_lib.is_gltf_safe(material)
        entries.append(
            {
                "name": material.name,
                "users": material.users,
                "gltf_safe": safe,
                "unsupported_nodes": offenders,
            }
        )
    unsafe = [e["name"] for e in entries if not e["gltf_safe"]]
    if unsafe:
        ctx.note(
            f"Materials that will not survive glTF export: {unsafe}. "
            "Run material.bake on the objects using them."
        )
    return {"materials": entries, "count": len(entries)}


@op(
    "material.face_assign",
    summary="Give a subset of faces its own material — trim strips, emissive panels, painted details. Selected by world-space direction or height.",
    params={
        "object": ("str", None, "Object name"),
        "preset": ("str", "gold", "Material preset for the selected faces"),
        "select": ("enum:up|down|sides|top_band|bottom_band", "up", "Face selection rule"),
        "band_min": ("num", 0.0, "top_band/bottom_band: lower bound as a fraction of height"),
        "band_max": ("num", 1.0, "top_band/bottom_band: upper bound as a fraction of height"),
        "color": ("str", "", "Override colour"),
    },
    tags=["material"],
)
def material_face_assign(ctx, object, preset, select, band_min, band_max, color):
    obj = _get(object)
    mesh = obj.data
    zs = [v.co.z for v in mesh.vertices] or [0.0]
    lo, hi = min(zs), max(zs)
    span = max(1e-6, hi - lo)
    picked = []
    for polygon in mesh.polygons:
        normal = polygon.normal
        centre_z = polygon.center.z
        t = (centre_z - lo) / span
        if select == "up" and normal.z > 0.7:
            picked.append(polygon.index)
        elif select == "down" and normal.z < -0.7:
            picked.append(polygon.index)
        elif select == "sides" and abs(normal.z) <= 0.7:
            picked.append(polygon.index)
        elif select == "top_band" and band_min <= t <= band_max:
            picked.append(polygon.index)
        elif select == "bottom_band" and band_min <= t <= band_max:
            picked.append(polygon.index)
    if not picked:
        raise OpError(f"no faces on '{object}' matched selection '{select}'")
    try:
        material = mat_lib.from_preset(preset, color=color or None)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
    slot = mat_lib.assign_to_faces(obj, material, picked)
    return {"object": obj.name, "material": material.name, "faces": len(picked), "slot": slot}


def _get(name):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
