"""Materials: glTF-safe PBR, procedural node graphs, and baking.

Two tiers on purpose.

**Tier 1 — Principled + image textures.** Exports to glTF verbatim, so this is
the default and what every recipe emits. The repo's own asset validator
(ADR 0006) rejects anything else, correctly.

**Tier 2 — procedural node graphs.** Noise/voronoi/gradient networks that make
a rock look like rock without an artist painting it. These *cannot* export, so
`bake_material` renders them down into Tier 1 image textures. The bake step is
what turns "procedural" from a Blender-only party trick into a shippable asset.
"""

from __future__ import annotations

import math

import bpy

# A deliberately small, harmonised palette. Stylised game art lives or dies on
# palette discipline; giving the agent 12 coherent colours beats letting it pick
# 12 random ones per asset and wondering why the scene looks like a bag of
# sweets.
PALETTE = {
    "stone_grey": (0.42, 0.43, 0.45, 1.0),
    "stone_warm": (0.55, 0.50, 0.43, 1.0),
    "wood_oak": (0.36, 0.22, 0.11, 1.0),
    "wood_dark": (0.18, 0.11, 0.07, 1.0),
    "iron": (0.29, 0.30, 0.33, 1.0),
    "bronze": (0.55, 0.33, 0.15, 1.0),
    "gold": (0.83, 0.63, 0.22, 1.0),
    "cloth_red": (0.48, 0.11, 0.10, 1.0),
    "cloth_blue": (0.13, 0.21, 0.42, 1.0),
    "leaf_green": (0.19, 0.36, 0.14, 1.0),
    "sand": (0.68, 0.58, 0.40, 1.0),
    "ice_blue": (0.55, 0.75, 0.85, 1.0),
    "crystal_violet": (0.44, 0.25, 0.72, 1.0),
    "ember": (0.95, 0.42, 0.10, 1.0),
    "bone": (0.79, 0.75, 0.65, 1.0),
    "rubber_black": (0.05, 0.05, 0.06, 1.0),
}

# Physically sane starting points, so an agent asking for "metal" gets metal.
PRESETS = {
    "stone":   {"color": "stone_grey", "roughness": 0.85, "metallic": 0.0},
    "rock":    {"color": "stone_warm", "roughness": 0.92, "metallic": 0.0},
    "wood":    {"color": "wood_oak", "roughness": 0.70, "metallic": 0.0},
    "metal":   {"color": "iron", "roughness": 0.38, "metallic": 1.0},
    "iron":    {"color": "iron", "roughness": 0.45, "metallic": 1.0},
    "bronze":  {"color": "bronze", "roughness": 0.35, "metallic": 1.0},
    "gold":    {"color": "gold", "roughness": 0.22, "metallic": 1.0},
    "cloth":   {"color": "cloth_red", "roughness": 0.95, "metallic": 0.0},
    "leaf":    {"color": "leaf_green", "roughness": 0.75, "metallic": 0.0},
    "sand":    {"color": "sand", "roughness": 1.00, "metallic": 0.0},
    "ice":     {"color": "ice_blue", "roughness": 0.12, "metallic": 0.0},
    "crystal": {"color": "crystal_violet", "roughness": 0.08, "metallic": 0.0, "emission": 0.35},
    "emissive": {"color": "ember", "roughness": 0.5, "metallic": 0.0, "emission": 3.0},
    "bone":    {"color": "bone", "roughness": 0.68, "metallic": 0.0},
    "rubber":  {"color": "rubber_black", "roughness": 0.92, "metallic": 0.0},
}


def srgb_to_linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def resolve_color(value) -> tuple:
    if isinstance(value, str):
        if value in PALETTE:
            # PALETTE is authored in sRGB, the space an artist picks colours in.
            # Blender's colour sockets are LINEAR. Feeding sRGB values straight
            # in makes every palette colour render roughly 40% too bright and
            # washed out — and it silently disagreed with hex colours, which
            # were being converted. Same treatment for both.
            rgba = PALETTE[value]
            return (*(srgb_to_linear(c) for c in rgba[:3]), rgba[3])
        if value.startswith("#"):
            return hex_to_rgba(value)
        raise ValueError(
            f"unknown colour '{value}'. Use a hex string like '#8899aa' or one of: "
            + ", ".join(sorted(PALETTE))
        )
    if isinstance(value, (list, tuple)):
        parts = [float(v) for v in value]
        return tuple(parts + [1.0]) if len(parts) == 3 else tuple(parts[:4])
    raise ValueError(f"cannot interpret colour: {value!r}")


def hex_to_rgba(text: str) -> tuple:
    text = text.lstrip("#")
    if len(text) not in (6, 8):
        raise ValueError(f"hex colour must be #RRGGBB or #RRGGBBAA, got '#{text}'")
    channels = [int(text[i : i + 2], 16) / 255.0 for i in range(0, len(text), 2)]
    # sRGB -> linear: Blender's colour sockets are linear, and skipping this is
    # why AI-made assets so often come out washed out.
    linear = [srgb_to_linear(c) for c in channels[:3]]
    alpha = channels[3] if len(channels) == 4 else 1.0
    return (*linear, alpha)


def principled(
    name: str,
    color=(0.8, 0.8, 0.8, 1.0),
    roughness=0.6,
    metallic=0.0,
    emission=0.0,
    emission_color=None,
    alpha=1.0,
    ior=1.45,
):
    rgba_requested = resolve_color(color)
    wanted = (
        tuple(round(c, 4) for c in rgba_requested),
        round(float(roughness), 4), round(float(metallic), 4),
        round(float(emission), 4), round(float(alpha), 4),
    )
    existing = bpy.data.materials.get(name)
    if existing is not None:
        if _describes(existing) == wanted:
            return existing
        # Same name, different appearance. Returning the cached one silently
        # hands back the WRONG colour — which is exactly what happened when a
        # scene asked for m_stone in grey after an earlier call made it warm,
        # and every stone surface in the build came out the same shade.
        # Make a deterministic variant instead; material.consolidate merges
        # any that really are identical later.
        index = 2
        while f"{name}_{index}" in bpy.data.materials:
            candidate = bpy.data.materials[f"{name}_{index}"]
            if _describes(candidate) == wanted:
                return candidate
            index += 1
        name = f"{name}_{index}"
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    bsdf = tree.nodes.get("Principled BSDF")
    rgba = rgba_requested
    _set(bsdf, "Base Color", rgba)
    _set(bsdf, "Roughness", float(roughness))
    _set(bsdf, "Metallic", float(metallic))
    _set(bsdf, "IOR", float(ior))
    _set(bsdf, "Alpha", float(alpha))
    if emission > 0.0:
        _set(bsdf, "Emission Color", resolve_color(emission_color or color))
        _set(bsdf, "Emission Strength", float(emission))
    if alpha < 1.0:
        material.blend_method = "BLEND" if hasattr(material, "blend_method") else material.blend_method
    material["bforge_preset"] = name
    return material


