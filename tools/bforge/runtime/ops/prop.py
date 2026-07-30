"""Finished prop recipes.

Each of these encodes proportions and construction tricks that a generic
"add a cube, scale it" agent does not know: that a crate reads as a crate
because of its *frame*, that a barrel needs a belly and two bands, that a rock
needs a flat bottom or it floats. Every recipe is seeded and deterministic, and
every one comes out chamfered, UV'd, materialled and pivoted for a game engine.

Triangle budgets in the summaries are the mid-range targets these ship at.
"""

from __future__ import annotations

import math

import bmesh
from lib import finish as finish_lib
from lib import mat as mat_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from mathutils import Matrix, Vector
from registry import OpError, op

BASE = {
    "name": ("str", "", "Object name (defaults to the recipe name)"),
    "location": ("vec3", [0.0, 0.0, 0.0], "World position in metres"),
    "seed": ("int", 0, "Random seed — same seed always gives the same asset"),
}


def _params(**extra):
    merged = dict(BASE)
    merged.update(extra)
    return merged


def _named(name, fallback):
    return scene_lib.unique_name(name or fallback)


def _recess_faces(bm, faces, inset, depth):
    """Inset each face and push it inward — the 'framed panel' look."""
    made = []
    for face in list(faces):
        if not face.is_valid or face.calc_area() < inset * inset * 4.0:
            continue
        inner = bmesh.ops.inset_region(
            bm, faces=[face], thickness=inset, depth=0.0, use_even_offset=True
        )["faces"]
        for panel in inner:
            if panel.is_valid:
                bmesh.ops.translate(
                    bm, vec=panel.normal * -depth, verts=list(panel.verts)
                )
                made.append(panel)
    return made


# ---------------------------------------------------------------------------
# containers
# ---------------------------------------------------------------------------


@op(
    "prop.crate",
    summary="Wooden crate with a recessed-panel frame. ~350 tris. The frame is what makes it read as a crate rather than a box.",
    params=_params(
        size=("vec3", [0.8, 0.8, 0.8], "Outer dimensions in metres"),
        frame_width=("num", 0.07, "Width of the corner/edge framing"),
        panel_depth=("num", 0.03, "How far the panels recess"),
        planks=("int", 2, "Horizontal plank divisions per panel (0 for plain)"),
        bevel=("num", 0.012, "Edge chamfer width"),
        material=("str", "wood", "Material preset"),
        color=("str", "", "Override colour"),
        uv_scale=("num", 1.0, "Metres per UV tile"),
    ),
    tags=["prop"],
)
def prop_crate(ctx, name, location, seed, size, frame_width, panel_depth, planks, bevel, material,
               color, uv_scale):
    ctx.reseed(seed)
    bm = mesh_lib.new_bmesh()
    faces = mesh_lib.add_box(bm, size=size, bevel=bevel, segments=2)
    flat = [f for f in faces if f.is_valid and f.calc_area() > (frame_width * 3) ** 2]
    panels = _recess_faces(bm, flat, frame_width, panel_depth)
    if planks > 0 and panels:
        edges = list({e for f in panels if f.is_valid for e in f.edges})
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=planks, use_grid_fill=False)
    obj = mesh_lib.to_object(bm, _named(name, "crate"))
    obj.location = location
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="box", uv_scale=uv_scale,
        origin="bottom", smooth=False,
    )
    finish_lib.budget_note(ctx, obj, 600)
    return result


@op(
    "prop.barrel",
    summary="Lathed barrel with a belly and iron bands. ~500 tris. Bands get their own material slot so they can read as metal.",
    params=_params(
        height=("num", 1.0, "Height in metres"),
        radius=("num", 0.32, "Radius at the widest point"),
        belly=("num", 0.18, "How much the middle bulges (0 = straight cylinder)"),
        segments=("int", 14, "Radial segments"),
        bands=("int", 2, "Number of iron hoops"),
        band_material=("str", "iron", "Hoop material preset"),
        material=("str", "wood", "Barrel material preset"),
        color=("str", "", "Override colour"),
        open_top=("bool", False, "Hollow out the top (for water butts, planters)"),
    ),
    tags=["prop"],
)
def prop_barrel(ctx, name, location, seed, height, radius, belly, segments, bands, band_material,
                material, color, open_top):
    ctx.reseed(seed)
    waist = radius * (1.0 - belly)
    profile = [
        (0.0, 0.0), (waist, 0.0), (waist * 1.02, height * 0.06),
        (radius, height * 0.32), (radius, height * 0.68),
        (waist * 1.02, height * 0.94), (waist, height),
    ]
    if open_top:
        profile.append((waist * 0.88, height * 0.97))
    else:
        profile.append((0.0, height))

    bm = mesh_lib.new_bmesh()
    mesh_lib.lathe(bm, profile, segments=segments)
    body = mesh_lib.to_object(bm, _named(name, "barrel"))
    body.location = location
    finish_lib.finish(
        ctx, body, material=material, color=color or None, uv="cylinder",
        origin="bottom", smooth=True, smooth_angle=45.0,
    )

    parts = [body]
    for index in range(max(0, bands)):
        fraction = (index + 1) / (bands + 1)
        z = height * fraction
        band_radius = _profile_radius(profile, z) + 0.012
        band_bm = mesh_lib.new_bmesh()
        # Capped, not an open tube: an open tube shows the barrel's smooth-shaded
        # surface through its own rim and reads as a serrated edge.
        mesh_lib.add_cylinder(
            band_bm, radius=band_radius, depth=height * 0.075, segments=segments,
            center=(0.0, 0.0, z), cap=True,
        )
        band = mesh_lib.to_object(band_bm, f"{body.name}_band{index}")
        band.location = location
        mat_lib.assign(band, mat_lib.from_preset(band_material))
        mesh_lib.shade_auto_smooth(band, 45.0)
        from lib import uvs as uv_lib

        uv_lib.cylinder_project(band)
        parts.append(band)

    merged = scene_lib.join(parts, body.name) if len(parts) > 1 else body
    scene_lib.set_origin(merged, "bottom")
    scene_lib.apply_transforms(merged)
    result = finish_lib.report(ctx, merged)
    finish_lib.budget_note(ctx, merged, 900)
    return result


def _profile_radius(profile, height):
    """Interpolate a lathe profile's radius at a given height."""
    best = profile[0][0]
    for (r0, h0), (r1, h1) in zip(profile, profile[1:]):
        if h0 <= height <= h1 and abs(h1 - h0) > 1e-9:
            t = (height - h0) / (h1 - h0)
            return r0 + (r1 - r0) * t
        best = max(best, r0, r1)
    return best


