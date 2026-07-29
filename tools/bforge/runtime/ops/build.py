"""Parametric primitives and mesh editing.

These are the raw verbs. Prefer the higher-level `prop.*` / `kit.*` / `env.*`
recipes when one fits — they already know the right proportions, chamfers and
UV strategy for their asset class. Drop to `build.*` when composing something
the recipes don't cover.
"""

from __future__ import annotations

import bmesh
from lib import finish as finish_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from registry import OpError, op

COMMON = {
    "name": ("str", "part", "Object name (coerced to snake_case)"),
    "location": ("vec3", [0.0, 0.0, 0.0], "World position in metres"),
    "material": ("str", "stone", "Material preset name, or '' for none. See meta.palette"),
    "color": ("str", "", "Override colour: palette name or #rrggbb"),
    "uv": ("enum:box|cylinder|smart|smart_packed|none", "box", "UV strategy"),
    "uv_scale": ("num", 1.0, "Metres per UV tile for box projection"),
    "origin": ("enum:bottom|center|center_xy|world", "center", "Pivot placement"),
    "smooth": ("bool", False, "Smooth shading with a sharp-edge threshold"),
}


def _params(**extra):
    merged = dict(COMMON)
    merged.update(extra)
    return merged


def _finish(ctx, obj, kwargs):
    return finish_lib.finish(
        ctx,
        obj,
        material=kwargs.get("material") or None,
        color=kwargs.get("color") or None,
        uv=kwargs.get("uv", "box"),
        uv_scale=kwargs.get("uv_scale", 1.0),
        origin=kwargs.get("origin", "center"),
        smooth=kwargs.get("smooth", False),
    )


@op(
    "build.box",
    summary="Chamfered box. The chamfer is what makes a box read as a solid object under game lighting instead of a flat card.",
    params=_params(
        size=("vec3", [1.0, 1.0, 1.0], "Outer dimensions in metres"),
        bevel=("num", 0.02, "Chamfer width in metres; 0 disables"),
        bevel_segments=("int", 2, "Chamfer resolution (2 is plenty for game assets)"),
    ),
    tags=["build"],
)
def build_box(ctx, name, size, bevel, bevel_segments, location, material, color, uv, uv_scale,
              origin, smooth):
    bm = mesh_lib.new_bmesh()
    mesh_lib.add_box(bm, size=size, bevel=bevel, segments=bevel_segments)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    return _finish(ctx, obj, locals())


@op(
    "build.cylinder",
    summary="Cylinder, cone or truncated cone (set radius_top). Pillars, pipes, barrels, tent poles.",
    params=_params(
        radius=("num", 0.5, "Bottom radius in metres"),
        radius_top=("num", -1.0, "Top radius; -1 means same as bottom, 0 makes a cone"),
        depth=("num", 1.0, "Height in metres"),
        segments=("int", 16, "Radial segments — 12-16 is the game-asset sweet spot"),
        cap=("bool", True, "Close the ends"),
        bevel=("num", 0.0, "Chamfer the rim edges"),
        smooth=("bool", True, "Smooth shading (usually right for round shapes)"),
        uv=("enum:box|cylinder|smart|smart_packed|none", "cylinder", "UV strategy"),
    ),
    tags=["build"],
)
def build_cylinder(ctx, name, radius, radius_top, depth, segments, cap, bevel, location, material,
                   color, uv, uv_scale, origin, smooth):
    bm = mesh_lib.new_bmesh()
    mesh_lib.add_cylinder(
        bm, radius=radius, depth=depth, segments=segments, cap=cap,
        radius_top=None if radius_top < 0 else radius_top, bevel=bevel,
    )
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    return _finish(ctx, obj, locals())


@op(
    "build.sphere",
    summary="UV sphere or icosphere. Icospheres have even topology and are better bases for rocks and organic shapes.",
    params=_params(
        radius=("num", 0.5, "Radius in metres"),
        kind=("enum:uv|ico", "ico", "Topology type"),
        segments=("int", 16, "UV sphere: radial segments"),
        rings=("int", 8, "UV sphere: vertical rings"),
        subdivisions=("int", 2, "Icosphere: subdivision level (2 = 320 tris)"),
        smooth=("bool", True, "Smooth shading"),
        uv=("enum:box|cylinder|smart|smart_packed|none", "smart", "UV strategy"),
    ),
    tags=["build"],
)
def build_sphere(ctx, name, radius, kind, segments, rings, subdivisions, location, material, color,
                 uv, uv_scale, origin, smooth):
    bm = mesh_lib.new_bmesh()
    if kind == "ico":
        mesh_lib.add_icosphere(bm, radius=radius, subdivisions=subdivisions)
    else:
        mesh_lib.add_sphere(bm, radius=radius, segments=segments, rings=rings)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    return _finish(ctx, obj, locals())


