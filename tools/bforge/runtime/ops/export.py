"""Export to engine-ready formats, plus the sidecar metadata the studio requires.

glTF/GLB is the only interchange format here by design (ADR 0006): it carries
meshes, skins, animation and PBR materials in one file that Godot, Unity,
Unreal, three.js and Babylon all read natively.

The per-engine presets exist because the defaults are wrong for games in
specific, silent ways — Y-up conversion, +Z forward, whether cameras and lights
come along, whether unused animations get baked in.
"""

from __future__ import annotations

import json

import bpy
from lib import mat as mat_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from registry import OpError, op

PRESETS = {
    "godot": {
        "export_yup": True, "export_apply": True, "export_cameras": False,
        "export_lights": False, "export_extras": True, "export_tangents": True,
    },
    "unity": {
        "export_yup": True, "export_apply": True, "export_cameras": False,
        "export_lights": False, "export_extras": False, "export_tangents": True,
    },
    "unreal": {
        "export_yup": True, "export_apply": True, "export_cameras": False,
        "export_lights": False, "export_extras": False, "export_tangents": True,
    },
    "threejs": {
        "export_yup": True, "export_apply": True, "export_cameras": True,
        "export_lights": True, "export_extras": True, "export_tangents": False,
    },
    "raw": {
        "export_yup": True, "export_apply": False, "export_cameras": True,
        "export_lights": True, "export_extras": True, "export_tangents": False,
    },
}


@op(
    "export.gltf",
    summary="Export to GLB/glTF with an engine-specific preset. Checks for the things that silently break an import first — unapplied scale, missing UVs, procedural materials — and tells you rather than shipping a broken file.",
    params={
        "out": ("path", "asset.glb", "Output path (.glb binary or .gltf text)"),
        "objects": ("str[]", [], "Objects to export (empty = whole scene)"),
        "engine": (f"enum:{'|'.join(PRESETS)}", "godot", "Target engine preset"),
        "format": ("enum:glb|gltf", "glb", "Binary GLB (one file) or text glTF (separate assets)"),
        "animations": ("bool", True, "Include armature actions"),
        "draco": ("bool", False, "Draco mesh compression — smaller files, slower load, not all importers support it"),
        "strict": ("bool", True, "Fail on problems that would corrupt the import instead of warning"),
        "rename": ("obj", None, "Names to apply IN THE EXPORTED FILE ONLY, e.g. {\"horse\": \"Horse\", \"m_coat\": \"Coat\", \"gallop\": \"Gallop\"}. Game code often looks up nodes and materials by exact name, and those names break the studio's snake_case rule — this satisfies both without renaming the master"),
    },
    tags=["export", "io"],
)
def export_gltf(ctx, out, objects, engine, format, animations, draco, strict, rename):
    targets = [_get(n) for n in objects] if objects else list(bpy.context.scene.objects)
    meshes = [o for o in targets if o.type == "MESH"]
    if not targets:
        raise OpError("nothing to export — the scene is empty")

    problems, warnings = _preflight(meshes)
    if problems and strict:
        raise OpError(
            "export blocked by problems that would corrupt the import:\n  - "
            + "\n  - ".join(problems)
            + "\nFix these, or pass strict=false to export anyway."
        )
    for warning in warnings + (problems if not strict else []):
        ctx.note(warning)

    suffix = ".glb" if format == "glb" else ".gltf"
    path = ctx.out_path(out, suffix)
    settings = dict(PRESETS[engine])

    previous = [o for o in bpy.context.scene.objects if o.select_get()]
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    for obj in targets:
        obj.select_set(True)

    # Apply engine-contract names for the duration of the export, then put the
    # master's own snake_case names back. Renaming the datablocks permanently
    # would make the .blend fail `just asset-validate`.
    restore = _apply_renames(rename or {})

    try:
        bpy.ops.export_scene.gltf(
            filepath=str(path),
            export_format="GLB" if format == "glb" else "GLTF_SEPARATE",
            use_selection=True,
            export_animations=animations,
            # ACTIONS exports every action reachable from the rig, not just the
            # one currently assigned — which is what you want when a character
            # has idle/walk/run/attack authored as separate clips.
            export_animation_mode="ACTIONS",
            export_draco_mesh_compression_enable=draco,
            export_materials="EXPORT",
            export_image_format="AUTO",
            export_skins=True,
            export_morph=True,
            **settings,
        )
    except (RuntimeError, TypeError) as exc:
        raise OpError(f"glTF export failed: {exc}") from exc
    finally:
        for datablock, original in restore:
            datablock.name = original
        for obj in bpy.context.scene.objects:
            obj.select_set(False)
        for obj in previous:
            if obj.name in bpy.context.scene.objects:
                obj.select_set(True)

    if not path.is_file():
        raise OpError(f"glTF export reported success but wrote no file at {path}")

    return {
        "path": str(path),
        "rel": ctx.rel(path),
        "bytes": path.stat().st_size,
        "engine": engine,
        "format": format,
        "objects": [o.name for o in targets],
        "meshes": len(meshes),
        "triangles": sum(mesh_lib.tri_count(o) for o in meshes),
        "animations": [a.name for a in bpy.data.actions] if animations else [],
        "renamed": dict(rename or {}),
        "warnings": warnings,
    }


