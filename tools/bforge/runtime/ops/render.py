"""Rendering — the feedback loop.

An agent that cannot see its own output is guessing. Every other Blender-AI
integration hands back a single viewport grab, which is enough to notice a
missing object and nothing else. The contact sheet here is built for critique:
one image containing a hero three-quarter view, orthographic front/side/top, a
wireframe pass that exposes topology and triangle waste, and a checker pass that
makes UV stretching and inconsistent texel density visible at a glance.

Renders go through Cycles on CPU by default because that is the only engine
guaranteed to work in background mode on a machine with no display server —
which includes CI, containers, and remote build boxes. EEVEE is offered for
speed where a GPU context exists, with an automatic fallback.
"""

from __future__ import annotations

import math
from pathlib import Path

import bpy
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from mathutils import Euler, Vector
from registry import OpError, op

VIEWS = {
    "hero": (math.radians(62), math.radians(0), math.radians(43)),
    "front": (math.radians(90), 0.0, 0.0),
    "back": (math.radians(90), 0.0, math.radians(180)),
    "left": (math.radians(90), 0.0, math.radians(-90)),
    "right": (math.radians(90), 0.0, math.radians(90)),
    "top": (0.0, 0.0, 0.0),
    "low": (math.radians(102), 0.0, math.radians(30)),
}


def _targets(names):
    if names:
        objs = []
        for name in names:
            try:
                objs.append(scene_lib.get_object(name))
            except ValueError as exc:
                raise OpError(str(exc)) from exc
        return objs
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objs:
        raise OpError("nothing to render — the scene has no mesh objects")
    return objs


def _bounding_sphere(objs):
    bpy.context.view_layer.update()  # world matrices must be current to frame anything
    points = []
    for obj in objs:
        if obj.type != "MESH":
            continue
        points.extend(obj.matrix_world @ Vector(c) for c in obj.bound_box)
    if not points:
        return Vector((0, 0, 0)), 1.0
    centre = sum(points, Vector((0, 0, 0))) / len(points)
    radius = max((p - centre).length for p in points) or 1.0
    return centre, radius


def _setup_world(strength=0.32):
    """Ambient dome.

    Kept deliberately low. A bright uniform dome lights every microfacet from
    every direction, which piles white specular sheen onto the albedo — at 0.6
    it measured as a +0.19 constant, enough to make saturated colours
    unreadable. Fidelity is measured by tests/test_fidelity.py.
    """
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.055, 0.06, 0.075, 1.0)
        background.inputs["Strength"].default_value = strength


def _setup_lights(centre, radius):
    """Three-point rig scaled to the subject.

    Fixed-position lights are the reason generated turntables come out either
    blown out or pitch black — the rig has to scale with the object.
    """
    for obj in [o for o in bpy.context.scene.objects if o.type == "LIGHT"]:
        scene_lib.delete(obj)
    distance = radius * 3.2
    # Large, soft sources and a big ambient share. Three hard lights produce a
    # broad white specular sheen on top of the albedo — negligible on bright
    # surfaces, DOMINANT on dark saturated ones, which measured as saturated
    # green rendering 5.4x too light. Soft and ambient-heavy is both closer to
    # a studio review setup and far more faithful to the actual albedo.
    rig = [
        ("key", (1.1, -1.5, 1.6), 1.0, radius * 3.0),
        ("fill", (-1.7, -0.9, 0.6), 0.38, radius * 4.0),
        ("rim", (-0.4, 1.8, 1.3), 0.30, radius * 2.6),
    ]
    made = []
    for name, direction, power_scale, size in rig:
        data = bpy.data.lights.new(f"_bforge_{name}", type="AREA")
        data.size = max(0.2, size)
        # Irradiance from a point-ish source falls off as 1/d², and d scales with
        # the subject, so power must scale with radius² to hold exposure constant
        # across a 0.2 m gem and a 30 m terrain.
        #
        # The constant is MEASURED, not derived: tests/calibrate_lighting.py
        # renders an 18% grey card at four subject scales and reports the ratio.
        # The original hand-derived 200 came out 3.41x too hot, which made every
        # dark albedo render as pale stone — and cost several rounds of "fixing"
        # a material that was correct all along. Re-run the calibration after
        # touching anything here.
        data.energy = power_scale * 105.0 * (radius**2) + 6.0
        light = bpy.data.objects.new(f"_bforge_{name}", data)
        bpy.context.scene.collection.objects.link(light)
        offset = Vector(direction).normalized() * distance
        light.location = centre + offset
        light.rotation_euler = (-offset).to_track_quat("-Z", "Y").to_euler()
        made.append(light)
    return made


