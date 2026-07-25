"""Environment generation: terrain, scatter, cliffs, water, roads."""

from __future__ import annotations

import math

import bmesh
from lib import finish as finish_lib
from lib import mat as mat_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from lib import uvs as uv_lib
from mathutils import Matrix, Vector
from registry import OpError, op


def _fbm(x, y, seed, octaves=4, lacunarity=2.0, gain=0.5):
    """Value-noise fBm built from sin/cos so it needs no external noise library
    and is bit-identical across platforms — which matters when CI regenerates
    an asset and diffs it against the committed one."""
    total = 0.0
    amplitude = 1.0
    frequency = 1.0
    norm = 0.0
    for octave in range(max(1, octaves)):
        phase = seed * 0.7919 + octave * 12.9898
        total += amplitude * (
            math.sin(x * frequency + phase) * math.cos(y * frequency * 1.13 - phase * 0.7)
            + 0.6 * math.sin((x + y) * frequency * 0.61 + phase * 1.7)
        )
        norm += amplitude * 1.6
        amplitude *= gain
        frequency *= lacunarity
    return total / max(norm, 1e-6)


@op(
    "env.terrain",
    summary="Heightfield terrain with fBm noise, optional plateaus and erosion-like smoothing. Deterministic across machines, so CI can regenerate and diff it.",
    params={
        "name": ("str", "terrain", "Object name"),
        "size": ("vec2", [40.0, 40.0], "Terrain extents in metres"),
        "resolution": ("int", 48, "Grid subdivisions per side (48 = ~4600 tris)"),
        "height": ("num", 5.0, "Peak-to-trough height in metres"),
        "scale": ("num", 0.12, "Noise frequency — lower is broader hills"),
        "octaves": ("int", 4, "Noise detail levels"),
        "style": ("enum:hills|mountains|plateau|dunes|island", "hills", "Terrain character"),
        "flatten_center": ("num", 0.0, "Radius in metres of a flat buildable area at the origin"),
        "seed": ("int", 0, "Random seed"),
        "material": ("str", "sand", "Material preset"),
        "color": ("str", "", "Override colour"),
        "uv_scale": ("num", 4.0, "Metres per UV tile"),
    },
    tags=["env", "nature"],
)
def env_terrain(ctx, name, size, resolution, height, scale, octaves, style, flatten_center, seed,
                material, color, uv_scale):
    ctx.reseed(seed)
    resolution = max(4, min(400, resolution))
    size_x, size_y = size
    bm = mesh_lib.new_bmesh()
    grid = []
    half_x, half_y = size_x * 0.5, size_y * 0.5
    radius_max = math.hypot(half_x, half_y)

    for iy in range(resolution + 1):
        row = []
        for ix in range(resolution + 1):
            x = -half_x + size_x * ix / resolution
            y = -half_y + size_y * iy / resolution
            value = _fbm(x * scale, y * scale, seed, octaves)

            if style == "mountains":
                value = (abs(value) ** 0.75) * 1.6 - 0.35
            elif style == "plateau":
                value = math.tanh(value * 2.6) * 0.7
            elif style == "dunes":
                value = math.sin(value * 3.2 + x * scale * 2.0) * 0.55
            elif style == "island":
                falloff = max(0.0, 1.0 - (math.hypot(x, y) / max(radius_max * 0.72, 1e-6)) ** 2)
                value = (value * 0.6 + 0.45) * falloff - 0.12

            z = value * height
            if flatten_center > 0.0:
                distance = math.hypot(x, y)
                if distance < flatten_center:
                    z = 0.0
                elif distance < flatten_center * 1.8:
                    blend = (distance - flatten_center) / max(flatten_center * 0.8, 1e-6)
                    z *= blend * blend
            row.append(bm.verts.new((x, y, z)))
        grid.append(row)

    for iy in range(resolution):
        for ix in range(resolution):
            bm.faces.new(
                (grid[iy][ix], grid[iy][ix + 1], grid[iy + 1][ix + 1], grid[iy + 1][ix])
            )

    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="box", uv_scale=uv_scale,
        origin=None, smooth=True, smooth_angle=60.0,
    )
    result["style"] = style
    result["extent_m"] = [size_x, size_y]
    if result["triangles"] > 20000:
        ctx.note(
            f"Terrain is {result['triangles']} triangles. For a streaming world, generate "
            "tiles of ~4-8k each instead of one large mesh, or run gameready.lod."
        )
    return result


