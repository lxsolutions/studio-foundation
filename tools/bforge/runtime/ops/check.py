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
from lib import mat as mat_lib
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
    "check.materials",
    summary="Measure whether an asset's materials are actually distinguishable — the '8 materials, all the same brown' failure that produces mud-blob characters. Reports every material's colour in CIELAB and the pairwise perceptual distance (ΔE); fails when several materials are perceptually identical or share one roughness/metallic signature.",
    params={
        "objects": ("str[]", [], "Objects whose materials to measure (empty = every mesh)"),
        "min_delta_e": ("num", 12.0, "Perceptual-separation floor in ΔE76. Below ~6 the difference is invisible in game; 12 is a safe bar for metal vs leather vs cloth"),
    },
    tags=["check", "inspect", "material"],
    mutates=False,
)
def check_materials(ctx, objects, min_delta_e):
    targets = [_get(n) for n in objects] if objects else scene_lib.mesh_objects()
    targets = [o for o in targets if o.type == "MESH"]
    if not targets:
        raise OpError("no mesh objects to measure materials on")

    materials = []
    seen = set()
    for obj in targets:
        for material in obj.data.materials:
            if material is None or material.name in seen:
                continue
            seen.add(material.name)
            materials.append(_material_appearance(material))

    for entry in materials:
        entry["lab"] = [round(c, 2) for c in _linear_rgb_to_lab(*entry["base_color"][:3])]

    pairs = []
    for i in range(len(materials)):
        for j in range(i + 1, len(materials)):
            a, b = materials[i]["lab"], materials[j]["lab"]
            delta = sum((a[k] - b[k]) ** 2 for k in range(3)) ** 0.5
            pairs.append({"a": materials[i]["name"], "b": materials[j]["name"], "delta_e": round(delta, 2)})

    findings = []
    max_pair = max(pairs, key=lambda p: p["delta_e"]) if pairs else None
    if len(materials) >= 3 and max_pair and max_pair["delta_e"] < min_delta_e:
        findings.append(
            {
                "object": f"{len(materials)} materials",
                "severity": "error",
                "issue": "perceptually identical materials",
                "detail": f"the most distant pair ('{max_pair['a']}' vs '{max_pair['b']}') is only "
                          f"ΔE {max_pair['delta_e']:.1f} — every material reads as the same "
                          "substance, so the asset renders as one flat mass no matter how many "
                          "slots it has. This is the single most common reason generated "
                          "characters look like brown blobs",
                "fix": "separate metal/leather/cloth/skin with material.set + material.pbr "
                       "(distinct base colours AND roughness/metallic), then add wear with "
                       "paint.cavity and paint.height",
            }
        )
    if len(materials) >= 2:
        rough = [m["roughness"] for m in materials]
        metal = [m["metallic"] for m in materials]
        if max(rough) - min(rough) < 0.05 and max(metal) - min(metal) < 0.05:
            findings.append(
                {
                    "object": f"{len(materials)} materials",
                    "severity": "warn",
                    "issue": "no material language",
                    "detail": f"all materials share roughness {rough[0]:.2f} and metallic "
                              f"{metal[0]:.2f} — even distinct colours will read as one "
                              "substance because light responds identically to all of them",
                    "fix": "spread the response: metal metallic=1 roughness~0.3, leather "
                           "metallic=0 roughness~0.7, cloth roughness~0.9 (material.set)",
                }
            )

    return {
        "materials": materials,
        "pairs": pairs,
        "max_delta_e": max_pair["delta_e"] if max_pair else None,
        "findings": findings,
        "separated": not findings,
        "note": "colours are linear-space base colours; ΔE76 below ~6 is invisible at gameplay distance",
    }


def _material_appearance(material):
    """Base colour / roughness / metallic for a material, nodes or not."""
    if material.use_nodes:
        described = mat_lib._describes(material)
        if described is not None:
            base, roughness, metallic = described[0], described[1], described[2]
            return {
                "name": material.name,
                "base_color": [round(float(c), 4) for c in base[:3]],
                "hex": "#" + "".join(
                    f"{max(0, min(255, round(_linear_to_srgb(float(c)) * 255))):02x}"
                    for c in base[:3]
                ),
                "roughness": round(float(roughness), 4),
                "metallic": round(float(metallic), 4),
            }
    base = tuple(material.diffuse_color)
    return {
        "name": material.name,
        "base_color": [round(float(c), 4) for c in base[:3]],
        "hex": "#" + "".join(
            f"{max(0, min(255, round(_linear_to_srgb(float(c)) * 255))):02x}" for c in base[:3]
        ),
        "roughness": round(float(getattr(material, "roughness", 0.5)), 4),
        "metallic": round(float(getattr(material, "metallic", 0.0)), 4),
    }