def _apply_renames(rename: dict):
    """Temporarily rename objects, materials and actions. Returns undo pairs."""
    if not rename:
        return []
    restore = []
    unmatched = []
    for source, target in rename.items():
        for collection in (bpy.data.objects, bpy.data.materials, bpy.data.actions):
            datablock = collection.get(source)
            if datablock is not None:
                restore.append((datablock, datablock.name))
                datablock.name = str(target)
                break
        else:
            unmatched.append(source)
    if unmatched:
        # Undo anything already applied so a typo cannot half-rename the export.
        for datablock, original in restore:
            datablock.name = original
        raise OpError(
            f"rename refers to names that do not exist: {sorted(unmatched)}. "
            "Check object/material/action names with session.info or material.list."
        )
    return restore


def _preflight(meshes):
    """Catch the failure modes that produce a file that imports but looks wrong."""
    problems: list[str] = []
    warnings: list[str] = []
    for obj in meshes:
        name = obj.name
        scale = obj.scale
        if any(abs(s - 1.0) > 1e-4 for s in scale):
            problems.append(
                f"'{name}' has unapplied scale {[round(s, 3) for s in scale]} — the engine will "
                "import it at the wrong size. Run object.transform apply=true."
            )
        if any(abs(r) > 1e-4 for r in obj.rotation_euler):
            warnings.append(
                f"'{name}' has unapplied rotation; most engines handle this, but physics and "
                "spawn alignment get confusing. Run object.transform apply=true."
            )
        if not obj.data.uv_layers:
            warnings.append(f"'{name}' has no UVs — any texture will be undefined. Run uv.unwrap.")
        if not obj.data.materials or all(m is None for m in obj.data.materials):
            warnings.append(f"'{name}' has no material; it will import as default grey.")
        for material in obj.data.materials:
            if material is None:
                continue
            safe, offenders = mat_lib.is_gltf_safe(material)
            if not safe:
                problems.append(
                    f"material '{material.name}' on '{name}' uses nodes glTF cannot express "
                    f"({offenders}) — run material.bake first or it exports as flat grey."
                )
        if len(obj.data.vertices) == 0:
            problems.append(f"'{name}' has no geometry.")
    return problems, warnings


@op(
    "export.blend",
    summary="Save the .blend master. Under ADR 0006 the .blend is the committed source of truth and the GLB is a derived artefact — always save both.",
    params={
        "out": ("path", "asset.blend", "Output .blend path"),
        "compress": ("bool", True, "Compress the file"),
        "pack_textures": ("bool", True, "Embed image textures in the .blend. A master links textures by RELATIVE path, so the moment it is copied into assets-source those links break and the committed master is useless — `just asset-validate` fails it on missing textures"),
    },
    tags=["export", "io"],
)
def export_blend(ctx, out, compress, pack_textures):
    packed = 0
    if pack_textures:
        # Filter on as little as possible. A baked map created with images.new()
        # and then saved keeps source "GENERATED" AND reports has_data False
        # once Blender frees the buffer — so both of the obvious filters skip
        # exactly the textures that most need packing, silently, leaving a
        # committed master whose texture links are dead.
        loose = [
            image
            for image in bpy.data.images
            if not image.packed_file and image.name != "Render Result"
        ]
        for image in loose:
            try:
                image.pack()
                packed += 1
            except RuntimeError as exc:  # generated image with nothing on disk
                ctx.note(f"could not pack '{image.name}': {exc}")

    path = ctx.out_path(out, ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True, compress=compress)
    return {
        "path": str(path),
        "rel": ctx.rel(path),
        "bytes": path.stat().st_size,
        "packed_textures": packed,
    }