def from_preset(preset: str, name=None, color=None, roughness=None, metallic=None):
    if preset not in PRESETS:
        raise ValueError(
            f"unknown material preset '{preset}'. Available: {', '.join(sorted(PRESETS))}"
        )
    spec = dict(PRESETS[preset])
    return principled(
        name or f"m_{preset}",
        color=color if color is not None else spec["color"],
        roughness=spec["roughness"] if roughness is None else roughness,
        metallic=spec["metallic"] if metallic is None else metallic,
        emission=spec.get("emission", 0.0),
    )


def _describes(material):
    """The appearance tuple used to tell a cache hit from a name collision."""
    if not material.use_nodes:
        return None
    bsdf = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return None

    def value(socket_name, default=0.0):
        socket = bsdf.inputs.get(socket_name)
        if socket is None or socket.is_linked:
            return default
        try:
            return round(float(socket.default_value), 4)
        except TypeError:
            return tuple(round(float(v), 4) for v in socket.default_value)

    base = value("Base Color", (0.0, 0.0, 0.0, 1.0))
    if bsdf.inputs.get("Base Color") is not None and bsdf.inputs["Base Color"].is_linked:
        # A texture-linked base (e.g. after material.bake_pbr) has no socket
        # value; the viewport colour is the authored readback instead of black.
        base = tuple(round(float(c), 4) for c in material.diffuse_color)
    if not isinstance(base, tuple):
        base = (base, base, base, 1.0)
    return (
        base, value("Roughness"), value("Metallic"),
        value("Emission Strength"), value("Alpha", 1.0),
    )


def _set(node, socket_name: str, value) -> None:
    socket = node.inputs.get(socket_name)
    if socket is None:
        return
    try:
        socket.default_value = value
    except (TypeError, ValueError):
        try:
            socket.default_value = value[0]
        except Exception:  # noqa: BLE001 — socket shape mismatch is non-fatal
            pass


def assign(obj, material, slot=0):
    mesh = obj.data
    while len(mesh.materials) <= slot:
        mesh.materials.append(None)
    mesh.materials[slot] = material
    return material


def assign_to_faces(obj, material, face_indices):
    """Second material slot on a face subset — trim, emissive panels, decals."""
    mesh = obj.data
    if material.name not in [m.name for m in mesh.materials if m]:
        mesh.materials.append(material)
    slot = [i for i, m in enumerate(mesh.materials) if m and m.name == material.name][0]
    for index in face_indices:
        if 0 <= index < len(mesh.polygons):
            mesh.polygons[index].material_index = slot
    mesh.update()
    return slot


# ---------------------------------------------------------------------------
# procedural graphs (tier 2 — must be baked before export)
# ---------------------------------------------------------------------------