@op(
    "prop.chest",
    summary="Treasure chest with a curved lid, iron banding and a lock plate. ~700 tris. Lid is a separate object so it can be hinged and animated.",
    params=_params(
        size=("vec3", [0.9, 0.55, 0.45], "Base dimensions (lid adds height on top)"),
        lid_height=("num", 0.22, "Height of the curved lid"),
        lid_segments=("int", 8, "Lid curvature resolution"),
        separate_lid=("bool", True, "Keep the lid as its own object for hinge animation"),
        material=("str", "wood", "Body material preset"),
        trim_material=("str", "iron", "Banding and lock material preset"),
        color=("str", "", "Override body colour"),
    ),
    tags=["prop"],
)
def prop_chest(ctx, name, location, seed, size, lid_height, lid_segments, separate_lid, material,
               trim_material, color):
    ctx.reseed(seed)
    base_name = _named(name, "chest")
    sx, sy, sz = size

    bm = mesh_lib.new_bmesh()
    faces = mesh_lib.add_box(bm, size=(sx, sy, sz), bevel=0.012, segments=2)
    sides = [f for f in faces if f.is_valid and abs(f.normal.z) < 0.7]
    _recess_faces(bm, sides, 0.055, 0.02)
    body = mesh_lib.to_object(bm, base_name)
    body.location = location
    finish_lib.finish(ctx, body, material=material, color=color or None, uv="box",
                      origin="bottom", smooth=False)

    # Half-cylinder lid, laid on its side along X.
    lid_bm = mesh_lib.new_bmesh()
    ring_count = max(3, lid_segments)
    sections = []
    for i in range(ring_count + 1):
        angle = math.pi * i / ring_count
        sections.append(
            (
                math.cos(angle) * sy * 0.5,
                max(0.0, math.sin(angle)) * lid_height,
            )
        )
    verts_a, verts_b = [], []
    for y, z in sections:
        verts_a.append(lid_bm.verts.new((-sx * 0.5, y, z)))
        verts_b.append(lid_bm.verts.new((sx * 0.5, y, z)))
    for i in range(len(sections) - 1):
        lid_bm.faces.new((verts_a[i], verts_a[i + 1], verts_b[i + 1], verts_b[i]))
    lid_bm.faces.new(list(reversed(verts_a)))
    lid_bm.faces.new(verts_b)
    mesh_lib.cleanup(lid_bm)
    lid = mesh_lib.to_object(lid_bm, f"{base_name}_lid")
    lid.location = (location[0], location[1], location[2] + sz)
    finish_lib.finish(ctx, lid, material=material, color=color or None, uv="box",
                      origin="center_xy", smooth=True, smooth_angle=50.0)

    # Iron banding + lock plate.
    trim = []
    for offset in (-sx * 0.3, sx * 0.3):
        band_bm = mesh_lib.new_bmesh()
        mesh_lib.add_box(band_bm, size=(0.05, sy * 1.02, sz * 1.02), bevel=0.004)
        band = mesh_lib.to_object(band_bm, f"{base_name}_band")
        band.location = (location[0] + offset, location[1], location[2] + sz * 0.5)
        trim.append(band)
    lock_bm = mesh_lib.new_bmesh()
    mesh_lib.add_box(lock_bm, size=(0.13, 0.03, 0.16), bevel=0.008)
    lock = mesh_lib.to_object(lock_bm, f"{base_name}_lock")
    lock.location = (location[0], location[1] - sy * 0.5, location[2] + sz * 0.88)
    trim.append(lock)
    trim_mat = mat_lib.from_preset(trim_material)
    from lib import uvs as uv_lib

    for part in trim:
        mat_lib.assign(part, trim_mat)
        uv_lib.box_project(part)

    body_final = scene_lib.join([body] + trim, base_name)
    scene_lib.set_origin(body_final, "bottom")
    scene_lib.apply_transforms(body_final)

    if not separate_lid:
        body_final = scene_lib.join([body_final, lid], base_name)
        scene_lib.set_origin(body_final, "bottom")
        scene_lib.apply_transforms(body_final)
        result = finish_lib.report(ctx, body_final)
    else:
        scene_lib.parent_to(lid, body_final)
        ctx.note(
            f"Lid '{lid.name}' is parented to '{body_final.name}' with its pivot at the back "
            "edge — rotate it about local X to open."
        )
        result = finish_lib.report(ctx, body_final)
        result["lid"] = finish_lib.report(ctx, lid)
    finish_lib.budget_note(ctx, body_final, 1000)
    return result


@op(
    "prop.sack",
    summary="Cloth sack, cinched at the neck. ~400 tris. Good filler for markets, camps and storerooms.",
    params=_params(
        height=("num", 0.7, "Height in metres"),
        radius=("num", 0.26, "Body radius"),
        segments=("int", 12, "Radial segments"),
        slump=("num", 0.25, "How much the body sags and spreads at the base"),
        material=("str", "cloth", "Material preset"),
        color=("str", "sand", "Colour"),
    ),
    tags=["prop"],
)
def prop_sack(ctx, name, location, seed, height, radius, segments, slump, material, color):
    rng = ctx.reseed(seed)
    profile = [
        (0.0, 0.0), (radius * (1.0 + slump), 0.02), (radius * (1.0 + slump * 0.7), height * 0.22),
        (radius, height * 0.5), (radius * 0.82, height * 0.72),
        (radius * 0.3, height * 0.88), (radius * 0.36, height * 0.95),
        (radius * 0.22, height), (0.0, height),
    ]
    bm = mesh_lib.new_bmesh()
    mesh_lib.lathe(bm, profile, segments=segments)
    mesh_lib.jitter_verts(bm, bm.verts[:], rng, amount=radius * 0.045)
    obj = mesh_lib.to_object(bm, _named(name, "sack"))
    obj.location = location
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="cylinder",
        origin="bottom", smooth=True, smooth_angle=60.0,
    )
    finish_lib.budget_note(ctx, obj, 700)
    return result


# ---------------------------------------------------------------------------
# natural
# ---------------------------------------------------------------------------


@op(
    "prop.rock",
    summary="Irregular rock with a flat base so it sits on the ground instead of floating. ~200 tris at detail 2. The single most reused environment prop in any game.",
    params=_params(
        size=("vec3", [1.0, 0.85, 0.7], "Bounding dimensions in metres"),
        detail=("int", 2, "Icosphere subdivisions: 1=80 tris, 2=320, 3=1280"),
        roughness=("num", 0.28, "Surface irregularity (0 = smooth boulder, 0.5 = jagged)"),
        flatten_base=("bool", True, "Cut a flat bottom so it beds into terrain"),
        angular=("bool", False, "Faceted/low-poly look instead of smooth"),
        material=("str", "rock", "Material preset"),
        color=("str", "", "Override colour"),
    ),
    tags=["prop", "nature"],
)
def prop_rock(ctx, name, location, seed, size, detail, roughness, flatten_base, angular, material,
              color):
    rng = ctx.reseed(seed)
    bm = mesh_lib.new_bmesh()
    mesh_lib.add_icosphere(bm, radius=0.5, subdivisions=max(1, min(4, detail)))
    bmesh.ops.transform(bm, matrix=Matrix.Diagonal(Vector(size)).to_4x4(), verts=bm.verts[:])

    # Layered displacement: broad lumps first, then fine chipping. One octave
    # alone reads as a potato; two reads as stone.
    for vert in bm.verts:
        direction = vert.co.normalized() if vert.co.length > 1e-6 else Vector((0, 0, 1))
        broad = math.sin(vert.co.x * 2.1 + seed) * math.cos(vert.co.y * 1.7 - seed)
        fine = rng.uniform(-1.0, 1.0)
        vert.co += direction * (broad * roughness * 0.35 + fine * roughness * 0.22) * min(size)

    if flatten_base:
        zs = [v.co.z for v in bm.verts]
        cut = min(zs) + (max(zs) - min(zs)) * 0.16
        for vert in bm.verts:
            if vert.co.z < cut:
                vert.co.z = cut

    mesh_lib.cleanup(bm, merge_dist=min(size) * 0.01)
    obj = mesh_lib.to_object(bm, _named(name, "rock"))
    obj.location = location
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="smart_packed",
        origin="bottom", smooth=not angular, smooth_angle=40.0,
    )
    finish_lib.budget_note(ctx, obj, 800)
    return result


@op(
    "prop.crystal",
    summary="Crystal cluster: several tapered prisms fanned from a common base. ~300 tris. Emissive by default — reads as a light source and a landmark.",
    params=_params(
        count=("int", 5, "Number of shards"),
        height=("num", 1.0, "Tallest shard height in metres"),
        radius=("num", 0.16, "Shard base radius"),
        sides=("int", 6, "Shard cross-section sides"),
        spread=("num", 28.0, "Maximum lean from vertical, in degrees"),
        material=("str", "crystal", "Material preset"),
        color=("str", "", "Override colour"),
        emission=("num", 1.2, "Glow strength"),
    ),
    tags=["prop", "nature"],
)
def prop_crystal(ctx, name, location, seed, count, height, radius, sides, spread, material, color,
                 emission):
    rng = ctx.reseed(seed)
    bm = mesh_lib.new_bmesh()
    for index in range(max(1, count)):
        scale = 1.0 if index == 0 else rng.uniform(0.35, 0.85)
        shard_h = height * scale
        shard_r = radius * (0.6 + 0.4 * scale)
        lean = 0.0 if index == 0 else math.radians(rng.uniform(spread * 0.3, spread))
        yaw = rng.uniform(0.0, math.tau)
        offset = 0.0 if index == 0 else rng.uniform(radius * 0.6, radius * 2.0)

        shard = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(
            shard, radius=shard_r, radius_top=shard_r * 0.12, depth=shard_h,
            segments=sides, center=(0.0, 0.0, shard_h * 0.5),
        )
        # Point the tip.
        top = max(v.co.z for v in shard.verts)
        tip = [v for v in shard.verts if abs(v.co.z - top) < 1e-4]
        for vert in tip:
            vert.co.x *= 0.25
            vert.co.y *= 0.25
            vert.co.z += shard_h * 0.18

        matrix = (
            Matrix.Translation((math.cos(yaw) * offset, math.sin(yaw) * offset, 0.0))
            @ Matrix.Rotation(yaw, 4, "Z")
            @ Matrix.Rotation(lean, 4, "Y")
        )
        bmesh.ops.transform(shard, matrix=matrix, verts=shard.verts[:])
        temp_mesh = mesh_lib.bpy.data.meshes.new("_shard")
        shard.to_mesh(temp_mesh)
        shard.free()
        bm.from_mesh(temp_mesh)
        mesh_lib.bpy.data.meshes.remove(temp_mesh)

    mesh_lib.cleanup(bm)
    obj = mesh_lib.to_object(bm, _named(name, "crystal"))
    obj.location = location
    crystal_mat = mat_lib.principled(
        f"m_crystal_{obj.name}",
        color=color or mat_lib.PRESETS["crystal"]["color"],
        roughness=0.08, metallic=0.0, emission=emission, alpha=1.0,
    )
    result = finish_lib.finish(
        ctx, obj, material=crystal_mat, uv="smart_packed", origin="bottom",
        smooth=True, smooth_angle=25.0,
    )
    finish_lib.budget_note(ctx, obj, 600)
    return result