@op(
    "env.scatter",
    summary="Scatter copies of an object over a surface with Poisson-ish spacing, aligned to the surface normal. The op that turns bare terrain into a forest, a rockfield or a graveyard.",
    params={
        "source": ("str", None, "Object to scatter"),
        "target": ("str", "", "Surface to scatter onto (empty = scatter on the Z=0 plane)"),
        "count": ("int", 30, "Number of instances to attempt"),
        "area": ("vec2", [20.0, 20.0], "Scatter area in metres when there is no target"),
        "min_spacing": ("num", 1.2, "Minimum distance between instances"),
        "scale_range": ("vec2", [0.75, 1.35], "Random uniform scale range"),
        "align_to_normal": ("num", 0.0, "0 = always upright, 1 = fully follow the surface tilt"),
        "max_slope": ("num", 40.0, "Skip spots steeper than this (degrees)"),
        "seed": ("int", 0, "Random seed"),
        "join": ("bool", True, "Merge into one mesh — critical for draw calls"),
        "name": ("str", "", "Name for the merged result"),
    },
    tags=["env", "nature"],
)
def env_scatter(ctx, source, target, count, area, min_spacing, scale_range, align_to_normal,
                max_slope, seed, join, name):
    rng = ctx.reseed(seed)
    src = _get(source)
    surface = _get(target) if target else None
    if surface is not None and surface.type != "MESH":
        raise OpError(f"scatter target '{target}' must be a mesh")

    sampler = None
    if surface is not None:
        sampler = _SurfaceSampler(surface)
        span_x, span_y = sampler.span
    else:
        span_x, span_y = area

    placed: list[Vector] = []
    made = []
    attempts = 0
    max_attempts = count * 30
    slope_limit = math.cos(math.radians(max(0.0, min(89.0, max_slope))))

    while len(placed) < count and attempts < max_attempts:
        attempts += 1
        x = rng.uniform(-span_x * 0.5, span_x * 0.5)
        y = rng.uniform(-span_y * 0.5, span_y * 0.5)
        if sampler is not None:
            hit = sampler.sample(x, y)
            if hit is None:
                continue
            z, normal = hit
            if normal.z < slope_limit:
                continue
        else:
            z, normal = 0.0, Vector((0.0, 0.0, 1.0))
        point = Vector((x, y, z))
        if any((point - other).length < min_spacing for other in placed):
            continue
        placed.append(point)

        copy = scene_lib.duplicate(src, f"{src.name}_s{len(placed)}")
        copy.location = point
        yaw = rng.uniform(0.0, math.tau)
        tilt = Vector((0.0, 0.0, 1.0)).lerp(normal, max(0.0, min(1.0, align_to_normal)))
        rotation = tilt.normalized().to_track_quat("Z", "Y").to_euler()
        copy.rotation_euler = (rotation.x, rotation.y, yaw)
        factor = rng.uniform(scale_range[0], scale_range[1])
        copy.scale = (factor, factor, factor)
        scene_lib.apply_transforms(copy)
        made.append(copy)

    if not made:
        raise OpError(
            f"placed 0 of {count} instances after {attempts} attempts. "
            f"Reduce min_spacing (now {min_spacing} m), widen the area, or raise max_slope."
        )
    if len(made) < count:
        ctx.note(
            f"Placed {len(made)} of {count} requested — min_spacing={min_spacing} m saturates "
            f"this area. Lower it or enlarge the area for a denser result."
        )

    if join:
        merged = scene_lib.join(made, scene_lib.sanitize(name or f"{src.name}_scatter"))
        scene_lib.apply_transforms(merged)
        result = finish_lib.report(ctx, merged)
        result["instances"] = len(made)
        if result["triangles"] > 60000:
            ctx.note(
                f"{result['triangles']} triangles in one scatter mesh. Consider a lower-poly "
                "source, fewer instances, or engine-side instancing instead of a merged mesh."
            )
        return result
    return {"objects": [o.name for o in made], "instances": len(made)}