@op(
    "build.plane",
    summary="Flat quad, optionally grid-subdivided. Floors, walls, water, billboards, terrain bases.",
    params=_params(
        size=("vec2", [1.0, 1.0], "Dimensions in metres"),
        cuts=("int", 0, "Grid subdivisions per edge"),
        origin=("enum:bottom|center|center_xy|world", "center", "Pivot placement"),
    ),
    tags=["build"],
)
def build_plane(ctx, name, size, cuts, location, material, color, uv, uv_scale, origin, smooth):
    bm = mesh_lib.new_bmesh()
    mesh_lib.add_plane(bm, size=size, cuts=cuts)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    return _finish(ctx, obj, locals())


@op(
    "build.prism",
    summary="N-sided prism. Hex tiles, crystals, columns, low-poly trunks.",
    params=_params(
        radius=("num", 0.5, "Circumradius in metres"),
        depth=("num", 1.0, "Height in metres"),
        sides=("int", 6, "Number of sides"),
    ),
    tags=["build"],
)
def build_prism(ctx, name, radius, depth, sides, location, material, color, uv, uv_scale, origin,
                smooth):
    bm = mesh_lib.new_bmesh()
    mesh_lib.add_prism(bm, radius=radius, depth=depth, sides=sides)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    return _finish(ctx, obj, locals())


@op(
    "build.wedge",
    summary="Right-triangle prism. Ramps, roof sections, chamfer blockouts.",
    params=_params(size=("vec3", [1.0, 1.0, 1.0], "Bounding dimensions in metres")),
    tags=["build"],
)
def build_wedge(ctx, name, size, location, material, color, uv, uv_scale, origin, smooth):
    bm = mesh_lib.new_bmesh()
    mesh_lib.add_wedge(bm, size=size)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    return _finish(ctx, obj, locals())


@op(
    "build.torus",
    summary="Torus. Rings, handles, hoops, portal frames.",
    params=_params(
        major=("num", 0.5, "Ring radius in metres"),
        minor=("num", 0.12, "Tube radius in metres"),
        major_segments=("int", 20, "Segments around the ring"),
        minor_segments=("int", 8, "Segments around the tube"),
        smooth=("bool", True, "Smooth shading"),
        uv=("enum:box|cylinder|smart|smart_packed|none", "smart", "UV strategy"),
    ),
    tags=["build"],
)
def build_torus(ctx, name, major, minor, major_segments, minor_segments, location, material, color,
                uv, uv_scale, origin, smooth):
    bm = mesh_lib.new_bmesh()
    mesh_lib.add_torus(bm, major, minor, major_segments, minor_segments)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    return _finish(ctx, obj, locals())


@op(
    "build.lathe",
    summary="Revolve a 2D profile into a solid. The highest value-per-parameter op here: bottles, vases, columns, goblets, chess pieces, tree trunks, fountains.",
    params=_params(
        profile=("num[]", None, "Flat [radius0, height0, radius1, height1, ...] pairs, bottom to top"),
        segments=("int", 16, "Radial segments"),
        smooth=("bool", True, "Smooth shading"),
        uv=("enum:box|cylinder|smart|smart_packed|none", "cylinder", "UV strategy"),
    ),
    tags=["build"],
)
def build_lathe(ctx, name, profile, segments, location, material, color, uv, uv_scale, origin,
                smooth):
    if len(profile) < 4 or len(profile) % 2 != 0:
        raise OpError(
            "profile must be an even-length list of at least 2 (radius, height) pairs, "
            "e.g. [0.3,0, 0.35,0.4, 0.3,0.8] for a barrel silhouette"
        )
    pairs = [(profile[i], profile[i + 1]) for i in range(0, len(profile), 2)]
    bm = mesh_lib.new_bmesh()
    mesh_lib.lathe(bm, pairs, segments=segments)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    return _finish(ctx, obj, locals())