def _tree_branch(bm, start: Vector, end: Vector, radius: float, segments: int = 8) -> None:
    """Append one tapered branch aligned between two local-space points."""
    axis = end - start
    if axis.length < 1e-5:
        return
    faces = mesh_lib.add_cylinder(
        bm,
        radius=max(radius, 0.008),
        radius_top=max(radius * 0.42, 0.004),
        depth=axis.length,
        segments=segments,
    )
    verts = list({vert for face in faces for vert in face.verts})
    orient = axis.normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()
    matrix = Matrix.Translation((start + end) * 0.5) @ orient
    bmesh.ops.transform(bm, matrix=matrix, verts=verts)


def _tree_ellipsoid(
    bm,
    centre: Vector,
    radius: float,
    scale: tuple[float, float, float],
    yaw: float,
) -> None:
    """Append a small rotated foliage mass without making a new object."""
    faces = mesh_lib.add_icosphere(bm, radius=1.0, subdivisions=1)
    verts = list({vert for face in faces for vert in face.verts})
    size = Matrix.Diagonal(Vector((
        radius * scale[0],
        radius * scale[1],
        radius * scale[2],
        1.0,
    )))
    matrix = Matrix.Translation(centre) @ Matrix.Rotation(yaw, 4, "Z") @ size
    bmesh.ops.transform(bm, matrix=matrix, verts=verts)


