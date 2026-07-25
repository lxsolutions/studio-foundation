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
        "color": ("str", "", "Override colour: palette name or #rrggbb"),
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