def procedural(name: str, kind: str, color_a, color_b, scale=5.0, detail=2.0, roughness=0.7,
               metallic=0.0, distortion=0.0):
    """Build a noise/voronoi/gradient-driven Principled material.

    Kinds: noise (rock, dirt), voronoi (cracked stone, scales, crystal),
    wave (wood grain, strata), gradient (vertical fade, moss line),
    checker (blockout/UV-debug).
    """
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    bsdf = nodes.get("Principled BSDF")

    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-900, 0)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-720, 0)
    links.new(coord.outputs["Object"], mapping.inputs["Vector"])

    if kind == "noise":
        tex = nodes.new("ShaderNodeTexNoise")
        _set(tex, "Scale", scale)
        _set(tex, "Detail", detail)
        _set(tex, "Distortion", distortion)
        factor = tex.outputs["Fac"]
    elif kind == "voronoi":
        tex = nodes.new("ShaderNodeTexVoronoi")
        _set(tex, "Scale", scale)
        tex.feature = "F1"
        factor = tex.outputs["Distance"]
    elif kind == "wave":
        tex = nodes.new("ShaderNodeTexWave")
        _set(tex, "Scale", scale)
        _set(tex, "Distortion", max(distortion, 6.0))
        _set(tex, "Detail", detail)
        tex.wave_type = "BANDS"
        factor = tex.outputs["Fac"]
    elif kind == "gradient":
        tex = nodes.new("ShaderNodeTexGradient")
        tex.gradient_type = "LINEAR"
        factor = tex.outputs["Fac"]
    elif kind == "checker":
        tex = nodes.new("ShaderNodeTexChecker")
        _set(tex, "Scale", scale)
        factor = tex.outputs["Fac"]
    else:
        raise ValueError(
            f"unknown procedural kind '{kind}' "
            "(noise | voronoi | wave | gradient | checker)"
        )
    tex.location = (-520, 0)
    links.new(mapping.outputs["Vector"], tex.inputs["Vector"])

    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-300, 0)
    ramp.color_ramp.elements[0].color = resolve_color(color_a)
    ramp.color_ramp.elements[1].color = resolve_color(color_b)
    links.new(factor, ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    # Vary roughness with the same signal — uniform roughness is the #1 tell of
    # a procedurally-generated material.
    rough_ramp = nodes.new("ShaderNodeValToRGB")
    rough_ramp.location = (-300, -260)
    rough_ramp.color_ramp.elements[0].color = (
        max(0.0, roughness - 0.18), max(0.0, roughness - 0.18), max(0.0, roughness - 0.18), 1.0
    )
    rough_ramp.color_ramp.elements[1].color = (
        min(1.0, roughness + 0.18), min(1.0, roughness + 0.18), min(1.0, roughness + 0.18), 1.0
    )
    links.new(factor, rough_ramp.inputs["Fac"])
    links.new(rough_ramp.outputs["Color"], bsdf.inputs["Roughness"])
    _set(bsdf, "Metallic", metallic)

    bump = nodes.new("ShaderNodeBump")
    bump.location = (-300, -520)
    _set(bump, "Strength", 0.25)
    links.new(factor, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    material["bforge_procedural"] = kind
    return material


def layered_pbr(
    name,
    base_color,
    roughness=0.75,
    metallic=0.0,
    detail_scale=14.0,
    grain=0.55,
    edge_wear=0.55,
    edge_color=None,
    cavity_dirt=0.5,
    dirt_color="#2b2118",
    bump=0.35,
    seed=0,
):
    """An AAA-style layered surface: base, edge wear, cavity dirt, micro-detail.

    This is the difference between a flat-shaded prop and a Diablo-grade one.
    Three signals do almost all the work, and none of them is hand-painted:

    * **Pointiness** (mesh curvature) isolates convex edges. Real objects are
      abraded where they stick out — corners lighten, paint rubs off, stone
      chips. Driving a lighter, smoother layer with it makes every silhouette
      edge catch light.
    * **Ambient occlusion** isolates cavities. Dirt, soot and moss settle where
      water and air do not reach, so an AO-masked dark layer instantly reads as
      "this has been outdoors for a century".
    * **Layered noise** at two frequencies breaks up the uniform albedo and,
      more importantly, the uniform ROUGHNESS. Constant roughness is the single
      loudest tell of a procedurally-made material.

    The graph is Cycles-only by design — it must be baked (`bake_pbr_set`) into
    image maps before it can ship, which is exactly the high-to-low workflow a
    game artist would use.
    """
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    bsdf = nodes.get("Principled BSDF")
    # The metal family is a scalar per piece - corroded bronze cuirass, iron
    # sickle. It MUST land on the Principled here: the bake passes carry no
    # metallic channel, so wire_pbr_set can only preserve a scalar that exists.
    _set(bsdf, "Metallic", float(metallic))
    base_rgba = resolve_color(base_color)
    # Worn stone is POLISHED, not bleached. Lifting the albedo a third of the
    # way to white made every angular prop read as chalk, because on a faceted
    # mesh almost every edge is convex and the mask covers the whole surface.
    # Most of the wear signal belongs in roughness; only a little in albedo.
    worn_rgba = resolve_color(edge_color) if edge_color else _lighten(base_rgba, 0.14)
    dirt_rgba = resolve_color(dirt_color)

    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = (-1500, 400)
    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-1500, -200)

    # --- micro detail: two octaves, deliberately different scales ---------
    coarse = nodes.new("ShaderNodeTexNoise")
    coarse.location = (-1280, -120)
    _set(coarse, "Scale", detail_scale * 0.35)
    _set(coarse, "Detail", 6.0)
    _set(coarse, "Roughness", 0.55)
    _set(coarse, "W", float(seed))
    links.new(coord.outputs["Object"], coarse.inputs["Vector"])

    fine = nodes.new("ShaderNodeTexNoise")
    fine.location = (-1280, -360)
    _set(fine, "Scale", detail_scale * 3.1)
    _set(fine, "Detail", 8.0)
    _set(fine, "W", float(seed) + 3.0)
    links.new(coord.outputs["Object"], fine.inputs["Vector"])

    detail_mix = nodes.new("ShaderNodeMix")
    detail_mix.data_type = "FLOAT"
    detail_mix.location = (-1060, -240)
    _set(detail_mix, "Factor", 0.42)
    links.new(coarse.outputs["Fac"], detail_mix.inputs[2])
    links.new(fine.outputs["Fac"], detail_mix.inputs[3])

    # A third, very low-frequency octave. Micro-grain alone reads as sandpaper;
    # what makes stone look like stone is BLOTCHING at the scale of the object —
    # mineral patches, damp, weathering that varies across a whole face.
    blotch = nodes.new("ShaderNodeTexNoise")
    blotch.location = (-1280, 120)
    _set(blotch, "Scale", max(0.4, detail_scale * 0.075))
    _set(blotch, "Detail", 3.0)
    _set(blotch, "Roughness", 0.7)
    _set(blotch, "W", float(seed) + 11.0)
    links.new(coord.outputs["Object"], blotch.inputs["Vector"])

    blotch_ramp = nodes.new("ShaderNodeValToRGB")
    blotch_ramp.location = (-1060, 40)
    blotch_ramp.color_ramp.elements[0].position = 0.34
    blotch_ramp.color_ramp.elements[1].position = 0.68
    links.new(blotch.outputs["Fac"], blotch_ramp.inputs["Fac"])

    # --- edge wear from curvature ----------------------------------------
    # Pointiness is exactly 0.5 on a flat surface and rises on convex edges. The
    # ramp must sit in a TIGHT band just above 0.5, or a smooth cylinder reads as
    # uniformly abraded and the whole asset washes out to bone white.
    curvature = nodes.new("ShaderNodeValToRGB")
    curvature.location = (-1060, 420)
    curvature.color_ramp.elements[0].position = 0.512
    curvature.color_ramp.elements[1].position = 0.512 + max(0.012, 0.055 * (1.0 - edge_wear))
    links.new(geometry.outputs["Pointiness"], curvature.inputs["Fac"])

    # Break the wear up with noise so it is not a clean vector outline.
    # Modulate the curvature mask by noise MULTIPLICATIVELY. Mixing toward the
    # noise instead adds a constant floor (noise averages ~0.5), so every flat
    # surface picked up ~20% wear and the whole asset bleached out.
    wear_mask = nodes.new("ShaderNodeMath")
    wear_mask.operation = "MULTIPLY"
    wear_mask.location = (-840, 420)
    links.new(curvature.outputs["Color"], wear_mask.inputs[0])
    links.new(detail_mix.outputs[0], wear_mask.inputs[1])

    wear_strength = nodes.new("ShaderNodeMath")
    wear_strength.operation = "MULTIPLY"
    wear_strength.location = (-640, 420)
    wear_strength.inputs[1].default_value = edge_wear
    links.new(wear_mask.outputs[0], wear_strength.inputs[0])

    # --- cavity dirt from ambient occlusion -------------------------------
    occlusion = nodes.new("ShaderNodeAmbientOcclusion")
    occlusion.location = (-1060, 140)
    occlusion.samples = 8
    _set(occlusion, "Distance", 0.35)

    cavity = nodes.new("ShaderNodeValToRGB")
    cavity.location = (-840, 140)
    cavity.color_ramp.elements[0].position = 0.05
    cavity.color_ramp.elements[1].position = 0.62
    cavity.color_ramp.elements[0].color = (1.0, 1.0, 1.0, 1.0)
    cavity.color_ramp.elements[1].color = (0.0, 0.0, 0.0, 1.0)
    links.new(occlusion.outputs["Color"], cavity.inputs["Fac"])

    dirt_strength = nodes.new("ShaderNodeMath")
    dirt_strength.operation = "MULTIPLY"
    dirt_strength.location = (-640, 140)
    dirt_strength.inputs[1].default_value = cavity_dirt
    links.new(cavity.outputs["Color"], dirt_strength.inputs[0])

    # --- albedo stack: base -> tinted by noise -> dirt -> edge wear -------
    # Blotch first (big patches), then micro-grain on top of it.
    blotched = nodes.new("ShaderNodeMix")
    blotched.data_type = "RGBA"
    blotched.location = (-840, -160)
    _set(blotched, "Factor", 0.85)
    blotched.inputs[6].default_value = _darken(base_rgba, 0.40)
    blotched.inputs[7].default_value = _lighten(base_rgba, 0.10)
    links.new(blotch_ramp.outputs["Color"], blotched.inputs[0])

    tinted = nodes.new("ShaderNodeMix")
    tinted.data_type = "RGBA"
    tinted.location = (-640, -160)
    _set(tinted, "Factor", grain * 0.55)
    tinted.inputs[7].default_value = _darken(base_rgba, 0.55)
    links.new(detail_mix.outputs[0], tinted.inputs[0])
    links.new(blotched.outputs[2], tinted.inputs[6])

    with_dirt = nodes.new("ShaderNodeMix")
    with_dirt.data_type = "RGBA"
    with_dirt.location = (-420, -60)
    with_dirt.inputs[7].default_value = dirt_rgba
    links.new(dirt_strength.outputs[0], with_dirt.inputs[0])
    links.new(tinted.outputs[2], with_dirt.inputs[6])

    # Albedo sees a fraction of the wear; roughness sees all of it.
    wear_albedo = nodes.new("ShaderNodeMath")
    wear_albedo.operation = "MULTIPLY"
    wear_albedo.location = (-420, 300)
    wear_albedo.inputs[1].default_value = 0.40
    links.new(wear_strength.outputs[0], wear_albedo.inputs[0])

    with_wear = nodes.new("ShaderNodeMix")
    with_wear.data_type = "RGBA"
    with_wear.location = (-220, 60)
    with_wear.inputs[7].default_value = worn_rgba
    links.new(wear_albedo.outputs[0], with_wear.inputs[0])
    links.new(with_dirt.outputs[2], with_wear.inputs[6])
    links.new(with_wear.outputs[2], bsdf.inputs["Base Color"])

    # --- roughness: never constant ----------------------------------------
    rough_noise = nodes.new("ShaderNodeMapRange")
    rough_noise.location = (-420, -420)
    _set(rough_noise, "To Min", max(0.05, roughness - 0.24))
    _set(rough_noise, "To Max", min(1.0, roughness + 0.16))
    links.new(detail_mix.outputs[0], rough_noise.inputs["Value"])

    # Worn edges are polished smoother than the surface around them.
    rough_final = nodes.new("ShaderNodeMix")
    rough_final.data_type = "FLOAT"
    rough_final.location = (-220, -420)
    rough_final.inputs[3].default_value = max(0.04, roughness * 0.42)
    links.new(wear_strength.outputs[0], rough_final.inputs[0])
    links.new(rough_noise.outputs["Result"], rough_final.inputs[2])
    links.new(rough_final.outputs[0], bsdf.inputs["Roughness"])
    _set(bsdf, "Metallic", metallic)

    # --- surface relief ----------------------------------------------------
    relief = nodes.new("ShaderNodeBump")
    relief.location = (-220, -680)
    _set(relief, "Strength", bump)
    _set(relief, "Distance", 0.04)
    links.new(detail_mix.outputs[0], relief.inputs["Height"])
    links.new(relief.outputs["Normal"], bsdf.inputs["Normal"])

    material["bforge_procedural"] = "layered_pbr"
    return material


def _torus_coords(tree, tiles=1.0):
    """UV -> a point on a torus, so 3D noise sampled there tiles seamlessly.

    Blender's noise textures are not periodic, so baking one straight to a map
    leaves a visible seam wherever it repeats. Wrapping UV around a torus makes
    the sample point return to itself at u=1 and v=1 by construction, which
    makes the baked result tile perfectly in both axes.

    This is what lets a 725 m stadium be textured from one 1k map. Baking a
    unique map for a building that size gives roughly 3 px/m, which is no
    texture at all.
    """
    nodes, links = tree.nodes, tree.links
    uv = nodes.new("ShaderNodeUVMap")
    uv.location = (-2200, 0)
    scaled = nodes.new("ShaderNodeVectorMath")
    scaled.operation = "MULTIPLY"
    scaled.location = (-2040, 0)
    scaled.inputs[1].default_value = (tiles, tiles, 0.0)
    links.new(uv.outputs["UV"], scaled.inputs[0])

    split = nodes.new("ShaderNodeSeparateXYZ")
    split.location = (-1880, 0)
    links.new(scaled.outputs["Vector"], split.inputs["Vector"])

    def angle(component, offset_y):
        turn = nodes.new("ShaderNodeMath")
        turn.operation = "MULTIPLY"
        turn.location = (-1720, offset_y)
        turn.inputs[1].default_value = math.tau
        links.new(component, turn.inputs[0])
        sine = nodes.new("ShaderNodeMath")
        sine.operation = "SINE"
        sine.location = (-1560, offset_y)
        links.new(turn.outputs[0], sine.inputs[0])
        cosine = nodes.new("ShaderNodeMath")
        cosine.operation = "COSINE"
        cosine.location = (-1560, offset_y - 120)
        links.new(turn.outputs[0], cosine.inputs[0])
        return sine, cosine

    sin_u, cos_u = angle(split.outputs["X"], 220)
    sin_v, cos_v = angle(split.outputs["Y"], -220)

    # radius = 1 + 0.25*cos(v): a fat torus, so both axes get similar feature
    # sizes instead of one being visibly stretched.
    ring = nodes.new("ShaderNodeMath")
    ring.operation = "MULTIPLY_ADD"
    ring.location = (-1400, -220)
    ring.inputs[1].default_value = 0.25
    ring.inputs[2].default_value = 1.0
    links.new(cos_v.outputs[0], ring.inputs[0])

    def planar(trig, offset_y):
        product = nodes.new("ShaderNodeMath")
        product.operation = "MULTIPLY"
        product.location = (-1240, offset_y)
        links.new(ring.outputs[0], product.inputs[0])
        links.new(trig.outputs[0], product.inputs[1])
        return product

    x_axis = planar(cos_u, 120)
    y_axis = planar(sin_u, -40)
    z_axis = nodes.new("ShaderNodeMath")
    z_axis.operation = "MULTIPLY"
    z_axis.location = (-1240, -340)
    z_axis.inputs[1].default_value = 0.25
    links.new(sin_v.outputs[0], z_axis.inputs[0])

    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.location = (-1080, 0)
    links.new(x_axis.outputs[0], combine.inputs["X"])
    links.new(y_axis.outputs[0], combine.inputs["Y"])
    links.new(z_axis.outputs[0], combine.inputs["Z"])
    return combine.outputs["Vector"]


def tileable_pbr(name, base_color, roughness=0.78, metallic=0.0, detail_scale=6.0,
                 dirt_color="#2b2118", dirt=0.35, bump=0.4, tiles=1.0, seed=0):
    """A seamless surface for tiling onto architecture.

    Deliberately excludes the curvature and ambient-occlusion layers that
    `layered_pbr` uses. Those describe a specific MESH — where its edges are,
    where its crevices are — and cannot be baked into a texture meant to repeat
    across arbitrary geometry. Tileable maps carry material detail; per-object
    wear needs its own bake.
    """
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    bsdf = nodes.get("Principled BSDF")
    base_rgba = resolve_color(base_color)
    dirt_rgba = resolve_color(dirt_color)
    coords = _torus_coords(tree, tiles)

    def noise(scale, detail, offset_y, w):
        node = nodes.new("ShaderNodeTexNoise")
        node.location = (-900, offset_y)
        node.noise_dimensions = "3D"
        _set(node, "Scale", scale)
        _set(node, "Detail", detail)
        _set(node, "Roughness", 0.6)
        _set(node, "W", float(w))
        links.new(coords, node.inputs["Vector"])
        return node

    coarse = noise(detail_scale, 6.0, -100, seed)
    fine = noise(detail_scale * 4.2, 8.0, -320, seed + 5)
    blotch = noise(max(0.5, detail_scale * 0.28), 3.0, 160, seed + 11)

    detail_mix = nodes.new("ShaderNodeMix")
    detail_mix.data_type = "FLOAT"
    detail_mix.location = (-700, -200)
    _set(detail_mix, "Factor", 0.4)
    links.new(coarse.outputs["Fac"], detail_mix.inputs[2])
    links.new(fine.outputs["Fac"], detail_mix.inputs[3])

    # LOW-FREQUENCY CONTENT IS WHAT MAKES TILING VISIBLE. A big blotch is the
    # eye's anchor, so once the map repeats those blotches line up into an
    # obvious grid across the wall — which is exactly what happened on the first
    # textured hippodrome. A tiling map has to be dominated by high-frequency
    # detail; large-scale variation belongs per-object (vertex colour, a second
    # unique map), not in the thing that repeats.
    blotch_ramp = nodes.new("ShaderNodeValToRGB")
    blotch_ramp.location = (-700, 160)
    blotch_ramp.color_ramp.elements[0].position = 0.42
    blotch_ramp.color_ramp.elements[1].position = 0.60
    links.new(blotch.outputs["Fac"], blotch_ramp.inputs["Fac"])

    blotched = nodes.new("ShaderNodeMix")
    blotched.data_type = "RGBA"
    blotched.location = (-500, 60)
    blotched.inputs[6].default_value = _darken(base_rgba, 0.12)
    blotched.inputs[7].default_value = _lighten(base_rgba, 0.06)
    links.new(blotch_ramp.outputs["Color"], blotched.inputs[0])

    # Grain is the high-frequency signal that survives tiling without reading as
    # a repeat, so it carries most of the surface interest. Kept moderate: a
    # full swing to half-darkness stacks with the grime below and drags the whole
    # building down.
    grained = nodes.new("ShaderNodeMix")
    grained.data_type = "RGBA"
    grained.location = (-320, 0)
    grained.inputs[7].default_value = _darken(base_rgba, 0.28)
    links.new(detail_mix.outputs[0], grained.inputs[0])
    links.new(blotched.outputs[2], grained.inputs[6])

    # Grime settled in the dips reads as age even on a flat wall, where there is
    # no cavity for an AO pass to find. Driven by the FINE detail, not the
    # blotch, for the same tiling reason.
    grime = nodes.new("ShaderNodeMath")
    grime.operation = "MULTIPLY"
    grime.location = (-320, 280)
    grime.inputs[1].default_value = dirt * 0.5
    links.new(detail_mix.outputs[0], grime.inputs[0])

    with_dirt = nodes.new("ShaderNodeMix")
    with_dirt.data_type = "RGBA"
    with_dirt.location = (-140, 60)
    with_dirt.inputs[7].default_value = dirt_rgba
    links.new(grime.outputs[0], with_dirt.inputs[0])
    links.new(grained.outputs[2], with_dirt.inputs[6])
    links.new(with_dirt.outputs[2], bsdf.inputs["Base Color"])

    rough = nodes.new("ShaderNodeMapRange")
    rough.location = (-320, -420)
    _set(rough, "To Min", max(0.05, roughness - 0.22))
    _set(rough, "To Max", min(1.0, roughness + 0.14))
    links.new(detail_mix.outputs[0], rough.inputs["Value"])
    links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])
    _set(bsdf, "Metallic", metallic)

    relief = nodes.new("ShaderNodeBump")
    relief.location = (-140, -420)
    _set(relief, "Strength", bump)
    _set(relief, "Distance", 0.05)
    links.new(detail_mix.outputs[0], relief.inputs["Height"])
    links.new(relief.outputs["Normal"], bsdf.inputs["Normal"])

    material["bforge_procedural"] = "tileable_pbr"
    return material