@op(
    "prop.tree",
    summary="Game-ready tree with stylised and natural Mediterranean forms. Olive and cypress styles add branch-readable medium-detail foliage while preserving the cheap legacy silhouettes.",
    params=_params(
        height=("num", 4.0, "Total height in metres"),
        trunk_radius=("num", 0.18, "Trunk radius at the base"),
        canopy_style=("enum:cone|blob|layered|palm|olive|cypress", "layered", "Canopy shape or natural species"),
        canopy_layers=("int", 3, "layered style: number of tiers"),
        canopy_radius=("num", 1.4, "Canopy spread in metres"),
        detail=("int", 2, "Natural olive/cypress foliage density, 1-3; ignored by legacy styles"),
        lean=("num", 4.0, "Trunk lean in degrees — a perfectly vertical tree looks fake"),
        trunk_material=("str", "wood", "Trunk material preset"),
        leaf_material=("str", "leaf", "Canopy material preset"),
        leaf_color=("str", "", "Override canopy colour"),
    ),
    tags=["prop", "nature"],
)
def prop_tree(ctx, name, location, seed, height, trunk_radius, canopy_style, canopy_layers,
              canopy_radius, detail, lean, trunk_material, leaf_material, leaf_color):
    rng = ctx.reseed(seed)
    base_name = _named(name, "tree")
    natural = canopy_style in {"olive", "cypress"}
    natural_detail = max(1, min(3, detail))
    trunk_h = height * (
        0.82 if canopy_style == "palm"
        else 0.52 if canopy_style == "olive"
        else 0.96 if canopy_style == "cypress"
        else 0.45
    )

    profile = [
        (0.0, 0.0), (trunk_radius * 1.5, 0.0), (trunk_radius, trunk_h * 0.12),
        (trunk_radius * 0.78, trunk_h * 0.5), (trunk_radius * 0.55, trunk_h),
        (0.0, trunk_h),
    ]
    bm = mesh_lib.new_bmesh()
    mesh_lib.lathe(bm, profile, segments=12 if natural else 8)
    lean_rad = math.radians(lean)
    for vert in bm.verts:
        t = vert.co.z / max(trunk_h, 1e-6)
        vert.co.x += math.sin(lean_rad) * t * t * trunk_h * 0.5
    trunk = mesh_lib.to_object(bm, base_name)
    trunk.location = location
    finish_lib.finish(ctx, trunk, material=trunk_material, uv="cylinder", origin="bottom",
                      smooth=True, smooth_angle=50.0)

    tip_x = math.sin(lean_rad) * trunk_h * 0.5
    canopy_bm = mesh_lib.new_bmesh()
    branch = None
    if canopy_style == "olive":
        branch_bm = mesh_lib.new_bmesh()
        limb_tips: list[Vector] = []
        limb_count = 6 + natural_detail * 2
        crown_span = max(height - trunk_h, height * 0.3)
        for index in range(limb_count):
            angle = math.tau * index / limb_count + rng.uniform(-0.18, 0.18)
            start = Vector((
                tip_x * 0.45,
                0.0,
                trunk_h * rng.uniform(0.52, 0.82),
            ))
            spread = canopy_radius * rng.uniform(0.56, 0.9)
            end = Vector((
                tip_x + math.cos(angle) * spread,
                math.sin(angle) * spread,
                trunk_h + crown_span * rng.uniform(0.3, 0.82),
            ))
            _tree_branch(
                branch_bm,
                start,
                end,
                trunk_radius * rng.uniform(0.38, 0.58),
                segments=8,
            )
            limb_tips.append(end)

            # A fork makes the crown read as grown wood rather than rods
            # holding foliage balls. Keep it short so the silhouette stays open.
            fork_start = start.lerp(end, 0.62)
            tangent = Vector((-math.sin(angle), math.cos(angle), rng.uniform(0.12, 0.3)))
            fork_end = end + tangent * canopy_radius * rng.uniform(0.18, 0.32)
            _tree_branch(
                branch_bm,
                fork_start,
                fork_end,
                trunk_radius * rng.uniform(0.18, 0.3),
                segments=7,
            )
            limb_tips.append(fork_end)

        mesh_lib.cleanup(branch_bm)
        branch = mesh_lib.to_object(branch_bm, f"{base_name}_branches")
        branch.location = location
        finish_lib.finish(
            ctx,
            branch,
            material=trunk_material,
            uv="smart_packed",
            origin=None,
            smooth=True,
            smooth_angle=48.0,
        )

        # Many small, flattened masses keep negative space between branches.
        # At gameplay distance they merge into an olive crown; in FPS they still
        # read as twigs and leaves rather than six inflated rocks.
        leaf_count = 30 + natural_detail * 22
        for index in range(leaf_count):
            tip = limb_tips[index % len(limb_tips)]
            centre = tip + Vector((
                rng.uniform(-1.0, 1.0) * canopy_radius * 0.32,
                rng.uniform(-1.0, 1.0) * canopy_radius * 0.32,
                rng.uniform(-0.35, 0.42) * canopy_radius,
            ))
            _tree_ellipsoid(
                canopy_bm,
                centre,
                canopy_radius * rng.uniform(0.085, 0.14),
                (
                    rng.uniform(1.5, 2.25),
                    rng.uniform(0.72, 1.08),
                    rng.uniform(0.38, 0.62),
                ),
                rng.uniform(0.0, math.tau),
            )
    elif canopy_style == "cypress":
        branch_bm = mesh_lib.new_bmesh()
        branch_count = 10 + natural_detail * 5
        for index in range(branch_count):
            t = index / max(1, branch_count - 1)
            angle = index * 2.399963 + rng.uniform(-0.2, 0.2)
            z = height * (0.14 + t * 0.76)
            reach = canopy_radius * (1.0 - t * 0.62) * rng.uniform(0.5, 0.82)
            start = Vector((tip_x * t * 0.7, 0.0, z))
            end = Vector((
                tip_x * t + math.cos(angle) * reach,
                math.sin(angle) * reach,
                z + height * rng.uniform(0.015, 0.055),
            ))
            _tree_branch(
                branch_bm,
                start,
                end,
                trunk_radius * (0.34 - t * 0.17),
                segments=7,
            )

        mesh_lib.cleanup(branch_bm)
        branch = mesh_lib.to_object(branch_bm, f"{base_name}_branches")
        branch.location = location
        finish_lib.finish(
            ctx,
            branch,
            material=trunk_material,
            uv="smart_packed",
            origin=None,
            smooth=True,
            smooth_angle=48.0,
        )

        tuft_count = 60 + natural_detail * 32
        for _ in range(tuft_count):
            t = rng.uniform(0.06, 0.98)
            z = height * (0.1 + t * 0.88)
            radius_here = canopy_radius * (1.0 - t * 0.58)
            angle = rng.uniform(0.0, math.tau)
            radial = radius_here * math.sqrt(rng.random()) * 0.72
            centre = Vector((
                tip_x * t + math.cos(angle) * radial,
                math.sin(angle) * radial,
                z,
            ))
            _tree_ellipsoid(
                canopy_bm,
                centre,
                canopy_radius * rng.uniform(0.1, 0.16),
                (
                    rng.uniform(0.82, 1.18),
                    rng.uniform(0.82, 1.18),
                    rng.uniform(1.5, 2.45),
                ),
                rng.uniform(0.0, math.tau),
            )
    elif canopy_style == "cone":
        mesh_lib.add_cylinder(
            canopy_bm, radius=canopy_radius, radius_top=0.0, depth=height - trunk_h,
            segments=8, center=(tip_x, 0.0, trunk_h + (height - trunk_h) * 0.5),
        )
    elif canopy_style == "blob":
        mesh_lib.add_icosphere(
            canopy_bm, radius=canopy_radius, subdivisions=2,
            center=(tip_x, 0.0, trunk_h + canopy_radius * 0.7),
        )
        for vert in canopy_bm.verts:
            vert.co += Vector(
                (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
            ) * canopy_radius * 0.14
    elif canopy_style == "palm":
        for i in range(7):
            angle = math.tau * i / 7
            frond = mesh_lib.new_bmesh()
            mesh_lib.add_plane(frond, size=(canopy_radius * 1.6, 0.34), cuts=2)
            matrix = (
                Matrix.Translation(
                    (
                        tip_x + math.cos(angle) * canopy_radius * 0.55,
                        math.sin(angle) * canopy_radius * 0.55,
                        trunk_h + 0.1,
                    )
                )
                @ Matrix.Rotation(angle, 4, "Z")
                @ Matrix.Rotation(math.radians(-28), 4, "Y")
            )
            bmesh.ops.transform(frond, matrix=matrix, verts=frond.verts[:])
            temp = mesh_lib.bpy.data.meshes.new("_frond")
            frond.to_mesh(temp)
            frond.free()
            canopy_bm.from_mesh(temp)
            mesh_lib.bpy.data.meshes.remove(temp)
    else:  # layered
        span = height - trunk_h
        for layer in range(max(1, canopy_layers)):
            t = layer / max(1, canopy_layers)
            radius = canopy_radius * (1.0 - t * 0.55)
            z = trunk_h + span * (0.12 + t * 0.72)
            mesh_lib.add_cylinder(
                canopy_bm, radius=radius, radius_top=radius * 0.25,
                depth=span * 0.42, segments=8,
                center=(tip_x + rng.uniform(-0.08, 0.08), rng.uniform(-0.08, 0.08), z),
            )

    mesh_lib.cleanup(canopy_bm)
    canopy = mesh_lib.to_object(canopy_bm, f"{base_name}_canopy")
    canopy.location = location
    leaf_mat = mat_lib.from_preset(leaf_material, color=leaf_color or None)
    from lib import uvs as uv_lib

    mat_lib.assign(canopy, leaf_mat)
    uv_lib.smart_project(canopy, margin=0.02)
    mesh_lib.shade_auto_smooth(canopy, 60.0)

    merged = scene_lib.join([trunk, *([branch] if branch else []), canopy], base_name)
    scene_lib.set_origin(merged, "bottom")
    scene_lib.apply_transforms(merged)
    result = finish_lib.report(ctx, merged)
    finish_lib.budget_note(ctx, merged, 4200 if natural else 1200)
    return result


# ---------------------------------------------------------------------------
# architecture & set dressing
# ---------------------------------------------------------------------------


@op(
    "prop.pillar",
    summary="Classical column: base, tapered shaft, capital, optional fluting. ~600 tris. Instant architecture.",
    params=_params(
        height=("num", 3.0, "Total height in metres"),
        radius=("num", 0.28, "Shaft radius"),
        style=("enum:doric|tuscan|square|broken", "doric", "Column style"),
        flutes=("int", 0, "Vertical grooves (0 = smooth). 16-20 is classical"),
        segments=("int", 16, "Radial segments"),
        material=("str", "stone", "Material preset"),
        color=("str", "", "Override colour"),
    ),
    tags=["prop", "architecture"],
)
def prop_pillar(ctx, name, location, seed, height, radius, style, flutes, segments, material,
                color):
    rng = ctx.reseed(seed)
    base_h = height * 0.08
    cap_h = height * 0.09
    shaft_top = height - cap_h

    if style == "square":
        bm = mesh_lib.new_bmesh()
        mesh_lib.add_box(bm, size=(radius * 2.4, radius * 2.4, base_h),
                         center=(0, 0, base_h * 0.5), bevel=0.02)
        mesh_lib.add_box(bm, size=(radius * 1.8, radius * 1.8, shaft_top - base_h),
                         center=(0, 0, (base_h + shaft_top) * 0.5), bevel=0.015)
        mesh_lib.add_box(bm, size=(radius * 2.5, radius * 2.5, cap_h),
                         center=(0, 0, height - cap_h * 0.5), bevel=0.02)
        smooth = False
    else:
        taper = 0.86 if style in ("doric", "broken") else 0.94
        top_height = shaft_top if style != "broken" else shaft_top * rng.uniform(0.45, 0.7)
        profile = [
            (0.0, 0.0), (radius * 1.42, 0.0), (radius * 1.42, base_h * 0.7),
            (radius * 1.1, base_h), (radius, base_h * 1.15),
            (radius * taper, top_height * 0.92),
        ]
        if style == "broken":
            profile += [(radius * taper * 0.94, top_height), (0.0, top_height)]
        else:
            profile += [
                (radius * taper, shaft_top), (radius * 1.34, shaft_top),
                (radius * 1.34, height - cap_h * 0.25),
                (radius * 1.5, height - cap_h * 0.25), (radius * 1.5, height), (0.0, height),
            ]
        bm = mesh_lib.new_bmesh()
        mesh_lib.lathe(bm, profile, segments=segments)
        smooth = True

    if flutes > 0 and style != "square":
        for vert in bm.verts:
            if base_h * 1.2 < vert.co.z < shaft_top * 0.95:
                angle = math.atan2(vert.co.y, vert.co.x)
                groove = math.cos(angle * flutes) * radius * 0.045
                length = math.hypot(vert.co.x, vert.co.y)
                if length > 1e-6:
                    factor = (length - groove) / length
                    vert.co.x *= factor
                    vert.co.y *= factor

    if style == "broken":
        top = max(v.co.z for v in bm.verts)
        for vert in bm.verts:
            if vert.co.z > top - height * 0.05:
                vert.co.z -= rng.uniform(0.0, height * 0.06)

    mesh_lib.cleanup(bm)
    obj = mesh_lib.to_object(bm, _named(name, "pillar"))
    obj.location = location
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="cylinder",
        origin="bottom", smooth=smooth, smooth_angle=40.0,
    )
    finish_lib.budget_note(ctx, obj, 1200)
    return result


