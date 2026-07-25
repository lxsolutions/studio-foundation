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


def is_gltf_safe(material) -> tuple[bool, list[str]]:
    """Mirror of the repo asset validator's allowlist, checked before export."""
    allowed = {
        "BSDF_PRINCIPLED", "TEX_IMAGE", "NORMAL_MAP", "UVMAP", "OUTPUT_MATERIAL",
        "MIX", "MIX_RGB", "SEPARATE_COLOR", "COMBINE_COLOR", "MAPPING", "TEX_COORD",
        "VERTEX_COLOR", "ATTRIBUTE", "VALUE", "RGB", "FRAME", "REROUTE",
    }
    if not material.use_nodes:
        return True, []
    offenders = sorted({n.type for n in material.node_tree.nodes if n.type not in allowed})
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