def _linear_rgb_to_lab(r, g, b):
    """Linear sRGB -> CIELAB (D65). Deterministic stdlib math; ΔE76 is the
    Euclidean distance in this space."""
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505

    def f(t):
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0

    fx, fy, fz = f(x / 0.95047), f(y), f(z / 1.08883)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


@op(
    "check.style",
    summary="Compute the style fingerprint of every mesh: area-weighted palette (in CIELAB), texel density, triangle density, hard-edge ratio, material count, UV coverage. This is the raw material of art direction — 'do these 40 assets look like one game' is unanswerable without it.",
    params={
        "objects": ("str[]", [], "Objects to fingerprint (empty = every mesh)"),
        "texture_size": ("int", 1024, "Texture resolution the texel-density figure assumes"),
        "palette_size": ("int", 4, "Dominant colours to keep per object, area-weighted"),
    },
    tags=["check", "inspect", "material"],
    mutates=False,
)
def check_style(ctx, objects, texture_size, palette_size):
    targets = [_get(n) for n in objects] if objects else scene_lib.mesh_objects()
    targets = [o for o in targets if o.type == "MESH"]
    if not targets:
        raise OpError("no mesh objects to fingerprint")

    fingerprints = [_fingerprint(o, texture_size, palette_size) for o in targets]
    texels = [f["texel_density"] for f in fingerprints if f["texel_density"] > 0]
    return {
        "objects": fingerprints,
        "set": {
            "count": len(fingerprints),
            "median_texel_density": _median(texels) if texels else 0.0,
            "median_hard_edge_ratio": _median([f["hard_edge_ratio"] for f in fingerprints]),
            "median_tris_per_m3": _median([f["tris_per_m3"] for f in fingerprints]),
        },
    }


@op(
    "check.conformance",
    summary="Score how well each object conforms to the set's (or a reference object's) style fingerprint. Names the exact axis that breaks coherence — palette drift, texel-density mismatch, density outlier, edge-treatment drift — with the op that fixes it. The art-director gate: run it over a whole pack before export.",
    params={
        "objects": ("str[]", [], "Objects to score (empty = every mesh)"),
        "reference": ("str", "", "Conform to THIS object's fingerprint instead of the set median"),
        "texture_size": ("int", 1024, "Texture resolution the texel-density figure assumes"),
    },
    tags=["check", "inspect", "material"],
    mutates=False,
)
def check_conformance(ctx, objects, reference, texture_size):
    targets = [_get(n) for n in objects] if objects else scene_lib.mesh_objects()
    targets = [o for o in targets if o.type == "MESH"]
    if len(targets) < 2:
        raise OpError("conformance needs at least two objects — a set, or an object plus its reference")

    prints = {o.name: _fingerprint(o, texture_size, 4) for o in targets}
    if reference:
        if reference not in prints:
            raise OpError(f"reference '{reference}' is not among the objects")
        anchor = prints[reference]
    else:
        anchor = {
            "palette": _set_palette(list(prints.values())),
            "texel_density": _median([f["texel_density"] for f in prints.values()
                                      if f["texel_density"] > 0] or [0.0]),
            "hard_edge_ratio": _median([f["hard_edge_ratio"] for f in prints.values()]),
            "tris_per_m3": _median([f["tris_per_m3"] for f in prints.values()]),
            "materials": _median([f["materials"] for f in prints.values()]),
        }

    results = []
    for name, fp in prints.items():
        axes = {
            "palette": _palette_distance(fp["palette"], anchor["palette"]),
            "texel_density": _ratio_off(fp["texel_density"], anchor["texel_density"]),
            "hard_edge": abs(fp["hard_edge_ratio"] - anchor["hard_edge_ratio"]),
            "tris_density": _ratio_off(fp["tris_per_m3"], anchor["tris_per_m3"]),
            "materials": abs(fp["materials"] - anchor["materials"]),
        }
        # Penalty weights tuned so each axis fires at its known coherence-break
        # point: texel >2.5x (ADR-level finding), palette ΔE ~12 (the blob
        # floor), hard-edge drift ~0.35, density ~4x, material count ±2.
        penalty = min(100.0,
                      axes["palette"] / 12.0 * 25.0
                      + max(0.0, axes["texel_density"] - 1.0) * 20.0
                      + axes["hard_edge"] / 0.35 * 15.0
                      + max(0.0, axes["tris_density"] - 2.0) * 10.0
                      + axes["materials"] / 2.0 * 10.0)
        score = round(max(0.0, 100.0 - penalty), 1)
        worst = max(axes, key=lambda a: (
            axes["palette"] / 12.0 * 25.0 if a == "palette" else
            max(0.0, axes["texel_density"] - 1.0) * 20.0 if a == "texel_density" else
            axes["hard_edge"] / 0.35 * 15.0 if a == "hard_edge" else
            max(0.0, axes["tris_density"] - 2.0) * 10.0 if a == "tris_density" else
            axes["materials"] / 2.0 * 10.0))
        verdict = ("coherent" if score >= 75 else
                   "drifting" if score >= 45 else "outlier")
        results.append({
            "object": name,
            "score": score,
            "verdict": verdict,
            "axes": {k: round(v, 3) for k, v in axes.items()},
            "worst_axis": worst,
            "fix": _conformance_fix(name, worst, axes),
        })

    results.sort(key=lambda r: r["score"])
    return {
        "reference": reference or "(set median)",
        "objects": results,
        "coherent": sum(1 for r in results if r["verdict"] == "coherent"),
        "outliers": [r["object"] for r in results if r["verdict"] == "outlier"],
    }