@op(
    "prop.torch",
    summary="Wall torch or standing brazier with an emissive flame. ~250 tris. Emissive props double as level-design landmarks.",
    params=_params(
        style=("enum:wall|standing|brazier", "wall", "Mounting style"),
        height=("num", 0.6, "Length or height in metres"),
        flame_color=("str", "ember", "Flame colour"),
        emission=("num", 6.0, "Flame emission strength"),
        material=("str", "iron", "Body material preset"),
    ),
    tags=["prop", "architecture", "light"],
)
def prop_torch(ctx, name, location, seed, style, height, flame_color, emission, material):
    rng = ctx.reseed(seed)
    base_name = _named(name, "torch")
    bm = mesh_lib.new_bmesh()

    if style == "wall":
        mesh_lib.add_box(bm, size=(0.09, 0.09, 0.16), center=(0, 0, 0), bevel=0.008)
        handle = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(handle, radius=0.028, depth=height, segments=8,
                              center=(0, 0, height * 0.5))
        bmesh.ops.transform(
            handle, matrix=Matrix.Rotation(math.radians(35), 4, "Y"), verts=handle.verts[:]
        )
        _absorb(bm, handle)
        cup_z = math.cos(math.radians(35)) * height
        cup_x = math.sin(math.radians(35)) * height
        mesh_lib.add_cylinder(bm, radius=0.075, radius_top=0.105, depth=0.13, segments=10,
                              center=(cup_x, 0, cup_z))
        flame_at = (cup_x, 0.0, cup_z + 0.12)
    elif style == "brazier":
        mesh_lib.lathe(
            bm,
            [(0.0, 0.0), (0.22, 0.0), (0.10, 0.06), (0.09, height * 0.55),
             (0.30, height * 0.85), (0.34, height), (0.26, height * 0.96), (0.0, height * 0.9)],
            segments=12,
        )
        flame_at = (0.0, 0.0, height + 0.08)
    else:  # standing
        mesh_lib.add_cylinder(bm, radius=0.16, depth=0.06, segments=10, center=(0, 0, 0.03))
        mesh_lib.add_cylinder(bm, radius=0.04, depth=height, segments=8,
                              center=(0, 0, height * 0.5))
        mesh_lib.add_cylinder(bm, radius=0.09, radius_top=0.13, depth=0.14, segments=10,
                              center=(0, 0, height))
        flame_at = (0.0, 0.0, height + 0.12)

    mesh_lib.cleanup(bm)
    body = mesh_lib.to_object(bm, base_name)
    body.location = location
    finish_lib.finish(ctx, body, material=material, uv="box", origin="center_xy", smooth=True,
                      smooth_angle=45.0)

    flame_bm = mesh_lib.new_bmesh()
    mesh_lib.add_icosphere(flame_bm, radius=0.11, subdivisions=1, center=flame_at)
    for vert in flame_bm.verts:
        local = vert.co - Vector(flame_at)
        vert.co = Vector(flame_at) + Vector(
            (local.x * 0.75, local.y * 0.75, local.z * 1.9 + 0.05)
        ) + Vector((rng.uniform(-0.01, 0.01),) * 3)
    flame = mesh_lib.to_object(flame_bm, f"{base_name}_flame")
    flame.location = location
    flame_mat = mat_lib.principled(
        f"m_flame_{base_name}", color=flame_color, roughness=1.0,
        emission=emission, emission_color=flame_color,
    )
    mat_lib.assign(flame, flame_mat)
    mesh_lib.shade_auto_smooth(flame, 60.0)
    from lib import uvs as uv_lib

    uv_lib.smart_project(flame, margin=0.02)

    merged = scene_lib.join([body, flame], base_name)
    scene_lib.set_origin(merged, "center_xy" if style == "wall" else "bottom")
    scene_lib.apply_transforms(merged)
    ctx.note(
        f"'{merged.name}' has an emissive flame material. Add a real point light at "
        f"{[round(v, 2) for v in flame_at]} in-engine — emissive geometry alone does not "
        "light a scene in most renderers."
    )
    result = finish_lib.report(ctx, merged)
    finish_lib.budget_note(ctx, merged, 500)
    return result


def _absorb(target_bm, source_bm):
    """Merge one bmesh into another (bmesh has no direct append)."""
    temp = mesh_lib.bpy.data.meshes.new("_absorb")
    source_bm.to_mesh(temp)
    source_bm.free()
    target_bm.from_mesh(temp)
    mesh_lib.bpy.data.meshes.remove(temp)


@op(
    "prop.fence",
    summary="Fence run with posts and rails. ~40 tris per metre. Blocks player movement and sells scale better than almost any other cheap prop.",
    params=_params(
        length=("num", 4.0, "Total run length in metres"),
        height=("num", 1.1, "Fence height"),
        style=("enum:picket|rail|palisade|iron", "rail", "Fence style"),
        post_spacing=("num", 1.3, "Distance between posts"),
        material=("str", "wood", "Material preset"),
        color=("str", "", "Override colour"),
    ),
    tags=["prop", "architecture"],
)
def prop_fence(ctx, name, location, seed, length, height, style, post_spacing, material, color):
    rng = ctx.reseed(seed)
    bm = mesh_lib.new_bmesh()
    post_count = max(2, int(length / max(0.2, post_spacing)) + 1)
    step = length / (post_count - 1)

    for index in range(post_count):
        x = -length * 0.5 + index * step
        wobble = rng.uniform(-0.015, 0.015)
        if style == "iron":
            mesh_lib.add_cylinder(bm, radius=0.035, depth=height, segments=6,
                                  center=(x, wobble, height * 0.5))
        else:
            mesh_lib.add_box(bm, size=(0.09, 0.09, height), center=(x, wobble, height * 0.5),
                             bevel=0.008)

    if style in ("rail", "iron"):
        for fraction in (0.35, 0.78):
            thickness = 0.05 if style == "rail" else 0.03
            mesh_lib.add_box(
                bm, size=(length, thickness, thickness * 1.4),
                center=(0.0, 0.0, height * fraction), bevel=0.006,
            )
    if style == "picket":
        picket_count = max(2, int(length / 0.16))
        for index in range(picket_count):
            x = -length * 0.5 + (index + 0.5) * (length / picket_count)
            picket_h = height * rng.uniform(0.86, 0.95)
            mesh_lib.add_box(bm, size=(0.055, 0.022, picket_h),
                             center=(x, 0.0, picket_h * 0.5), bevel=0.004)
        for fraction in (0.35, 0.8):
            mesh_lib.add_box(bm, size=(length, 0.045, 0.05),
                             center=(0.0, 0.0, height * fraction), bevel=0.005)
    if style == "palisade":
        stake_count = max(2, int(length / 0.13))
        for index in range(stake_count):
            x = -length * 0.5 + (index + 0.5) * (length / stake_count)
            stake_h = height * rng.uniform(0.9, 1.0)
            mesh_lib.add_cylinder(bm, radius=0.062, radius_top=0.012, depth=stake_h, segments=6,
                                  center=(x, rng.uniform(-0.01, 0.01), stake_h * 0.5))

    mesh_lib.cleanup(bm)
    obj = mesh_lib.to_object(bm, _named(name, "fence"))
    obj.location = location
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="box",
        origin="center_xy", smooth=False,
    )
    finish_lib.budget_note(ctx, obj, int(length * 120))
    return result


@op(
    "prop.furniture",
    summary="Table, bench, stool, shelf or bed frame. ~200 tris. The set dressing that makes an interior look inhabited.",
    params=_params(
        kind=("enum:table|bench|stool|shelf|bed", "table", "Furniture type"),
        size=("vec3", [1.6, 0.8, 0.78], "Overall dimensions in metres"),
        leg_radius=("num", 0.05, "Leg thickness"),
        round_legs=("bool", False, "Turned/round legs instead of square"),
        material=("str", "wood", "Material preset"),
        color=("str", "", "Override colour"),
    ),
    tags=["prop", "furniture"],
)
def prop_furniture(ctx, name, location, seed, kind, size, leg_radius, round_legs, material, color):
    ctx.reseed(seed)
    sx, sy, sz = size
    bm = mesh_lib.new_bmesh()
    top_thickness = max(0.04, sz * 0.07)

    def leg(x, y, height):
        if round_legs:
            mesh_lib.add_cylinder(bm, radius=leg_radius, depth=height, segments=8,
                                  center=(x, y, height * 0.5))
        else:
            mesh_lib.add_box(bm, size=(leg_radius * 2, leg_radius * 2, height),
                             center=(x, y, height * 0.5), bevel=0.006)

    inset = leg_radius * 2.2
    if kind in ("table", "bench", "bed"):
        leg_h = sz - top_thickness
        for dx in (-1, 1):
            for dy in (-1, 1):
                leg(dx * (sx * 0.5 - inset), dy * (sy * 0.5 - inset), leg_h)
        mesh_lib.add_box(bm, size=(sx, sy, top_thickness),
                         center=(0, 0, sz - top_thickness * 0.5), bevel=0.01)
        if kind == "bed":
            mesh_lib.add_box(bm, size=(sx * 0.06, sy, sz * 0.9),
                             center=(-sx * 0.5 + sx * 0.03, 0, sz * 0.45 + top_thickness),
                             bevel=0.01)
    elif kind == "stool":
        leg_h = sz - top_thickness
        for i in range(3):
            angle = math.tau * i / 3
            leg(math.cos(angle) * sx * 0.32, math.sin(angle) * sx * 0.32, leg_h)
        mesh_lib.add_cylinder(bm, radius=sx * 0.5, depth=top_thickness, segments=12,
                              center=(0, 0, sz - top_thickness * 0.5), bevel=0.008)
    elif kind == "shelf":
        for dx in (-1, 1):
            mesh_lib.add_box(bm, size=(leg_radius * 2, sy, sz),
                             center=(dx * (sx * 0.5 - leg_radius), 0, sz * 0.5), bevel=0.006)
        shelves = max(2, int(sz / 0.42))
        for index in range(shelves):
            z = sz * (index + 0.5) / shelves
            mesh_lib.add_box(bm, size=(sx - leg_radius * 2, sy, top_thickness * 0.8),
                             center=(0, 0, z), bevel=0.006)

    mesh_lib.cleanup(bm)
    obj = mesh_lib.to_object(bm, _named(name, kind))
    obj.location = location
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="box",
        origin="bottom", smooth=round_legs,
    )
    finish_lib.budget_note(ctx, obj, 500)
    return result


