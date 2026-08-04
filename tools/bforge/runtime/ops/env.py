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


@op(
    "env.amphitheatre",
    summary="A complete Roman venue in one call: raked cavea, podium, arched arcade storey, statued attic colonnade, vomitoria stair wedges, velarium masts, hanging banners and gateways. This is the difference between a stone bowl and the Colosseum — arches and vertical rhythm. Use shape='oval' for a circus/hippodrome, 'circle' for an amphitheatre.",
    params={
        "name": ("str", "amphitheatre", "Object name"),
        "shape": ("enum:oval|circle", "circle", "oval = circus/hippodrome, circle = amphitheatre"),
        "arena_radius": ("num", 40.0, "Arena half-width in metres (short axis)"),
        "straight": ("num", 0.0, "oval only: length of each straight in metres"),
        "arena_margin": ("num", 6.0, "Flat run-off between the arena edge and the podium wall"),
        "podium_height": ("num", 4.0, "Height of the solid wall between arena and first seats"),
        "tiers": ("int", 3, "Seating tiers (maenianum), separated by walkway walls"),
        "tier_depth": ("num", 9.0, "Depth of each tier in metres"),
        "tier_rise": ("num", 5.4, "Height gained across each tier"),
        "tier_riser": ("num", 2.4, "Walkway wall height between tiers"),
        "rows_per_tier": ("int", 7, "Seat steps cut per tier"),
        "arcade_height": ("num", 9.5, "Height of the arched storey crowning the stands; 0 for none"),
        "arcade_bays": ("int", 0, "Arch count; 0 auto-sizes to roughly one arch per 8 m"),
        "colonnade": ("bool", True, "Statued attic colonnade above the arcade"),
        "vomitoria": ("int", 0, "Stair wedges dividing the seating; 0 auto-sizes"),
        "masts": ("int", 0, "Velarium masts on the rim; 0 auto-sizes, -1 for none"),
        "gateways": ("int", 2, "Monumental arched gates cut through the podium"),
        "banners": ("int", 0, "Hanging banners between arcade bays; 0 auto-sizes"),
        "stone": ("str", "#d6c4a0", "Sunlit stone colour (travertine, not concrete)"),
        "stone_shade": ("str", "#9c8763", "Shadowed stone colour"),
        "sand": ("str", "#d9bd8e", "Arena floor colour"),
        "banner_color": ("str", "#7a201a", "Banner cloth colour"),
        "quality": ("enum:low|medium|high", "medium", "Path and detail resolution"),
        "join": ("bool", True, "Merge into one object"),
        "seed": ("int", 0, "Random seed"),
    },
    tags=["env", "architecture"],
)
def env_amphitheatre(ctx, name, shape, arena_radius, straight, arena_margin, podium_height,
                     tiers, tier_depth, tier_rise, tier_riser, rows_per_tier, arcade_height,
                     arcade_bays, colonnade, vomitoria, masts, gateways, banners, stone,
                     stone_shade, sand, banner_color, quality, join, seed):
    from .arch import arch_arcade, arch_colonnade, arch_gateway

    ctx.reseed(seed)
    segments = {"low": 14, "medium": 24, "high": 40}[quality]
    straight = max(0.0, straight) if shape == "oval" else 0.0
    podium_r = arena_radius + arena_margin
    stand_depth = tiers * tier_depth
    back_r = podium_r + stand_depth
    stand_top = podium_height + tiers * (tier_rise + tier_riser)
    perimeter = 2.0 * straight + 2.0 * math.pi * back_r

    if arcade_bays <= 0:
        arcade_bays = max(8, int(perimeter / 8.0))
    if vomitoria <= 0:
        vomitoria = max(6, int(perimeter / 34.0))
    if masts == 0:
        masts = max(8, int(perimeter / 16.0))
    if banners <= 0:
        banners = max(4, arcade_bays // 4)

    def oval(extra=0.0):
        return dict(path_shape="oval" if shape == "oval" else "circle",
                    straight=straight, radius=arena_radius + extra)

    parts = []

    # --- arena floor -----------------------------------------------------
    floor = mesh_lib.new_bmesh()
    if shape == "oval":
        mesh_lib.sweep(
            floor,
            mesh_lib.oval_path(straight, arena_radius * 0.5, segments),
            [(-arena_radius * 0.5 - arena_margin, -0.3),
             (arena_radius * 0.5 + arena_margin, -0.3),
             (arena_radius * 0.5 + arena_margin, 0.0),
             (-arena_radius * 0.5 - arena_margin, 0.0)],
            closed_path=True,
        )
    else:
        mesh_lib.add_cylinder(floor, radius=podium_r, depth=0.6, segments=segments * 2,
                              center=(0.0, 0.0, -0.3))
    mesh_lib.cleanup(floor)
    sand_obj = mesh_lib.to_object(floor, scene_lib.unique_name(f"{name}_sand"))
    finish_lib.finish(ctx, sand_obj, material="sand", color=sand, uv="box", uv_scale=10.0,
                      origin="world", smooth=False)
    parts.append(sand_obj.name)

    # --- cavea: podium wall then stepped seating -------------------------
    profile = [(podium_r, 0.0), (podium_r, podium_height)]
    lateral, vertical = podium_r, podium_height
    rows = max(1, rows_per_tier)
    for _tier in range(max(1, tiers)):
        vertical += tier_riser
        profile.append((lateral, vertical))
        for _row in range(rows):
            lateral += tier_depth / rows
            profile.append((lateral, vertical))
            vertical += tier_rise / rows
            profile.append((lateral, vertical))
    profile.append((lateral, vertical + 1.2))
    profile.append((lateral + 3.0, vertical + 1.2))
    profile.append((lateral + 3.0, 0.0))

    cavea = mesh_lib.new_bmesh()
    path = (
        mesh_lib.oval_path(straight, arena_radius, segments)
        if shape == "oval"
        else [
            (math.cos(2 * math.pi * i / (segments * 2)) * arena_radius,
             math.sin(2 * math.pi * i / (segments * 2)) * arena_radius, 0.0)
            for i in range(segments * 2)
        ]
    )
    # Profile laterals are absolute radii; the sweep wants them relative.
    mesh_lib.sweep(
        cavea, path,
        [(lat - arena_radius, vert) for lat, vert in profile],
        closed_path=True,
    )
    mesh_lib.cleanup(cavea)
    cavea_obj = mesh_lib.to_object(cavea, scene_lib.unique_name(f"{name}_cavea"))
    finish_lib.finish(ctx, cavea_obj, material="stone", color=stone, uv="box", uv_scale=4.0,
                      origin="world", smooth=False)
    parts.append(cavea_obj.name)

    # --- the Roman elevation --------------------------------------------
    if arcade_height > 0.0:
        arch_arcade(
            ctx, name=f"{name}_arcade", path=[], **oval(back_r - arena_radius),
            length=0.0, arc_degrees=180.0, resolution=segments * 2, bays=arcade_bays,
            height=arcade_height, thickness=2.4, opening=0.60, arch_rise=0.0,
            springing=0.44, voussoirs=7, plinth=0.7, cornice=0.9, cornice_jut=0.35,
            engaged_columns=True, material="stone", color=stone, uv_scale=3.0, z=stand_top,
        )
        parts.append(f"{name}_arcade")
    if colonnade:
        arch_colonnade(
            ctx, name=f"{name}_attic", path=[], **oval(back_r - arena_radius - 0.6),
            length=0.0, arc_degrees=180.0, resolution=segments * 2, columns=arcade_bays,
            height=5.2, column_radius=0.46, segments=8, entablature=1.1, flutes=False,
            statues=True, material="stone", color=stone_shade, uv_scale=3.0,
            z=stand_top + arcade_height,
        )
        parts.append(f"{name}_attic")

    # Vomitoria are stair wedges that FOLLOW the seating rake. Building them as
    # upright slabs centred on the arena edge walls the bowl off completely —
    # they must be swept along the same profile as the cavea, raised a step, and
    # kept narrow.
    seat_profile = [(lat - arena_radius, vert + 0.75) for lat, vert in profile[:-3]]
    total_path = len(path)
    for index in range(max(1, vomitoria)):
        centre = total_path * index / max(1, vomitoria)
        lo = int(math.floor(centre)) % total_path
        hi = (lo + 1) % total_path
        nxt = (lo + 2) % total_path
        wedge = mesh_lib.new_bmesh()
        mesh_lib.sweep(wedge, [path[lo], path[hi], path[nxt]], seat_profile,
                       closed_path=False, closed_profile=False, cap_ends=False)
        obj = mesh_lib.to_object(wedge, scene_lib.unique_name(f"{name}_vom{index}"))
        finish_lib.finish(ctx, obj, material="stone", color=stone_shade, uv="box",
                          uv_scale=3.0, origin=None, smooth=False)
        parts.append(obj.name)

    if masts > 0:
        rim = mesh_lib.sample_path(path, masts, closed=True)
        for index, (position, _t, normal) in enumerate(rim):
            at = position + normal * (back_r - arena_radius + 1.4)
            mast = mesh_lib.new_bmesh()
            mesh_lib.add_cylinder(mast, radius=0.28, radius_top=0.16, depth=11.0,
                                  segments=6, center=(0.0, 0.0, 5.5))
            obj = mesh_lib.to_object(mast, scene_lib.unique_name(f"{name}_mast{index}"))
            obj.location = (at.x, at.y, stand_top + arcade_height + (5.2 if colonnade else 0.0))
            finish_lib.finish(ctx, obj, material="wood", color="#6b5335", uv="cylinder",
                              origin=None, smooth=False)
            parts.append(obj.name)

    if banners > 0 and arcade_height > 0.0:
        hang = mesh_lib.sample_path(path, banners, closed=True)
        for index, (position, tangent, normal) in enumerate(hang):
            at = position + normal * (back_r - arena_radius - 1.3)
            cloth = mesh_lib.new_bmesh()
            mesh_lib.sweep(
                cloth,
                [(0.0, 0.0, 0.0), (0.0, 0.12, -arcade_height * 0.72),
                 (0.0, 0.05, -arcade_height * 0.95)],
                [(-1.1, -0.06), (1.1, -0.06), (1.1, 0.06), (-1.1, 0.06)],
            )
            obj = mesh_lib.to_object(cloth, scene_lib.unique_name(f"{name}_banner{index}"))
            obj.location = (at.x, at.y, stand_top + arcade_height * 0.94)
            obj.rotation_euler = (
                0.0, 0.0, math.atan2(tangent.y, tangent.x)
            )
            finish_lib.finish(ctx, obj, material="cloth", color=banner_color, uv="box",
                              uv_scale=2.0, origin=None, smooth=False)
            parts.append(obj.name)

    for index in range(max(0, gateways)):
        angle = math.pi * index + math.pi * 0.5 if gateways == 2 else 2 * math.pi * index / max(1, gateways)
        gx = math.cos(angle) * (podium_r + 1.0)
        gy = math.sin(angle) * (podium_r + 1.0)
        if shape == "oval":
            gx = (straight * 0.5 + arena_radius) * (1 if index % 2 == 0 else -1)
            gy = 0.0
        arch_gateway(
            ctx, name=f"{name}_gate{index}", width=15.0, height=17.0, thickness=3.2,
            side_arches=True, attic=4.0, voussoirs=9,
            location=[gx, gy, 0.0],
            rotation=math.degrees(math.atan2(gy, gx)) + 90.0,
            material="stone", color=stone, uv_scale=3.0,
        )
        parts.append(f"{name}_gate{index}")

    from .material import material_consolidate

    material_consolidate(ctx, tolerance=0.02, objects=[], dry_run=False)

    if not join:
        return {"objects": parts, "count": len(parts), "stand_top_m": round(stand_top, 2)}

    try:
        merged = scene_lib.join([scene_lib.get_object(p) for p in parts],
                                scene_lib.sanitize(name))
    except ValueError as exc:
        raise OpError(str(exc)) from exc
    scene_lib.set_origin(merged, "world")
    scene_lib.apply_transforms(merged)
    result = finish_lib.report(ctx, merged)
    result.update({
        "arena_radius_m": arena_radius,
        "podium_radius_m": round(podium_r, 2),
        "stand_back_m": round(back_r, 2),
        "stand_top_m": round(stand_top, 2),
        "total_height_m": round(stand_top + arcade_height + (5.2 if colonnade else 0.0), 2),
        "arcade_bays": arcade_bays,
        "vomitoria": vomitoria,
        "masts": masts,
    })
    ctx.note(
        f"Seating surface runs {podium_r:.1f} m to {back_r:.1f} m out, {podium_height:.1f} m "
        f"to {stand_top:.1f} m high. Seat a crowd on exactly that band or it will float."
    )
    finish_lib.budget_note(ctx, merged, 45000)
    return result


def _absorb(target_bm, source_bm):
    import bpy

    temp = bpy.data.meshes.new("_absorb")
    source_bm.to_mesh(temp)
    source_bm.free()
    target_bm.from_mesh(temp)
    bpy.data.meshes.remove(temp)


def _absorb(target_bm, source_bm):
    import bpy

    temp = bpy.data.meshes.new("_absorb")
    source_bm.to_mesh(temp)
    source_bm.free()
    target_bm.from_mesh(temp)
    bpy.data.meshes.remove(temp)


@op(
    "env.camp",
    summary="A complete Age-1 settlement in one call: central fire (stones, log teepee, live embers), A-frame shelters ringing it, a stockade perimeter with a gate opening, a well, and storage racks on a deterministic seeded layout. The homeland diorama, not a bag of props — the layout relationships (fire at the heart, shelters facing it, one way in) are what makes it read as a camp instead of a yard sale.",
    params={
        "name": ("str", "camp", "Object-name prefix for the camp's structures"),
        "radius": ("num", 8.0, "Palisade ring radius in metres; shelters sit at ~55% of it"),
        "shelters": ("int", 5, "A-frame shelters around the fire"),
        "palisade": ("bool", True, "Build the sharpened-log perimeter"),
        "gate_angle": ("num", 90.0, "Compass degrees the gate opening faces (0 = +X, 90 = +Y). The ONE way in — put it toward where threats should come from"),
        "well": ("bool", True, "Stone well with windlass frame"),
        "racks": ("int", 1, "Storage racks with sacks (0-3)"),
        "ground": ("bool", True, "Flatten a dirt disc under the camp — helps dioramas; skip when the game supplies terrain"),
        "wood_color": ("colorref", "", "Override the timber family colour"),
        "cloth_color": ("colorref", "", "Override the hide/cloth family colour"),
        "seed": ("int", 0, "Layout seed — same seed, same camp, forever"),
    },
    tags=["env", "architecture"],
)
def env_camp(ctx, name, radius, shelters, palisade, gate_angle, well, racks, ground,
             wood_color, cloth_color, seed):
    rng = ctx.reseed(seed)
    made = []

    def finish_part(bm, part, preset, color=None, rough=-1.0, smooth=True):
        mesh_lib.cleanup(bm, merge_dist=1e-4)
        obj = mesh_lib.to_object(bm, scene_lib.unique_name(f"{name}_{part}"))
        mat = mat_lib.from_preset(preset, color=color or None,
                                  roughness=rough if rough >= 0 else None)
        result = finish_lib.finish(
            ctx, obj, material=mat, uv="smart_packed", origin="bottom",
            smooth=smooth, smooth_angle=45.0,
        )
        made.append({"object": obj.name, "part": part, "triangles": result["triangles"]})
        return obj

    def cyl(bm, radius, depth, center, tip=False, segments=10, axis="Z", yaw=0.0, pitch=0.0):
        piece = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(
            piece, radius=radius, radius_top=0.0 if tip else -1.0, depth=depth,
            segments=segments, center=(0.0, 0.0, 0.0),
        )
        matrix = (
            Matrix.Translation(Vector(center))
            @ Matrix.Rotation(math.radians(yaw), 4, "Z")
            @ Matrix.Rotation(math.radians(pitch), 4, "Y")
        )
        bmesh.ops.transform(piece, matrix=matrix, verts=piece.verts[:])
        _absorb(bm, piece)

    wood = wood_color or "#6a4e2c"
    cloth = cloth_color or "#7a5a38"

    # --- the fire at the heart ------------------------------------------------
    stones = mesh_lib.new_bmesh()
    for i in range(8):
        angle = math.tau * i / 8.0
        rock = mesh_lib.new_bmesh()
        mesh_lib.add_icosphere(rock, radius=0.13, subdivisions=1)
        bmesh.ops.transform(
            rock,
            matrix=Matrix.Translation(
                Vector((0.45 * math.cos(angle), 0.45 * math.sin(angle), 0.09))
            ) @ Matrix.Diagonal(Vector((1.0, 0.9, 0.75))).to_4x4(),
            verts=rock.verts[:],
        )
        _absorb(stones, rock)
    finish_part(stones, "fire_stones", "stone")

    logs = mesh_lib.new_bmesh()
    for i in range(3):
        cyl(logs, 0.045, 0.7, (0.0, 0.0, 0.28), segments=8, yaw=i * 120.0, pitch=62.0)
    finish_part(logs, "fire_logs", "wood", wood)

    coals_bm = mesh_lib.new_bmesh()
    cyl(coals_bm, 0.26, 0.1, (0.0, 0.0, 0.05), segments=12)
    coals = mesh_lib.to_object(coals_bm, scene_lib.unique_name(f"{name}_embers"))
    embers = mat_lib.principled("m_camp_embers", color="#ff5a14", roughness=0.9,
                                emission=4.5, emission_color="#ff6a1a")
    finish_lib.finish(ctx, coals, material=embers, uv="smart_packed", origin="bottom",
                      smooth=True, smooth_angle=45.0)
    made.append({"object": coals.name, "part": "embers", "triangles": mesh_lib.tri_count(coals)})

    # --- shelters ringing the fire, facing it ----------------------------------
    for i in range(max(0, shelters)):
        base_angle = math.tau * i / max(1, shelters) + rng.uniform(-0.14, 0.14)
        dist = radius * (0.55 + rng.uniform(-0.05, 0.05))
        cx, cy = dist * math.cos(base_angle), dist * math.sin(base_angle)
        scale = rng.uniform(0.9, 1.1)
        yaw_deg = math.degrees(base_angle) + 90.0  # open side toward the fire

        frame = mesh_lib.new_bmesh()
        ridge = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(ridge, radius=0.035, depth=2.4 * scale, segments=8,
                              center=(0.0, 0.0, 1.55 * scale))
        bmesh.ops.transform(
            ridge, matrix=Matrix.Translation(Vector((cx, cy, 0.0)))
            @ Matrix.Rotation(math.radians(yaw_deg), 4, "Z")
            @ Matrix.Rotation(math.radians(90.0), 4, "Y"),
            verts=ridge.verts[:],
        )
        _absorb(frame, ridge)
        for end in (-1, 1):
            pole = mesh_lib.new_bmesh()
            mesh_lib.add_cylinder(pole, radius=0.035, depth=1.6 * scale, segments=8,
                                  center=(end * 1.1 * scale, 0.0, 0.8 * scale))
            bmesh.ops.transform(
                pole, matrix=Matrix.Translation(Vector((cx, cy, 0.0)))
                @ Matrix.Rotation(math.radians(yaw_deg), 4, "Z"),
                verts=pole.verts[:],
            )
            _absorb(frame, pole)
        finish_part(frame, f"shelter_{i}_frame", "wood", wood)

        hide = mesh_lib.new_bmesh()
        for side, pitch in ((-1, 58.0), (1, -58.0)):
            panel = mesh_lib.new_bmesh()
            mesh_lib.add_box(panel, size=(2.3 * scale, 0.05, 1.9 * scale),
                             center=(0.0, side * 0.72 * scale, 0.82 * scale), bevel=0.01)
            bmesh.ops.transform(
                panel,
                matrix=Matrix.Translation(Vector((cx, cy, 0.0)))
                @ Matrix.Rotation(math.radians(yaw_deg), 4, "Z")
                @ Matrix.Rotation(math.radians(pitch), 4, "X"),
                verts=panel.verts[:],
            )
            _absorb(hide, panel)
        finish_part(hide, f"shelter_{i}_hide", "cloth", cloth, rough=0.9)

    # --- stockade with exactly one way in ---------------------------------------
    if palisade:
        ring = mesh_lib.new_bmesh()
        spacing = 0.23
        gate_half = math.radians(11.0)  # ~3 m opening at radius 8
        count = int(math.tau * radius / spacing)
        for i in range(count):
            angle = math.tau * i / count
            gate_delta = (math.degrees(angle) - gate_angle + 540.0) % 360.0 - 180.0
            if abs(gate_delta) < math.degrees(gate_half):
                continue
            depth = 2.4 if i % 2 == 0 else 2.55
            px, py = radius * math.cos(angle), radius * math.sin(angle)
            cyl(ring, 0.09, depth, (px, py, depth * 0.5), tip=True, segments=10)
        for edge in (-1, 1):
            angle = math.radians(gate_angle) + edge * gate_half
            px, py = radius * math.cos(angle), radius * math.sin(angle)
            cyl(ring, 0.13, 2.8, (px, py, 1.4), tip=True, segments=12)
        finish_part(ring, "palisade", "wood", wood, smooth=False)

    # --- the well ----------------------------------------------------------------
    if well:
        wangle = rng.uniform(0.0, math.tau)
        wx, wy = radius * 0.3 * math.cos(wangle), radius * 0.3 * math.sin(wangle)
        ring_bm = mesh_lib.new_bmesh()
        for row in range(2):
            for i in range(9):
                angle = math.tau * i / 9.0 + row * 0.35
                rock = mesh_lib.new_bmesh()
                mesh_lib.add_icosphere(rock, radius=0.15, subdivisions=1)
                bmesh.ops.transform(
                    rock,
                    matrix=Matrix.Translation(Vector((
                        wx + 0.62 * math.cos(angle),
                        wy + 0.62 * math.sin(angle),
                        0.14 + row * 0.24,
                    ))) @ Matrix.Diagonal(Vector((1.0, 0.9, 0.8))).to_4x4(),
                    verts=rock.verts[:],
                )
                _absorb(ring_bm, rock)
        finish_part(ring_bm, "well_stones", "stone")
        wood_bm = mesh_lib.new_bmesh()
        for side in (-1, 1):
            cyl(wood_bm, 0.05, 1.3, (wx + side * 0.62, wy, 0.65), segments=8)
        bar = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(bar, radius=0.045, depth=1.34, segments=8,
                              center=(0.0, 0.0, 0.0))
        bmesh.ops.transform(
            bar,
            matrix=Matrix.Translation(Vector((wx, wy, 1.28)))
            @ Matrix.Rotation(math.radians(90.0), 4, "Y"),
            verts=bar.verts[:],
        )
        _absorb(wood_bm, bar)
        finish_part(wood_bm, "well_frame", "wood", wood)

    # --- storage racks -------------------------------------------------------------
    for r in range(max(0, min(3, racks))):
        rangle = gate_angle + 140.0 + r * 80.0 + rng.uniform(-10.0, 10.0)
        rr = radius * 0.4
        rx, ry = rr * math.cos(math.radians(rangle)), rr * math.sin(math.radians(rangle))
        frame = mesh_lib.new_bmesh()
        for side in (-1, 1):
            for depth in (1.1,):
                cyl(frame, 0.04, depth, (rx + side * 0.6, ry, depth * 0.5), segments=8)
        shelf = mesh_lib.new_bmesh()
        mesh_lib.add_box(shelf, size=(1.4, 0.5, 0.06), center=(rx, ry, 0.72), bevel=0.01)
        _absorb(frame, shelf)
        finish_part(frame, f"rack_{r}_frame", "wood", wood)
        sacks = mesh_lib.new_bmesh()
        for s in range(2):
            sack = mesh_lib.new_bmesh()
            mesh_lib.add_icosphere(sack, radius=0.22, subdivisions=2)
            bmesh.ops.transform(
                sack,
                matrix=Matrix.Translation(
                    Vector((rx - 0.3 + s * 0.6, ry, 0.95 if s == 0 else 0.2))
                ) @ Matrix.Diagonal(Vector((1.0, 0.85, 1.15))).to_4x4(),
                verts=sack.verts[:],
            )
            _absorb(sacks, sack)
        finish_part(sacks, f"rack_{r}_sacks", "cloth", cloth, rough=0.9)

    # --- ground --------------------------------------------------------------------)
    if ground:
        disc = mesh_lib.new_bmesh()
        mesh_lib.add_cylinder(disc, radius=radius + 2.0, depth=0.2, segments=32,
                              center=(0.0, 0.0, -0.1))
        finish_part(disc, "ground", "sand", "#8a7350", rough=1.0, smooth=False)

    total = sum(entry["triangles"] for entry in made)
    ctx.note(
        f"Camp layout: fire at the heart, {shelters} shelters facing it, gate at "
        f"{gate_angle:.0f} degrees. Dress the surroundings with env.scatter "
        "(trees/rocks) and put a watch at the gate — it is the only way in."
    )
    return {
        "structures": made,
        "object_count": len(made),
        "triangles": total,
        "gate_angle": gate_angle,
        "radius": radius,
    }


def _get(name):
    try:
        return scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