def _fingerprint(obj, texture_size, palette_size):
    import bmesh

    mesh = obj.data
    tris = mesh_lib.tri_count(obj)
    bounds = mesh_lib.bounds(obj)
    volume = max(1e-6, bounds["size"][0] * bounds["size"][1] * bounds["size"][2])

    # Area-weighted palette from the materials actually facing outward.
    areas = {}
    for poly in mesh.polygons:
        if poly.material_index < len(mesh.materials) and mesh.materials[poly.material_index]:
            key = mesh.materials[poly.material_index].name
            areas[key] = areas.get(key, 0.0) + poly.area
    palette = []
    total_area = sum(areas.values()) or 1.0
    for mat_name, area in sorted(areas.items(), key=lambda kv: -kv[1])[:palette_size]:
        appearance = _material_appearance(bpy.data.materials[mat_name])
        palette.append({
            "material": mat_name,
            "hex": appearance["hex"],
            "lab": [round(c, 2) for c in _linear_rgb_to_lab(*appearance["base_color"])],
            "share": round(area / total_area, 3),
        })

    bm = bmesh.new()
    bm.from_mesh(mesh)
    hard = 0
    for edge in bm.edges:
        if len(edge.link_faces) == 2:
            angle = edge.link_faces[0].normal.angle(edge.link_faces[1].normal)
            if angle > 0.61:  # ~35 degrees, matching the studio shade threshold
                hard += 1
    boundary = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    bm.free()
    solid = max(1, len(mesh.edges) - boundary)

    uv_stats = uv_lib.stats(obj, texture_size=texture_size)
    return {
        "name": obj.name,
        "triangles": tris,
        "tris_per_m3": round(tris / volume, 1),
        "materials": len(areas),
        "palette": palette,
        "texel_density": uv_stats.get("texel_density_px_per_m", 0.0),
        "uv_coverage": uv_stats.get("coverage", 0.0),
        "hard_edge_ratio": round(hard / solid, 3),
    }


