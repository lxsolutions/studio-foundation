"""Validation and critique.

`check.asset` mirrors `tools/blender/validate.py` (ADR 0006) so an agent finds
out about a problem while the scene is still open and fixable, rather than at
`just asset-validate` time when it has already committed the file.

`check.critique` is the numeric half of the feedback loop that
`render.contact_sheet` covers visually — it names specific defects and the op
that fixes each one, because "your mesh has issues" is not actionable and
"triangle density on the base is 8x the rest, run gameready.optimize" is.
"""

from __future__ import annotations

import re

import bpy
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from lib import uvs as uv_lib
from registry import OpError, op

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(-col|-convcol|_lod[0-9])?$")
ALLOWED_NODES = {
    "BSDF_PRINCIPLED", "TEX_IMAGE", "NORMAL_MAP", "UVMAP", "OUTPUT_MATERIAL",
    "MIX", "MIX_RGB", "SEPARATE_COLOR", "COMBINE_COLOR", "MAPPING", "TEX_COORD",
    "VERTEX_COLOR", "ATTRIBUTE", "VALUE", "RGB",
}


@op(
    "check.asset",
    summary="Run the studio's ADR 0006 asset rules against the open scene: naming, units, applied transforms, origins, UVs, budgets, bone conventions, collision, textures, glTF-safe shaders. Same checks as `just asset-validate`, but before you write the file.",
    params={
        "triangle_budget": ("int", 2000, "Triangle ceiling for the check"),
        "material_budget": ("int", 2, "Material ceiling"),
        "require_collision": ("bool", False, "Fail when no -col/-convcol proxy exists"),
        "require_lods": ("bool", False, "Fail when no _lod1 object exists"),
    },
    tags=["check", "inspect"],
    mutates=False,
)
def check_asset(ctx, triangle_budget, material_budget, require_collision, require_lods):
    checks: list[dict] = []

    def record(check_id, ok, message, level="error"):
        checks.append({"id": check_id, "level": "ok" if ok else level, "msg": message})

    scene = bpy.context.scene
    record(
        "units",
        scene.unit_settings.system == "METRIC"
        and abs(scene.unit_settings.scale_length - 1.0) < 1e-6,
        "Scene must be Metric with unit scale 1.0 — run session.reset",
    )

    all_meshes = scene_lib.mesh_objects()
    render_meshes = [
        o for o in all_meshes if "-col" not in o.name and "-convcol" not in o.name
    ]

    for obj in bpy.context.scene.objects:
        record(
            f"naming:{obj.name}",
            NAME_RE.match(obj.name) is not None,
            f"'{obj.name}' must be snake_case with an optional -col/-convcol/_lodN suffix "
            "— run object.rename",
        )

    for obj in all_meshes:
        clean = all(abs(a) < 1e-5 for a in obj.rotation_euler) and all(
            abs(s - 1.0) < 1e-5 for s in obj.scale
        )
        record(
            f"transforms:{obj.name}",
            clean,
            f"'{obj.name}' has unapplied rotation/scale — run object.transform apply=true",
        )

    for obj in [o for o in render_meshes if o.parent is None]:
        # ERROR, not warn: tools/blender/validate.py fails the build on this, and
        # a pre-flight check that is more lenient than the real gate is worse
        # than no check at all — it tells you you are fine right up until CI
        # says otherwise.
        record(
            f"origin:{obj.name}",
            all(abs(c) < 1e-4 for c in obj.location),
            f"Root object '{obj.name}' must sit at the world origin — run "
            "gameready.pivot with to_origin=true",
        )

    for obj in render_meshes:
        record(
            f"uvs:{obj.name}",
            len(obj.data.uv_layers) >= 1,
            f"'{obj.name}' has no UV map — run uv.unwrap",
        )

    material_names = {m.name for o in render_meshes for m in o.data.materials if m}
    record(
        "materials",
        len(material_names) <= material_budget,
        f"{len(material_names)} materials exceeds budget {material_budget} "
        "— run gameready.atlas",
    )

    triangles = sum(mesh_lib.tri_count(o) for o in render_meshes)
    record(
        "triangles",
        triangles <= triangle_budget,
        f"{triangles} triangles exceeds budget {triangle_budget} "
        "— run gameready.lod or lower the generator's detail parameters",
    )

    for armature in [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]:
        bad = [b.name for b in armature.data.bones if not re.match(r"^[a-z][a-z0-9_.]*$", b.name)]
        record(f"skeleton:{armature.name}", not bad, f"Bones must be snake_case: {bad[:5]}")
        roots = [b for b in armature.data.bones if b.parent is None]
        record(
            f"skeleton_root:{armature.name}",
            len(roots) == 1,
            f"'{armature.name}' must have exactly one root bone, has {len(roots)}: "
            f"{[b.name for b in roots][:5]}",
        )

    for action in bpy.data.actions:
        record(
            f"anim_naming:{action.name}",
            re.match(r"^[a-z][a-z0-9_]*$", action.name) is not None,
            f"Action '{action.name}' must be snake_case",
        )

    if require_collision:
        record(
            "collision",
            any("-col" in o.name or "-convcol" in o.name for o in all_meshes),
            "No collision proxy — run gameready.collision",
        )
    if require_lods:
        record(
            "lods",
            any(re.search(r"_lod[1-9]$", o.name) for o in all_meshes),
            "No LOD chain — run gameready.lod",
        )

    for image in bpy.data.images:
        if image.source == "FILE" and not image.packed_file:
            record(
                f"texture:{image.name}",
                bool(image.filepath) and bpy.path.abspath(image.filepath),
                f"Texture '{image.name}' has no resolvable path",
                level="warn",
            )

    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        offenders = sorted(
            {
                n.type
                for n in material.node_tree.nodes
                if n.type not in ALLOWED_NODES and n.type not in ("FRAME", "REROUTE")
            }
        )
        record(
            f"shader:{material.name}",
            not offenders,
            f"'{material.name}' uses nodes glTF cannot export: {offenders} "
            "— run material.bake",
        )

    errors = [c for c in checks if c["level"] == "error"]
    warnings = [c for c in checks if c["level"] == "warn"]
    return {
        "ok": not errors,
        "triangles": triangles,
        "materials": len(material_names),
        "errors": len(errors),
        "warnings": len(warnings),
        "failures": [c for c in checks if c["level"] != "ok"],
        "checks": checks,
    }


