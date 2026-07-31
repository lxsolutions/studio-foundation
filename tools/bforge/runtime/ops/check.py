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
    "BSDF_PRINCIPLED",
    "TEX_IMAGE",
    "NORMAL_MAP",
    "UVMAP",
    "OUTPUT_MATERIAL",
    "MIX",
    "MIX_RGB",
    "SEPARATE_COLOR",
    "COMBINE_COLOR",
    "MAPPING",
    "TEX_COORD",
    "VERTEX_COLOR",
    "ATTRIBUTE",
    "VALUE",
    "RGB",
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
    render_meshes = [o for o in all_meshes if "-col" not in o.name and "-convcol" not in o.name]

    for obj in bpy.context.scene.objects:
        record(
            f"naming:{obj.name}",
            NAME_RE.match(obj.name) is not None,
            f"'{obj.name}' must be snake_case with an optional -col/-convcol/_lodN suffix "
            "— run object.rename",
        )

    for obj in all_meshes:
        bone_attachment = (
            obj.parent_type == "BONE" and obj.parent is not None and obj.parent.type == "ARMATURE"
        )
        # A bone-attached prop necessarily carries a local rotation/offset: that
        # is how a vertical spear is aligned to a hand bone. Applying it after
        # parenting destroys the authored attachment. Scale must still be clean.
        clean = (bone_attachment or all(abs(a) < 1e-5 for a in obj.rotation_euler)) and all(
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
        f"{len(material_names)} materials exceeds budget {material_budget} — run gameready.atlas",
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
            f"'{material.name}' uses nodes glTF cannot export: {offenders} — run material.bake",
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
    summary="Quality critique with specific, actionable findings: topology and UV faults, texel-density drift, unused slots, and natural rock that never received a textured or layered surface. Pair it with render.contact_sheet — numbers plus eyes.",
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
        materials = [material for material in mesh.materials if material is not None]
        image_materials = sum(
            1
            for material in materials
            if material.use_nodes
            and material.node_tree
            and any(
                node.type == "TEX_IMAGE" and getattr(node, "image", None) is not None
                for node in material.node_tree.nodes
            )
        )
        layered_materials = sum(
            1 for material in materials if bool(material.get("bforge_procedural"))
        )

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
                "image_materials": image_materials,
                "layered_materials": layered_materials,
            }
        )

        if degenerate:
            findings.append(
                {
                    "object": obj.name,
                    "severity": "error",
                    "issue": "degenerate faces",
                    "detail": f"{degenerate} zero-area faces will render as artefacts",
                    "fix": f"gameready.optimize objects=['{obj.name}']",
                }
            )
        if non_manifold:
            findings.append(
                {
                    "object": obj.name,
                    "severity": "warn",
                    "issue": "non-manifold edges",
                    "detail": f"{non_manifold} edges shared by more than two faces — breaks "
                    "boolean ops, physics cooking and normal baking",
                    "fix": f"build.cleanup name='{obj.name}' merge_distance=0.001",
                }
            )
        if loose:
            findings.append(
                {
                    "object": obj.name,
                    "severity": "warn",
                    "issue": "loose vertices",
                    "detail": f"{loose} vertices belong to no face; they inflate the vertex "
                    "buffer for nothing",
                    "fix": f"gameready.optimize objects=['{obj.name}']",
                }
            )
        if ngons:
            findings.append(
                {
                    "object": obj.name,
                    "severity": "info",
                    "issue": "n-gons",
                    "detail": f"{ngons} faces with more than 4 sides; engines triangulate these "
                    "unpredictably, which can flip shading",
                    "fix": f"gameready.optimize objects=['{obj.name}'] triangulate=true",
                }
            )
        if not uv_stats.get("has_uvs"):
            findings.append(
                {
                    "object": obj.name,
                    "severity": "error",
                    "issue": "no UVs",
                    "detail": "textures cannot be applied",
                    "fix": f"uv.unwrap object='{obj.name}' style='smart_packed'",
                }
            )
        elif uv_stats.get("coverage", 0) < 0.25 and uv_stats.get("faces_outside_0_1", 0) == 0:
            findings.append(
                {
                    "object": obj.name,
                    "severity": "warn",
                    "issue": "low UV coverage",
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
                        "object": obj.name,
                        "severity": "info",
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
                    "object": obj.name,
                    "severity": "warn",
                    "issue": "empty material slots",
                    "detail": f"{empty_slots} slots with no material export as default grey",
                    "fix": f"material.set object='{obj.name}'",
                }
            )
        if obj.get("bforge_asset_kind") == "rock" and not image_materials and not layered_materials:
            findings.append(
                {
                    "object": obj.name,
                    "severity": "warn",
                    "issue": "flat natural rock surface",
                    "detail": "the geological silhouette has only a constant material; at FPS "
                    "distance it will read as faceted blockout geometry rather than stone",
                    "fix": f"material.pbr object='{obj.name}' base_color='stone_warm' "
                    f"roughness=0.9; material.bake_pbr object='{obj.name}'",
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
                    "object": f"{worst_low[0]} vs {worst_high[0]}",
                    "severity": "warn",
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
    "check.image",
    summary="Measure an image instead of eyeballing it: luminance range, blown highlights, crushed blacks, contrast, saturation, dominant colours and subject coverage. Reading a render is slow and cannot tell 'the asset is wrong' from 'the render is over-lit'. These numbers can, in a fraction of the time.",
    params={
        "path": (
            "path",
            None,
            "PNG, JPEG or WebP to analyse — a render, sprite sheet, contact sheet, or baked texture",
        ),
        "colors": ("int", 6, "How many dominant colours to report"),
        "background": (
            "color",
            [0.05, 0.055, 0.065, 1.0],
            "Backdrop colour, excluded from subject stats",
        ),
        "require_alpha": (
            "bool",
            False,
            "Fail when the image has no meaningful transparent pixels",
        ),
        "require_clear_corners": (
            "bool",
            False,
            "Fail when the four corners are not transparent; useful for UI icons and cutouts",
        ),
        "require_square": ("bool", False, "Fail when width and height differ"),
        "minimum_size": (
            "int",
            0,
            "Fail when either image dimension is below this many pixels (0 disables)",
        ),
        "minimum_coverage": (
            "num",
            0.04,
            "Minimum fraction of the frame occupied by the visible subject",
        ),
        "maximum_coverage": (
            "num",
            1.0,
            "Maximum fraction of the frame occupied by the visible subject",
        ),
    },
    tags=["check", "inspect"],
    mutates=False,
)
def check_image(
    ctx,
    path,
    colors,
    background,
    require_alpha,
    require_clear_corners,
    require_square,
    minimum_size,
    minimum_coverage,
    maximum_coverage,
):
    if minimum_size < 0:
        raise OpError("minimum_size must be zero or greater")
    if not 0 <= minimum_coverage <= maximum_coverage <= 1:
        raise OpError("coverage bounds must satisfy 0 <= minimum_coverage <= maximum_coverage <= 1")
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
    alpha = data[:, :, 3]
    # Rec. 709 luma: matches how an eye weights the channels, so "too bright"
    # here means what it means visually.
    luma = rgb @ numpy.array([0.2126, 0.7152, 0.0722], dtype=numpy.float32)

    corner = min(8, width // 8, height // 8) or 1
    corner_alpha = numpy.concatenate(
        [
            alpha[:corner, :corner].reshape(-1),
            alpha[:corner, -corner:].reshape(-1),
            alpha[-corner:, :corner].reshape(-1),
            alpha[-corner:, -corner:].reshape(-1),
        ]
    )
    transparent_fraction = float((alpha <= 0.01).mean())
    partial_fraction = float(((alpha > 0.01) & (alpha < 0.99)).mean())
    has_transparency = transparent_fraction > 1e-4 or partial_fraction > 1e-4
    corners_clear = float((corner_alpha <= 0.01).mean()) >= 0.99

    # Alpha is the authoritative subject mask for a cutout. Previously a
    # transparent green-screen removal was measured as though invisible RGB
    # fringe were visible background, giving a false coverage number and no way
    # to prove that a UI icon actually had useful transparency.
    if has_transparency:
        subject = alpha > 0.01
    else:
        # Sample the actual corners rather than trusting a nominal backdrop
        # colour: the world is lit and tone-mapped like everything else, so the
        # rendered background rarely matches the value originally assigned.
        corners = numpy.concatenate(
            [
                rgb[:corner, :corner].reshape(-1, 3),
                rgb[:corner, -corner:].reshape(-1, 3),
                rgb[-corner:, :corner].reshape(-1, 3),
                rgb[-corner:, -corner:].reshape(-1, 3),
            ]
        )
        backdrop = numpy.median(corners, axis=0)
        if float(numpy.std(corners)) > 0.05:
            backdrop = numpy.array(background[:3], dtype=numpy.float32)
        distance = numpy.linalg.norm(rgb - backdrop, axis=2)
        subject = distance > 0.06

    coverage = float(subject.mean())
    if coverage < 1e-4:
        raise OpError(
            f"{target.name} is essentially empty — nothing but backdrop or transparent "
            "pixels. The camera is probably pointed away from the subject, or the alpha "
            "matte removed it."
        )

    validation_findings = []
    if require_alpha and not has_transparency:
        validation_findings.append(
            "alpha is required, but the image is fully opaque — export RGBA or remove "
            "the chroma-key background before shipping."
        )
    if require_clear_corners and not corners_clear:
        validation_findings.append(
            "the corners are not transparent — trim the backdrop or add padding around "
            "the cutout before using it as a UI icon."
        )
    if require_square and width != height:
        validation_findings.append(
            f"image is {width}x{height}, not square — crop to a square icon canvas."
        )
    if minimum_size > 0 and min(width, height) < minimum_size:
        validation_findings.append(
            f"short edge is {min(width, height)}px, below the {minimum_size}px minimum."
        )
    if coverage < minimum_coverage:
        validation_findings.append(
            f"the subject fills only {coverage:.1%} of frame, below the "
            f"{minimum_coverage:.1%} minimum — crop closer."
        )
    if coverage > maximum_coverage:
        validation_findings.append(
            f"the subject fills {coverage:.1%} of frame, above the "
            f"{maximum_coverage:.1%} maximum — add safe padding."
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
        dominant.append(
            {
                "linear": [round(float(c), 4) for c in mean],
                "hex": "#"
                + "".join(
                    f"{max(0, min(255, round(_linear_to_srgb(float(c)) * 255))):02x}" for c in mean
                ),
                "share": round(float(counts[index]) / len(keys), 4),
                "_bucket": [round(b, 3) for b in bucket],
            }
        )

    findings = list(validation_findings)
    if blown > 0.08:
        findings.append(
            f"{blown:.0%} of the subject is blown to white — the LIGHTING is too hot, "
            "not the material. Lower the light rig or check the view transform before "
            "touching the albedo."
        )
    if crushed > 0.12:
        findings.append(f"{crushed:.0%} of the subject is crushed to black — add fill light.")
    if peak - floor < 0.12:
        findings.append(f"contrast is flat (luma {floor:.2f}..{peak:.2f}); the form will not read.")
    if saturation < 0.06:
        findings.append(
            f"near-monochrome (mean saturation {saturation:.2f}) — if colour was expected, "
            "the material is probably not reaching the shader."
        )
    return {
        "path": str(target),
        "size": [width, height],
        "subject_coverage": round(coverage, 4),
        "alpha": {
            "has_transparency": has_transparency,
            "transparent_fraction": round(transparent_fraction, 4),
            "partial_fraction": round(partial_fraction, 4),
            "corners_clear": corners_clear,
        },
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
            "hex": "#"
            + "".join(
                f"{max(0, min(255, round(_linear_to_srgb(float(c)) * 255))):02x}"
                for c in subject_rgb.mean(axis=0)
            ),
        },
        "dominant_colors": dominant,
        "findings": findings,
        "ok": not findings,
    }


@op(
    "check.sprite",
    summary=(
        "Audit every cell of a sprite atlas instead of approving only the sheet as a "
        "whole: alpha, coverage, cell-edge clipping, baseline drift, scale consistency "
        "and chroma-key residue. These are the defects that make a detailed run cycle "
        "glide, hop or bleed into the next frame in game."
    ),
    params={
        "path": ("path", None, "RGBA sprite sheet to analyse"),
        "columns": ("int", 1, "Number of equal atlas columns"),
        "rows": ("int", 1, "Number of equal atlas rows"),
        "require_alpha": ("bool", True, "Fail when the atlas has no transparency"),
        "minimum_coverage": ("num", 0.08, "Minimum visible coverage in every cell"),
        "maximum_coverage": ("num", 0.8, "Maximum visible coverage in every cell"),
        "maximum_baseline_drift": (
            "num",
            0.04,
            "Maximum normalized difference between cell subject baselines",
        ),
        "maximum_height_variation": (
            "num",
            0.12,
            "Maximum subject-height span divided by mean subject height",
        ),
        "edge_padding": (
            "num",
            0.01,
            "Required transparent padding at each cell edge, normalized to its short side",
        ),
        "forbidden_color": (
            "color",
            [1.0, 0.0, 1.0, 1.0],
            "Chroma-key colour that must not remain in visible pixels",
        ),
        "color_tolerance": (
            "num",
            0.16,
            "Maximum RGB distance counted as forbidden-colour residue",
        ),
        "max_forbidden_share": (
            "num",
            0.002,
            "Maximum visible-pixel share allowed near the forbidden colour",
        ),
    },
    tags=["check", "inspect", "sprite"],
    mutates=False,
)
def check_sprite(
    ctx,
    path,
    columns,
    rows,
    require_alpha,
    minimum_coverage,
    maximum_coverage,
    maximum_baseline_drift,
    maximum_height_variation,
    edge_padding,
    forbidden_color,
    color_tolerance,
    max_forbidden_share,
):
    columns = int(columns)
    rows = int(rows)
    if columns < 1 or rows < 1:
        raise OpError("columns and rows must both be at least one")
    if not 0 <= minimum_coverage <= maximum_coverage <= 1:
        raise OpError("coverage bounds must satisfy 0 <= minimum_coverage <= maximum_coverage <= 1")
    for label, value in (
        ("maximum_baseline_drift", maximum_baseline_drift),
        ("maximum_height_variation", maximum_height_variation),
        ("edge_padding", edge_padding),
        ("color_tolerance", color_tolerance),
        ("max_forbidden_share", max_forbidden_share),
    ):
        if float(value) < 0:
            raise OpError(f"{label} must be zero or greater")
    if max_forbidden_share > 1:
        raise OpError("max_forbidden_share cannot exceed one")

    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - Blender bundles numpy
        raise OpError("numpy unavailable in this Blender build") from exc

    target = ctx.resolve(path)
    if not target.is_file():
        target = ctx.out_path(path, ".png")
    if not target.is_file():
        raise OpError(f"no sprite sheet at {target}")

    image = bpy.data.images.load(str(target))
    try:
        width, height = image.size
        data = numpy.array(image.pixels[:], dtype=numpy.float32).reshape((height, width, 4))
    finally:
        bpy.data.images.remove(image)

    findings = []

    def record(severity, issue, detail):
        findings.append({"severity": severity, "issue": issue, "detail": detail})

    if width < columns or height < rows:
        raise OpError(f"{width}x{height} image cannot contain a {columns}x{rows} sprite grid")
    if width % columns or height % rows:
        record(
            "warn",
            "fractional atlas cells",
            f"{width}x{height} is not evenly divisible by {columns}x{rows}; linear sampling "
            "can pull pixels from the neighbouring frame",
        )

    alpha = data[:, :, 3]
    has_transparency = bool(numpy.any(alpha <= 0.01))
    if require_alpha and not has_transparency:
        record(
            "error",
            "missing alpha",
            "the sprite sheet is fully opaque; ship an RGBA cutout before runtime atlasing",
        )

    forbidden = numpy.array(forbidden_color[:3], dtype=numpy.float32)
    cells = []
    baselines = []
    heights = []
    for row in range(rows):
        y0 = round(height * row / rows)
        y1 = round(height * (row + 1) / rows)
        for column in range(columns):
            x0 = round(width * column / columns)
            x1 = round(width * (column + 1) / columns)
            cell = data[y0:y1, x0:x1]
            cell_alpha = cell[:, :, 3]
            if has_transparency:
                subject = cell_alpha > 0.01
            else:
                cell_rgb = cell[:, :, :3]
                corners = numpy.array(
                    [cell_rgb[0, 0], cell_rgb[0, -1], cell_rgb[-1, 0], cell_rgb[-1, -1]]
                )
                backdrop = numpy.median(corners, axis=0)
                subject = numpy.linalg.norm(cell_rgb - backdrop, axis=2) > 0.06

            index = row * columns + column
            coverage = float(subject.mean())
            if not numpy.any(subject):
                record("error", "empty sprite cell", f"cell {index} has no visible subject")
                cells.append(
                    {
                        "index": index,
                        "row": row,
                        "column": column,
                        "coverage": 0.0,
                        "bounds": None,
                        "baseline": None,
                        "height": 0.0,
                        "edge_contacts": ["all"],
                        "forbidden_color_share": 0.0,
                    }
                )
                continue

            ys, xs = numpy.nonzero(subject)
            cell_height, cell_width = subject.shape
            left = int(xs.min())
            right = int(xs.max()) + 1
            bottom = int(ys.min())
            top = int(ys.max()) + 1
            baseline = top / cell_height
            subject_height = (top - bottom) / cell_height
            baselines.append(baseline)
            heights.append(subject_height)

            padding = max(1, round(min(cell_width, cell_height) * edge_padding))
            edge_contacts = []
            if left < padding:
                edge_contacts.append("left")
            if right > cell_width - padding:
                edge_contacts.append("right")
            if bottom < padding:
                edge_contacts.append("bottom")
            if top > cell_height - padding:
                edge_contacts.append("top")
            if edge_contacts:
                record(
                    "warn",
                    "cell-edge contact",
                    f"cell {index} touches {', '.join(edge_contacts)}; add transparent padding "
                    "or inset runtime UVs to prevent frame bleed",
                )

            subject_rgb = cell[:, :, :3][subject]
            near_forbidden = numpy.linalg.norm(subject_rgb - forbidden, axis=1) <= color_tolerance
            forbidden_share = float(near_forbidden.mean())
            if forbidden_share > max_forbidden_share:
                record(
                    "error",
                    "chroma-key residue",
                    f"cell {index} has {forbidden_share:.2%} forbidden-colour pixels, above "
                    f"the {max_forbidden_share:.2%} allowance",
                )
            if coverage < minimum_coverage or coverage > maximum_coverage:
                record(
                    "error",
                    "cell coverage outside bounds",
                    f"cell {index} covers {coverage:.1%}; required range is "
                    f"{minimum_coverage:.1%}..{maximum_coverage:.1%}",
                )

            cells.append(
                {
                    "index": index,
                    "row": row,
                    "column": column,
                    "coverage": round(coverage, 4),
                    "bounds": [
                        round(left / cell_width, 4),
                        round(bottom / cell_height, 4),
                        round(right / cell_width, 4),
                        round(top / cell_height, 4),
                    ],
                    "baseline": round(baseline, 4),
                    "height": round(subject_height, 4),
                    "edge_contacts": edge_contacts,
                    "forbidden_color_share": round(forbidden_share, 6),
                }
            )

    baseline_drift = max(baselines) - min(baselines) if baselines else 0.0
    mean_height = float(numpy.mean(heights)) if heights else 0.0
    height_variation = (max(heights) - min(heights)) / mean_height if mean_height > 1e-6 else 0.0
    if baseline_drift > maximum_baseline_drift:
        record(
            "warn",
            "baseline drift",
            f"frame baselines span {baseline_drift:.3f}, above the "
            f"{maximum_baseline_drift:.3f} limit; feet will slide or hop without anchors",
        )
    if height_variation > maximum_height_variation:
        record(
            "warn",
            "subject scale variation",
            f"frame subject heights vary by {height_variation:.1%}, above the "
            f"{maximum_height_variation:.1%} limit",
        )

    errors = sum(1 for finding in findings if finding["severity"] == "error")
    warnings = sum(1 for finding in findings if finding["severity"] == "warn")
    return {
        "path": str(target),
        "size": [width, height],
        "grid": {"columns": columns, "rows": rows, "cells": columns * rows},
        "has_transparency": has_transparency,
        "cells": cells,
        "baseline_drift": round(baseline_drift, 4),
        "height_variation": round(height_variation, 4),
        "findings": findings,
        "errors": errors,
        "warnings": warnings,
        "ok": errors == 0 and warnings == 0,
    }


def _srgb_to_linear_array(numpy, values):
    return numpy.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


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
