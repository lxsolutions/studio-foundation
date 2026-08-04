"""Vertex-colour painting — the textureless way to make an asset read.

Vertex colours export to glTF as COLOR_0 and every engine multiplies them into
the material for free. For low-poly game assets this replaces a whole class of
textures: dust at the base of a wall, a snow line, waterline grime, dirt baked
into crevices, edge wear, mottled rust or moss. No UVs, no image memory, no
bake step.

Colours are stored on a CORNER-domain BYTE_COLOR attribute (one colour per
loop), which is what the glTF exporter turns into COLOR_0. Everything is
computed from mesh geometry with sin/cos maths only — same params, same seed,
same bytes, on any platform.
"""

from __future__ import annotations

import builtins
import math

from lib import mat as mat_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from registry import OpError, op

WHITE = (1.0, 1.0, 1.0, 1.0)


def _layer(obj, layer):
    """Get or create the CORNER-domain byte colour attribute the exporter wants."""
    mesh = obj.data
    attr = mesh.color_attributes.get(layer)
    if attr is None:
        attr = mesh.color_attributes.new(name=layer, type="BYTE_COLOR", domain="CORNER")
        # A fresh attribute defaults to black, which would multiply the material
        # down to nothing in-engine. Start at white instead, so a paint op that
        # only touches part of the mesh leaves the rest visually unchanged.
        attr.data.foreach_set("color", list(WHITE) * len(mesh.loops))
        mesh.update()
    return attr


def _loop_vertex_map(mesh):
    """loop index -> vertex index, so per-vertex maths can paint per-loop data."""
    mapping = [0] * len(mesh.loops)
    mesh.loops.foreach_get("vertex_index", mapping)
    return mapping


def _write_per_vertex(obj, attr, vertex_colors):
    """Expand one RGBA per vertex onto that vertex's loops."""
    mesh = obj.data
    flat = [0.0] * (4 * len(mesh.loops))
    for loop_index, vertex_index in enumerate(_loop_vertex_map(mesh)):
        flat[loop_index * 4 : loop_index * 4 + 4] = vertex_colors[vertex_index]
    attr.data.foreach_set("color", flat)
    mesh.update()


def _read_loops(attr, mesh):
    flat = [0.0] * (4 * len(mesh.loops))
    attr.data.foreach_get("color", flat)
    return flat


def _lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))


def _clamp01(value):
    return max(0.0, min(1.0, value))


def _mean_edge_length(mesh):
    if not mesh.edges:
        return 0.0
    verts = mesh.vertices
    total = 0.0
    for edge in mesh.edges:
        total += (verts[edge.vertices[0]].co - verts[edge.vertices[1]].co).length
    return total / len(mesh.edges)


@op(
    "paint.fill",
    summary="Set every loop of a mesh to one vertex colour. The base coat for the other paint.* ops — fill white before paint.cavity so unpainted areas stay neutral, or fill a flat tint for a stylised asset.",
    params={
        "name": ("str", None, "Mesh object to paint"),
        "color": ("colorref", None, "Colour: palette name, #rrggbb, or linear [r,g,b]. White leaves the material unchanged when the engine multiplies COLOR_0 in"),
        "layer": ("str", "color", "Colour attribute name; the glTF exporter ships the active one as COLOR_0"),
    },
    tags=["paint"],
)
def paint_fill(ctx, name, color, layer):
    obj = _get_mesh(name)
    rgba = _color(color)
    attr = _layer(obj, layer)
    mesh = obj.data
    attr.data.foreach_set("color", list(rgba) * len(mesh.loops))
    mesh.update()
    return {
        "name": obj.name,
        "layer": layer,
        "loops_painted": len(mesh.loops),
        "color": [round(c, 4) for c in rgba],
    }