@op(
    "prop.weapon",
    summary="Sword, axe, spear, hammer or shield built from a blade/haft/grip breakdown. ~400 tris. Pivot sits at the grip so it parents straight to a hand bone.",
    params=_params(
        kind=("enum:sword|axe|spear|hammer|shield|dagger", "sword", "Weapon type"),
        length=("num", 1.0, "Overall length in metres"),
        blade_width=("num", 0.09, "Blade or head width"),
        metal=("str", "iron", "Blade material preset"),
        grip=("str", "wood", "Handle material preset"),
        color=("str", "", "Override blade colour"),
    ),
    tags=["prop", "weapon"],
)
def prop_weapon(ctx, name, location, seed, kind, length, blade_width, metal, grip, color):
    ctx.reseed(seed)
    base_name = _named(name, kind)
    metal_bm = mesh_lib.new_bmesh()
    grip_bm = mesh_lib.new_bmesh()

    if kind in ("sword", "dagger"):
        blade_len = length * (0.74 if kind == "sword" else 0.62)
        grip_len = length - blade_len
        mesh_lib.add_box(metal_bm, size=(blade_width, blade_width * 0.24, blade_len),
                         center=(0, 0, grip_len + blade_len * 0.5), bevel=blade_width * 0.09)
        tip = grip_len + blade_len
        for vert in metal_bm.verts:
            if vert.co.z > tip - blade_len * 0.16:
                vert.co.x *= 0.18
                vert.co.y *= 0.5
        mesh_lib.add_box(metal_bm, size=(blade_width * 3.1, blade_width * 0.55, 0.035),
                         center=(0, 0, grip_len), bevel=0.006)
        mesh_lib.add_cylinder(grip_bm, radius=blade_width * 0.32, depth=grip_len * 0.82,
                              segments=8, center=(0, 0, grip_len * 0.5))
        mesh_lib.add_icosphere(metal_bm, radius=blade_width * 0.42, subdivisions=1,
                               center=(0, 0, grip_len * 0.05))
    elif kind == "axe":
        haft = length
        mesh_lib.add_cylinder(grip_bm, radius=0.026, depth=haft, segments=8,
                              center=(0, 0, haft * 0.5))
        head_z = haft * 0.88
        mesh_lib.add_box(metal_bm, size=(blade_width * 2.6, 0.05, blade_width * 2.2),
                         center=(blade_width * 1.0, 0, head_z), bevel=0.008)
        for vert in metal_bm.verts:
            if vert.co.x > blade_width * 1.9:
                vert.co.y *= 0.22
                vert.co.z += (vert.co.z - head_z) * 0.35
    elif kind == "spear":
        mesh_lib.add_cylinder(grip_bm, radius=0.022, depth=length * 0.9, segments=8,
                              center=(0, 0, length * 0.45))
        mesh_lib.add_cylinder(metal_bm, radius=blade_width * 0.5, radius_top=0.0,
                              depth=length * 0.16, segments=6,
                              center=(0, 0, length * 0.92))
    elif kind == "hammer":
        mesh_lib.add_cylinder(grip_bm, radius=0.03, depth=length, segments=8,
                              center=(0, 0, length * 0.5))
        mesh_lib.add_box(metal_bm, size=(blade_width * 2.4, blade_width * 1.6, blade_width * 1.6),
                         center=(0, 0, length * 0.9), bevel=0.012)
    else:  # shield
        mesh_lib.add_cylinder(metal_bm, radius=length * 0.42, depth=0.05, segments=14,
                              center=(0, 0, 0), bevel=0.012)
        for vert in metal_bm.verts:
            radial = math.hypot(vert.co.x, vert.co.y) / max(length * 0.42, 1e-6)
            vert.co.z += (1.0 - radial * radial) * 0.07
        mesh_lib.add_icosphere(metal_bm, radius=length * 0.09, subdivisions=1,
                               center=(0, 0, 0.06))
        mesh_lib.add_box(grip_bm, size=(length * 0.5, 0.035, 0.035), center=(0, 0, -0.05),
                         bevel=0.005)

    mesh_lib.cleanup(metal_bm)
    mesh_lib.cleanup(grip_bm)
    blade = mesh_lib.to_object(metal_bm, base_name)
    blade.location = location
    finish_lib.finish(ctx, blade, material=metal, color=color or None, uv="box",
                      origin=None, smooth=True, smooth_angle=35.0, apply_transforms=False)

    parts = [blade]
    handle = mesh_lib.to_object(grip_bm, f"{base_name}_grip")
    if len(handle.data.vertices) == 0:
        scene_lib.delete(handle)
    else:
        handle.location = location
        finish_lib.finish(ctx, handle, material=grip, uv="cylinder", origin=None, smooth=True,
                          apply_transforms=False)
        parts.append(handle)

    merged = scene_lib.join(parts, base_name) if len(parts) > 1 else blade
    scene_lib.set_origin(merged, "center_xy" if kind == "shield" else "bottom")
    scene_lib.apply_transforms(merged)
    ctx.note(
        f"'{merged.name}' pivot is at the "
        f"{'centre' if kind == 'shield' else 'grip end'} so it parents directly to a hand bone."
    )
    result = finish_lib.report(ctx, merged)
    finish_lib.budget_note(ctx, merged, 700)
    return result


