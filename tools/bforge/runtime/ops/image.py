"""Concept image -> production mesh.

The 2D images AI generators make are art direction, not assets. This namespace
is the bridge: `image.analyze` measures what the image actually shows
(silhouette, proportions, palette, symmetry) and `image.to_mesh` turns that
silhouette into a real, UV'd, textured 3D solid — then scores itself against
the source image, because 'it looks like the picture' should be a number.

What this is honest about: a single 2D image cannot invent depth or anatomy.
Extrusion is genuinely excellent for emblems, totems, props, weapons, stylized
creatures in side view, relief architecture and foliage. For anatomical
characters the right path is the parametric one (char.humanoid et al) guided
by image.analyze's palette and proportions — the report says so.
"""

from __future__ import annotations

import math

import bpy
from lib import finish as finish_lib
from lib import mat as mat_lib
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from registry import OpError, op

WORK_RES = 160  # long side of the working mask


def _load_subject(path, threshold):
    """Load the image and segment subject from background.

    Returns (mask, w, h, pixels_rgb) where mask is a set of (x, y) subject
    cells at working resolution and pixels_rgb the FULL-res subject samples
    for palette work.
    """
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - Blender bundles numpy
        raise OpError("numpy unavailable in this Blender build") from exc

    target = bpy.path.abspath(str(path))
    try:
        image = bpy.data.images.load(target, check_existing=True)
    except RuntimeError as exc:
        raise OpError(f"cannot load image at {target}: {exc}") from exc
    width, height = image.size
    data = numpy.array(image.pixels[:], dtype=numpy.float32).reshape((height, width, 4))
    rgb = data[:, :, :3]
    alpha = data[:, :, 3]

    if float(alpha.min()) < 0.5:
        subject = alpha > 0.5
    else:
        corner = min(8, width // 8, height // 8) or 1
        corners = numpy.concatenate([
            rgb[:corner, :corner].reshape(-1, 3), rgb[:corner, -corner:].reshape(-1, 3),
            rgb[-corner:, :corner].reshape(-1, 3), rgb[-corner:, -corner:].reshape(-1, 3),
        ])
        backdrop = numpy.median(corners, axis=0)
        subject = numpy.linalg.norm(rgb - backdrop, axis=2) > threshold

    if not bool(subject.any()):
        raise OpError(
            "no subject found — the whole image reads as background. Pass a "
            "larger threshold, or an image with a real alpha channel."
        )

    scale = max(1, int(math.ceil(max(width, height) / WORK_RES)))
    cells = set()
    for cy in range(0, height, scale):
        for cx in range(0, width, scale):
            block = subject[cy:cy + scale, cx:cx + scale]
            if block.size and float(block.mean()) > 0.5:
                cells.add((cx // scale, cy // scale))
    return cells, width // scale, height // scale, rgb, subject


def _boundary_loops(cells):
    """Marching-squares boundary edges of the subject cells, chained into loops.

    Each boundary edge runs between grid vertices (x, y) in cell space. Every
    clean boundary vertex has exactly two boundary edges, so chaining is a walk.
    """
    edges = set()

    def add(a, b):
        edges.add((a, b) if a <= b else (b, a))

    for (cx, cy) in cells:
        if (cx, cy - 1) not in cells:
            add((cx, cy), (cx + 1, cy))
        if (cx, cy + 1) not in cells:
            add((cx, cy + 1), (cx + 1, cy + 1))
        if (cx - 1, cy) not in cells:
            add((cx, cy), (cx, cy + 1))
        if (cx + 1, cy) not in cells:
            add((cx + 1, cy), (cx + 1, cy + 1))

    adjacency = {}
    for a, b in edges:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)

    loops = []
    pool = dict(adjacency)
    while pool:
        start = next(iter(pool))
        # A node whose edges were all consumed from the other side must not be
        # re-picked forever — empty lists are deleted wherever they appear.
        if not pool[start]:
            del pool[start]
            continue
        loop = [start]
        prev, current = None, start
        while True:
            neighbours = [n for n in pool.get(current, []) if n != prev]
            if not neighbours:
                break
            nxt = neighbours[0]
            pool[current].remove(nxt)
            pool[nxt].remove(current)
            if not pool[current]:
                del pool[current]
            if nxt in pool and not pool[nxt]:
                del pool[nxt]
            prev, current = current, nxt
            if current == start:
                break
            loop.append(current)
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def _simplify(points, epsilon):
    """Douglas-Peucker for a CLOSED loop, order-preserving.

    Running DP on the doubled path keeps points from both copies and returns
    an overlapping scramble. Instead: split the loop at its diameter pair
    (the two farthest-apart points), simplify each open half, and rejoin.
    """
    if len(points) < 6:
        return points
    best, pair = -1.0, (0, 0)
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d = ((points[i][0] - points[j][0]) ** 2
                 + (points[i][1] - points[j][1]) ** 2)
            if d > best:
                best, pair = d, (i, j)
    i, j = pair
    half_a = _dp(points[i:j + 1], epsilon)
    half_b = _dp(points[j:] + points[:i + 1], epsilon)
    merged = half_a[:-1] + half_b[:-1]
    if len(merged) < 3:
        return points
    return merged


def _dp(points, epsilon):
    if len(points) < 3:
        return points
    start, end = points[0], points[-1]
    axis_x, axis_y = end[0] - start[0], end[1] - start[1]
    length_sq = axis_x * axis_x + axis_y * axis_y or 1e-9
    worst, worst_index = -1.0, -1
    for index in range(1, len(points) - 1):
        px, py = points[index]
        t = max(0.0, min(1.0, ((px - start[0]) * axis_x + (py - start[1]) * axis_y) / length_sq))
        dx = px - (start[0] + t * axis_x)
        dy = py - (start[1] + t * axis_y)
        distance = dx * dx + dy * dy
        if distance > worst:
            worst, worst_index = distance, index
    if worst <= epsilon * epsilon:
        return [start, end]
    left = _dp(points[:worst_index + 1], epsilon)
    right = _dp(points[worst_index:], epsilon)
    return left[:-1] + right


def _palette(rgb, subject, count=5):
    """Dominant subject colours by coarse quantisation (deterministic)."""
    import numpy

    samples = rgb[subject]
    if len(samples) == 0:
        return []
    quantised = numpy.clip((samples * 8).astype(numpy.int32), 0, 7)
    keys = quantised[:, 0] * 64 + quantised[:, 1] * 8 + quantised[:, 2]
    unique, counts = numpy.unique(keys, return_counts=True)
    order = numpy.argsort(-counts)[:count]
    out = []
    for index in order:
        members = samples[keys == int(unique[index])]
        mean = members.mean(axis=0)
        # Loaded PNG pixels come back sRGB-encoded (verified by measurement):
        # hex is the direct display value; linear is the physical albedo.
        out.append({
            "linear": [round(_srgb_to_linear(float(c)), 4) for c in mean],
            "hex": "#" + "".join(
                f"{max(0, min(255, round(float(c) * 255))):02x}" for c in mean
            ),
            "share": round(float(counts[index]) / len(samples), 3),
        })
    return out


def _linear_to_srgb(value):
    if value <= 0.0031308:
        return value * 12.92
    return 1.055 * (max(value, 0.0) ** (1 / 2.4)) - 0.055


def _srgb_to_linear(value):
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _mask_stats(cells, w, h):
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    bw, bh = max_x - min_x + 1, max_y - min_y + 1
    # Left-right mirror IoU across the bbox vertical centreline.
    mirrored = {(min_x + max_x - (cx - min_x), cy) for (cx, cy) in cells}
    mirrored = {(min_x + (max_x - cx), cy) for (cx, cy) in cells}
    both = cells & mirrored
    either = cells | mirrored
    symmetry = len(both) / max(1, len(either))
    return {
        "bbox_cells": [min_x, min_y, max_x, max_y],
        "bbox_size_cells": [bw, bh],
        "aspect_h_over_w": round(bh / max(1, bw), 3),
        "fill_ratio": round(len(cells) / max(1, bw * bh), 3),
        "coverage": round(len(cells) / max(1, w * h), 4),
        "symmetry": round(symmetry, 3),
    }


def _rasterize(loop, w, h):
    """Scanline-fill a contour into a cell mask (for the IoU fidelity score)."""
    filled = set()
    for y in range(h + 1):
        crossings = []
        for i in range(len(loop)):
            x1, y1 = loop[i]
            x2, y2 = loop[(i + 1) % len(loop)]
            if (y1 <= y < y2) or (y2 <= y < y1):
                t = (y - y1) / (y2 - y1)
                crossings.append(x1 + t * (x2 - x1))
        crossings.sort()
        for i in range(0, len(crossings) - 1, 2):
            for x in range(max(0, int(math.ceil(crossings[i]))),
                           min(w, int(crossings[i + 1]) + 1)):
                filled.add((x, y))
    return filled


@op(
    "image.analyze",
    summary="Measure a concept image instead of eyeballing it: silhouette coverage and proportions, left-right symmetry, dominant and regional palette, and an honest recommendation — extrude it (image.to_mesh) or use it as parametric guidance for a recipe. The first step of concept art -> production asset.",
    params={
        "path": ("path", None, "Image file (PNG with alpha, or any subject on a fairly uniform background)"),
        "threshold": ("num", 0.06, "Background distance cutoff when there is no alpha channel; raise if the backdrop bleeds into the subject"),
        "colors": ("int", 5, "Dominant palette colours to report"),
    },
    tags=["inspect", "image"],
    mutates=False,
)
def image_analyze(ctx, path, threshold, colors):
    cells, w, h, rgb, subject = _load_subject(ctx.resolve(path), threshold)
    stats = _mask_stats(cells, w, h)
    palette = _palette(rgb, subject, colors)
    loops = _boundary_loops(cells)
    fill, aspect, symmetry = stats["fill_ratio"], stats["aspect_h_over_w"], stats["symmetry"]
    if fill > 0.35 and 0.25 < aspect < 4.0:
        approach = ("extrude — this reads as a single solid subject; image.to_mesh "
                    "will produce a good solid from it")
    else:
        approach = ("parametric guidance — the silhouette is too sparse or too extreme "
                    "for clean extrusion; drive char.* / prop.* / char.creature with "
                    "this palette and these proportions instead")
    return {
        "path": str(ctx.resolve(path)),
        "image_size": [w, h],
        **stats,
        "contours": len(loops),
        "palette": palette,
        "approach": approach,
        "note": "symmetry near 1.0 means left-right symmetric (front views, emblems); "
                "low values are natural for side-view creatures and action poses",
    }


@op(
    "image.to_mesh",
    summary="Turn a concept image into a real 3D solid: extract the subject silhouette, extrude it with a bevelled rim, and map the source image onto the front face as a texture (or bake it to vertex colours). Returns the silhouette IoU against the source — 'how close is the model to the picture' as a number, not a vibe. Emblems, totems, props, side-view creatures, relief work.",
    params={
        "path": ("path", None, "Concept image (alpha or uniform background)"),
        "name": ("str", "concept", "Object name"),
        "target_height": ("num", 1.0, "Silhouette height in metres; width follows the image aspect"),
        "depth": ("num", 0.25, "Extrusion depth in metres along the view axis"),
        "bevel": ("num", 0.02, "Rim chamfer — catches light so the edge reads; 0 disables"),
        "texture": ("enum:project|vertex|none", "project", "project: map the source image on the front face; vertex: bake nearest pixel colours to COLOR_0; none: flat palette material"),
        "simplify": ("num", 1.5, "Contour simplification tolerance in working pixels — higher is fewer vertices and smoother shapes"),
        "threshold": ("num", 0.06, "Background distance cutoff (no alpha)"),
        "seed": ("int", 0, "Random seed (reserved; the mesh is a pure function of the image)"),
    },
    tags=["build", "image"],
)
def image_to_mesh(ctx, path, name, target_height, depth, bevel, texture, simplify,
                  threshold, seed):
    ctx.reseed(seed)
    cells, w, h, rgb, subject = _load_subject(ctx.resolve(path), threshold)
    stats = _mask_stats(cells, w, h)
    loops = _boundary_loops(cells)
    if not loops:
        raise OpError("subject found but no closed silhouette — try a larger threshold")
    loops.sort(key=len, reverse=True)
    contour = _simplify(loops[0], max(0.5, simplify))
    if len(contour) < 3:
        raise OpError("silhouette simplified to nothing — lower simplify")

    min_x, min_y, max_x, max_y = stats["bbox_cells"]
    bw = max_x - min_x + 1
    scale = target_height / max(1, (max_y - min_y + 1))
    # Image space -> metres: x to the right, z up (image y grows downward).
    points = [((cx - (min_x + bw / 2.0)) * scale, (max_y - cy - (max_y - min_y + 1) / 2.0) * scale)
              for cx, cy in contour]

    from mathutils.geometry import tessellate_polygon

    triangles = tessellate_polygon([points])
    if not triangles:
        raise OpError("silhouette could not be triangulated — try a higher simplify")

    bm = mesh_lib.new_bmesh()
    half = depth * 0.5
    front = [bm.verts.new((x, -half, z)) for x, z in points]
    back = [bm.verts.new((x, half, z)) for x, z in points]
    n = len(points)
    for tri in triangles:
        bm.faces.new([front[tri[2]], front[tri[1]], front[tri[0]]])
        bm.faces.new([back[tri[0]], back[tri[1]], back[tri[2]]])
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([front[i], front[j], back[j], back[i]])

    if bevel > 0:
        caps = set()
        for face in bm.faces:
            if len(face.verts) == 3:
                caps.add(face)
        rim = [e for e in bm.edges
               if len(e.link_faces) == 2
               and (e.link_faces[0] in caps) != (e.link_faces[1] in caps)]
        if rim:
            mesh_lib.bevel_edges(bm, edges=rim, offset=min(bevel, depth * 0.3), segments=2)

    obj = mesh_lib.to_object(bm, scene_lib.unique_name(name))

    # UVs: caps map image space 1:1 (the concept art lands exactly on the
    # front face); the rim stretches the edge texels, which is the correct look.
    uv_layer = obj.data.uv_layers.new(name="UVMap")
    loop_uvs = {}
    for face in obj.data.polygons:
        is_cap = abs(face.normal.y) > 0.5
        for loop_index in face.loop_indices:
            vertex = obj.data.vertices[obj.data.loops[loop_index].vertex_index].co
            if is_cap:
                u = vertex.x / (bw * scale) + 0.5
                v = vertex.z / ((max_y - min_y + 1) * scale) + 0.5
            else:
                u = (vertex.x + vertex.z) / max(bw * scale, 1e-6) + 0.5
                v = (vertex.y + half) / max(depth, 1e-6)
            loop_uvs[loop_index] = (u, v)
    for loop_index, uv in loop_uvs.items():
        uv_layer.data[loop_index].uv = uv

    palette = _palette(rgb, subject, 1)
    base_hex = palette[0]["hex"] if palette else "#888888"
    if texture == "project":
        mat = mat_lib.principled(f"m_{obj.name}_concept", color=(1, 1, 1, 1), roughness=0.75)
        tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex_node.image = bpy.data.images.load(str(ctx.resolve(path)), check_existing=True)
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        mat.node_tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        finish_lib.finish(ctx, obj, material=mat, uv=None, origin="center",
                          smooth=True, smooth_angle=40.0)
    elif texture == "vertex":
        _bake_vertex_colors(ctx, obj, points, half, rgb, subject, w, h, stats, scale, bw)
        mat = mat_lib.principled(f"m_{obj.name}_concept", color=(1, 1, 1, 1), roughness=0.75)
        finish_lib.finish(ctx, obj, material=mat, uv=None, origin="center",
                          smooth=True, smooth_angle=40.0)
    else:
        mat = mat_lib.principled(f"m_{obj.name}_concept", color=base_hex, roughness=0.75)
        finish_lib.finish(ctx, obj, material=mat, uv=None, origin="center",
                          smooth=True, smooth_angle=40.0)

    filled = _rasterize(contour, w, h)
    intersection = len(filled & cells)
    union = len(filled | cells)
    iou = intersection / max(1, union)
    if len(loops) > 1:
        ctx.note(
            f"{len(loops) - 1} smaller separate silhouettes were dropped (kept the "
            "largest). Extrude them as their own meshes if they matter."
        )
    return {
        "object": obj.name,
        "triangles": mesh_lib.tri_count(obj),
        "contour_vertices": len(contour),
        "silhouette_iou": round(iou, 3),
        "palette": _palette(rgb, subject, 5),
        "approach": "extrusion",
        "bounds": mesh_lib.bounds(obj),
        "note": "IoU 1.0 = the model's silhouette IS the picture's. Below ~0.8 the "
                "outline lost detail — lower simplify and re-run",
    }


def _bake_vertex_colors(ctx, obj, points, half, rgb, subject, w, h, stats, scale, bw):
    """Nearest-source-pixel colour per vertex, in a COLOR_0-ready attribute."""
    import numpy

    min_x, min_y, max_x, max_y = stats["bbox_cells"]
    ys, xs = numpy.nonzero(subject)
    attr = obj.data.color_attributes.new(name="color", type="BYTE_COLOR", domain="POINT")
    mesh_scale = max(1, max(w, h) / max(1, WORK_RES) )
    for index, vertex in enumerate(obj.data.vertices):
        cx = int((vertex.co.x / scale + bw / 2.0 + min_x) * mesh_scale)
        cy = int((max_y - (vertex.co.z / scale + (max_y - min_y + 1) / 2.0)) * mesh_scale)
        distance = (xs - cx) ** 2 + (ys - cy) ** 2
        nearest = int(distance.argmin()) if len(distance) else 0
        color = rgb[ys[nearest], xs[nearest]] if len(distance) else (0.5, 0.5, 0.5)
        # The attribute stores scene-linear floats; the source samples are sRGB.
        attr.data[index].color = (
            _srgb_to_linear(float(color[0])), _srgb_to_linear(float(color[1])),
            _srgb_to_linear(float(color[2])), 1.0,
        )