def _lighten(rgba, amount):
    return tuple(min(1.0, c + (1.0 - c) * amount) for c in rgba[:3]) + (rgba[3],)


def _darken(rgba, amount):
    return tuple(max(0.0, c * (1.0 - amount)) for c in rgba[:3]) + (rgba[3],)


def bake_tileable_set(material, out_dir, stem, size=1024, samples=16,
                      maps=("base_color", "normal", "roughness")):
    """Bake a tileable material to seamless maps off a throwaway flat plane.

    A plane with exact 0..1 UVs and no curvature means the bake captures the
    material and nothing about any particular mesh — which is the whole point
    of a tiling texture. Margin is 0: a margin bleeds edge pixels outward and
    would break the seam the torus mapping just guaranteed.
    """
    scene = bpy.context.scene
    previous_engine = scene.render.engine
    scene.render.engine = "CYCLES"
    scene.cycles.samples = max(1, samples)
    if hasattr(scene.cycles, "device"):
        scene.cycles.device = "CPU"
    scene.render.bake.margin = 0
    scene.render.bake.use_clear = True

    mesh = bpy.data.meshes.new("_bforge_swatch")
    verts = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    layer = mesh.uv_layers.new(name="UVMap")
    for index, uv in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        layer.data[index].uv = uv
    plane = bpy.data.objects.new("_bforge_swatch", mesh)
    plane.data.materials.append(material)
    scene.collection.objects.link(plane)

    view_layer = bpy.context.view_layer
    previous_selection = [o for o in scene.objects if o.select_get()]
    previous_active = view_layer.objects.active
    for other in scene.objects:
        other.select_set(False)
    plane.select_set(True)
    view_layer.objects.active = plane

    produced = {}
    try:
        for map_name in maps:
            if map_name not in PBR_PASSES:
                continue
            bake_type, is_data = PBR_PASSES[map_name]
            image = bpy.data.images.new(
                f"{stem}_{map_name}", width=size, height=size,
                alpha=False, float_buffer=False, is_data=is_data,
            )
            node = material.node_tree.nodes.new("ShaderNodeTexImage")
            node.image = image
            node.location = (-2400, 600)
            node.select = True
            material.node_tree.nodes.active = node
            if bake_type == "DIFFUSE":
                scene.render.bake.use_pass_direct = False
                scene.render.bake.use_pass_indirect = False
                scene.render.bake.use_pass_color = True
            bpy.ops.object.bake(type=bake_type, use_clear=True, margin=0)
            path = f"{out_dir}/{stem}_{map_name}.png"
            image.filepath_raw = path
            image.file_format = "PNG"
            image.save()
            produced[map_name] = (image, path)
            material.node_tree.nodes.remove(node)
    finally:
        bpy.data.objects.remove(plane, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        for other in previous_selection:
            if other.name in scene.objects:
                other.select_set(True)
        view_layer.objects.active = previous_active
        scene.render.engine = previous_engine
    return produced


def tiled_material(name, produced, tiles=4.0, base_color=None):
    """A glTF-safe material that repeats baked maps across a surface."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    bsdf = nodes.get("Principled BSDF")
    if base_color is not None:
        _set(bsdf, "Base Color", resolve_color(base_color))

    uv = nodes.new("ShaderNodeUVMap")
    uv.location = (-900, 0)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-740, 0)
    _set(mapping, "Scale", (tiles, tiles, 1.0))
    links.new(uv.outputs["UV"], mapping.inputs["Vector"])

    row = 300
    for map_name, (image, _path) in produced.items():
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.extension = "REPEAT"
        tex.location = (-520, row)
        row -= 300
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        if map_name == "base_color":
            links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        elif map_name == "roughness":
            image.colorspace_settings.name = "Non-Color"
            links.new(tex.outputs["Color"], bsdf.inputs["Roughness"])
        elif map_name == "normal":
            image.colorspace_settings.name = "Non-Color"
            normal_map = nodes.new("ShaderNodeNormalMap")
            normal_map.location = (-260, row + 300)
            links.new(tex.outputs["Color"], normal_map.inputs["Color"])
            links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    return material


# Which Cycles pass produces each map, and whether it is colour or data.
PBR_PASSES = {
    "base_color": ("DIFFUSE", False),
    "roughness": ("ROUGHNESS", True),
    "normal": ("NORMAL", True),
    "ao": ("AO", False),
}


def bake_pbr_set(obj, out_dir, stem, size=1024, samples=24, margin=10,
                 maps=("base_color", "normal", "roughness", "ao")):
    """Bake a procedural material into a glTF-shippable PBR map set.

    Returns {map_name: (image, path)}. The material is rewired afterwards by
    `wire_pbr_set` so the exported asset carries real textures instead of a
    node graph glTF cannot express.
    """
    scene = bpy.context.scene
    previous_engine = scene.render.engine
    scene.render.engine = "CYCLES"
    scene.cycles.samples = max(1, samples)
    if hasattr(scene.cycles, "device"):
        scene.cycles.device = "CPU"
    scene.render.bake.margin = margin
    scene.render.bake.use_clear = True

    view_layer = bpy.context.view_layer
    previous_selection = [o for o in scene.objects if o.select_get()]
    previous_active = view_layer.objects.active
    for other in scene.objects:
        other.select_set(False)
    obj.select_set(True)
    view_layer.objects.active = obj

    produced = {}
    try:
        for map_name in maps:
            if map_name not in PBR_PASSES:
                continue
            bake_type, is_data = PBR_PASSES[map_name]
            image = bpy.data.images.new(
                f"{stem}_{map_name}", width=size, height=size,
                alpha=False, float_buffer=False, is_data=is_data,
            )
            targets = []
            for material in obj.data.materials:
                if material is None or not material.use_nodes:
                    continue
                node = material.node_tree.nodes.new("ShaderNodeTexImage")
                node.image = image
                node.location = (-1900, 600)
                node.select = True
                material.node_tree.nodes.active = node
                targets.append((material, node))
            if bake_type == "DIFFUSE":
                scene.render.bake.use_pass_direct = False
                scene.render.bake.use_pass_indirect = False
                scene.render.bake.use_pass_color = True
            bpy.ops.object.bake(type=bake_type, use_clear=True, margin=margin)
            path = f"{out_dir}/{stem}_{map_name}.png"
            image.filepath_raw = path
            image.file_format = "PNG"
            image.save()
            produced[map_name] = (image, path)
            for material, node in targets:
                material.node_tree.nodes.remove(node)
    finally:
        obj.select_set(False)
        for other in previous_selection:
            if other.name in scene.objects:
                other.select_set(True)
        view_layer.objects.active = previous_active
        scene.render.engine = previous_engine
    return produced


def wire_pbr_set(obj, produced):
    """Rebuild each material as a glTF-safe Principled + image texture stack."""
    wired = []
    for material in obj.data.materials:
        if material is None or not material.use_nodes:
            continue
        tree = material.node_tree
        # Capture what the rebuild drops: the authored metal family. Without
        # this, baked bronze exports metallicFactor 0 and reads as black clay
        # under IBL instead of metal.
        old_bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        metallic = 0.0
        if old_bsdf is not None:
            socket = old_bsdf.inputs.get("Metallic")
            if socket is not None and not socket.is_linked:
                metallic = float(socket.default_value)
        tree.nodes.clear()
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        output.location = (400, 0)
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (100, 0)
        bsdf.inputs["Metallic"].default_value = metallic
        tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
        uv = tree.nodes.new("ShaderNodeUVMap")
        uv.location = (-800, 0)

        row = 300
        for map_name, (image, _path) in produced.items():
            tex = tree.nodes.new("ShaderNodeTexImage")
            tex.image = image
            tex.location = (-560, row)
            row -= 280
            tree.links.new(uv.outputs["UV"], tex.inputs["Vector"])
            if map_name == "base_color":
                tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            elif map_name == "roughness":
                tex.image.colorspace_settings.name = "Non-Color"
                tree.links.new(tex.outputs["Color"], bsdf.inputs["Roughness"])
            elif map_name == "normal":
                tex.image.colorspace_settings.name = "Non-Color"
                normal_map = tree.nodes.new("ShaderNodeNormalMap")
                normal_map.location = (-300, row + 280)
                tree.links.new(tex.outputs["Color"], normal_map.inputs["Color"])
                tree.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
            elif map_name == "ao":
                # glTF carries AO as occlusionTexture; the Blender exporter's
                # convention for it is a node group named "glTF Material
                # Output" with an Occlusion input. Before this, the baked AO
                # was silently dropped and every crevice shipped flat.
                tex.image.colorspace_settings.name = "Non-Color"
                group_tree = bpy.data.node_groups.get("glTF Material Output")
                if group_tree is None:
                    group_tree = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
                    group_tree.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
                group = tree.nodes.new("ShaderNodeGroup")
                group.node_tree = group_tree
                group.location = (100, row + 560)
                tree.links.new(tex.outputs["Color"], group.inputs["Occlusion"])
        material.pop("bforge_procedural", None)
        wired.append(material.name)
    return wired


def is_gltf_safe(material) -> tuple[bool, list[str]]:
    """Mirror of the repo asset validator's allowlist, checked before export."""
    allowed = {
        "BSDF_PRINCIPLED", "TEX_IMAGE", "NORMAL_MAP", "UVMAP", "OUTPUT_MATERIAL",
        "MIX", "MIX_RGB", "SEPARATE_COLOR", "COMBINE_COLOR", "MAPPING", "TEX_COORD",
        "VERTEX_COLOR", "ATTRIBUTE", "VALUE", "RGB", "FRAME", "REROUTE",
    }
    if not material.use_nodes:
        return True, []
    offenders = sorted({
        n.type for n in material.node_tree.nodes
        if n.type not in allowed
        # The glTF exporter's own occlusion convention: a group named
        # "glTF Material Output" IS expressible — it maps to occlusionTexture.
        and not (n.type == "GROUP" and getattr(n.node_tree, "name", "") == "glTF Material Output")
    })
    return (not offenders), offenders


# ---------------------------------------------------------------------------
# baking — the bridge from tier 2 back to tier 1
# ---------------------------------------------------------------------------

BAKE_PASSES = {
    "base_color": ("DIFFUSE", {"use_pass_direct": False, "use_pass_indirect": False}),
    "normal": ("NORMAL", {}),
    "roughness": ("ROUGHNESS", {}),
    "ao": ("AO", {}),
    "emit": ("EMIT", {}),
    "combined": ("COMBINED", {}),
}


def bake_material(obj, out_path, size=1024, pass_name="base_color", samples=16, margin=8):
    """Bake `obj`'s material into an image and rewire it as a glTF-safe texture.

    Requires non-overlapping UVs — call `uvs.smart_project` + `uvs.pack` first.
    """
    if pass_name not in BAKE_PASSES:
        raise ValueError(f"unknown bake pass '{pass_name}' ({', '.join(BAKE_PASSES)})")
    if not obj.data.uv_layers:
        raise ValueError(
            f"'{obj.name}' has no UVs — bake needs a unique layout. "
            "Run uv.unwrap with style='smart_packed' first."
        )
    if not obj.data.materials or obj.data.materials[0] is None:
        raise ValueError(f"'{obj.name}' has no material to bake")

    scene = bpy.context.scene
    previous_engine = scene.render.engine
    scene.render.engine = "CYCLES"
    scene.cycles.samples = max(1, samples)
    if hasattr(scene.cycles, "device"):
        scene.cycles.device = "CPU"

    is_data = pass_name in ("normal", "roughness")
    image = bpy.data.images.new(
        f"{obj.name}_{pass_name}", width=size, height=size,
        alpha=False, float_buffer=False, is_data=is_data,
    )

    targets = []
    for material in obj.data.materials:
        if material is None or not material.use_nodes:
            continue
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        node.location = (-1200, 400)
        node.select = True
        material.node_tree.nodes.active = node
        targets.append((material, node))

    bake_type, flags = BAKE_PASSES[pass_name]
    for key, value in flags.items():
        setattr(scene.render.bake, key, value)
    scene.render.bake.margin = margin
    scene.render.bake.use_clear = True

    view_layer = bpy.context.view_layer
    previous_selection = [o for o in scene.objects if o.select_get()]
    previous_active = view_layer.objects.active
    for other in scene.objects:
        other.select_set(False)
    obj.select_set(True)
    view_layer.objects.active = obj
    try:
        bpy.ops.object.bake(type=bake_type, use_clear=True, margin=margin)
        image.filepath_raw = str(out_path)
        image.file_format = "PNG"
        image.save()
    finally:
        obj.select_set(False)
        for other in previous_selection:
            if other.name in scene.objects:
                other.select_set(True)
        view_layer.objects.active = previous_active
        scene.render.engine = previous_engine

    return {"image": image, "nodes": targets, "path": str(out_path)}


def rewire_baked(obj, image, pass_name="base_color"):
    """Replace a procedural graph with the baked texture so glTF can carry it."""
    rewired = []
    for material in obj.data.materials:
        if material is None or not material.use_nodes:
            continue
        tree = material.node_tree
        bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        for node in [n for n in tree.nodes if n.type not in
                     ("BSDF_PRINCIPLED", "OUTPUT_MATERIAL", "TEX_IMAGE", "NORMAL_MAP", "UVMAP")]:
            tree.nodes.remove(node)
        tex = next((n for n in tree.nodes if n.type == "TEX_IMAGE" and n.image == image), None)
        if tex is None:
            tex = tree.nodes.new("ShaderNodeTexImage")
            tex.image = image
        tex.location = (-400, 200)
        socket = {"base_color": "Base Color", "roughness": "Roughness", "emit": "Emission Color"}
        if pass_name == "normal":
            normal_map = tree.nodes.new("ShaderNodeNormalMap")
            normal_map.location = (-200, -200)
            tree.links.new(tex.outputs["Color"], normal_map.inputs["Color"])
            tree.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
        elif pass_name in socket:
            tree.links.new(tex.outputs["Color"], bsdf.inputs[socket[pass_name]])
        material.pop("bforge_procedural", None)
        rewired.append(material.name)
    return rewired


DETAIL_PASSES = {
    "normal": ("NORMAL", True),
    "ao": ("AO", True),
    "base_color": ("DIFFUSE", False),
}


def bake_detail(
    low_obj, high_objs, out_path, *, pass_name="normal", size=2048, samples=32,
    cage_extrusion=0.02, max_ray_distance=0.05, margin=8,
):
    """Bake detail from high-poly `high_objs` onto low-poly `low_obj` (selected-to-active).

    This is the transfer that makes a cheap mesh read as an expensive one: the
    silhouette stays low-poly, the surface detail arrives as a tangent-space
    normal map. `bake_material` cannot do it -- it bakes an object onto itself,
    so a normal pass there just reproduces the mesh's own flat normals.
    """
    if pass_name not in DETAIL_PASSES:
        raise ValueError(f"unknown detail pass '{pass_name}' ({', '.join(DETAIL_PASSES)})")
    if not high_objs:
        raise ValueError("bake_detail needs at least one high-poly source object")
    if low_obj in high_objs:
        raise ValueError(f"'{low_obj.name}' is both the low-poly target and a high-poly source")
    if not low_obj.data.uv_layers:
        raise ValueError(
            f"'{low_obj.name}' has no UVs -- a detail bake needs a unique layout. "
            "Run uv.unwrap with style='smart_packed' first."
        )
    if not low_obj.data.materials or low_obj.data.materials[0] is None:
        raise ValueError(f"'{low_obj.name}' has no material to hold the baked map")

    scene = bpy.context.scene
    previous_engine = scene.render.engine
    scene.render.engine = "CYCLES"
    scene.cycles.samples = max(1, samples)
    if hasattr(scene.cycles, "device"):
        scene.cycles.device = "CPU"

    bake_type, is_data = DETAIL_PASSES[pass_name]
    image = bpy.data.images.new(
        f"{low_obj.name}_{pass_name}_detail", width=size, height=size,
        alpha=False, float_buffer=False, is_data=is_data,
    )

    targets = []
    for material in low_obj.data.materials:
        if material is None or not material.use_nodes:
            continue
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        node.location = (-1200, 400)
        node.select = True
        material.node_tree.nodes.active = node
        targets.append((material, node))
    if not targets:
        bpy.data.images.remove(image)
        scene.render.engine = previous_engine
        raise ValueError(f"'{low_obj.name}' has no node-based material to bake into")

    bake = scene.render.bake
    previous_sta = bake.use_selected_to_active
    previous_cage = bake.cage_extrusion
    previous_ray = bake.max_ray_distance
    previous_margin = bake.margin

    view_layer = bpy.context.view_layer
    previous_selection = [o for o in scene.objects if o.select_get()]
    previous_active = view_layer.objects.active
    try:
        bake.use_selected_to_active = True
        bake.cage_extrusion = cage_extrusion
        bake.max_ray_distance = max_ray_distance
        bake.margin = margin
        bake.use_clear = True
        if pass_name == "normal":
            # Tangent space is what glTF and every engine expect; object space would
            # bake correctly and then light completely wrong once the mesh moves.
            bake.normal_space = "TANGENT"

        for other in scene.objects:
            other.select_set(False)
        for high in high_objs:
            high.select_set(True)
        # Selected-to-active bakes FROM the selected objects INTO the active one,
        # and the active object must itself be selected.
        low_obj.select_set(True)
        view_layer.objects.active = low_obj

        bpy.ops.object.bake(type=bake_type, use_clear=True, margin=margin)
        image.filepath_raw = str(out_path)
        image.file_format = "PNG"
        image.save()
    finally:
        # Leaving use_selected_to_active on would silently corrupt every later
        # bake_material call in the same session -- it would try to project from
        # whatever happened to be selected. Always put it back.
        bake.use_selected_to_active = previous_sta
        bake.cage_extrusion = previous_cage
        bake.max_ray_distance = previous_ray
        bake.margin = previous_margin
        for other in scene.objects:
            other.select_set(False)
        for other in previous_selection:
            if other.name in scene.objects:
                other.select_set(True)
        view_layer.objects.active = previous_active
        scene.render.engine = previous_engine

    return {"image": image, "nodes": targets, "path": str(out_path)}


def attach_baked_map(obj, image, pass_name="normal"):
    """Link a baked map into the existing material without demolishing it.

    `rewire_baked` deletes the procedural graph on purpose, because that is the
    whole point of baking a procedural material down. A detail bake is additive:
    the low-poly already has an albedo worth keeping, so only the new node and
    its link are introduced.
    """
    attached = []
    for material in obj.data.materials:
        if material is None or not material.use_nodes:
            continue
        tree = material.node_tree
        bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        tex = next((n for n in tree.nodes if n.type == "TEX_IMAGE" and n.image == image), None)
        if tex is None:
            tex = tree.nodes.new("ShaderNodeTexImage")
            tex.image = image
        tex.location = (-700, -200)
        if pass_name == "normal":
            normal_map = next(
                (n for n in tree.nodes if n.type == "NORMAL_MAP"
                 and n.inputs["Color"].is_linked
                 and n.inputs["Color"].links[0].from_node is tex),
                None,
            )
            if normal_map is None:
                normal_map = tree.nodes.new("ShaderNodeNormalMap")
                normal_map.location = (-400, -240)
                tree.links.new(tex.outputs["Color"], normal_map.inputs["Color"])
            tree.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
        elif pass_name == "base_color":
            tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        # AO has no Principled socket; it is carried as a texture for the engine
        # to consume (and for ORM packing later), so the node is left unlinked.
        attached.append(material.name)
    return attached