@op(
    "prop.crossbow",
    summary=(
        "Serious game-ready crossbow with a shouldered stock, curved segmented prod, "
        "taut three-part string, trigger guard, loaded bolt and integrated optic. "
        "Mastery styles add magazines, Daedalus gearing and an Aegis power core "
        "without changing the hand-ready pivot. One joined multi-material mesh."
    ),
    params=_params(
        style=("enum:pilgrim|repeater|daedalus|aegis", "pilgrim", "Construction and mastery tier"),
        length=("num", 1.18, "Stock length in metres"),
        span=("num", 0.92, "Unstrung prod span in metres"),
        scope=("bool", True, "Mount a compact tube optic and lens"),
        wood_color=("str", "#493323", "Seasoned stock colour"),
        bronze_color=("str", "#73512b", "Bronze fittings and prod colour"),
        iron_color=("str", "#343a3c", "Iron rail, trigger and mechanism colour"),
        cord_color=("str", "#9a8d72", "String and fletching colour"),
        lens_color=("str", "#431514", "Dark optic or Aegis core colour"),
        uv_scale=("num", 2.0, "Box unwrap scale"),
    ),
    tags=["prop", "weapon", "crossbow", "fps"],
)
def prop_crossbow(
    ctx,
    name,
    location,
    seed,
    style,
    length,
    span,
    scope,
    wood_color,
    bronze_color,
    iron_color,
    cord_color,
    lens_color,
    uv_scale,
):
    """Build a viewmodel-readable crossbow as one draw mesh.

    Local +Z is the firing axis and local +Y is the top of the stock. The pivot
    sits at the shoulder end, matching prop.weapon's hand-ready convention and
    making the asset predictable in Babylon/Godot/Three without corrective
    object transforms in Blender.
    """
    ctx.reseed(seed)
    tier = {"pilgrim": 0, "repeater": 1, "daedalus": 2, "aegis": 3}[style]
    length = max(0.82, min(1.65, float(length)))
    span = max(length * 0.55, min(length * 1.08, float(span)))
    uv_scale = max(0.1, float(uv_scale))

    materials = [
        mat_lib.principled("m_crossbow_wood", wood_color, roughness=0.82),
        mat_lib.principled("m_crossbow_bronze", bronze_color, roughness=0.34, metallic=0.78),
        mat_lib.principled("m_crossbow_iron", iron_color, roughness=0.3, metallic=0.88),
        mat_lib.principled("m_crossbow_cord", cord_color, roughness=0.96),
        mat_lib.principled(
            "m_crossbow_lens",
            lens_color,
            roughness=0.18,
            metallic=0.12,
            emission=0.18 + tier * 0.12,
            emission_color=lens_color,
        ),
    ]
    WOOD, BRONZE, IRON, CORD, LENS = range(len(materials))
    bm = mesh_lib.new_bmesh()
    parts = 0

    def mark(faces, slot):
        nonlocal parts
        for face in faces:
            face.material_index = slot
        parts += 1
        return faces

    def box(size, center, slot, bevel=0.008, rotation=None):
        faces = mesh_lib.add_box(bm, size=size, bevel=bevel)
        verts = list({vert for face in faces for vert in face.verts})
        matrix = Matrix.Translation(Vector(center))
        if rotation:
            rx, ry, rz = rotation
            matrix = (
                matrix
                @ Matrix.Rotation(rz, 4, "Z")
                @ Matrix.Rotation(ry, 4, "Y")
                @ Matrix.Rotation(rx, 4, "X")
            )
        bmesh.ops.transform(bm, matrix=matrix, verts=verts)
        return mark(faces, slot)

    def between(start, end, radius, slot, segments=8, top_scale=1.0):
        a, b = Vector(start), Vector(end)
        axis = b - a
        if axis.length < 1e-5:
            return []
        faces = mesh_lib.add_cylinder(
            bm,
            radius=radius,
            radius_top=max(0.002, radius * top_scale),
            depth=axis.length,
            segments=segments,
        )
        verts = list({vert for face in faces for vert in face.verts})
        orient = axis.normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.transform(
            bm,
            matrix=Matrix.Translation((a + b) * 0.5) @ orient,
            verts=verts,
        )
        return mark(faces, slot)

    def torus(major, minor, center, slot, rotation=None, segments=16):
        faces = mesh_lib.add_torus(
            bm,
            major=major,
            minor=minor,
            major_segments=segments,
            minor_segments=6,
        )
        verts = list({vert for face in faces for vert in face.verts})
        matrix = Matrix.Translation(Vector(center))
        if rotation:
            rx, ry, rz = rotation
            matrix = (
                matrix
                @ Matrix.Rotation(rz, 4, "Z")
                @ Matrix.Rotation(ry, 4, "Y")
                @ Matrix.Rotation(rx, 4, "X")
            )
        bmesh.ops.transform(bm, matrix=matrix, verts=verts)
        return mark(faces, slot)

    def swept_stock(path, scales, slot):
        """Append a shouldered octagonal stock with a grown-wood silhouette."""
        profile = [
            (-0.5, -0.30), (-0.30, -0.5), (0.30, -0.5), (0.5, -0.30),
            (0.5, 0.30), (0.30, 0.5), (-0.30, 0.5), (-0.5, 0.30),
        ]
        return mark(
            mesh_lib.sweep(
                bm,
                path,
                profile,
                scales=scales,
                up=(0.0, 1.0, 0.0),
            ),
            slot,
        )

    stock_w = length * (0.092 + tier * 0.004)
    stock_h = length * 0.105
    prod_z = length * 0.72
    latch_z = length * 0.47

    # Shoulder stock: one continuous octagonal grown-wood form, tapered at the
    # waist and swollen around the lock. The old stack of cuboids read as a
    # wooden T in gameplay; this profile holds a weapon silhouette at distance.
    swept_stock(
        [
            (0.0, -stock_h * 0.06, length * 0.015),
            (0.0, -stock_h * 0.03, length * 0.17),
            (0.0, -stock_h * 0.08, length * 0.31),
            (0.0, 0.0, length * 0.50),
            (0.0, stock_h * 0.05, length * 0.70),
            (0.0, stock_h * 0.03, length * 0.91),
            (0.0, 0.0, length * 0.99),
        ],
        [
            (stock_w * 0.88, stock_h * 0.92),
            (stock_w * 0.82, stock_h * 0.78),
            (stock_w * 0.56, stock_h * 0.64),
            (stock_w * 0.70, stock_h * 0.76),
            (stock_w * 0.62, stock_h * 0.68),
            (stock_w * 0.47, stock_h * 0.54),
            (stock_w * 0.38, stock_h * 0.45),
        ],
        WOOD,
    )
    # Broad iron buttplate catches a rim light and gives the shoulder end a
    # deliberate termination instead of a bare rectangular cap.
    box((stock_w * 1.88, stock_h * 1.10, length * 0.028),
        (0.0, -stock_h * 0.06, length * 0.018), IRON, stock_w * 0.12)
    box((stock_w * 1.7, stock_h * 0.38, length * 0.19),
        (0.0, stock_h * 0.63, length * 0.17), WOOD, stock_w * 0.08)
    box((stock_w * 0.86, stock_h * 0.7, length * 0.24),
        (0.0, -stock_h * 0.5, length * 0.25), WOOD, stock_w * 0.08,
        rotation=(math.radians(-13), 0.0, 0.0))

    # Bronze reinforcing furniture and an iron firing channel.
    for z in (length * 0.27, length * 0.55, length * 0.69):
        box((stock_w * 1.36, stock_h * 1.14, length * 0.025),
            (0.0, 0.0, z), BRONZE, 0.004)
    box((stock_w * 0.34, stock_h * 0.12, length * 0.65),
        (0.0, stock_h * 0.58, length * 0.63), IRON, 0.004)
    box((stock_w * 1.55, stock_h * 1.35, length * 0.12),
        (0.0, 0.0, prod_z - length * 0.035), BRONZE, 0.012)

    # Trigger and guard. The open ring catches highlights and instantly reads as
    # a manufactured weapon rather than a wooden T shape.
    between(
        (-stock_w * 0.17, -stock_h * 0.46, length * 0.34),
        (stock_w * 0.16, -stock_h * 0.72, length * 0.29),
        stock_w * 0.038,
        IRON,
        6,
    )
    torus(
        stock_w * 0.32,
        stock_w * 0.045,
        (0.0, -stock_h * 0.68, length * 0.30),
        BRONZE,
        rotation=(math.pi * 0.5, 0.0, 0.0),
        segments=14,
    )

    # The prod is a shallow recurved arc made from three tapered segments per
    # side. A straight rod says toy; this silhouette says stored energy.
    tips = []
    for side in (-1.0, 1.0):
        root = Vector((side * stock_w * 0.5, 0.0, prod_z))
        elbow = Vector((side * span * 0.28, 0.006, prod_z + length * 0.075))
        outer = Vector((side * span * 0.46, 0.0, prod_z + length * 0.035))
        tip = Vector((side * span * 0.5, -0.004, prod_z - length * 0.025))
        between(root, elbow, stock_w * 0.145, BRONZE, 10, 0.84)
        between(elbow, outer, stock_w * 0.118, BRONZE, 9, 0.76)
        between(outer, tip, stock_w * 0.084, IRON, 8, 0.66)
        torus(stock_w * 0.09, stock_w * 0.026, tip, IRON, segments=10)
        tips.append(tip)

    # Taut bowstring converges on the latch, visibly separating the mechanism
    # from the prod even in a dark first-person frame.
    latch = Vector((0.0, -stock_h * 0.04, latch_z))
    between(tips[0], latch, stock_w * 0.021, CORD, 5)
    between(latch, tips[1], stock_w * 0.021, CORD, 5)
    between(tips[0], tips[1], stock_w * 0.013, CORD, 4)

    # Loaded bolt, head and fletching.
    bolt_y = stock_h * 0.69
    between((0.0, bolt_y, length * 0.43), (0.0, bolt_y, length * 1.02),
            stock_w * 0.026, IRON, 7, 0.72)
    faces = mesh_lib.add_cylinder(
        bm,
        radius=stock_w * 0.065,
        radius_top=0.0,
        depth=length * 0.10,
        segments=6,
    )
    head_verts = list({vert for face in faces for vert in face.verts})
    bmesh.ops.transform(
        bm,
        matrix=Matrix.Translation(Vector((0.0, bolt_y, length * 1.06))),
        verts=head_verts,
    )
    mark(faces, IRON)
    for side in (-1.0, 1.0):
        box((stock_w * 0.06, stock_w * 0.22, length * 0.095),
            (side * stock_w * 0.055, bolt_y, length * 0.47), CORD, 0.002,
            rotation=(0.0, 0.0, side * math.radians(16)))

    # Compact integrated optic. It is proportioned to the weapon, unlike a
    # screen-space cylinder bolted on after import.
    if scope:
        scope_y = stock_h * 1.43
        scope_a, scope_b = length * 0.39, length * 0.68
        box((stock_w * 0.54, stock_h * 0.18, scope_b - scope_a + length * 0.09),
            (0.0, stock_h * 0.84, (scope_a + scope_b) * 0.5), IRON, 0.004)
        between((0.0, scope_y, scope_a), (0.0, scope_y, scope_b),
                stock_w * (0.20 + tier * 0.012), IRON, 12)
        for z in (scope_a, scope_b):
            torus(stock_w * (0.245 + tier * 0.012), stock_w * 0.048,
                  (0.0, scope_y, z), BRONZE, segments=16)
        faces = mesh_lib.add_cylinder(
            bm,
            radius=stock_w * (0.19 + tier * 0.01),
            depth=stock_w * 0.025,
            segments=14,
            center=(0.0, scope_y, scope_b + stock_w * 0.012),
        )
        mark(faces, LENS)

    # Mastery tiers change construction, not just paint.
    if tier >= 1:
        # Under-slung bolt cassette and visible spare shafts.
        box((stock_w * 1.55, stock_h * 0.78, length * (0.22 + tier * 0.025)),
            (0.0, -stock_h * 0.9, length * 0.57), IRON, 0.009)
        spare_count = 3 if tier == 1 else 5
        for index in range(spare_count):
            x = (index - (spare_count - 1) * 0.5) * stock_w * 0.28
            between((x, -stock_h * 1.32, length * 0.46),
                    (x, -stock_h * 1.32, length * 0.66),
                    stock_w * 0.018, CORD, 5)
    if tier >= 2:
        # Daedalus ratchet wheels on both sides and rigid side rails.
        for side in (-1.0, 1.0):
            gear_x = side * stock_w * 0.92
            torus(stock_w * 0.26, stock_w * 0.055,
                  (gear_x, 0.0, length * 0.58), BRONZE,
                  rotation=(0.0, math.pi * 0.5, 0.0), segments=18)
            between(
                (side * stock_w * 0.72, 0.0, length * 0.43),
                (side * stock_w * 0.72, 0.0, prod_z),
                stock_w * 0.038,
                IRON,
                7,
            )
    if tier >= 3:
        # Aegis power cores and a broader forward armour plate.
        box((stock_w * 2.05, stock_h * 1.58, length * 0.10),
            (0.0, 0.0, prod_z - length * 0.08), BRONZE, 0.016)
        for side in (-1.0, 0.0, 1.0):
            faces = mesh_lib.add_icosphere(
                bm,
                radius=stock_w * (0.12 if side else 0.16),
                subdivisions=2,
                center=(side * stock_w * 0.55, stock_h * 0.62, length * 0.61),
            )
            mark(faces, LENS)

    mesh_lib.cleanup(bm, merge_dist=1e-5)
    obj = mesh_lib.to_object(bm, _named(name, f"crossbow_{style}"))
    for material in materials:
        obj.data.materials.append(material)
    obj.location = location
    obj["bforge_weapon"] = "crossbow"
    obj["bforge_crossbow_style"] = style
    obj["bforge_parts"] = parts
    result = finish_lib.finish(
        ctx,
        obj,
        material="",
        uv="box",
        uv_scale=uv_scale,
        origin="bottom",
        smooth=True,
        smooth_angle=38.0,
    )
    result.update({
        "style": style,
        "parts": parts,
        "scope": bool(scope),
        "magazine": tier >= 1,
        "gearing": tier >= 2,
        "power_core": tier >= 3,
    })
    finish_lib.budget_note(ctx, obj, 6500)
    return result