@op(
    "build.sweep",
    summary="Sweep a 2D cross-section along a path — the workhorse for level geometry. Racetracks, grandstands, roads, ramparts, rails, tunnels, mouldings and pipes are all one profile plus one path. Frames use parallel transport, so a closed loop does not twist.",
    params=_params(
        profile=("num[]", None, "Flat [lateral0, vertical0, lateral1, vertical1, ...] cross-section in metres, relative to the path"),
        profile_scales=("num[]", [], "Flat [lateral0, vertical0, ...] multipliers applied to the cross-section ALONG the path, interpolated to fit. This is what turns a uniform tube into an anatomy — a barrel that swells at the girth, a neck that tapers to the poll. Give a few key values, not one per point"),
        path=("num[]", [], "Flat [x0,y0,z0, x1,y1,z1, ...] path points; leave empty and use path_shape instead"),
        path_shape=("enum:custom|oval|circle|line|arc", "custom", "Built-in path generator"),
        straight=("num", 40.0, "oval: length of each straight in metres"),
        radius=("num", 12.0, "oval/circle/arc radius in metres"),
        length=("num", 20.0, "line: total length in metres along X"),
        arc_degrees=("num", 180.0, "arc: sweep angle in degrees"),
        segments=("int", 24, "Path resolution (per turn for an oval)"),
        closed_path=("bool", True, "Close the path into a loop (oval and circle are always closed)"),
        closed_profile=("bool", True, "Treat the cross-section as a closed outline (a solid tube) rather than an open strip"),
        smooth=("bool", False, "Smooth shading"),
        uv=("enum:box|cylinder|smart|smart_packed|none", "box", "UV strategy"),
        uv_scale=("num", 4.0, "Metres per UV tile"),
        origin=("enum:bottom|center|center_xy|world", "world", "Pivot placement"),
    ),
    tags=["build", "architecture"],
)
def build_sweep(ctx, name, profile, profile_scales, path, path_shape, straight, radius, length,
                arc_degrees, segments, closed_path, closed_profile, location, material, color, uv,
                uv_scale, origin, smooth):
    import math

    if len(profile) < 4 or len(profile) % 2 != 0:
        raise OpError(
            "profile must be an even-length list of at least 2 (lateral, vertical) pairs, "
            "e.g. [-12,0, 12,0, 12,0.4, -12,0.4] for a 24 m wide, 0.4 m thick road"
        )
    section = [(profile[i], profile[i + 1]) for i in range(0, len(profile), 2)]
    segments = max(3, segments)

    if path_shape == "custom":
        if len(path) < 6 or len(path) % 3 != 0:
            raise OpError(
                "path_shape='custom' needs a flat list of at least 2 (x, y, z) points, "
                "or pick path_shape='oval'|'circle'|'line'|'arc'"
            )
        points = [(path[i], path[i + 1], path[i + 2]) for i in range(0, len(path), 3)]
    elif path_shape == "oval":
        points = mesh_lib.oval_path(straight, radius, segments)
        closed_path = True
    elif path_shape == "circle":
        points = [
            (math.cos(2 * math.pi * i / segments) * radius,
             math.sin(2 * math.pi * i / segments) * radius, 0.0)
            for i in range(segments)
        ]
        closed_path = True
    elif path_shape == "arc":
        total = math.radians(arc_degrees)
        points = [
            (math.cos(total * i / segments) * radius,
             math.sin(total * i / segments) * radius, 0.0)
            for i in range(segments + 1)
        ]
        closed_path = False
    else:  # line
        points = [(-length * 0.5 + length * i / segments, 0.0, 0.0) for i in range(segments + 1)]
        closed_path = False

    if len(profile_scales) % 2 != 0:
        raise OpError("profile_scales must be an even-length list of (lateral, vertical) pairs")
    scales = [
        (profile_scales[i], profile_scales[i + 1]) for i in range(0, len(profile_scales), 2)
    ]

    bm = mesh_lib.new_bmesh()
    try:
        mesh_lib.sweep(bm, points, section, closed_path=closed_path,
                       closed_profile=closed_profile, scales=scales or None)
    except ValueError as exc:
        bm.free()
        raise OpError(str(exc)) from exc
    mesh_lib.cleanup(bm)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    obj.location = location
    result = _finish(ctx, obj, locals())
    result["path_points"] = len(points)
    result["path_shape"] = path_shape
    return result


# ---------------------------------------------------------------------------
# editing existing geometry
# ---------------------------------------------------------------------------


