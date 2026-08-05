"""Game-correct mesh construction on top of bmesh.

The design rule here is the one thing that separates a game asset from a render
asset: **every face must earn its triangles**. So these helpers default to
chamfers rather than subdivision, quads rather than n-gons, and closed manifold
shells rather than floating detail. They never call `bpy.ops` for geometry —
`bpy.ops` depends on selection/context state that behaves differently in
background mode, which is exactly the flakiness this toolset exists to avoid.

Everything is deterministic: pass the same params and you get the same mesh,
vertex order included.
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

# ---------------------------------------------------------------------------
# object / bmesh lifecycle
# ---------------------------------------------------------------------------


def new_bmesh() -> bmesh.types.BMesh:
    return bmesh.new()


def to_object(bm, name: str, collection=None, free: bool = True):
    """Realise a bmesh as a scene object. Cleans up degenerate geometry first."""
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    if free:
        bm.free()
    mesh.validate(verbose=False)
    obj = bpy.data.objects.new(name, mesh)
    target = collection or bpy.context.scene.collection
    target.objects.link(obj)
    return obj


def obj_bmesh(obj) -> bmesh.types.BMesh:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    return bm


def write_bmesh(bm, obj, free: bool = True) -> None:
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    if free:
        bm.free()
    obj.data.update()


def geom_of(bm) -> list:
    return bm.verts[:] + bm.edges[:] + bm.faces[:]


# ---------------------------------------------------------------------------
# primitives (all centred on the origin unless `center` says otherwise)
# ---------------------------------------------------------------------------


def add_box(bm, size=(1.0, 1.0, 1.0), center=(0.0, 0.0, 0.0), bevel=0.0, segments=2):
    """Axis-aligned box. `bevel` is an absolute chamfer width in metres.

    A chamfer is the cheapest way to make a hard-surface prop read as solid
    under game lighting: it gives the silhouette a highlight edge for ~8 extra
    triangles per corner, where a subdivision would cost hundreds.
    """
    before = set(bm.faces)
    result = bmesh.ops.create_cube(bm, size=1.0)
    verts = result["verts"]
    scale = Matrix.Diagonal(Vector(size)).to_4x4()
    bmesh.ops.transform(bm, matrix=scale, verts=verts)
    bmesh.ops.translate(bm, vec=Vector(center), verts=verts)
    faces = [f for f in bm.faces if f not in before]
    if bevel > 0.0:
        limit = min(size) * 0.49
        # BMesh element sets iterate in hash order, which varies run to run;
        # sort by element index or the op's output order (and the exported
        # index buffer) becomes nondeterministic.
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        edges = {e for f in faces for e in f.edges}
        verts_set = {v for f in faces for v in f.verts}
        bmesh.ops.bevel(
            bm,
            geom=(sorted(verts_set, key=lambda v: v.index)
                  + sorted(edges, key=lambda e: e.index) + faces),
            offset=min(bevel, limit),
            offset_type="OFFSET",
            segments=max(1, segments),
            profile=0.5,
            affect="EDGES",
            clamp_overlap=True,
        )
        # bevel's "faces" output is only the new chamfer strips; callers want the
        # whole region back, including the (now smaller) original faces.
        faces = [f for f in bm.faces if f not in before]
    return faces


def add_cylinder(
    bm,
    radius=0.5,
    depth=1.0,
    segments=16,
    center=(0.0, 0.0, 0.0),
    cap=True,
    radius_top=None,
    bevel=0.0,
):
    before = set(bm.faces)
    top = radius if radius_top is None else radius_top
    bmesh.ops.create_cone(
        bm,
        cap_ends=cap,
        cap_tris=False,
        segments=max(3, segments),
        radius1=radius,
        radius2=top,
        depth=depth,
        matrix=Matrix.Translation(Vector(center)),
    )
    faces = [f for f in bm.faces if f not in before]
    if bevel > 0.0 and cap:
        rim = [
            e
            for f in faces
            for e in f.edges
            if len({round(v.co.z, 5) for v in e.verts}) == 1
        ]
        if rim:
            bmesh.ops.bevel(
                bm,
                geom=list(set(rim)),
                offset=min(bevel, radius * 0.4, depth * 0.4),
                offset_type="OFFSET",
                segments=2,
                profile=0.5,
                affect="EDGES",
                clamp_overlap=True,
            )
            faces = [f for f in bm.faces if f not in before]
    return faces


def add_sphere(bm, radius=0.5, segments=16, rings=8, center=(0.0, 0.0, 0.0)):
    before = set(bm.faces)
    bmesh.ops.create_uvsphere(
        bm,
        u_segments=max(3, segments),
        v_segments=max(2, rings),
        radius=radius,
        matrix=Matrix.Translation(Vector(center)),
    )
    return [f for f in bm.faces if f not in before]


def add_icosphere(bm, radius=0.5, subdivisions=2, center=(0.0, 0.0, 0.0)):
    before = set(bm.faces)
    bmesh.ops.create_icosphere(
        bm,
        subdivisions=max(1, min(5, subdivisions)),
        radius=radius,
        matrix=Matrix.Translation(Vector(center)),
    )
    return [f for f in bm.faces if f not in before]


def add_plane(bm, size=(1.0, 1.0), center=(0.0, 0.0, 0.0), cuts=0):
    before = set(bm.faces)
    half_x, half_y = size[0] * 0.5, size[1] * 0.5
    cx, cy, cz = center
    corners = [
        bm.verts.new((cx - half_x, cy - half_y, cz)),
        bm.verts.new((cx + half_x, cy - half_y, cz)),
        bm.verts.new((cx + half_x, cy + half_y, cz)),
        bm.verts.new((cx - half_x, cy + half_y, cz)),
    ]
    face = bm.faces.new(corners)
    if cuts > 0:
        bmesh.ops.subdivide_edges(bm, edges=face.edges[:], cuts=cuts, use_grid_fill=True)
    return [f for f in bm.faces if f not in before]


def add_prism(bm, radius=0.5, depth=1.0, sides=6, center=(0.0, 0.0, 0.0)):
    return add_cylinder(bm, radius=radius, depth=depth, segments=sides, center=center)


def add_wedge(bm, size=(1.0, 1.0, 1.0), center=(0.0, 0.0, 0.0)):
    """Right-triangle prism — ramps, roof pieces, chamfer blockouts."""
    sx, sy, sz = (v * 0.5 for v in size)
    cx, cy, cz = center
    before = set(bm.faces)
    lower = [
        bm.verts.new((cx - sx, cy - sy, cz - sz)),
        bm.verts.new((cx + sx, cy - sy, cz - sz)),
        bm.verts.new((cx + sx, cy + sy, cz - sz)),
        bm.verts.new((cx - sx, cy + sy, cz - sz)),
    ]
    upper = [
        bm.verts.new((cx - sx, cy - sy, cz + sz)),
        bm.verts.new((cx - sx, cy + sy, cz + sz)),
    ]
    bm.faces.new(lower)
    bm.faces.new([lower[0], lower[1], upper[0]][::-1])
    bm.faces.new([lower[3], upper[1], lower[2]][::-1])
    bm.faces.new([lower[1], lower[2], upper[1], upper[0]])
    bm.faces.new([lower[0], upper[0], upper[1], lower[3]])
    return [f for f in bm.faces if f not in before]


def add_torus(bm, major=0.5, minor=0.12, major_segments=20, minor_segments=8, center=(0, 0, 0)):
    before = set(bm.faces)
    rings = []
    for i in range(major_segments):
        theta = 2.0 * math.pi * i / major_segments
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        ring = []
        for j in range(minor_segments):
            phi = 2.0 * math.pi * j / minor_segments
            r = major + minor * math.cos(phi)
            ring.append(
                bm.verts.new(
                    (
                        center[0] + r * cos_t,
                        center[1] + r * sin_t,
                        center[2] + minor * math.sin(phi),
                    )
                )
            )
        rings.append(ring)
    for i in range(major_segments):
        nxt = rings[(i + 1) % major_segments]
        cur = rings[i]
        for j in range(minor_segments):
            k = (j + 1) % minor_segments
            bm.faces.new((cur[j], cur[k], nxt[k], nxt[j]))
    return [f for f in bm.faces if f not in before]


# ---------------------------------------------------------------------------
# profile-driven construction — where interesting silhouettes come from
# ---------------------------------------------------------------------------


def lathe(bm, profile, segments=16, axis=(0.0, 0.0, 1.0), center=(0.0, 0.0, 0.0), cap=True):
    """Revolve a 2D profile [(radius, height), ...] around an axis.

    This is how you get barrels, vases, columns, goblets, chess pieces and
    tree trunks from four numbers instead of four hundred vertices.
    """
    if len(profile) < 2:
        raise ValueError("lathe needs at least two profile points")
    before = set(bm.faces)
    verts = [bm.verts.new((center[0] + r, center[1], center[2] + h)) for r, h in profile]
    edges = [bm.edges.new((verts[i], verts[i + 1])) for i in range(len(verts) - 1)]
    bmesh.ops.spin(
        bm,
        geom=verts + edges,
        cent=Vector(center),
        axis=Vector(axis),
        angle=2.0 * math.pi,
        steps=max(3, segments),
        use_merge=True,
    )
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    faces = [f for f in bm.faces if f not in before]
    if cap:
        faces = _cap_open_boundaries(bm, before)
    return faces


def _cap_open_boundaries(bm, before_faces):
    boundary = [e for e in bm.edges if len(e.link_faces) == 1]
    if boundary:
        bmesh.ops.holes_fill(bm, edges=boundary)
    return [f for f in bm.faces if f not in before_faces]


def loft(bm, sections, closed_ends=True):
    """Bridge a stack of equal-length vertex rings [[(x,y,z), ...], ...]."""
    if len(sections) < 2:
        raise ValueError("loft needs at least two sections")
    width = len(sections[0])
    if any(len(s) != width for s in sections):
        raise ValueError("loft sections must all have the same vertex count")
    before = set(bm.faces)
    rings = [[bm.verts.new(p) for p in section] for section in sections]
    for lower, upper in zip(rings, rings[1:]):
        for i in range(width):
            j = (i + 1) % width
            bm.faces.new((lower[i], lower[j], upper[j], upper[i]))
    if closed_ends:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
    return [f for f in bm.faces if f not in before]


def resample(values, count):
    """Stretch a short list of control values across `count` samples.

    Lets a caller give five key cross-section scales for a forty-point path
    instead of forty, which is the difference between describing a horse's
    barrel and typing out a spreadsheet.
    """
    if not values:
        return [(1.0, 1.0)] * count
    if len(values) == 1:
        return [values[0]] * count
    out = []
    span = len(values) - 1
    for index in range(count):
        t = (index / max(1, count - 1)) * span
        low = min(int(t), span - 1)
        frac = t - low
        a, b = values[low], values[low + 1]
        out.append((a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac))
    return out


def sweep(bm, path_points, profile, closed_path=False, closed_profile=True, cap_ends=True,
          up=(0.0, 0.0, 1.0), scales=None):
    """Sweep a 2D cross-section along a 3D polyline.

    `profile` is [(lateral, vertical), ...] in the plane perpendicular to the
    path; `path_points` is [(x, y, z), ...].

    Frames are carried along the path by parallel transport rather than
    recomputed from a fixed up-vector at each step. A fresh Frenet frame flips
    at inflection points and spins the cross-section, which on a closed oval
    shows up as the track surface twisting into a Mobius strip halfway round.

    This is the highest-leverage primitive for level geometry: racetracks,
    grandstands, roads, ramparts, rails, pipes, tunnels and mouldings are all
    one profile plus one path.
    """
    if len(path_points) < 2:
        raise ValueError("sweep needs at least two path points")
    if len(profile) < 2:
        raise ValueError("sweep needs at least two profile points")

    points = [Vector(p) for p in path_points]
    if closed_path and (points[0] - points[-1]).length < 1e-6:
        points.pop()

    count = len(points)
    tangents = []
    for index in range(count):
        if closed_path:
            ahead = points[(index + 1) % count]
            behind = points[(index - 1) % count]
        else:
            ahead = points[min(index + 1, count - 1)]
            behind = points[max(index - 1, 0)]
        tangent = ahead - behind
        if tangent.length < 1e-9:
            tangent = Vector((1.0, 0.0, 0.0))
        tangents.append(tangent.normalized())

    world_up = Vector(up).normalized()
    # Seed the first frame, then rotate it along the path minimally.
    reference = world_up
    if abs(tangents[0].dot(reference)) > 0.999:
        reference = Vector((1.0, 0.0, 0.0))
    normal = (reference - tangents[0] * tangents[0].dot(reference)).normalized()

    frames = []
    for index in range(count):
        tangent = tangents[index]
        if index > 0:
            previous = tangents[index - 1]
            axis = previous.cross(tangent)
            if axis.length > 1e-9:
                angle = math.atan2(axis.length, previous.dot(tangent))
                normal = normal @ Matrix.Rotation(-angle, 3, axis.normalized())
            normal = (normal - tangent * tangent.dot(normal))
            if normal.length < 1e-9:
                normal = Vector((0.0, 0.0, 1.0))
            normal = normal.normalized()
        binormal = tangent.cross(normal).normalized()
        frames.append((normal, binormal))

    # Per-point cross-section scaling is what turns a uniform tube into an
    # anatomy: a horse's barrel swells at the girth and tapers to the loin, and
    # a neck is deep and narrow where the body is wide and shallow. Without it
    # every swept form is a pipe.
    ramp = resample(list(scales), count) if scales else [(1.0, 1.0)] * count

    before = set(bm.faces)
    rings = []
    for index, origin in enumerate(points):
        normal, binormal = frames[index]
        scale_lateral, scale_vertical = ramp[index]
        # `binormal` is lateral, `normal` is vertical: a profile authored as
        # (width, height) reads the way an artist expects.
        rings.append([
            bm.verts.new(
                origin
                + binormal * (lateral * scale_lateral)
                + normal * (vertical * scale_vertical)
            )
            for lateral, vertical in profile
        ])

    width = len(profile)
    span = count if closed_path else count - 1
    for index in range(span):
        current = rings[index]
        nxt = rings[(index + 1) % count]
        limit = width if closed_profile else width - 1
        for j in range(limit):
            k = (j + 1) % width
            try:
                bm.faces.new((current[j], current[k], nxt[k], nxt[j]))
            except ValueError:
                pass  # duplicate face where the path doubles back; skip it

    if cap_ends and not closed_path and closed_profile:
        for ring_verts in (list(reversed(rings[0])), rings[-1]):
            try:
                bm.faces.new(ring_verts)
            except ValueError:
                pass
    return [f for f in bm.faces if f not in before]


def sample_path(points, count, closed=False):
    """Resample a polyline at `count` equal arc-length stations.

    Returns [(position, tangent, normal)] with `normal` the horizontal outward
    direction, which is what you need to stand a wall, a column or an arch bay
    on a curve. Placing bays by index instead of by arc length bunches them at
    the ends of an oval — the giveaway that a colonnade was faked.
    """
    pts = [Vector(p) for p in points]
    if closed and (pts[0] - pts[-1]).length > 1e-6:
        pts.append(pts[0].copy())

    lengths = [0.0]
    for a, b in zip(pts, pts[1:]):
        lengths.append(lengths[-1] + (b - a).length)
    total = lengths[-1]
    if total < 1e-9:
        raise ValueError("path has zero length")

    out = []
    for index in range(count):
        target = total * index / count if closed else total * index / max(1, count - 1)
        seg = 0
        while seg < len(lengths) - 2 and lengths[seg + 1] < target:
            seg += 1
        span = max(1e-9, lengths[seg + 1] - lengths[seg])
        t = (target - lengths[seg]) / span
        position = pts[seg].lerp(pts[seg + 1], t)
        tangent = (pts[seg + 1] - pts[seg]).normalized()
        # Outward horizontal normal: rotate the tangent 90 degrees about Z.
        normal = Vector((tangent.y, -tangent.x, 0.0))
        if normal.length < 1e-9:
            normal = Vector((1.0, 0.0, 0.0))
        out.append((position, tangent, normal.normalized()))
    return out


def oval_path(straight, radius, segments_per_turn=24, lane_offset=0.0):
    """Points around a hippodrome/stadium oval, matching a straight+radius spec.

    Returns Godot-friendly XY-plane points (Z=0); the glTF exporter maps Y to
    -Z, which is the convention the games' track maths already assumes.
    """
    points = []
    half = straight * 0.5
    r = radius + lane_offset
    points.append((-half, -r, 0.0))
    points.append((half, -r, 0.0))
    for step in range(1, segments_per_turn):
        theta = math.pi * step / segments_per_turn
        points.append((half + math.sin(theta) * r, -math.cos(theta) * r, 0.0))
    points.append((half, r, 0.0))
    points.append((-half, r, 0.0))
    for step in range(1, segments_per_turn):
        theta = math.pi * step / segments_per_turn
        points.append((-half - math.sin(theta) * r, math.cos(theta) * r, 0.0))
    return points


def ring(radius, height, sides, jitter=None, rng=None, squash=1.0):
    """A single loft section: a polygon ring, optionally noised."""
    points = []
    for i in range(sides):
        theta = 2.0 * math.pi * i / sides
        r = radius
        if jitter and rng:
            r *= 1.0 + rng.uniform(-jitter, jitter)
        points.append((math.cos(theta) * r, math.sin(theta) * r * squash, height))
    return points


# ---------------------------------------------------------------------------
# editing operations
# ---------------------------------------------------------------------------


def extrude(bm, faces, distance, inset=0.0):
    """Inset-then-extrude — the two-step that makes panels instead of spikes."""
    targets = list(faces)
    if inset > 0.0:
        targets = bmesh.ops.inset_region(
            bm, faces=targets, thickness=inset, depth=0.0, use_even_offset=True
        )["faces"]
    result = bmesh.ops.extrude_face_region(bm, geom=targets)
    new_faces = [g for g in result["geom"] if isinstance(g, bmesh.types.BMFace)]
    moved = {v for g in result["geom"] if isinstance(g, bmesh.types.BMVert) for v in [g]}
    for face in targets:
        if face.is_valid:
            bmesh.ops.delete(bm, geom=[face], context="FACES")
    if moved:
        normal = _average_normal(new_faces)
        bmesh.ops.translate(bm, vec=normal * distance, verts=list(moved))
    return new_faces


def _average_normal(faces) -> Vector:
    total = Vector((0.0, 0.0, 0.0))
    for face in faces:
        if face.is_valid:
            total += face.normal
    return total.normalized() if total.length > 1e-9 else Vector((0.0, 0.0, 1.0))


def bevel_edges(bm, edges=None, offset=0.02, segments=2, angle_min=0.35):
    """Chamfer edges sharper than `angle_min` radians. The workhorse for reads."""
    if edges is None:
        edges = [
            e
            for e in bm.edges
            if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > angle_min
        ]
    edges = [e for e in edges if e.is_valid]
    if not edges:
        return []
    return bmesh.ops.bevel(
        bm,
        geom=edges,
        offset=offset,
        offset_type="OFFSET",
        segments=max(1, segments),
        profile=0.5,
        affect="EDGES",
        clamp_overlap=True,
    )["faces"]


def greeble(bm, faces, rng, density=0.4, min_depth=0.01, max_depth=0.05, inset=0.15, cuts=1):
    """Panel-line detail: subdivide, then push/pull a random subset of faces.

    Deliberately biased toward shallow depths — greeble reads as surface
    variation under normal-mapped lighting, and deep greeble just eats
    silhouette budget and shadow-acnes on mobile.
    """
    targets = [f for f in faces if f.is_valid]
    if cuts > 0 and targets:
        bm.edges.ensure_lookup_table()
        edges = sorted({e for f in targets for e in f.edges}, key=lambda e: e.index)
        subdivided = bmesh.ops.subdivide_edges(
            bm, edges=edges, cuts=cuts, use_grid_fill=True
        )
        targets = [g for g in subdivided["geom_inner"] if isinstance(g, bmesh.types.BMFace)]
        targets = targets or [f for f in faces if f.is_valid]
    picked = [f for f in targets if rng.random() < density]
    made = []
    for face in picked:
        if not face.is_valid or len(face.verts) < 3:
            continue
        depth = rng.uniform(min_depth, max_depth)
        if rng.random() < 0.35:
            depth = -depth * 0.6
        inner = bmesh.ops.inset_region(
            bm, faces=[face], thickness=face.calc_area() ** 0.5 * inset,
            depth=0.0, use_even_offset=True,
        )["faces"]
        if not inner:
            continue
        result = bmesh.ops.extrude_face_region(bm, geom=inner)
        verts = [g for g in result["geom"] if isinstance(g, bmesh.types.BMVert)]
        new_faces = [g for g in result["geom"] if isinstance(g, bmesh.types.BMFace)]
        for old in inner:
            if old.is_valid:
                bmesh.ops.delete(bm, geom=[old], context="FACES")
        if verts:
            bmesh.ops.translate(bm, vec=_average_normal(new_faces) * depth, verts=verts)
        made.extend(new_faces)
    return made


def taper(bm, verts, factor, axis_min, axis_max, axis=2, center=(0.0, 0.0)):
    """Scale cross-sections toward `factor` as they approach axis_max."""
    span = max(1e-6, axis_max - axis_min)
    for vert in verts:
        t = (vert.co[axis] - axis_min) / span
        t = max(0.0, min(1.0, t))
        scale = 1.0 + (factor - 1.0) * t
        others = [i for i in range(3) if i != axis]
        for idx, k in enumerate(others):
            vert.co[k] = center[idx] + (vert.co[k] - center[idx]) * scale


def bend_noise(bm, verts, rng, amount=0.02, frequency=3.0):
    """Organic wobble — rocks, roots, cloth folds. Deterministic per-vertex."""
    for vert in verts:
        offset = Vector(
            (
                math.sin(vert.co.y * frequency + rng.random() * 0.001),
                math.cos(vert.co.z * frequency + rng.random() * 0.001),
                math.sin(vert.co.x * frequency + rng.random() * 0.001),
            )
        )
        vert.co += offset * amount


def jitter_verts(bm, verts, rng, amount=0.01):
    for vert in verts:
        vert.co += Vector(
            (
                rng.uniform(-amount, amount),
                rng.uniform(-amount, amount),
                rng.uniform(-amount, amount),
            )
        )


def mirror(bm, axis="X", merge_dist=1e-4):
    index = {"X": 0, "Y": 1, "Z": 2}[axis.upper()]
    direction = f"-{axis.upper()}"
    bmesh.ops.symmetrize(bm, input=geom_of(bm), direction=direction, dist=merge_dist)
    return index


def cleanup(bm, merge_dist=1e-5, limited_dissolve=False, angle=0.087):
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=merge_dist)
    if limited_dissolve:
        bmesh.ops.dissolve_limit(
            bm, angle_limit=angle, verts=bm.verts[:], edges=bm.edges[:]
        )
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])


def triangulate(bm, faces=None):
    bmesh.ops.triangulate(bm, faces=faces if faces is not None else bm.faces[:])


def bounds(obj) -> dict:
    """World-space AABB — every generator reports this so agents can compose."""
    bpy.context.view_layer.update()  # matrix_world is stale after any move
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    if not corners:
        return {"min": [0, 0, 0], "max": [0, 0, 0], "size": [0, 0, 0]}
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    lo = [min(xs), min(ys), min(zs)]
    hi = [max(xs), max(ys), max(zs)]
    return {
        "min": [round(v, 5) for v in lo],
        "max": [round(v, 5) for v in hi],
        "size": [round(hi[i] - lo[i], 5) for i in range(3)],
    }


def tri_count(obj) -> int:
    mesh = obj.data
    if not isinstance(mesh, bpy.types.Mesh):
        return 0
    total = 0
    for polygon in mesh.polygons:
        total += max(0, len(polygon.vertices) - 2)
    return total


def shade_auto_smooth(obj, angle_degrees=35.0):
    """Blender 4.1+ removed mesh auto-smooth; sharp-edge flags are the portable
    replacement and, unlike the Smooth by Angle modifier, they survive glTF."""
    mesh = obj.data
    threshold = math.radians(angle_degrees)
    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    for edge in mesh.edges:
        edge.use_edge_sharp = False
    bm = bmesh.new()
    bm.from_mesh(mesh)
    sharp = []
    for index, edge in enumerate(bm.edges):
        if len(edge.link_faces) == 2 and edge.calc_face_angle(0.0) > threshold:
            sharp.append(index)
    bm.free()
    for index in sharp:
        mesh.edges[index].use_edge_sharp = True
    mesh.update()
    return len(sharp)


def shade_flat(obj):
    obj.data.polygons.foreach_set("use_smooth", [False] * len(obj.data.polygons))
    obj.data.update()