@op(
    "paint.height",
    summary="Paint a two-colour gradient along an axis — dust at the base of a wall, a snow line on a peak, waterline grime on a hull. Cheaper than any texture and it can never stretch or seam.",
    params={
        "name": ("str", None, "Mesh object to paint"),
        "low": ("colorref", None, "Colour at the bottom of the range: palette name, #rrggbb, or linear [r,g,b]"),
        "high": ("colorref", None, "Colour at the top of the range"),
        "axis": ("enum:x|y|z", "z", "Axis the gradient runs along (z is up). Measured in the mesh's LOCAL space, like material.face_assign"),
        "min": ("num", None, "Axis value for 100% `low`; omit to use the mesh's own lower bound. Set both min and max to share one gradient across several objects"),
        "max": ("num", None, "Axis value for 100% `high`; omit to use the mesh's upper bound"),
        "curve": ("enum:linear|smooth", "linear", "Gradient easing; smooth eases in and out, which hides the band edges"),
        "layer": ("str", "color", "Colour attribute name; the glTF exporter ships the active one as COLOR_0"),
    },
    tags=["paint"],
)
def paint_height(ctx, name, low, high, axis, min, max, curve, layer):
    obj = _get_mesh(name)
    low_rgba = _color(low)
    high_rgba = _color(high)
    mesh = obj.data
    index = {"x": 0, "y": 1, "z": 2}[axis]
    coords = [v.co[index] for v in mesh.vertices]
    if not coords:
        raise OpError(f"'{name}' has no vertices to paint")
    lo = min if min is not None else builtins.min(coords)
    hi = max if max is not None else builtins.max(coords)
    span = hi - lo
    if span < 1e-6:
        kind = "inverted" if span < 0 else "flat"
        raise OpError(
            f"'{name}' has a {kind} range along {axis} (min {lo:.4f}, max {hi:.4f}) — "
            "a height gradient needs max > min along its axis. The mesh's own lower "
            f"bound is {builtins.min(coords):.4f} and upper is {builtins.max(coords):.4f}; "
            "pass min/max inside that span, or omit both to auto-range the whole mesh."
        )
    vertex_colors = []
    for value in coords:
        t = _clamp01((value - lo) / span)
        if curve == "smooth":
            t = t * t * (3.0 - 2.0 * t)
        vertex_colors.append(_lerp(low_rgba, high_rgba, t))
    attr = _layer(obj, layer)
    _write_per_vertex(obj, attr, vertex_colors)
    return {
        "name": obj.name,
        "layer": layer,
        "loops_painted": len(mesh.loops),
        "axis": axis,
        "range": [round(lo, 5), round(hi, 5)],
        "curve": curve,
    }


@op(
    "paint.cavity",
    summary="Bake 'dirt in the crevices' or 'edge wear' without textures: a deterministic geometric curvature estimate per vertex. Concave spots (recesses, grooves, inside corners) take the colour in cavity mode; convex ridges take it in edge mode. Blends over the existing layer, so fill white first if the mesh is unpainted.",
    params={
        "name": ("str", None, "Mesh object to paint — needs real surface relief; a flat quad has no curvature to find"),
        "color": ("colorref", None, "Colour blended into the crevices/edges: palette name, #rrggbb, or linear [r,g,b]. Dark browns read as grime, light greys as worn edges"),
        "mode": ("enum:cavity|edge", "cavity", "cavity paints concave spots (dirt), edge paints convex ridges (wear)"),
        "strength": ("num", 1.0, "Blend strength multiplier; the deepest cavity gets the full colour at 1.0"),
        "invert": ("bool", False, "Flip the result — paint everything EXCEPT the crevices/edges"),
        "layer": ("str", "color", "Colour attribute name; the glTF exporter ships the active one as COLOR_0"),
    },
    tags=["paint"],
)
def paint_cavity(ctx, name, color, mode, strength, invert, layer):
    obj = _get_mesh(name)
    rgba = _color(color)
    mesh = obj.data
    if len(mesh.vertices) < 3:
        raise OpError(f"'{name}' has too few vertices for a curvature estimate")

    # Curvature estimate: the centroid of a vertex's linked face centres sits
    # INSIDE the material for a convex ridge (a cube corner: dot with the vertex
    # normal is negative) and OUTSIDE it for a concave crease (the recess walls
    # fold away from the vertex: dot is positive). Purely geometric — no ray
    # casts, no randomness, identical on every platform.
    bm = mesh_lib.obj_bmesh(obj)
    bm.verts.ensure_lookup_table()
    bm.normal_update()
    signed = [0.0] * len(bm.verts)
    for vert in bm.verts:
        if not vert.link_faces:
            continue
        centroid = vert.link_faces[0].calc_center_median().copy()
        for face in vert.link_faces[1:]:
            centroid += face.calc_center_median()
        centroid /= len(vert.link_faces)
        signed[vert.index] = (centroid - vert.co).dot(vert.normal)
    bm.free()

    scale = builtins.max((abs(v) for v in signed), default=0.0)
    if scale < 1e-9:
        raise OpError(
            f"'{name}' has no measurable curvature (a flat or fully symmetric mesh) — "
            "nothing to paint. Cut a recess with build.extrude, or paint.noise for "
            "variation that does not need relief."
        )

    weights = []
    for value in signed:
        t = _clamp01((value / scale) * (-1.0 if mode == "edge" else 1.0) * strength)
        weights.append(1.0 - t if invert else t)

    attr = _layer(obj, layer)
    existing = _read_loops(attr, mesh)
    mapping = _loop_vertex_map(mesh)
    painted = 0
    for loop_index, vertex_index in enumerate(mapping):
        t = weights[vertex_index]
        if t <= 0.004:  # below byte-colour quantisation — nothing changes
            continue
        base = existing[loop_index * 4 : loop_index * 4 + 4]
        blended = _lerp(base, rgba, t)
        existing[loop_index * 4 : loop_index * 4 + 4] = blended
        painted += 1
    attr.data.foreach_set("color", existing)
    mesh.update()

    result = {
        "name": obj.name,
        "layer": layer,
        "mode": mode,
        "loops_painted": painted,
        "loops_total": len(mesh.loops),
        "painted_fraction": round(painted / max(1, len(mesh.loops)), 4),
    }
    if painted == 0:
        result["note"] = (
            "no loops crossed the paint threshold — the mesh may be too smooth for "
            f"mode='{mode}'. Try invert=true, or give it relief with build.extrude first."
        )
    return result