@op(
    "build.bevel",
    summary="Chamfer an object's sharp edges. The single highest-impact polish step for hard-surface props.",
    params={
        "name": ("str", None, "Object name"),
        "width": ("num", 0.015, "Chamfer width in metres"),
        "segments": ("int", 2, "Chamfer resolution"),
        "angle": ("num", 30.0, "Only bevel edges sharper than this (degrees)"),
    },
    tags=["build", "polish"],
)
def build_bevel(ctx, name, width, segments, angle):
    import math

    obj = _get(name)
    bm = mesh_lib.obj_bmesh(obj)
    mesh_lib.bevel_edges(bm, offset=width, segments=segments, angle_min=math.radians(angle))
    mesh_lib.write_bmesh(bm, obj)
    return finish_lib.report(ctx, obj)


@op(
    "build.extrude",
    summary="Inset-and-extrude faces selected by their normal direction. Makes panels, ledges, windows and recesses.",
    params={
        "name": ("str", None, "Object name"),
        "direction": ("enum:up|down|north|south|east|west|all|outward", "up", "Which faces to affect"),
        "distance": ("num", 0.1, "Extrude distance in metres (negative recesses)"),
        "inset": ("num", 0.05, "Inset before extruding — this is what makes a panel not a spike"),
        "threshold": ("num", 0.7, "Normal alignment required to count as facing that direction"),
    },
    tags=["build"],
)
def build_extrude(ctx, name, direction, distance, inset, threshold):
    obj = _get(name)
    bm = mesh_lib.obj_bmesh(obj)
    axes = {
        "up": (0, 0, 1), "down": (0, 0, -1), "north": (0, 1, 0), "south": (0, -1, 0),
        "east": (1, 0, 0), "west": (-1, 0, 0),
    }
    if direction == "all":
        faces = bm.faces[:]
    elif direction == "outward":
        faces = [f for f in bm.faces if f.normal.dot(f.calc_center_median()) > 0]
    else:
        target = axes[direction]
        faces = [
            f for f in bm.faces
            if sum(f.normal[i] * target[i] for i in range(3)) >= threshold
        ]
    if not faces:
        bm.free()
        raise OpError(
            f"no faces on '{name}' point {direction} (threshold {threshold}). "
            "Lower `threshold`, or use direction='all'."
        )
    mesh_lib.extrude(bm, faces, distance, inset)
    mesh_lib.write_bmesh(bm, obj)
    return finish_lib.report(ctx, obj)


@op(
    "build.greeble",
    summary="Scatter panel detail across faces — sci-fi hulls, machinery, city blocks, tech walls. Deterministic for a given seed.",
    params={
        "name": ("str", None, "Object name"),
        "seed": ("int", 0, "Random seed; same seed gives the same result forever"),
        "density": ("num", 0.35, "Fraction of faces that get a panel (0..1)"),
        "depth": ("num", 0.03, "Maximum panel depth in metres"),
        "cuts": ("int", 1, "Subdivision passes before panelling — more cuts, finer greeble"),
        "panel_size": (
            "num",
            0.0,
            "Target panel size in metres. Refines big faces and leaves small ones alone, "
            "so one call suits a 16 m wall and a 0.4 m crate lid. Overrides `cuts`; 0 = use `cuts`.",
        ),
    },
    tags=["build", "hardsurface"],
)
def build_greeble(ctx, name, seed, density, depth, cuts, panel_size):
    obj = _get(name)
    rng = ctx.reseed(seed)
    bm = mesh_lib.obj_bmesh(obj)
    made = mesh_lib.greeble(
        bm, bm.faces[:], rng, density=density, min_depth=depth * 0.3, max_depth=depth,
        cuts=cuts, panel_size=panel_size,
    )
    mesh_lib.write_bmesh(bm, obj)
    result = finish_lib.report(ctx, obj)
    result["panels"] = len(made)
    return result


@op(
    "build.subdivide",
    summary="Subdivide all faces. Use sparingly — subdivision multiplies triangles fast.",
    params={
        "name": ("str", None, "Object name"),
        "cuts": ("int", 1, "Cuts per edge"),
        "smooth": ("num", 0.0, "Smoothing factor (0 keeps the silhouette)"),
    },
    tags=["build"],
)
def build_subdivide(ctx, name, cuts, smooth):
    obj = _get(name)
    bm = mesh_lib.obj_bmesh(obj)
    bmesh.ops.subdivide_edges(
        bm, edges=bm.edges[:], cuts=max(1, cuts), smooth=smooth, use_grid_fill=True
    )
    mesh_lib.write_bmesh(bm, obj)
    return finish_lib.report(ctx, obj)