@op(
    "check.critique",
    summary="Quality critique with specific, actionable findings: triangle-density hot spots, degenerate and n-gon faces, UV stretch, texel-density mismatch between objects, non-manifold edges, unused material slots. Pair it with render.contact_sheet — numbers plus eyes.",
    params={
        "objects": ("str[]", [], "Objects to critique (empty = every mesh)"),
        "texture_size": ("int", 1024, "Texture resolution the texel-density figures assume"),
    },
    tags=["check", "inspect"],
    mutates=False,
)
def check_critique(ctx, objects, texture_size):
    import bmesh

    targets = [_get(n) for n in objects] if objects else scene_lib.mesh_objects()
    targets = [o for o in targets if o.type == "MESH"]
    if not targets:
        raise OpError("no mesh objects to critique")

    findings: list[dict] = []
    densities = []
    rows = []

    for obj in targets:
        mesh = obj.data
        tris = mesh_lib.tri_count(obj)
        bounds = mesh_lib.bounds(obj)
        volume = max(1e-6, bounds["size"][0] * bounds["size"][1] * bounds["size"][2])

        bm = bmesh.new()
        bm.from_mesh(mesh)
        ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
        degenerate = sum(1 for f in bm.faces if f.calc_area() < 1e-9)
        non_manifold = sum(1 for e in bm.edges if len(e.link_faces) not in (1, 2))
        loose = sum(1 for v in bm.verts if not v.link_edges)
        boundary = sum(1 for e in bm.edges if len(e.link_faces) == 1)
        areas = [f.calc_area() for f in bm.faces if f.calc_area() > 1e-12]
        bm.free()

        uv_stats = uv_lib.stats(obj, texture_size=texture_size)
        density = uv_stats.get("texel_density_px_per_m", 0.0)
        if density > 0:
            densities.append((obj.name, density))

        rows.append(
            {
                "name": obj.name,
                "triangles": tris,
                "tris_per_m3": round(tris / volume, 1),
                "ngons": ngons,
                "degenerate_faces": degenerate,
                "non_manifold_edges": non_manifold,
                "loose_vertices": loose,
                "boundary_edges": boundary,
                "texel_density": density,
                "uv_overlap": uv_lib.overlap_estimate(obj) if uv_stats.get("has_uvs") else None,
                "material_slots": len(mesh.materials),
                "empty_material_slots": sum(1 for m in mesh.materials if m is None),
            }
        )

        if degenerate:
            findings.append(
                {
                    "object": obj.name, "severity": "error", "issue": "degenerate faces",
                    "detail": f"{degenerate} zero-area faces will render as artefacts",
                    "fix": f"gameready.optimize objects=['{obj.name}']",
                }
            )
        if non_manifold:
            findings.append(
                {
                    "object": obj.name, "severity": "warn", "issue": "non-manifold edges",
                    "detail": f"{non_manifold} edges shared by more than two faces — breaks "
                              "boolean ops, physics cooking and normal baking",
                    "fix": f"build.cleanup name='{obj.name}' merge_distance=0.001",
                }
            )
        if loose:
            findings.append(
                {
                    "object": obj.name, "severity": "warn", "issue": "loose vertices",
                    "detail": f"{loose} vertices belong to no face; they inflate the vertex "
                              "buffer for nothing",
                    "fix": f"gameready.optimize objects=['{obj.name}']",
                }
            )
        if ngons:
            findings.append(
                {
                    "object": obj.name, "severity": "info", "issue": "n-gons",
                    "detail": f"{ngons} faces with more than 4 sides; engines triangulate these "
                              "unpredictably, which can flip shading",
                    "fix": f"gameready.optimize objects=['{obj.name}'] triangulate=true",
                }
            )
        if not uv_stats.get("has_uvs"):
            findings.append(
                {
                    "object": obj.name, "severity": "error", "issue": "no UVs",
                    "detail": "textures cannot be applied",
                    "fix": f"uv.unwrap object='{obj.name}' style='smart_packed'",
                }
            )
        elif uv_stats.get("coverage", 0) < 0.25 and uv_stats.get("faces_outside_0_1", 0) == 0:
            findings.append(
                {
                    "object": obj.name, "severity": "warn", "issue": "low UV coverage",
                    "detail": f"islands fill only {uv_stats['coverage']:.0%} of the texture; "
                              "most texture memory is wasted on empty space",
                    "fix": f"uv.pack object='{obj.name}' margin=0.01",
                }
            )
        if areas:
            largest, smallest = max(areas), min(areas)
            if smallest > 0 and largest / smallest > 4000:
                findings.append(
                    {
                        "object": obj.name, "severity": "info",
                        "issue": "uneven face density",
                        "detail": f"largest face is {largest / smallest:,.0f}x the smallest — "
                                  "detail is concentrated somewhere that may not need it",
                        "fix": "check the wireframe panel of render.contact_sheet",
                    }
                )
        empty_slots = sum(1 for m in mesh.materials if m is None)
        if empty_slots:
            findings.append(
                {
                    "object": obj.name, "severity": "warn", "issue": "empty material slots",
                    "detail": f"{empty_slots} slots with no material export as default grey",
                    "fix": f"material.set object='{obj.name}'",
                }
            )

    if len(densities) > 1:
        values = [d for _n, d in densities]
        low, high = min(values), max(values)
        if low > 0 and high / low > 2.5:
            worst_low = min(densities, key=lambda item: item[1])
            worst_high = max(densities, key=lambda item: item[1])
            findings.append(
                {
                    "object": f"{worst_low[0]} vs {worst_high[0]}", "severity": "warn",
                    "issue": "inconsistent texel density",
                    "detail": f"'{worst_low[0]}' is {low:.0f} px/m but '{worst_high[0]}' is "
                              f"{high:.0f} px/m ({high / low:.1f}x). Side by side, one will look "
                              "blurry or noisy against the other — this is the most common "
                              "reason a set of individually-fine assets looks wrong together",
                    "fix": "re-run uv.unwrap style='box' with the SAME scale on both, "
                           "or uv.pack to equalise",
                }
            )

    severity_rank = {"error": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: severity_rank.get(f["severity"], 3))
    return {
        "objects": rows,
        "findings": findings,
        "errors": sum(1 for f in findings if f["severity"] == "error"),
        "warnings": sum(1 for f in findings if f["severity"] == "warn"),
        "clean": not findings,
        "texel_densities": dict(densities),
    }