class _SurfaceSampler:
    """Cheap vertical raycast against a mesh's evaluated triangles."""

    def __init__(self, obj):
        self.obj = obj
        self.matrix = obj.matrix_world
        corners = [self.matrix @ Vector(c) for c in obj.bound_box]
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        self.span = (max(xs) - min(xs), max(ys) - min(ys))
        self.top = max(c.z for c in corners) + 1.0

    def sample(self, x, y):
        origin = Vector((x, y, self.top))
        direction = Vector((0.0, 0.0, -1.0))
        local_origin = self.matrix.inverted() @ origin
        local_dir = (self.matrix.inverted().to_3x3() @ direction).normalized()
        hit, location, normal, _index = self.obj.ray_cast(local_origin, local_dir)
        if not hit:
            return None
        world = self.matrix @ location
        world_normal = (self.matrix.to_3x3() @ normal).normalized()
        return world.z, world_normal


@op(
    "env.cliff",
    summary="Rock cliff wall or canyon face with stratified layers. Blocks sightlines and frames a play space without the cost of terrain.",
    params={
        "name": ("str", "cliff", "Object name"),
        "length": ("num", 20.0, "Length along X in metres"),
        "height": ("num", 8.0, "Height in metres"),
        "depth": ("num", 3.0, "Depth variation in metres"),
        "segments": ("int", 20, "Horizontal segments"),
        "layers": ("int", 6, "Vertical strata"),
        "strata": ("num", 0.35, "How pronounced the rock layering is"),
        "seed": ("int", 0, "Random seed"),
        "material": ("str", "rock", "Material preset"),
        "color": ("str", "", "Override colour"),
        "uv_scale": ("num", 3.0, "Metres per UV tile"),
    },
    tags=["env", "nature"],
)
def env_cliff(ctx, name, length, height, depth, segments, layers, strata, seed, material, color,
              uv_scale):
    rng = ctx.reseed(seed)
    segments = max(3, segments)
    layers = max(2, layers)
    bm = mesh_lib.new_bmesh()
    grid = []
    for iy in range(layers + 1):
        t = iy / layers
        row = []
        for ix in range(segments + 1):
            u = ix / segments
            x = (u - 0.5) * length
            base = _fbm(u * 5.0, t * 3.0, seed, 3) * depth
            ledge = math.sin(t * math.pi * layers) * strata * depth * 0.5
            y = base + ledge + rng.uniform(-0.05, 0.05) * depth
            z = t * height
            row.append(bm.verts.new((x, y, z)))
        grid.append(row)
    for iy in range(layers):
        for ix in range(segments):
            bm.faces.new(
                (grid[iy][ix], grid[iy][ix + 1], grid[iy + 1][ix + 1], grid[iy + 1][ix])
            )
    # Give it thickness so it is a solid, not a one-sided sheet the player can see through.
    bmesh.ops.solidify(bm, geom=bm.faces[:], thickness=max(0.4, depth * 0.35))
    mesh_lib.cleanup(bm)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="box", uv_scale=uv_scale,
        origin="bottom", smooth=True, smooth_angle=45.0,
    )
    finish_lib.budget_note(ctx, obj, segments * layers * 8)
    return result