@op(
    "prop.banner",
    summary="Hanging banner or flag with a cloth wave. ~180 tris. Cheap way to add faction identity and colour to grey architecture.",
    params=_params(
        size=("vec2", [0.9, 1.8], "Cloth width and drop in metres"),
        wave=("num", 0.09, "Wave amplitude in metres"),
        segments=("int", 8, "Vertical cloth segments"),
        pole=("bool", True, "Include a crossbar pole"),
        material=("str", "cloth", "Cloth material preset"),
        color=("str", "cloth_red", "Cloth colour"),
    ),
    tags=["prop", "architecture"],
)
def prop_banner(ctx, name, location, seed, size, wave, segments, pole, material, color):
    rng = ctx.reseed(seed)
    width, drop = size
    bm = mesh_lib.new_bmesh()
    columns = 5
    rows = max(2, segments)
    grid = []
    for row in range(rows + 1):
        t = row / rows
        line = []
        for col in range(columns + 1):
            u = col / columns
            x = (u - 0.5) * width
            y = math.sin(t * math.pi * 1.7 + u * 1.1) * wave * (0.35 + t)
            z = -t * drop
            if row == rows:
                z -= abs(math.sin(u * math.pi * 2.0)) * drop * 0.06
            line.append(bm.verts.new((x, y + rng.uniform(-0.004, 0.004), z)))
        grid.append(line)
    for row in range(rows):
        for col in range(columns):
            bm.faces.new(
                (grid[row][col], grid[row][col + 1], grid[row + 1][col + 1], grid[row + 1][col])
            )
    cloth = mesh_lib.to_object(bm, _named(name, "banner"))
    cloth.location = location
    finish_lib.finish(ctx, cloth, material=material, color=color or None, uv="box",
                      uv_scale=max(width, drop), origin=None, smooth=True, smooth_angle=70.0,
                      apply_transforms=False)

    parts = [cloth]
    if pole:
        pole_bm = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(pole_bm, radius=0.032, depth=width * 1.25, segments=8)
        bmesh.ops.transform(
            pole_bm, matrix=Matrix.Rotation(math.radians(90), 4, "Y"), verts=pole_bm.verts[:]
        )
        pole_obj = mesh_lib.to_object(pole_bm, f"{cloth.name}_pole")
        pole_obj.location = (location[0], location[1], location[2] + 0.03)
        mat_lib.assign(pole_obj, mat_lib.from_preset("wood"))
        from lib import uvs as uv_lib

        uv_lib.cylinder_project(pole_obj)
        mesh_lib.shade_auto_smooth(pole_obj, 45.0)
        parts.append(pole_obj)

    merged = scene_lib.join(parts, cloth.name) if len(parts) > 1 else cloth
    scene_lib.apply_transforms(merged)
    result = finish_lib.report(ctx, merged)
    finish_lib.budget_note(ctx, merged, 400)
    return result


@op(
    "prop.debris",
    summary="Scattered rubble field: broken stone, planks and dust chunks around a point. ~50 tris per piece. Turns a clean floor into a fought-over one.",
    params=_params(
        count=("int", 9, "Number of pieces"),
        radius=("num", 1.5, "Scatter radius in metres"),
        piece_size=("num", 0.22, "Average piece size"),
        kind=("enum:stone|wood|mixed", "stone", "Debris type"),
        material=("str", "", "Material preset override"),
    ),
    tags=["prop", "nature"],
)
def prop_debris(ctx, name, location, seed, count, radius, piece_size, kind, material):
    rng = ctx.reseed(seed)
    bm = mesh_lib.new_bmesh()
    for _ in range(max(1, count)):
        angle = rng.uniform(0, math.tau)
        distance = radius * math.sqrt(rng.random())
        scale = piece_size * rng.uniform(0.45, 1.5)
        piece = mesh_lib.new_bmesh()
        style = kind if kind != "mixed" else rng.choice(["stone", "wood"])
        if style == "wood":
            mesh_lib.add_box(piece, size=(scale * 2.6, scale * 0.32, scale * 0.22), bevel=0.004)
        else:
            mesh_lib.add_icosphere(piece, radius=scale * 0.5, subdivisions=1)
            for vert in piece.verts:
                vert.co.x *= rng.uniform(0.6, 1.4)
                vert.co.y *= rng.uniform(0.6, 1.4)
                vert.co.z *= rng.uniform(0.35, 0.8)
        matrix = (
            Matrix.Translation(
                (
                    math.cos(angle) * distance,
                    math.sin(angle) * distance,
                    scale * 0.18,
                )
            )
            @ Matrix.Rotation(rng.uniform(0, math.tau), 4, "Z")
            @ Matrix.Rotation(rng.uniform(-0.4, 0.4), 4, "X")
        )
        bmesh.ops.transform(piece, matrix=matrix, verts=piece.verts[:])
        _absorb(bm, piece)

    mesh_lib.cleanup(bm)
    obj = mesh_lib.to_object(bm, _named(name, "debris"))
    obj.location = location
    preset = material or ("wood" if kind == "wood" else "rock")
    result = finish_lib.finish(
        ctx, obj, material=preset, uv="box", origin="center_xy", smooth=False,
    )
    finish_lib.budget_note(ctx, obj, count * 90)
    return result