@op(
    "paint.noise",
    summary="Blend two colours by deterministic fBm noise sampled at vertex positions — mottled wear, rust patches, moss, dirt variation. Breaks up flat fills so large surfaces stop looking computer-perfect.",
    params={
        "name": ("str", None, "Mesh object to paint"),
        "color_a": ("colorref", None, "Colour where the noise is low: palette name, #rrggbb, or linear [r,g,b]"),
        "color_b": ("colorref", None, "Colour where the noise is high"),
        "scale": ("num", 2.0, "Noise frequency in 1/metres — higher gives smaller, busier patches"),
        "seed": ("int", 0, "Random seed; same seed gives the same pattern forever"),
        "octaves": ("int", 3, "Fractal detail levels; more octaves, finer grain"),
        "layer": ("str", "color", "Colour attribute name; the glTF exporter ships the active one as COLOR_0"),
    },
    tags=["paint"],
)
def paint_noise(ctx, name, color_a, color_b, scale, seed, octaves, layer):
    obj = _get_mesh(name)
    rgba_a = _color(color_a)
    rgba_b = _color(color_b)
    mesh = obj.data
    if not mesh.vertices:
        raise OpError(f"'{name}' has no vertices to paint")

    vertex_colors = []
    for vert in mesh.vertices:
        value = _fbm3(vert.co.x * scale, vert.co.y * scale, vert.co.z * scale,
                      seed, octaves)
        vertex_colors.append(_lerp(rgba_a, rgba_b, _clamp01(value * 0.5 + 0.5)))
    attr = _layer(obj, layer)
    _write_per_vertex(obj, attr, vertex_colors)

    result = {
        "name": obj.name,
        "layer": layer,
        "loops_painted": len(mesh.loops),
        "scale": scale,
        "seed": seed,
        "octaves": octaves,
    }
    # Vertex colour can only show detail the mesh has vertices for. Fewer than
    # ~4 vertices per noise wavelength aliases the pattern into mush.
    edge = _mean_edge_length(mesh)
    if edge > 1e-9 and (2.0 * math.pi) / (scale * edge) < 4.0:
        result["note"] = (
            f"average edge length is {edge:.3f} m, too coarse for noise at scale "
            f"{scale} — the pattern will alias. Run build.subdivide name='{obj.name}' "
            "or lower `scale`."
        )
    return result


def _fbm3(x, y, z, seed, octaves=3):
    """3D value-noise fBm built from sin/cos, in the spirit of env._fbm: no
    external noise library, bit-identical across platforms, so CI can regenerate
    an asset and diff the colours."""
    total = 0.0
    amplitude = 1.0
    frequency = 1.0
    norm = 0.0
    for octave in range(max(1, octaves)):
        phase = seed * 0.7919 + octave * 12.9898
        total += amplitude * (
            math.sin(x * frequency + phase) * math.cos(y * frequency * 1.13 - phase * 0.7)
            + 0.6
            * math.sin((y + z) * frequency * 0.61 + phase * 1.7)
            * math.cos((x - z) * frequency * 0.83 - phase * 1.3)
        )
        norm += amplitude * 1.6
        amplitude *= 0.5
        frequency *= 2.0
    return total / max(norm, 1e-6)


def _color(value):
    try:
        return mat_lib.resolve_color(value)
    except ValueError as exc:
        raise OpError(str(exc)) from exc


def _get_mesh(name):
    try:
        obj = scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
    if obj.type != "MESH":
        raise OpError(f"'{name}' is a {obj.type}, not a mesh — paint the render mesh")
    return obj