def _median(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _set_palette(fps):
    merged = {}
    for fp in fps:
        for entry in fp["palette"]:
            key = entry["hex"]
            if key not in merged or entry["share"] > merged[key]["share"]:
                merged[key] = entry
    return sorted(merged.values(), key=lambda e: -e["share"])[:6]


def _palette_distance(palette, anchor_palette):
    """Mean ΔE from each of the object's colours to the nearest anchor colour."""
    if not palette or not anchor_palette:
        return 0.0
    total = 0.0
    weight = 0.0
    for entry in palette:
        best = min(
            sum((entry["lab"][k] - anchor["lab"][k]) ** 2 for k in range(3)) ** 0.5
            for anchor in anchor_palette
        )
        total += best * entry["share"]
        weight += entry["share"]
    return total / max(weight, 1e-6)


def _ratio_off(value, anchor):
    """log2-style fold distance from the anchor: 0 = identical, 1 = 2x off."""
    if value <= 0 or anchor <= 0:
        return 0.0
    import math as _math
    return abs(_math.log2(value / anchor))


def _conformance_fix(name, worst, axes):
    if worst == "palette":
        return (f"'{name}' palette drifts ΔE {axes['palette']:.1f} from the set — "
                "re-colour with material.set using the set's hex values (check.style "
                "prints them), then re-run check.conformance")
    if worst == "texel_density":
        return (f"'{name}' texel density is {axes['texel_density']:.1f} doublings off the "
                "set — re-unwrap with uv.unwrap using the SAME uv_scale as the rest of "
                "the pack")
    if worst == "hard_edge":
        return (f"'{name}' edge treatment differs — object.shade angle=35 to match the "
                "studio threshold, or add the missing chamfer with build.bevel")
    if worst == "tris_density":
        return (f"'{name}' spends triangles {axes['tris_density']:.1f} doublings off the "
                "set's density — gameready.optimize or raise the generator detail to match")
    return (f"'{name}' uses {axes['materials']:.0f} more/fewer materials than the set — "
            "gameready.atlas or material.consolidate")


@op(
    "check.image",
    summary="Measure an image instead of eyeballing it: luminance range, blown highlights, crushed blacks, contrast, saturation, dominant colours and subject coverage. Reading a render is slow and cannot tell 'the asset is wrong' from 'the render is over-lit'. These numbers can, in a fraction of the time.",    params={
        "path": ("path", None, "PNG to analyse — a render, a contact sheet, or a baked texture"),
        "colors": ("int", 6, "How many dominant colours to report"),
        "background": ("color", [0.05, 0.055, 0.065, 1.0], "Backdrop colour, excluded from subject stats"),
    },
    tags=["check", "inspect"],
    mutates=False,
)
def check_image(ctx, path, colors, background):
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - Blender bundles numpy
        raise OpError("numpy unavailable in this Blender build") from exc

    target = ctx.resolve(path)
    if not target.is_file():
        target = ctx.out_path(path, ".png")
    if not target.is_file():
        raise OpError(f"no image at {target}")

    image = bpy.data.images.load(str(target))
    try:
        width, height = image.size
        data = numpy.array(image.pixels[:], dtype=numpy.float32).reshape((height, width, 4))
    finally:
        bpy.data.images.remove(image)

    rgb = data[:, :, :3]
    # Rec. 709 luma: matches how an eye weights the channels, so "too bright"
    # here means what it means visually.
    luma = rgb @ numpy.array([0.2126, 0.7152, 0.0722], dtype=numpy.float32)

    # Sample the actual corners rather than trusting a nominal backdrop colour:
    # the world is lit and tone-mapped like everything else, so the rendered
    # background never matches the value that was set on it.
    corner = min(8, width // 8, height // 8) or 1
    corners = numpy.concatenate([
        rgb[:corner, :corner].reshape(-1, 3), rgb[:corner, -corner:].reshape(-1, 3),
        rgb[-corner:, :corner].reshape(-1, 3), rgb[-corner:, -corner:].reshape(-1, 3),
    ])
    backdrop = numpy.median(corners, axis=0)
    if float(numpy.std(corners)) > 0.05:
        backdrop = numpy.array(background[:3], dtype=numpy.float32)
    distance = numpy.linalg.norm(rgb - backdrop, axis=2)
    subject = distance > 0.06
    coverage = float(subject.mean())
    if coverage < 1e-4:
        raise OpError(
            f"{target.name} is essentially empty — nothing but backdrop. The camera "
            "is probably pointed away from the subject, or the scene is unlit."
        )

    subject_luma = luma[subject]
    subject_rgb = rgb[subject]
    peak = float(numpy.percentile(subject_luma, 99))
    floor = float(numpy.percentile(subject_luma, 1))
    blown = float((subject_luma > 0.97).mean())
    crushed = float((subject_luma < 0.02).mean())

    maxc = subject_rgb.max(axis=1)
    minc = subject_rgb.min(axis=1)
    saturation = float(numpy.mean((maxc - minc) / numpy.maximum(maxc, 1e-5)))

    # Quantise to a coarse grid and count — cheap, deterministic, and enough to
    # answer "is this thing actually the colour I asked for".
    quantised = numpy.clip((subject_rgb * 8).astype(numpy.int32), 0, 7)
    keys = quantised[:, 0] * 64 + quantised[:, 1] * 8 + quantised[:, 2]
    unique, counts = numpy.unique(keys, return_counts=True)
    order = numpy.argsort(-counts)[: max(1, colors)]
    dominant = []
    for index in order:
        key = int(unique[index])
        bucket = ((key // 64) / 8.0, ((key // 8) % 8) / 8.0, (key % 8) / 8.0)
        members = subject_rgb[keys == key]
        mean = members.mean(axis=0)
        dominant.append({
            "linear": [round(float(c), 4) for c in mean],
            "hex": "#" + "".join(
                f"{max(0, min(255, round(_linear_to_srgb(float(c)) * 255))):02x}" for c in mean
            ),
            "share": round(float(counts[index]) / len(keys), 4),
            "_bucket": [round(b, 3) for b in bucket],
        })

    findings = []
    if blown > 0.08:
        findings.append(
            f"{blown:.0%} of the subject is blown to white — the LIGHTING is too hot, "
            "not the material. Lower the light rig or check the view transform before "
            "touching the albedo."
        )
    if crushed > 0.12:
        findings.append(f"{crushed:.0%} of the subject is crushed to black — add fill light.")
    if peak - floor < 0.12:
        findings.append(
            f"contrast is flat (luma {floor:.2f}..{peak:.2f}); the form will not read."
        )
    if saturation < 0.06:
        findings.append(
            f"near-monochrome (mean saturation {saturation:.2f}) — if colour was expected, "
            "the material is probably not reaching the shader."
        )
    if coverage < 0.04:
        findings.append(
            f"the subject fills only {coverage:.1%} of frame — move the camera closer."
        )

    return {
        "path": str(target),
        "size": [width, height],
        "subject_coverage": round(coverage, 4),
        "luma": {
            "mean": round(float(subject_luma.mean()), 4),
            "p1": round(floor, 4),
            "p99": round(peak, 4),
            "contrast": round(peak - floor, 4),
            "space": "srgb (as displayed)",
        },
        # A PNG is sRGB-encoded. Albedo, light power and every other physical
        # quantity are LINEAR. Comparing a displayed luma against a linear
        # target silently misreads exposure by ~2x — it did exactly that during
        # light-rig calibration. Both are reported so the mistake is not
        # available to make.
        "luma_linear": {
            "mean": round(float(_srgb_to_linear_array(numpy, subject_luma).mean()), 4),
            "space": "linear (physical)",
        },
        "blown_highlights": round(blown, 4),
        "crushed_shadows": round(crushed, 4),
        "mean_saturation": round(saturation, 4),
        # The straight mean, un-quantised. `dominant_colors` buckets into 8
        # levels per channel, which is fine for "what colour family is this"
        # and useless for dark values — a 0.05 albedo falls in bucket 0 whose
        # midpoint is 0.06, reporting a colour 4x too bright. Use this for any
        # comparison against a requested colour.
        "mean_color": {
            "linear": [round(float(c), 4) for c in subject_rgb.mean(axis=0)],
            "hex": "#" + "".join(
                f"{max(0, min(255, round(_linear_to_srgb(float(c)) * 255))):02x}"
                for c in subject_rgb.mean(axis=0)
            ),
        },
        "dominant_colors": dominant,
        "findings": findings,
        "ok": not findings,
    }


def _srgb_to_linear_array(numpy, values):
    return numpy.where(
        values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4
    )


def _linear_to_srgb(value):
    if value <= 0.0031308:
        return value * 12.92
    return 1.055 * (max(value, 0.0) ** (1 / 2.4)) - 0.055


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