@op(
    "check.silhouette",
    summary="Score how readable an object's silhouette is from the standard game camera angles. A prop that fails here will not read at gameplay distance no matter how good its texture is.",
    params={
        "name": ("str", None, "Object to test"),
        "samples": ("int", 64, "Rays per axis for the projected-area estimate"),
    },
    tags=["check", "inspect"],
    mutates=False,
)
def check_silhouette(ctx, name, samples):
    obj = _get(name)
    if obj.type != "MESH":
        raise OpError(f"'{name}' is a {obj.type}, not a mesh")
    bounds = mesh_lib.bounds(obj)
    size = bounds["size"]
    if min(size) < 1e-6:
        raise OpError(f"'{name}' is flat in at least one axis; silhouette scoring needs volume")

    # Ratio of the object's projected area to its bounding-box area, per axis.
    # Low values mean a boxy, unreadable shape; very high values mean a shape so
    # thin it disappears at distance.
    from mathutils import Vector

    matrix = obj.matrix_world
    inverse = matrix.inverted()
    results = {}
    for axis_name, axis in (("front", (0, 1, 0)), ("side", (1, 0, 0)), ("top", (0, 0, 1))):
        others = [i for i in range(3) if axis[i] == 0]
        hits = 0
        total = 0
        steps = max(8, min(128, samples))
        for i in range(steps):
            for j in range(steps):
                point = [0.0, 0.0, 0.0]
                point[others[0]] = bounds["min"][others[0]] + size[others[0]] * (i + 0.5) / steps
                point[others[1]] = bounds["min"][others[1]] + size[others[1]] * (j + 0.5) / steps
                index = axis.index(1)
                point[index] = bounds["min"][index] - size[index]
                direction = [0.0, 0.0, 0.0]
                direction[index] = 1.0
                origin = inverse @ Vector(point)
                local_dir = (inverse.to_3x3() @ Vector(direction)).normalized()
                hit, _loc, _nrm, _idx = obj.ray_cast(origin, local_dir)
                total += 1
                hits += 1 if hit else 0
        results[axis_name] = round(hits / max(1, total), 4)

    fill = sum(results.values()) / 3.0
    if fill > 0.88:
        verdict = "boxy — the silhouette is nearly its bounding box, so it will read as a crate at distance"
        advice = "cut into the shape: build.extrude with a negative distance, or add asymmetry"
    elif fill < 0.16:
        verdict = "sparse — very little solid area, it will disappear at gameplay distance"
        advice = "thicken the main forms, or accept it only as a close-range detail prop"
    else:
        verdict = "good — clear, readable form with real negative space"
        advice = "no action needed"
    return {
        "object": obj.name,
        "fill_ratio": results,
        "average_fill": round(fill, 4),
        "verdict": verdict,
        "advice": advice,
        "bounds": bounds,
    }


def _get(name):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