def _setup_camera(centre, radius, view, ortho=False, margin=1.28):
    camera_data = bpy.data.cameras.new("_bforge_cam")
    camera = bpy.data.objects.new("_bforge_cam", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera

    rotation = VIEWS.get(view)
    if rotation is None:
        raise OpError(f"unknown view '{view}'. Available: {', '.join(VIEWS)}")
    camera.rotation_euler = rotation

    if ortho:
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = radius * 2.0 * margin
        distance = radius * 4.0
    else:
        camera_data.type = "PERSP"
        camera_data.lens = 55.0
        half_fov = camera_data.angle * 0.5
        distance = (radius * margin) / max(math.sin(half_fov), 1e-4)

    # Derive the offset from the Euler directly. Reading camera.matrix_world here
    # would return the PREVIOUS matrix: Blender does not recompute object
    # matrices until the depsgraph updates, so the camera would be placed as if
    # unrotated and every render would come back empty.
    direction = Euler(rotation, "XYZ").to_matrix() @ Vector((0.0, 0.0, 1.0))
    camera.location = centre + direction * distance
    camera_data.clip_start = max(0.01, distance * 0.01)
    camera_data.clip_end = distance * 6.0
    bpy.context.view_layer.update()
    return camera


def _configure_engine(engine, samples, resolution):
    scene = bpy.context.scene
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"

    # Blender defaults to the AgX view transform, which is a filmic look that
    # deliberately desaturates and rolls off highlights. That is right for a
    # beauty render and wrong here: an agent judging whether a material is the
    # colour it asked for needs the albedo back unmodified.
    view = scene.view_settings
    for candidate in ("Standard", "Raw"):
        try:
            view.view_transform = candidate
            break
        except TypeError:
            continue
    try:
        view.look = "None"
    except TypeError:
        pass
    view.exposure = 0.0
    view.gamma = 1.0

    chosen = engine
    if engine == "auto":
        chosen = "cycles"
    if chosen == "eevee":
        # EEVEE and Workbench both need a live GPU context. In background mode
        # on a box with no display server that is a hard crash
        # (EXCEPTION_ACCESS_VIOLATION), not an exception we can catch — so this
        # is opt-in only and Cycles/CPU is the default everywhere.
        try:
            scene.render.engine = "BLENDER_EEVEE"
            if hasattr(scene, "eevee"):
                scene.eevee.taa_render_samples = max(4, min(64, samples))
            return "eevee"
        except Exception:  # noqa: BLE001 — fall through to Cycles
            pass
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = max(1, samples)
    scene.cycles.use_denoising = False
    # Two bounces, not four. These are review renders: with full GI a large
    # saturated surface (a red racetrack, a green field) bleeds its colour over
    # every other material in the scene and you can no longer judge any of them.
    scene.cycles.max_bounces = 2
    scene.cycles.diffuse_bounces = 2
    scene.cycles.caustics_reflective = False
    scene.cycles.caustics_refractive = False
    return "cycles"


def _render_to(path):
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return path


def _camera_is_buried(eye, target):
    """Is the camera inside solid geometry? Returns the object name, or None.

    Placing a camera inside a wall renders pure black, which looks identical to
    a lighting failure and costs a full render to diagnose. It is also the most
    common spatial mistake there is: a stadium camera at radius 55 sounds
    reasonable and sits squarely inside a stand that spans 44 to 71.

    Cast a ray along the view direction and inspect the first hit's normal. If
    it faces the SAME way we are looking, we are seeing a backface, which means
    we started inside the mesh.
    """
    direction = Vector(target) - Vector(eye)
    if direction.length < 1e-6:
        return None
    direction.normalize()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    hit, _location, normal, _index, obj, _matrix = bpy.context.scene.ray_cast(
        depsgraph, Vector(eye), direction
    )
    if hit and normal.dot(direction) > 0.0:
        return obj.name if obj else "solid geometry"
    return None


def _analyse(ctx, path):
    """Attach measured stats to every render.

    An agent reading a PNG can see that something is wrong but not usually WHY.
    These numbers separate the two failure modes that look identical in an
    image — a blown-out light rig and a broken material — which otherwise costs
    several minutes of renders each time to tell apart.
    """
    from .check import check_image

    try:
        report = check_image(ctx, path=str(path), colors=4, background=[0.05, 0.055, 0.065, 1.0])
    except Exception as exc:  # noqa: BLE001 — diagnostics must never fail a render
        return {"error": str(exc)}
    return {
        "subject_coverage": report["subject_coverage"],
        "luma": report["luma"],
        "luma_linear": report["luma_linear"],
        "blown_highlights": report["blown_highlights"],
        "crushed_shadows": report["crushed_shadows"],
        "mean_saturation": report["mean_saturation"],
        "mean_color": report["mean_color"],
        "dominant_colors": [c["hex"] for c in report["dominant_colors"]],
        "findings": report["findings"],
    }


def _cleanup_rig(objs):
    for obj in objs:
        if obj and obj.name in bpy.data.objects:
            scene_lib.delete(obj)


def _hide_others(keep):
    keep_names = {o.name for o in keep}
    hidden = []
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and obj.name not in keep_names and not obj.hide_render:
            obj.hide_render = True
            hidden.append(obj)
    return hidden


@op(
    "render.view",
    summary="Render one framed view of the scene or of specific objects. The camera and a three-point light rig are auto-fitted to the subject, so you never get an empty or blown-out frame.",
    params={
        "out": ("path", "preview.png", "PNG output path"),
        "objects": ("str[]", [], "Objects to frame and show (empty = whole scene)"),
        "view": ("enum:hero|front|back|left|right|top|low", "hero", "Camera angle"),
        "resolution": ("int", 512, "Square render resolution in pixels"),
        "samples": ("int", 24, "Render samples — 24 is enough to judge form"),
        "engine": (
            "enum:auto|cycles|eevee",
            "auto",
            "Render engine. 'auto' means Cycles/CPU, which is the only one that works without a GPU context; 'eevee' is faster but crashes headless on machines with no display server",
        ),
        "ortho": ("bool", False, "Orthographic projection (right for front/side/top reference)"),
        "world_light": (
            "num",
            0.32,
            "Ambient dome strength. Higher fills shadows but piles white specular sheen onto every surface, which washes out saturated albedo",
        ),
    },
    tags=["render"],
)
def render_view(ctx, out, objects, view, resolution, samples, engine, ortho, world_light):
    targets = _targets(objects)
    hidden = _hide_others(targets) if objects else []
    centre, radius = _bounding_sphere(targets)
    _setup_world(world_light)
    lights = _setup_lights(centre, radius)
    camera = _setup_camera(centre, radius, view, ortho)
    used = _configure_engine(engine, samples, resolution)
    path = ctx.out_path(out, ".png")
    try:
        _render_to(path)
    finally:
        _cleanup_rig(lights + [camera])
        for obj in hidden:
            obj.hide_render = False
    return {
        "path": str(path),
        "rel": ctx.rel(path),
        "view": view,
        "engine": used,
        "resolution": resolution,
        "subject_radius_m": round(radius, 4),
        "analysis": _analyse(ctx, path),
    }


@op(
    "render.camera",
    summary="Render from an explicit camera position and target. Auto-framing always fits the WHOLE subject, which is useless on a 700 m stadium or a 40 m terrain — this is how you get a close-up, an eye-level gameplay view, or a hero shot.",
    params={
        "out": ("path", "shot.png", "PNG output path"),
        "position": ("vec3", None, "Camera position in metres"),
        "target": ("vec3", [0.0, 0.0, 0.0], "Point to look at"),
        "lens": ("num", 50.0, "Focal length in mm — 24 is wide, 50 neutral, 105 compressed"),
        "resolution": ("int", 640, "Width in pixels"),
        "aspect": ("num", 1.0, "Width / height. Use 1.78 for a 16:9 gameplay framing"),
        "samples": ("int", 32, "Render samples"),
        "engine": ("enum:auto|cycles|eevee", "auto", "Render engine"),
        "light_distance": ("num", 0.0, "Light rig scale in metres; 0 fits it to the whole scene"),
        "world_light": (
            "num",
            0.32,
            "Ambient dome strength. Higher fills shadows but piles white specular sheen onto every surface, which washes out saturated albedo",
        ),
    },
    tags=["render"],
)
def render_camera(
    ctx,
    out,
    position,
    target,
    lens,
    resolution,
    aspect,
    samples,
    engine,
    light_distance,
    world_light,
):
    if not [o for o in bpy.context.scene.objects if o.type == "MESH"]:
        raise OpError("nothing to render — the scene has no mesh objects")
    centre = Vector(target)
    eye = Vector(position)
    # Light the region being looked at, not the whole 700 m building, or the
    # rig ends up so far away and so powerful that the close-up is unlit.
    radius = light_distance if light_distance > 0 else max(1.0, (eye - centre).length * 0.55)

    _setup_world(world_light)
    lights = _setup_lights(centre, radius)

    camera_data = bpy.data.cameras.new("_bforge_shot")
    camera = bpy.data.objects.new("_bforge_shot", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    camera_data.lens = max(8.0, lens)
    camera.location = eye
    camera.rotation_euler = (centre - eye).to_track_quat("-Z", "Y").to_euler()
    distance = max(0.1, (eye - centre).length)
    camera_data.clip_start = max(0.01, distance * 0.001)
    camera_data.clip_end = distance * 20.0

    used = _configure_engine(engine, samples, resolution)
    scene = bpy.context.scene
    scene.render.resolution_x = resolution
    scene.render.resolution_y = max(1, int(resolution / max(0.1, aspect)))
    bpy.context.view_layer.update()

    path = ctx.out_path(out, ".png")
    try:
        _render_to(path)
    finally:
        _cleanup_rig(lights + [camera])
    return {
        "path": str(path),
        "rel": ctx.rel(path),
        "engine": used,
        "position": [round(v, 3) for v in eye],
        "target": [round(v, 3) for v in centre],
        "lens_mm": lens,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "analysis": _analyse(ctx, path),
    }


@op(
    "render.cinematic",
    summary="A film-grade beauty render: physical sun and sky, global illumination, atmospheric haze, depth of field and a filmic tonemap. render.view and render.camera are flat REVIEW rigs built to judge albedo honestly; this one is built to show the asset at its best, and it is the render that tells you whether the art actually holds up.",
    params={
        "out": ("path", "hero.png", "PNG output path"),
        "position": ("vec3", None, "Camera position in metres"),
        "target": ("vec3", [0.0, 0.0, 0.0], "Point to look at"),
        "lens": ("num", 40.0, "Focal length in mm"),
        "resolution": ("int", 1280, "Width in pixels"),
        "aspect": ("num", 2.39, "Width / height. 2.39 is anamorphic, 1.78 is 16:9"),
        "samples": ("int", 96, "Path-tracing samples. This is a beauty render; it costs time"),
        "sun_energy": ("num", 4.0, "Sun strength in W/m2. 3-6 reads as hard daylight"),
        "sun_angle": (
            "vec2",
            [52.0, 35.0],
            "Sun elevation and azimuth in degrees. Low sun = long shadows",
        ),
        "sun_color": ("colorref", "#fff2dc", "Sunlight colour; warmer at low elevation"),
        "sky_color": ("colorref", "#6fa3dc", "Zenith sky colour, which is also the fill light"),
        "horizon_color": ("colorref", "#e8dcc0", "Horizon haze colour"),
        "sky_strength": ("num", 1.1, "Sky/ambient strength"),
        "haze": (
            "num",
            0.0,
            "Volumetric atmosphere density. 0.0005-0.004 separates distant forms; costs render time",
        ),
        "focus": ("num", 0.0, "Depth of field focus distance; 0 measures it to the target"),
        "aperture": ("num", 0.0, "f-stop. 0 disables depth of field. 2.8 is shallow, 8 is deep"),
        "bounces": ("int", 6, "Light bounces. GI is most of what makes a render look expensive"),
        "exposure": ("num", 0.0, "Exposure compensation in stops"),
        "look": (
            "enum:filmic|agx|standard|contrast",
            "agx",
            "View transform. Filmic/AgX roll off highlights like film; standard clips them",
        ),
    },
    tags=["render"],
)
def render_cinematic(
    ctx,
    out,
    position,
    target,
    lens,
    resolution,
    aspect,
    samples,
    sun_energy,
    sun_angle,
    sun_color,
    sky_color,
    horizon_color,
    sky_strength,
    haze,
    focus,
    aperture,
    bounces,
    exposure,
    look,
):
    from lib import mat as mat_lib

    if not [o for o in bpy.context.scene.objects if o.type == "MESH"]:
        raise OpError("nothing to render — the scene has no mesh objects")

    scene = bpy.context.scene
    centre = Vector(target)
    eye = Vector(position)

    # --- sky: a real gradient environment, not a flat backdrop -----------
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    world = scene.world
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputWorld")
    background = tree.nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = sky_strength
    gradient = tree.nodes.new("ShaderNodeTexGradient")
    gradient.gradient_type = "EASING"
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.inputs["Rotation"].default_value = (0.0, math.radians(90.0), 0.0)
    coord = tree.nodes.new("ShaderNodeTexCoord")
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = mat_lib.resolve_color(horizon_color)
    ramp.color_ramp.elements[1].color = mat_lib.resolve_color(sky_color)
    ramp.color_ramp.elements[0].position = 0.42
    ramp.color_ramp.elements[1].position = 0.62
    tree.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], gradient.inputs["Vector"])
    tree.links.new(gradient.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], background.inputs["Color"])
    tree.links.new(background.outputs["Background"], output.inputs["Surface"])

    # --- sun: a real SUN lamp with angular size --------------------------
    for obj in [o for o in scene.objects if o.type == "LIGHT"]:
        scene_lib.delete(obj)
    sun_data = bpy.data.lights.new("_bforge_sun", type="SUN")
    sun_data.energy = sun_energy
    sun_data.color = mat_lib.resolve_color(sun_color)[:3]
    # ~0.53 degrees is the real sun. Slightly wider softens contact shadows
    # without turning them to mush.
    sun_data.angle = math.radians(1.2)
    sun = bpy.data.objects.new("_bforge_sun", sun_data)
    scene.collection.objects.link(sun)
    elevation = math.radians(max(2.0, min(88.0, sun_angle[0])))
    azimuth = math.radians(sun_angle[1])
    direction = Vector(
        (
            math.cos(elevation) * math.cos(azimuth),
            math.cos(elevation) * math.sin(azimuth),
            math.sin(elevation),
        )
    )
    sun.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()

    # --- atmosphere -------------------------------------------------------
    haze_volume = None
    if haze > 0.0:
        extent = max(200.0, (eye - centre).length * 8.0)
        haze_bm = mesh_lib.new_bmesh()
        mesh_lib.add_box(
            haze_bm, size=(extent, extent, extent * 0.5), center=(centre.x, centre.y, centre.z)
        )
        haze_volume = mesh_lib.to_object(haze_bm, "_bforge_haze")
        material = bpy.data.materials.new("_bforge_haze")
        material.use_nodes = True
        volume_tree = material.node_tree
        volume_tree.nodes.clear()
        volume_out = volume_tree.nodes.new("ShaderNodeOutputMaterial")
        scatter = volume_tree.nodes.new("ShaderNodeVolumeScatter")
        scatter.inputs["Density"].default_value = haze
        scatter.inputs["Anisotropy"].default_value = 0.4
        volume_tree.links.new(scatter.outputs["Volume"], volume_out.inputs["Volume"])
        haze_volume.data.materials.append(material)

    # --- camera ------------------------------------------------------------
    camera_data = bpy.data.cameras.new("_bforge_cine")
    camera = bpy.data.objects.new("_bforge_cine", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.lens = max(8.0, lens)
    camera.location = eye
    camera.rotation_euler = (centre - eye).to_track_quat("-Z", "Y").to_euler()
    distance = max(0.1, (eye - centre).length)
    camera_data.clip_start = max(0.01, distance * 0.001)
    camera_data.clip_end = distance * 40.0
    if aperture > 0.0:
        camera_data.dof.use_dof = True
        camera_data.dof.focus_distance = focus if focus > 0 else distance
        camera_data.dof.aperture_fstop = aperture

    # --- engine ------------------------------------------------------------
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = max(8, samples)
    scene.cycles.max_bounces = max(2, bounces)
    scene.cycles.diffuse_bounces = max(2, bounces)
    scene.cycles.glossy_bounces = max(2, bounces)
    scene.cycles.transmission_bounces = max(2, bounces)
    scene.cycles.volume_bounces = 2 if haze > 0 else 0
    scene.cycles.use_denoising = True
    scene.render.resolution_x = resolution
    scene.render.resolution_y = max(1, int(resolution / max(0.1, aspect)))
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"

    view = scene.view_settings
    transform = {"filmic": "Filmic", "agx": "AgX", "standard": "Standard", "contrast": "Standard"}[
        look
    ]
    for candidate in (transform, "AgX", "Filmic", "Standard"):
        try:
            view.view_transform = candidate
            break
        except TypeError:
            continue
    try:
        view.look = (
            "AgX - Punchy"
            if look == "agx"
            else ("Medium High Contrast" if look == "contrast" else "None")
        )
    except TypeError:
        pass
    view.exposure = exposure
    view.gamma = 1.0

    bpy.context.view_layer.update()
    buried = _camera_is_buried(eye, centre)
    if buried:
        ctx.note(
            f"the camera at {[round(v, 1) for v in eye]} is INSIDE '{buried}' — the frame "
            "will render black. Move it into open space; for a stadium or a room that "
            "means inside the bowl or outside the outer wall, not within the wall itself."
        )

    path = ctx.out_path(out, ".png")
    try:
        _render_to(path)
    finally:
        _cleanup_rig([sun, camera] + ([haze_volume] if haze_volume else []))

    return {
        "path": str(path),
        "rel": ctx.rel(path),
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "samples": samples,
        "bounces": bounces,
        "look": view.view_transform,
        "haze": haze,
        "depth_of_field": aperture > 0.0,
        "analysis": _analyse(ctx, path),
    }


@op(
    "render.contact_sheet",
    summary="THE review image. Renders hero/front/side/top plus a wireframe pass (shows topology and wasted triangles) and a checker pass (shows UV stretch and texel-density mismatches), composited into one PNG. Look at this after generating anything — it is how you catch problems a triangle count cannot show.",
    params={
        "out": ("path", "contact_sheet.png", "PNG output path"),
        "objects": ("str[]", [], "Objects to review (empty = whole scene)"),
        "tile": ("int", 400, "Pixel size of each tile"),
        "samples": ("int", 20, "Render samples per tile"),
        "engine": ("enum:auto|cycles|eevee", "auto", "Render engine"),
        "panels": (
            "str[]",
            ["hero", "front", "left", "top", "wireframe", "checker"],
            "Which panels to include",
        ),
        "columns": ("int", 3, "Tiles per row"),
    },
    tags=["render", "inspect"],
)
def render_contact_sheet(ctx, out, objects, tile, samples, engine, panels, columns):
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - Blender bundles numpy
        raise OpError(
            "numpy is unavailable in this Blender build; use render.view instead"
        ) from exc

    targets = _targets(objects)
    hidden = _hide_others(targets) if objects else []
    centre, radius = _bounding_sphere(targets)
    columns = max(1, columns)
    rows = math.ceil(len(panels) / columns)
    sheet = numpy.zeros((rows * tile, columns * tile, 4), dtype=numpy.float32)
    sheet[:, :, 3] = 1.0

    stats = {
        "triangles": sum(mesh_lib.tri_count(o) for o in targets if o.type == "MESH"),
        "objects": len(targets),
        "materials": sorted(
            {m.name for o in targets if o.type == "MESH" for m in o.data.materials if m}
        ),
    }

    rendered = []
    used = "cycles"
    # Multiple bforge daemons may legitimately render different assets into
    # one output root in parallel. A shared `_sheet/panel_0_hero.png` lets one
    # daemon replace or delete another's panel between render and load.
    scratch_dir = ctx.out_dir / "_sheet" / scene_lib.sanitize(Path(str(out)).stem)
    for index, panel in enumerate(panels):
        _setup_world(0.6)
        lights = _setup_lights(centre, radius)
        view = panel if panel in VIEWS else "hero"
        ortho = panel in ("front", "back", "left", "right", "top")
        camera = _setup_camera(centre, radius, view, ortho)

        swapped = []
        if panel == "wireframe":
            swapped = _swap_materials(targets, _wireframe_material())
        elif panel == "checker":
            swapped = _swap_materials(targets, _checker_material())
        used = _configure_engine(engine, samples, tile)

        path = scratch_dir / f"panel_{index}_{panel}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _render_to(path)
            pixels = _load_pixels(numpy, path, tile)
            row = index // columns
            column = index % columns
            sheet[row * tile : (row + 1) * tile, column * tile : (column + 1) * tile] = pixels
            rendered.append(panel)
        finally:
            _cleanup_rig(lights + [camera])
            if swapped:
                _restore_materials(swapped)

    for obj in hidden:
        obj.hide_render = False

    target_path = ctx.out_path(out, ".png")
    image = bpy.data.images.new(
        "_bforge_sheet", width=columns * tile, height=rows * tile, alpha=True
    )
    # Blender images are bottom-up; our sheet is laid out top-down.
    image.pixels = numpy.flipud(sheet).ravel().tolist()
    image.filepath_raw = str(target_path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)

    return {
        "path": str(target_path),
        "rel": ctx.rel(target_path),
        "panels": rendered,
        "layout": f"{columns}x{rows}",
        "tile": tile,
        "engine": used,
        "scene_stats": stats,
        "read_this": (
            "Wireframe panel: look for dense areas that carry no silhouette — those are wasted "
            "triangles. Checker panel: squares must stay square and the same size everywhere; "
            "stretched squares mean bad UVs, differently-sized squares mean inconsistent texel "
            "density between parts."
        ),
    }


def _load_pixels(numpy, path, tile):
    loaded = bpy.data.images.load(str(path))
    try:
        width, height = loaded.size
        data = numpy.array(loaded.pixels[:], dtype=numpy.float32)
        expected = width * height * 4
        if width < 1 or height < 1 or data.size != expected:
            raise OpError(
                f"rendered panel '{path}' is empty or incomplete "
                f"({width}x{height}, {data.size}/{expected} values)"
            )
        data = data.reshape((height, width, 4))
        data = numpy.flipud(data)
        if (height, width) != (tile, tile):
            ys = (numpy.arange(tile) * height / tile).astype(int).clip(0, height - 1)
            xs = (numpy.arange(tile) * width / tile).astype(int).clip(0, width - 1)
            data = data[ys][:, xs]
        return data
    finally:
        bpy.data.images.remove(loaded)


def _checker_material():
    """UV checker so stretching and texel-density mismatch become visible."""
    material = bpy.data.materials.get("_bforge_checker")
    if material is not None:
        return material
    material = bpy.data.materials.new("_bforge_checker")
    material.use_nodes = True
    tree = material.node_tree
    bsdf = tree.nodes.get("Principled BSDF")
    coord = tree.nodes.new("ShaderNodeUVMap")
    coord.location = (-600, 0)
    checker = tree.nodes.new("ShaderNodeTexChecker")
    checker.location = (-380, 0)
    checker.inputs["Scale"].default_value = 12.0
    checker.inputs["Color1"].default_value = (0.85, 0.85, 0.88, 1.0)
    checker.inputs["Color2"].default_value = (0.10, 0.42, 0.62, 1.0)
    tree.links.new(coord.outputs["UV"], checker.inputs["Vector"])
    tree.links.new(checker.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.75
    bsdf.inputs["Metallic"].default_value = 0.0
    return material


def _wireframe_material():
    """Topology view rendered by Cycles, not by the viewport.

    The obvious way to render a wireframe is the Workbench engine with
    `show_wire`. That needs a live OpenGL context, and in background mode
    without a display server it does not raise — it segfaults. A Wireframe
    shader node gets the same picture out of a pure CPU path, so this works
    identically on a laptop, in CI, and on a headless build box.
    """
    material = bpy.data.materials.get("_bforge_wire")
    if material is not None:
        return material
    material = bpy.data.materials.new("_bforge_wire")
    material.use_nodes = True
    tree = material.node_tree
    bsdf = tree.nodes.get("Principled BSDF")
    wire = tree.nodes.new("ShaderNodeWireframe")
    wire.location = (-560, 0)
    wire.use_pixel_size = True
    wire.inputs["Size"].default_value = 1.1
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.location = (-320, 0)
    mix.inputs["A"].default_value = (0.30, 0.32, 0.36, 1.0)  # surface
    mix.inputs["B"].default_value = (0.02, 0.85, 0.65, 1.0)  # wire
    tree.links.new(wire.outputs["Fac"], mix.inputs["Factor"])
    tree.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    # Emission carries the wire so it stays legible in unlit areas.
    emit_mix = tree.nodes.new("ShaderNodeMix")
    emit_mix.data_type = "RGBA"
    emit_mix.location = (-320, -260)
    emit_mix.inputs["A"].default_value = (0.0, 0.0, 0.0, 1.0)
    emit_mix.inputs["B"].default_value = (0.02, 0.85, 0.65, 1.0)
    tree.links.new(wire.outputs["Fac"], emit_mix.inputs["Factor"])
    tree.links.new(emit_mix.outputs["Result"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.4
    bsdf.inputs["Roughness"].default_value = 0.9
    bsdf.inputs["Metallic"].default_value = 0.0
    return material


def _swap_materials(objs, material):
    backup = []
    for obj in objs:
        if obj.type != "MESH":
            continue
        backup.append((obj, list(obj.data.materials)))
        obj.data.materials.clear()
        obj.data.materials.append(material)
    return backup


def _restore_materials(backup):
    for obj, materials in backup:
        obj.data.materials.clear()
        for material in materials:
            obj.data.materials.append(material)


@op(
    "render.turntable",
    summary="Render an orbit of frames around the subject. Use when a single angle cannot settle whether a silhouette works.",
    params={
        "out_dir": ("path", "turntable", "Directory for the frames"),
        "objects": ("str[]", [], "Objects to frame (empty = whole scene)"),
        "frames": ("int", 8, "Number of orbit steps"),
        "resolution": ("int", 384, "Square resolution per frame"),
        "samples": ("int", 16, "Render samples"),
        "elevation": ("num", 22.0, "Camera elevation in degrees"),
        "engine": ("enum:auto|cycles|eevee", "auto", "Render engine"),
    },
    tags=["render"],
)
def render_turntable(ctx, out_dir, objects, frames, resolution, samples, elevation, engine):
    targets = _targets(objects)
    hidden = _hide_others(targets) if objects else []
    centre, radius = _bounding_sphere(targets)
    frames = max(1, min(64, frames))
    _setup_world(0.6)
    lights = _setup_lights(centre, radius)
    used = _configure_engine(engine, samples, resolution)

    camera_data = bpy.data.cameras.new("_bforge_tt")
    camera = bpy.data.objects.new("_bforge_tt", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    camera_data.lens = 55.0
    distance = (radius * 1.3) / max(math.sin(camera_data.angle * 0.5), 1e-4)
    camera_data.clip_end = distance * 6.0

    paths = []
    base = ctx.out_path(f"{out_dir}/frame.png", ".png").parent
    try:
        for index in range(frames):
            azimuth = math.tau * index / frames
            tilt = math.radians(elevation)
            offset = (
                Vector(
                    (
                        math.cos(azimuth) * math.cos(tilt),
                        math.sin(azimuth) * math.cos(tilt),
                        math.sin(tilt),
                    )
                )
                * distance
            )
            camera.location = centre + offset
            camera.rotation_euler = (-offset).to_track_quat("-Z", "Y").to_euler()
            path = base / f"frame_{index:03d}.png"
            _render_to(path)
            paths.append(str(path))
    finally:
        _cleanup_rig(lights + [camera])
        for obj in hidden:
            obj.hide_render = False

    return {
        "directory": str(base),
        "rel": ctx.rel(base),
        "frames": len(paths),
        "files": paths,
        "engine": used,
    }