@op(
    "env.water",
    summary="Water plane with a gentle wave mesh and a translucent material. Fills moats, lakes and canals.",
    params={
        "name": ("str", "water", "Object name"),
        "size": ("vec2", [30.0, 30.0], "Extents in metres"),
        "resolution": ("int", 16, "Grid subdivisions"),
        "wave_height": ("num", 0.08, "Wave amplitude in metres"),
        "level": ("num", 0.0, "Z height of the water surface"),
        "color": ("str", "#20465e", "Water colour"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["env", "nature"],
)
def env_water(ctx, name, size, resolution, wave_height, level, color, seed):
    ctx.reseed(seed)
    resolution = max(2, min(200, resolution))
    bm = mesh_lib.new_bmesh()
    grid = []
    for iy in range(resolution + 1):
        row = []
        for ix in range(resolution + 1):
            x = (ix / resolution - 0.5) * size[0]
            y = (iy / resolution - 0.5) * size[1]
            z = level + _fbm(x * 0.35, y * 0.35, seed, 2) * wave_height
            row.append(bm.verts.new((x, y, z)))
        grid.append(row)
    for iy in range(resolution):
        for ix in range(resolution):
            bm.faces.new(
                (grid[iy][ix], grid[iy][ix + 1], grid[iy + 1][ix + 1], grid[iy + 1][ix])
            )
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    water = mat_lib.principled(
        f"m_{obj.name}", color=color, roughness=0.06, metallic=0.0, alpha=0.72, ior=1.33
    )
    result = finish_lib.finish(
        ctx, obj, material=water, uv="box", uv_scale=6.0, origin=None, smooth=True,
        smooth_angle=80.0,
    )
    ctx.note(
        "Water uses alpha blending. In Godot set the material's transparency mode and "
        "disable shadow casting, or it will render as an opaque slab."
    )
    return result


@op(
    "env.road",
    summary="Road, path or river bed following a polyline, conformed to a terrain surface if given.",
    params={
        "name": ("str", "road", "Object name"),
        "points": ("num[]", [-15.0, 0.0, 0.0, 0.0, 15.0, 6.0], "Flat [x0,y0, x1,y1, ...] control points"),
        "width": ("num", 3.0, "Road width in metres"),
        "target": ("str", "", "Terrain to drape onto (empty = flat at Z=0)"),
        "offset": ("num", 0.06, "Height above the surface, to avoid z-fighting"),
        "segments_per_span": ("int", 8, "Subdivisions between control points"),
        "material": ("str", "stone", "Material preset"),
        "color": ("str", "", "Override colour"),
        "uv_scale": ("num", 3.0, "Metres per UV tile"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["env"],
)
def env_road(ctx, name, points, width, target, offset, segments_per_span, material, color,
             uv_scale, seed):
    ctx.reseed(seed)
    if len(points) < 4 or len(points) % 2 != 0:
        raise OpError(
            "points must be an even-length list of at least 2 (x, y) pairs, "
            "e.g. [-10,0, 0,2, 10,0]"
        )
    control = [(points[i], points[i + 1]) for i in range(0, len(points), 2)]
    surface = _get(target) if target else None
    sampler = _SurfaceSampler(surface) if surface is not None else None

    centre = []
    for index in range(len(control) - 1):
        x0, y0 = control[index]
        x1, y1 = control[index + 1]
        steps = max(1, segments_per_span)
        for step in range(steps + (1 if index == len(control) - 2 else 0)):
            t = step / steps
            centre.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))

    bm = mesh_lib.new_bmesh()
    left, right = [], []
    for index, (x, y) in enumerate(centre):
        nxt = centre[min(index + 1, len(centre) - 1)]
        prv = centre[max(index - 1, 0)]
        tangent = Vector((nxt[0] - prv[0], nxt[1] - prv[1], 0.0))
        if tangent.length < 1e-6:
            tangent = Vector((1.0, 0.0, 0.0))
        normal = Vector((-tangent.y, tangent.x, 0.0)).normalized() * (width * 0.5)
        z = 0.0
        if sampler is not None:
            hit = sampler.sample(x, y)
            if hit is not None:
                z = hit[0]
        left.append(bm.verts.new((x - normal.x, y - normal.y, z + offset)))
        right.append(bm.verts.new((x + normal.x, y + normal.y, z + offset)))
    for index in range(len(centre) - 1):
        bm.faces.new((left[index], right[index], right[index + 1], left[index + 1]))

    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="box", uv_scale=uv_scale,
        origin=None, smooth=False,
    )
    result["length_m"] = round(
        sum(math.dist(centre[i], centre[i + 1]) for i in range(len(centre) - 1)), 3
    )
    return result


@op(
    "env.arena",
    summary="Complete combat arena in one call: floor, tiered walls, entrance arches and corner towers. A whole playable space from a single op.",
    params={
        "name": ("str", "arena", "Object name"),
        "radius": ("num", 16.0, "Arena floor radius in metres"),
        "wall_height": ("num", 6.0, "Perimeter wall height"),
        "sides": ("int", 16, "Perimeter segments (higher is rounder)"),
        "entrances": ("int", 2, "Number of gate openings"),
        "tiers": ("int", 2, "Spectator tiers stepping up behind the wall"),
        "material": ("str", "stone", "Material preset"),
        "color": ("str", "", "Override colour"),
        "uv_scale": ("num", 3.0, "Metres per UV tile"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["env", "architecture"],
)
def env_arena(ctx, name, radius, wall_height, sides, entrances, tiers, material, color, uv_scale,
              seed):
    ctx.reseed(seed)
    sides = max(6, sides)
    bm = mesh_lib.new_bmesh()

    mesh_lib.add_cylinder(bm, radius=radius, depth=0.4, segments=sides, center=(0, 0, -0.2))

    gate_slots = set()
    if entrances > 0:
        stride = max(1, sides // entrances)
        gate_slots = {(index * stride) % sides for index in range(entrances)}

    for index in range(sides):
        if index in gate_slots:
            continue
        angle = math.tau * (index + 0.5) / sides
        segment_width = 2.0 * math.pi * radius / sides * 1.06
        panel = mesh_lib.new_bmesh()
        mesh_lib.add_box(panel, size=(segment_width, 0.7, wall_height),
                         center=(0, 0, wall_height * 0.5), bevel=0.04)
        matrix = (
            Matrix.Translation((math.cos(angle) * radius, math.sin(angle) * radius, 0.0))
            @ Matrix.Rotation(angle + math.pi * 0.5, 4, "Z")
        )
        bmesh.ops.transform(panel, matrix=matrix, verts=panel.verts[:])
        _absorb(bm, panel)

    # Tiers are RINGS, built the same way as the wall panels. Building them from
    # concentric cylinders instead produces a solid disc that lids the arena over
    # — it renders as a cake, not a colosseum.
    tier_depth = 1.8
    for tier in range(max(0, tiers)):
        tier_radius = radius + 1.2 + tier * tier_depth
        tier_z = wall_height * 0.55 + tier * 1.0
        segment_width = 2.0 * math.pi * tier_radius / sides * 1.06
        for index in range(sides):
            angle = math.tau * (index + 0.5) / sides
            seat = mesh_lib.new_bmesh()
            mesh_lib.add_box(seat, size=(segment_width, tier_depth, 1.0),
                             center=(0, 0, 0.5), bevel=0.03)
            matrix = (
                Matrix.Translation(
                    (math.cos(angle) * tier_radius, math.sin(angle) * tier_radius, tier_z)
                )
                @ Matrix.Rotation(angle + math.pi * 0.5, 4, "Z")
            )
            bmesh.ops.transform(seat, matrix=matrix, verts=seat.verts[:])
            _absorb(bm, seat)

    mesh_lib.cleanup(bm, merge_dist=1e-4)
    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))
    result = finish_lib.finish(
        ctx, obj, material=material, color=color or None, uv="box", uv_scale=uv_scale,
        origin="world", smooth=False,
    )
    result["playable_radius_m"] = radius
    result["entrances"] = len(gate_slots)
    ctx.note(
        f"Arena floor radius is {radius} m with {len(gate_slots)} gates. Run "
        "gameready.collision mode='simplified' before shipping — the tiers make a convex "
        "hull useless here."
    )
    finish_lib.budget_note(ctx, obj, 12000)
    return result


def _absorb(target_bm, source_bm):
    import bpy

    temp = bpy.data.meshes.new("_absorb")
    source_bm.to_mesh(temp)
    source_bm.free()
    target_bm.from_mesh(temp)
    bpy.data.meshes.remove(temp)


def _get(name):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