@op(
    "export.meta",
    summary="Write the .meta.json sidecar the studio asset pipeline requires — id, licence, provenance including AI-generation disclosure, budgets and policies. Without this, `just asset-validate` rejects the asset.",
    params={
        "out": ("path", "asset.meta.json", "Output .meta.json path"),
        "asset_id": ("str", None, "snake_case asset identifier"),
        "category": ("enum:prop|character|environment|weapon|architecture|vfx|ui", "prop", "Asset category"),
        "license": ("str", "CC-BY-4.0", "Licence identifier"),
        "creator": ("str", "bforge", "Creator name"),
        "source": ("str", "procedural", "Where the asset came from"),
        "ai_tool": ("str", "bforge", "AI tool used — required for honest provenance"),
        "ai_model": ("str", "", "Model that drove the generation, if any"),
        "ai_prompt": ("str", "", "Prompt or intent that produced the asset"),
        "triangles": ("int", 0, "Triangle budget; 0 measures the scene"),
        "materials": ("int", 2, "Material budget"),
        "collision_policy": ("enum:explicit|auto|none", "explicit", "Collision policy"),
        "lod_policy": ("enum:explicit|auto|none", "auto", "LOD policy"),
    },
    tags=["export", "io"],
)
def export_meta(ctx, out, asset_id, category, license, creator, source, ai_tool, ai_model,
                ai_prompt, triangles, materials, collision_policy, lod_policy):
    identifier = scene_lib.sanitize(asset_id)
    meshes = [o for o in scene_lib.mesh_objects()]
    measured = sum(mesh_lib.tri_count(o) for o in meshes)
    payload = {
        "asset_id": identifier,
        "category": category,
        "license": license,
        "source": source,
        "creator": creator,
        "provenance": {
            "method": "ai_generated",
            "commercial_use_allowed": True,
            "modified": False,
            "ai": {
                "tool": ai_tool,
                "model": ai_model or "unspecified",
                "prompt": ai_prompt,
                "deterministic": True,
            },
        },
        "budgets": {
            "triangles": triangles or max(measured, 1),
            "materials": materials,
        },
        "collision_policy": collision_policy,
        "lod_policy": lod_policy,
        "measured": {
            "triangles": measured,
            "objects": len(meshes),
            "materials": sorted(
                {m.name for o in meshes for m in o.data.materials if m}
            ),
        },
    }
    path = ctx.out_path(out, ".json")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "rel": ctx.rel(path), "meta": payload}


@op(
    "export.asset",
    summary="One call: save the .blend master, export the GLB, write the .meta.json sidecar and render a contact sheet. The complete hand-off for a finished asset.",
    params={
        "asset_id": ("str", None, "snake_case asset identifier — names every output file"),
        "out_dir": ("path", "", "Directory for the outputs (defaults to the session output dir)"),
        "objects": ("str[]", [], "Objects to export (empty = whole scene)"),
        "engine": (f"enum:{'|'.join(PRESETS)}", "godot", "Target engine preset"),
        "category": ("enum:prop|character|environment|weapon|architecture|vfx|ui", "prop", "Asset category"),
        "ai_prompt": ("str", "", "What the asset was asked for — recorded in provenance"),
        "triangle_budget": ("int", 0, "Triangle budget recorded in metadata; 0 uses the measured export"),
        "material_budget": ("int", 0, "Material budget recorded in metadata; 0 uses the measured export"),
        "contact_sheet": ("bool", True, "Also render a review contact sheet"),
        "strict": ("bool", True, "Block export on problems that would corrupt the import"),
    },
    tags=["export", "io"],
)
def export_asset(ctx, asset_id, out_dir, objects, engine, category, ai_prompt, triangle_budget,
                 material_budget, contact_sheet, strict):
    from . import render as render_ops

    identifier = scene_lib.sanitize(asset_id)
    prefix = f"{out_dir.rstrip('/')}/{identifier}" if out_dir else identifier

    blend = export_blend(ctx, f"{prefix}.blend", True, True)
    glb = export_gltf(ctx, f"{prefix}.glb", objects, engine, "glb", True, False, strict, None)
    meshes = [obj for obj in scene_lib.mesh_objects()]
    measured_materials = len({
        material.name
        for obj in meshes
        for material in obj.data.materials
        if material
    })
    meta = export_meta(
        ctx, f"{prefix}.meta.json", identifier, category, "CC-BY-4.0", "bforge",
        "procedural", "bforge", "", ai_prompt, triangle_budget,
        material_budget or max(measured_materials, 1), "explicit", "auto",
    )
    outputs = {"blend": blend, "glb": glb, "meta": meta}
    if contact_sheet:
        outputs["contact_sheet"] = render_ops.render_contact_sheet(
            ctx, f"{prefix}_sheet.png", objects, 400, 20, "auto",
            ["hero", "front", "left", "top", "wireframe", "checker"], 3,
        )
    return {
        "asset_id": identifier,
        "outputs": {k: v.get("rel", v.get("path")) for k, v in outputs.items()},
        "triangles": glb["triangles"],
        "bytes": glb["bytes"],
        "warnings": glb.get("warnings", []),
        "detail": outputs,
    }


def _get(name):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