@op(
    "build.deform",
    summary="Taper, twist or noise-displace a mesh. Turns generic primitives into things with character.",
    params={
        "name": ("str", None, "Object name"),
        "mode": ("enum:taper|noise|jitter|squash", "taper", "Deformation type"),
        "amount": ("num", 0.5, "taper: top scale factor. noise/jitter: displacement in metres. squash: Z scale"),
        "frequency": ("num", 3.0, "noise: spatial frequency"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["build"],
)
def build_deform(ctx, name, mode, amount, frequency, seed):
    obj = _get(name)
    rng = ctx.reseed(seed)
    bm = mesh_lib.obj_bmesh(obj)
    zs = [v.co.z for v in bm.verts] or [0.0]
    if mode == "taper":
        mesh_lib.taper(bm, bm.verts[:], amount, min(zs), max(zs))
    elif mode == "noise":
        mesh_lib.bend_noise(bm, bm.verts[:], rng, amount=amount, frequency=frequency)
    elif mode == "jitter":
        mesh_lib.jitter_verts(bm, bm.verts[:], rng, amount=amount)
    elif mode == "squash":
        for vert in bm.verts:
            vert.co.z *= amount
    mesh_lib.write_bmesh(bm, obj)
    return finish_lib.report(ctx, obj)


@op(
    "build.array",
    summary="Repeat an object along a vector, or in a 2D/3D grid. Fences, columns, pipes, city blocks, crowd props.",
    params={
        "name": ("str", None, "Object to repeat"),
        "counts": ("int[]", [3], "Repeat count per axis, e.g. [5] or [4,4] or [3,3,2]"),
        "spacing": ("vec3", [1.0, 1.0, 1.0], "Distance between copies in metres"),
        "join": ("bool", True, "Merge into a single mesh (fewer draw calls)"),
    },
    tags=["build"],
)
def build_array(ctx, name, counts, spacing, join):
    obj = _get(name)
    counts = (list(counts) + [1, 1, 1])[:3]
    made = [obj]
    base = tuple(obj.location)
    for ix in range(counts[0]):
        for iy in range(counts[1]):
            for iz in range(counts[2]):
                if ix == iy == iz == 0:
                    continue
                copy = scene_lib.duplicate(obj, f"{obj.name}_{ix}_{iy}_{iz}")
                copy.location = (
                    base[0] + ix * spacing[0],
                    base[1] + iy * spacing[1],
                    base[2] + iz * spacing[2],
                )
                made.append(copy)
    if join and len(made) > 1:
        merged = scene_lib.join(made, obj.name)
        return finish_lib.report(ctx, merged)
    return {"objects": [o.name for o in made], "count": len(made)}


@op(
    "build.mirror",
    summary="Mirror geometry across an axis. Halves the modelling work for anything symmetrical — characters, vehicles, buildings.",
    params={
        "name": ("str", None, "Object name"),
        "axis": ("enum:X|Y|Z", "X", "Mirror axis"),
    },
    tags=["build"],
)
def build_mirror(ctx, name, axis):
    obj = _get(name)
    bm = mesh_lib.obj_bmesh(obj)
    mesh_lib.mirror(bm, axis)
    mesh_lib.write_bmesh(bm, obj)
    return finish_lib.report(ctx, obj)


@op(
    "build.cleanup",
    summary="Weld duplicate vertices and optionally dissolve coplanar faces. Run before measuring or exporting.",
    params={
        "name": ("str", None, "Object name"),
        "merge_distance": ("num", 0.0001, "Weld threshold in metres"),
        "dissolve_flat": ("bool", False, "Merge coplanar faces (cuts triangles, can create n-gons)"),
    },
    tags=["build", "polish"],
)
def build_cleanup(ctx, name, merge_distance, dissolve_flat):
    obj = _get(name)
    before = mesh_lib.tri_count(obj)
    bm = mesh_lib.obj_bmesh(obj)
    mesh_lib.cleanup(bm, merge_dist=merge_distance, limited_dissolve=dissolve_flat)
    mesh_lib.write_bmesh(bm, obj)
    result = finish_lib.report(ctx, obj)
    result["triangles_before"] = before
    return result


def _get(name):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
