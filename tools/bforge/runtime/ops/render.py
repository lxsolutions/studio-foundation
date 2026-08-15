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

import json
import math
import os
import tempfile
from pathlib import Path

import bpy
from lib import mesh as mesh_lib
from lib import scene as scene_lib
from lib import sprite_budget
from mathutils import Euler, Vector
from registry import REQUIRED, OpError, op

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
        "position": (
            "vec3",
            REQUIRED,
            "Camera position in metres. This op exists to place the camera by hand; use render.cinematic or render.view when you want the framing fitted for you",
        ),
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


def _frame_distance(radius, lens, aspect, margin, sensor=36.0):
    """How far back a `lens` mm camera must sit to fit a sphere of `radius`.

    Framing on the horizontal FOV alone crops the subject's head off at 2.39:1,
    because the vertical field is 2.39x narrower. Fit whichever axis is tighter.
    """
    half_x = math.atan(sensor / (2.0 * max(8.0, lens)))
    half_y = math.atan(math.tan(half_x) / max(0.1, aspect))
    return (max(1e-6, radius) * max(1.0, margin)) / max(math.sin(min(half_x, half_y)), 1e-4)


def _cinematic_eye(centre, radius, lens, aspect, margin=1.35, elevation=22.0, azimuth=-47.0):
    """A three-quarter beauty angle scaled to the subject.

    Slightly lower and looser than the review rig's `hero` view: a beauty shot
    wants some sky under the horizon line and air around the silhouette, where
    a review frame wants the subject as large as it can legibly be.
    """
    distance = _frame_distance(radius, lens, aspect, margin)
    el, az = math.radians(elevation), math.radians(azimuth)
    direction = Vector(
        (
            math.cos(el) * math.cos(az),
            math.cos(el) * math.sin(az),
            math.sin(el),
        )
    )
    return centre + direction * distance


@op(
    "render.cinematic",
    summary="A film-grade beauty render: physical sun and sky, global illumination, atmospheric haze, depth of field and a filmic tonemap. render.view and render.camera are flat REVIEW rigs built to judge albedo honestly; this one is built to show the asset at its best, and it is the render that tells you whether the art actually holds up.",
    params={
        "out": ("path", "hero.png", "PNG output path"),
        "position": (
            "vec3",
            None,
            "Camera position in metres. Omit it and a three-quarter beauty angle is fitted to the subject — set it for a close-up or a specific composition",
        ),
        "target": (
            "vec3",
            None,
            "Point to look at. When both camera position and target are omitted, the camera aims at the subject's own centre so assets built off-origin are still framed. An explicit position with no target keeps the established world-origin target",
        ),
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
    # `position` has no sensible fixed default — a camera at a hardcoded point is
    # either inside a stadium or a speck away from a gem. Omitting it means "frame
    # the subject for me", which is what every other render op does; without this
    # the documented default of None reached Vector(None) and raised.
    auto_framed = position is None
    subject_radius = None
    if auto_framed:
        subject_centre, subject_radius = _bounding_sphere(_targets(None))
        centre = subject_centre if target is None else Vector(target)
        # A caller can aim away from the subject centre for a deliberate
        # composition. Fit the sphere around that aim point as well, otherwise
        # an off-centre target can put part of the asset outside the frame.
        frame_radius = subject_radius + (subject_centre - centre).length
        eye = _cinematic_eye(centre, frame_radius, lens, aspect)
    else:
        # Preserve the original explicit-camera contract: before auto-framing,
        # an omitted target meant world origin.
        centre = Vector((0.0, 0.0, 0.0)) if target is None else Vector(target)
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
    focal_length = max(8.0, lens)
    camera_data.lens = focal_length
    if auto_framed:
        # `_frame_distance` uses the 36 mm horizontal sensor. Lock Blender to
        # that same fit so portrait and landscape outputs obey identical math.
        camera_data.sensor_fit = "HORIZONTAL"
    camera.location = eye
    camera.rotation_euler = (centre - eye).to_track_quat("-Z", "Y").to_euler()
    distance = max(0.1, (eye - centre).length)
    # A fixed 1 cm near plane erases millimetre-scale jewellery. Auto-framing
    # knows its distance is safe, so scale the near plane with it. Keep the
    # established explicit-camera value unchanged.
    camera_data.clip_start = (
        max(1e-5, distance * 0.001) if auto_framed else max(0.01, distance * 0.001)
    )
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
        "auto_framed": auto_framed,
        "position": [round(v, 5) for v in eye],
        "target": [round(v, 5) for v in centre],
        "lens_mm": focal_length,
        "subject_radius_m": (round(subject_radius, 5) if subject_radius is not None else None),
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

        path = ctx.out_dir / "_sheet" / f"panel_{index}_{panel}.png"
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


def _impostor_normal_material():
    """World-space normal -> emission colour, the standard impostor bake.

    The Geometry node's Normal output is the world-space shading normal in
    -1..1; a billboard shader expects the 0..1 texture encoding, so scale by
    0.5 and bias by 0.5. Emission makes the pass independent of the light rig.
    """
    material = bpy.data.materials.get("_bforge_impostor_normal")
    if material is not None:
        return material
    material = bpy.data.materials.new("_bforge_impostor_normal")
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    geometry = tree.nodes.new("ShaderNodeNewGeometry")
    multiply = tree.nodes.new("ShaderNodeVectorMath")
    multiply.operation = "MULTIPLY"
    multiply.inputs[1].default_value = (0.5, 0.5, 0.5)
    add = tree.nodes.new("ShaderNodeVectorMath")
    add.operation = "ADD"
    add.inputs[1].default_value = (0.5, 0.5, 0.5)
    tree.links.new(geometry.outputs["Normal"], multiply.inputs[0])
    tree.links.new(multiply.outputs[0], add.inputs[0])
    tree.links.new(add.outputs[0], emission.inputs["Color"])
    tree.links.new(emission.outputs[0], output.inputs["Surface"])
    return material


def _save_sheet_png(numpy, grid, path, cols, rows, size):
    """Same compositing path as render.contact_sheet: a data-API image saved
    directly, so no GUI-dependent writer is involved."""
    image = bpy.data.images.new(
        "_bforge_impostor", width=cols * size, height=rows * size, alpha=True
    )
    # Blender images are bottom-up; the grid is laid out top-down.
    image.pixels = numpy.flipud(grid).ravel().tolist()
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


@op(
    "render.impostor",
    summary="Bake an object into a billboard impostor sprite sheet: N orthographic views orbiting it, packed left-to-right then top-to-bottom into ONE transparent PNG, plus a JSON sidecar (grid layout, yaw angles, bounds) with everything a game engine needs to billboard it. This is THE distant-LOD technique — swap the real mesh for a camera-facing quad with this sheet beyond a few hundred metres and a browser can show thousands of instances at full frame rate. Pass normals=True to also bake a world-space normal sheet so the billboard can react to scene lighting.",
    params={
        "name": (
            "str",
            None,
            "Object to bake; its children are baked with it. Use object.list if you are unsure of the exact name",
        ),
        "out": (
            "path",
            "impostor.png",
            "Sprite-sheet PNG path. The JSON sidecar is written next to it as <stem>.json",
        ),
        "views": (
            "int",
            8,
            "Yaw angles around the object, evenly spaced over 360 degrees. 8 is the standard for props; 4 is enough for near-symmetric ones and halves the bake time",
        ),
        "size": (
            "int",
            128,
            "Pixel size of each frame (frames are square). Billboards are only ever seen at distance, so 64-256 is the useful range — bigger just costs render time",
        ),
        "normals": (
            "bool",
            False,
            "Also write <stem>_normal.png: world-space normals packed into 0..1 colour, so the billboard can be lit instead of looking pasted on. Doubles render cost",
        ),
        "samples": (
            "int",
            16,
            "Cycles samples per frame. 16 is plenty at these sizes; raise only if the sprites look grainy",
        ),
        "elevation": (
            "num",
            0.0,
            "Camera height above the horizon in degrees, the same for every view. Ground props read best at 0-15; high values waste frame area on the top face",
        ),
    },
    tags=["render"],
)
def render_impostor(ctx, name, out, views, size, normals, samples, elevation):
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - Blender bundles numpy
        raise OpError(
            "numpy is unavailable in this Blender build; use render.turntable instead"
        ) from exc

    try:
        root = scene_lib.get_object(name)
    except ValueError as exc:
        raise OpError(f"{exc} Run 'object.list' to see the names in the scene.") from exc
    meshes = [o for o in [root, *root.children_recursive] if o.type == "MESH"]
    triangles = sum(mesh_lib.tri_count(o) for o in meshes)
    if triangles == 0:
        raise OpError(
            f"'{name}' has no triangles to bake — it and its children are not meshes. "
            "Bake a mesh object: build one with build.*/prop.* first, or run "
            "'session.info' to see what every object in the scene actually is."
        )

    views = max(1, min(64, views))
    size = max(8, min(1024, size))
    cols = math.ceil(math.sqrt(views))
    rows = math.ceil(views / cols)

    # Frame from the world AABB of the whole hierarchy. The diagonal is the
    # worst-case projected extent over every yaw angle, so sizing the ortho
    # frame to it guarantees the subject fills ~90% of the square frame at its
    # widest and never clips at any other angle.
    bpy.context.view_layer.update()  # world matrices must be current to frame anything
    points = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector((min(p[i] for p in points) for i in range(3)))
    hi = Vector((max(p[i] for p in points) for i in range(3)))
    centre = (lo + hi) * 0.5
    diagonal = max((hi - lo).length, 1e-6)

    hidden = _hide_others(meshes)
    _setup_world(0.6)
    lights = _setup_lights(centre, diagonal * 0.5)
    used = _configure_engine("cycles", samples, size)
    scene = bpy.context.scene
    scene.render.film_transparent = True
    scene.render.image_settings.color_mode = "RGBA"

    camera_data = bpy.data.cameras.new("_bforge_impostor")
    camera = bpy.data.objects.new("_bforge_impostor", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = diagonal / 0.9
    distance = diagonal * 2.0
    camera_data.clip_start = max(0.01, distance * 0.01)
    camera_data.clip_end = distance * 4.0

    sheet_path = ctx.out_path(out, ".png")
    normal_path = sheet_path.with_name(f"{sheet_path.stem}_normal.png")
    sidecar_path = sheet_path.with_suffix(".json")
    scratch = ctx.out_dir / "_impostor"
    scratch.mkdir(parents=True, exist_ok=True)

    tilt = math.radians(elevation)

    def _render_frames(stem):
        # Empty grid cells (views not filling the last row) stay transparent.
        grid = numpy.zeros((rows * size, cols * size, 4), dtype=numpy.float32)
        for index in range(views):
            # The camera orbits while the light rig stays fixed — the sprite
            # lighting is then consistent across frames, as if the object spun.
            yaw = math.tau * index / views
            offset = (
                Vector(
                    (
                        math.cos(yaw) * math.cos(tilt),
                        math.sin(yaw) * math.cos(tilt),
                        math.sin(tilt),
                    )
                )
                * distance
            )
            camera.location = centre + offset
            camera.rotation_euler = (-offset).to_track_quat("-Z", "Y").to_euler()
            _render_to(scratch / f"{stem}_{index:03d}.png")
            pixels = _load_pixels(numpy, scratch / f"{stem}_{index:03d}.png", size)
            row, column = divmod(index, cols)
            grid[row * size : (row + 1) * size, column * size : (column + 1) * size] = pixels
        return grid

    try:
        _save_sheet_png(numpy, _render_frames("beauty"), sheet_path, cols, rows, size)
        if normals:
            swapped = _swap_materials(meshes, _impostor_normal_material())
            view = scene.view_settings
            previous_transform = view.view_transform
            try:
                # A normal map is data, not a beauty image: Raw writes the
                # remapped 0..1 normal to the PNG exactly, skipping the display
                # transform the colour pass wants.
                try:
                    view.view_transform = "Raw"
                except TypeError:
                    pass
                _save_sheet_png(numpy, _render_frames("normal"), normal_path, cols, rows, size)
            finally:
                view.view_transform = previous_transform
                _restore_materials(swapped)
    finally:
        _cleanup_rig(lights + [camera])
        for obj in hidden:
            obj.hide_render = False

    sidecar = {
        "frames": views,
        "cols": cols,
        "rows": rows,
        "frame_px": size,
        "yaw_degrees": [round(360.0 * i / views, 6) for i in range(views)],
        "elevation": elevation,
        "object": root.name,
        "bounds_m": [round(v, 5) for v in (hi - lo)],
    }
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")

    result = {
        "sheet": ctx.rel(sheet_path),
        "sidecar": ctx.rel(sidecar_path),
        "frames": views,
        "cols": cols,
        "rows": rows,
        "bytes": sheet_path.stat().st_size,
    }
    if normals:
        result["normal_sheet"] = ctx.rel(normal_path)
    return result


# ==========================================================================
# render.sprite — the icon rig
# ==========================================================================
#
# render.view judges albedo, render.cinematic judges whether the art holds up
# in a world, and neither produces something you can put in an inventory grid.
# An icon has requirements those two do not: every asset must occupy the same
# fraction of its frame however big it is, the silhouette must separate from
# the backdrop without relying on the subject happening to be lighter than it,
# the alpha has to survive being composited onto a UI nobody has designed yet,
# and forty of them shot on different days have to look like one set.

ICON_KEY = "#fff1d6"  # warm key — the sun side
ICON_FILL = "#b9d0f2"  # cool fill — the sky side. Warm/cool split is most
ICON_RIM = "#dcecff"  # of what separates a lit object from a coloured one.


def _camera_basis(view_dir):
    """Right/up/forward for a camera looking along `view_dir`."""
    forward = Vector(view_dir).normalized()
    world_up = Vector((0.0, 0.0, 1.0))
    if abs(forward.dot(world_up)) > 0.999:  # looking straight down: pick any right
        world_up = Vector((0.0, 1.0, 0.0))
    right = forward.cross(world_up).normalized()
    up = right.cross(forward).normalized()
    return right, up, forward


def _fit_sprite_views(meshes, view_dirs, lens, aspect, fill, sensor=36.0):
    """Return one target, distance, and ground anchor safe for every yaw.

    Refitting each yaw makes an asymmetric subject pulse larger and smaller in
    a directional sheet. A common world-space target and the worst-case
    perspective fit keep metres-per-pixel fixed. The target sits directly
    above the world-AABB ground anchor, so that anchor also projects to the same
    pixel at every yaw when distance and elevation are shared.
    """
    bpy.context.view_layer.update()
    corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    if not corners:
        raise OpError("nothing to frame — the subject has no geometry")
    lo = Vector((min(point[axis] for point in corners) for axis in range(3)))
    hi = Vector((max(point[axis] for point in corners) for axis in range(3)))
    target = (lo + hi) * 0.5
    ground_anchor = Vector((target.x, target.y, lo.z))
    half_x = math.atan(sensor / (2.0 * max(8.0, lens)))
    half_y = math.atan(math.tan(half_x) / max(0.1, aspect))
    fill = max(0.05, min(0.98, fill))
    tan_x = math.tan(half_x) * fill
    tan_y = math.tan(half_y) * fill
    radius = max((point - target).length for point in corners) or 1.0
    distance = radius * 1.05
    bases = []
    for view_dir in view_dirs:
        right, up, forward = _camera_basis(view_dir)
        bases.append((right, up, forward))
        for point in corners:
            delta = point - target
            depth_offset = delta.dot(forward)
            # Solve the perspective inequalities per corner. This is exact:
            # abs(axis) / (distance + depth_offset) <= tan(fov/2) * fill.
            distance = max(
                distance,
                abs(delta.dot(right)) / max(1e-6, tan_x) - depth_offset,
                abs(delta.dot(up)) / max(1e-6, tan_y) - depth_offset,
            )
    return target, max(distance, radius * 1.05), radius, ground_anchor, bases


def _project_sprite_point(point, target, distance, basis, lens, aspect, size, sensor=36.0):
    """Project a world point into top-down, frame-local pixel coordinates."""
    right, up, forward = basis
    delta = point - target
    depth = max(1e-6, distance + delta.dot(forward))
    half_x = math.atan(sensor / (2.0 * max(8.0, lens)))
    half_y = math.atan(math.tan(half_x) / max(0.1, aspect))
    ndc_x = delta.dot(right) / (depth * math.tan(half_x))
    ndc_y = delta.dot(up) / (depth * math.tan(half_y))
    extent = max(1, size - 1)
    return [
        round((0.5 + ndc_x * 0.5) * extent, 4),
        round((0.5 - ndc_y * 0.5) * extent, 4),
    ]


def _atomic_write_text(path, text):
    """Durably write beside path and atomically replace the destination."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _icon_lights(
    target,
    radius,
    right,
    up,
    forward,
    key_color,
    fill_color,
    rim_color,
    rim,
    key_energy,
    fill_energy,
):
    """A three-point rig defined in CAMERA space, not world space.

    World-space lights mean an asset modelled facing +X and one facing -Y light
    differently, so a set shot over several sessions never matches. Anchoring
    the rig to the camera makes the lighting a property of the shot.
    """
    for obj in [o for o in bpy.context.scene.objects if o.type == "LIGHT"]:
        scene_lib.delete(obj)
    # Distance and light size both scale with the subject, so the rig subtends a
    # constant solid angle and energy proportional to radius^2 holds exposure
    # fixed from a gem to a stadium. No additive floor term: a constant watt is
    # the one thing in this expression that would break that invariance.
    #
    # 420 is an icon-specific baseline, intentionally ~4x the calibrated
    # review-rig constant: a review render preserves albedo, while an icon puts
    # mid-tones high and leaves enough highlight energy for the bloom pass.
    distance = radius * 3.2
    base = 420.0 * (radius**2)
    rig = [
        # name    direction (camera space: right, up, -forward=towards camera)
        ("key", (-0.85, 0.95, 1.15), key_energy, radius * 2.4, key_color),
        # Big, soft, and slightly BELOW the lens axis. The shadow side of a
        # three-quarter view is half the icon; letting it fall to black reads as
        # a rendering fault rather than as shape.
        ("fill", (1.25, -0.15, 0.85), fill_energy, radius * 4.5, fill_color),
        # The kicker sits BEHIND the subject and rakes across it. This is the
        # separation light: it draws a bright line down the silhouette so the
        # shape reads against any backdrop, which is the single biggest
        # difference between a render and an icon.
        ("rim", (0.75, 0.85, -1.35), 0.85 * rim, radius * 1.1, rim_color),
    ]
    made = []
    for name, (dr, du, dt), power, size, color in rig:
        if power <= 0.0:
            continue
        data = bpy.data.lights.new(f"_bforge_icon_{name}", type="AREA")
        data.size = max(0.05, size)
        data.energy = power * base
        data.color = color[:3]
        light = bpy.data.objects.new(f"_bforge_icon_{name}", data)
        bpy.context.scene.collection.objects.link(light)
        offset = (right * dr + up * du + (-forward) * dt).normalized() * distance
        light.location = target + offset
        light.rotation_euler = (-offset).to_track_quat("-Z", "Y").to_euler()
        made.append(light)
    return made


def _shadow_catcher(meshes, radius):
    """A ground plane that renders only the shadow falling on it.

    An icon with no contact shadow floats. One with a painted-on ellipse looks
    like a sticker. A real shadow catcher costs one plane and stays correct when
    the subject changes shape.
    """
    bpy.context.view_layer.update()
    corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    floor = min(p.z for p in corners)
    centre = sum(corners, Vector((0.0, 0.0, 0.0))) / len(corners)
    bm = mesh_lib.new_bmesh()
    mesh_lib.add_plane(
        bm,
        size=(radius * 14.0, radius * 14.0),
        center=(centre.x, centre.y, floor - max(1e-5, radius * 1e-4)),
    )
    plane = mesh_lib.to_object(bm, "_bforge_icon_floor")
    plane.is_shadow_catcher = True
    return plane


@op(
    "render.sprite",
    summary="Render a GAME ICON, not a screenshot: silhouette-safe shared framing on a long lens, a warm-key/cool-fill/bright-kicker rig anchored to the camera so a whole set matches, a real contact shadow, supersampled edges, a radial backdrop or clean alpha, and a linear-light post chain (highlight bloom, ACES tonemap, grade, vignette). Pass views>1 for a directional sheet with stable world scale and ground anchor at every angle.",
    params={
        "name": (
            "str",
            None,
            "Object to shoot; its children come with it. Omit to frame every mesh in the scene",
        ),
        "out": (
            "path",
            "sprite.png",
            "PNG output path. With views>1 a <stem>.json sidecar describing the grid is written next to it",
        ),
        "size": (
            "int",
            512,
            "Output size in pixels per square frame, clamped to 32-2048. Sheet dimensions participate in the aggregate resource preflight; 256-1024 is the useful icon range",
        ),
        "supersample": (
            "int",
            2,
            "Render each axis at 1-4x then area-downsample in premultiplied linear light for cleaner silhouette edges. The internal render is capped at 4096 px per axis and all supersampled pixels participate in the resource preflight",
        ),
        "views": (
            "int",
            1,
            "How many yaw angles to shoot, clamped to 1-64. 1 is an icon; 8 or 16 packs a stable-scale directional sheet. Every view participates in the aggregate resource preflight",
        ),
        "azimuth": (
            "num",
            -47.0,
            "Camera compass angle in degrees. -47 is the standard three-quarter view that shows a front and a side at once",
        ),
        "elevation": (
            "num",
            24.0,
            "Camera height above the horizon in degrees. 20-30 reads as 'held up in front of you'; 45+ becomes a map marker",
        ),
        "lens": (
            "num",
            85.0,
            "Focal length in mm. Long lenses flatten perspective, which is why product and icon work uses them — 85-135 keeps the far side of the object from tapering away",
        ),
        "fill": (
            "num",
            0.86,
            "Fraction of the frame the subject spans at its widest. Hold this constant across a set and the icons line up; that is the whole trick",
        ),
        "background": (
            "enum:gradient|solid|alpha",
            "gradient",
            "gradient is a radial backdrop that separates the silhouette everywhere; alpha leaves it transparent for compositing into a UI; solid is a flat fill",
        ),
        "bg_inner": ("colorref", "#4a5a72", "Backdrop colour behind the subject"),
        "bg_outer": ("colorref", "#1a2130", "Backdrop colour at the corners (gradient only)"),
        "key_color": ("colorref", ICON_KEY, "Key light colour — warm reads as sunlight"),
        "fill_color": (
            "colorref",
            ICON_FILL,
            "Fill light colour — cool reads as sky, and the warm/cool split is most of what makes a surface look lit rather than painted",
        ),
        "rim_color": ("colorref", ICON_RIM, "Kicker colour; the light that draws the silhouette"),
        "rim": (
            "num",
            1.0,
            "Kicker strength. 0 turns separation off, 1.5-2 is a hero/legendary treatment",
        ),
        "key_energy": (
            "num",
            1.0,
            "Key light strength multiplier. 1.0 puts an 18% grey card near the top of the mid-tones, which is where an icon wants to sit",
        ),
        "fill_energy": (
            "num",
            0.38,
            "Fill light strength multiplier. Raise it when the analysis reports crushed shadows — the shadow side of a three-quarter view is half the icon",
        ),
        "exposure": (
            "num",
            0.0,
            "Exposure compensation in stops, clamped to -16..16 and applied in linear light before the tonemap",
        ),
        "bloom": (
            "num",
            0.3,
            "Highlight glow strength. 0 disables it; above ~0.8 the asset starts to dissolve",
        ),
        "bloom_threshold": ("num", 0.85, "Linear luminance a pixel must exceed to bloom"),
        "contrast": ("num", 1.06, "Contrast multiplier about mid-grey, applied after the tonemap"),
        "saturation": (
            "num",
            1.04,
            "Saturation multiplier. Stylised game icons run hot; 1.0 is neutral",
        ),
        "vignette": (
            "num",
            0.22,
            "Corner darkening. Ignored when background=alpha, which must stay compositable",
        ),
        "look": (
            "enum:aces|punchy|linear",
            "aces",
            "Tonemap. aces is the film-style curve games ship; punchy adds saturation in the curve; linear clips, for data",
        ),
        "shadow": (
            "bool",
            True,
            "Cast a real contact shadow onto an invisible ground plane so the subject sits on something",
        ),
        "samples": (
            "int",
            96,
            "Path-tracing samples, clamped to 8-256 and charged per supersampled pixel/view by the aggregate resource preflight. Icons are small and seen close; 96-256 is the honest range",
        ),
    },
    tags=["render"],
)
def render_sprite(
    ctx,
    name,
    out,
    size,
    supersample,
    views,
    azimuth,
    elevation,
    lens,
    fill,
    background,
    bg_inner,
    bg_outer,
    key_color,
    fill_color,
    rim_color,
    rim,
    key_energy,
    fill_energy,
    exposure,
    bloom,
    bloom_threshold,
    contrast,
    saturation,
    vignette,
    look,
    shadow,
    samples,
):
    try:
        resource_plan = sprite_budget.plan_sprite_request(
            size=size,
            supersample=supersample,
            views=views,
            samples=samples,
        )
    except sprite_budget.SpriteBudgetError as exc:
        raise OpError(str(exc)) from exc
    size = resource_plan["frame_px"]
    render_size = resource_plan["render_px"]
    supersample = resource_plan["supersample"]
    views = resource_plan["views"]
    samples = resource_plan["samples"]
    cols = resource_plan["cols"]
    rows = resource_plan["rows"]

    from lib import mat as mat_lib
    from lib import post

    try:
        numpy = post.require_numpy()
    except RuntimeError as exc:
        raise OpError(str(exc)) from exc

    if name:
        try:
            root = scene_lib.get_object(name)
        except ValueError as exc:
            raise OpError(f"{exc} Run 'object.list' to see the names in the scene.") from exc
        meshes = [o for o in [root, *root.children_recursive] if o.type == "MESH"]
        if not meshes:
            raise OpError(
                f"'{name}' has no mesh geometry to shoot — it and its children are "
                "empties, armatures or lights. Run 'session.info' to see what is there."
            )
        object_name = root.name
    else:
        meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
        if not meshes:
            raise OpError("nothing to render — the scene has no mesh objects")
        object_name = ""

    try:
        inner = mat_lib.resolve_color(bg_inner)
        outer = mat_lib.resolve_color(bg_outer)
        resolved_key = mat_lib.resolve_color(key_color)
        resolved_fill = mat_lib.resolve_color(fill_color)
        resolved_rim = mat_lib.resolve_color(rim_color)
    except ValueError as exc:
        raise OpError(str(exc)) from exc

    elevation = max(-85.0, min(85.0, elevation))
    lens = max(8.0, lens)
    fill = max(0.05, min(0.98, fill))
    exposure = max(-16.0, min(16.0, exposure))
    el = math.radians(elevation)
    az = math.radians(azimuth)

    def _view_dir(yaw):
        """Unit vector FROM the camera TOWARDS the subject."""
        return -Vector(
            (
                math.cos(el) * math.cos(yaw),
                math.cos(el) * math.sin(yaw),
                math.sin(el),
            )
        )

    yaws = [az + (math.tau * index / views if views > 1 else 0.0) for index in range(views)]
    directions = [_view_dir(yaw) for yaw in yaws]
    target, distance, frame_radius, ground_anchor, bases = _fit_sprite_views(
        meshes, directions, lens, 1.0, fill
    )
    rigs = [
        (yaw, direction, right, up, forward)
        for yaw, direction, (right, up, forward) in zip(yaws, directions, bases, strict=True)
    ]
    _subject_centre, subject_radius = _bounding_sphere(meshes)
    scale_px_per_m = size / (2.0 * distance * math.tan(math.atan(36.0 / (2.0 * lens))))

    scene = bpy.context.scene
    settings = scene.render.image_settings
    view = scene.view_settings
    previous_render = {
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
        "resolution_percentage": scene.render.resolution_percentage,
        "film_transparent": scene.render.film_transparent,
        "filepath": scene.render.filepath,
    }
    previous_image = {
        "file_format": settings.file_format,
        "color_mode": settings.color_mode,
        "color_depth": settings.color_depth,
        "exr_codec": settings.exr_codec,
    }
    previous_view = {
        "transform": view.view_transform,
        "look": view.look,
        "exposure": view.exposure,
        "gamma": view.gamma,
    }

    hidden = _hide_others(meshes)
    path = ctx.out_path(out, ".png")
    sidecar = path.with_suffix(".json")
    scratch = ctx.out_dir / "_sprite"
    scratch.mkdir(parents=True, exist_ok=True)
    sheet = numpy.zeros((rows * size, cols * size, 4), dtype=numpy.float32)
    floor = None
    camera = None
    lights = []
    frame_metrics = []
    try:
        floor = _shadow_catcher(meshes, subject_radius) if shadow else None

        camera_data = bpy.data.cameras.new("_bforge_sprite")
        camera = bpy.data.objects.new("_bforge_sprite", camera_data)
        scene.collection.objects.link(camera)
        scene.camera = camera
        camera_data.lens = lens
        camera_data.sensor_width = 36.0
        camera_data.sensor_fit = "HORIZONTAL"

        if scene.world is None:
            scene.world = bpy.data.worlds.new("World")
        scene.world.use_nodes = True
        world_tree = scene.world.node_tree
        world_tree.nodes.clear()
        world_output = world_tree.nodes.new("ShaderNodeOutputWorld")
        dome = world_tree.nodes.new("ShaderNodeBackground")
        dome.inputs["Color"].default_value = (0.05, 0.055, 0.07, 1.0)
        dome.inputs["Strength"].default_value = 0.35
        world_tree.links.new(dome.outputs["Background"], world_output.inputs["Surface"])

        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = samples
        scene.cycles.seed = 0
        scene.cycles.use_denoising = True
        scene.cycles.max_bounces = 4
        scene.cycles.diffuse_bounces = 4
        scene.cycles.glossy_bounces = 4
        scene.cycles.transmission_bounces = 4
        scene.cycles.caustics_reflective = False
        scene.cycles.caustics_refractive = False
        scene.render.resolution_x = render_size
        scene.render.resolution_y = render_size
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True

        # EXR preserves the scene-linear highlights that bloom needs. PNG would
        # clip and display-transform them before the post chain ever saw them.
        settings.file_format = "OPEN_EXR"
        settings.color_mode = "RGBA"
        settings.color_depth = "32"
        settings.exr_codec = "ZIP"
        for candidate in ("Raw", "Standard"):
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

        for index, rig_data in enumerate(rigs):
            yaw, direction, right, up, forward = rig_data
            camera.location = target - direction * distance
            camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
            nearest = max(1e-5, distance - subject_radius * 1.1)
            camera_data.clip_start = max(1e-5, min(distance * 0.001, nearest))
            camera_data.clip_end = max(distance * 8.0, distance + subject_radius * 2.0)

            _cleanup_rig(lights)
            lights = _icon_lights(
                target,
                subject_radius,
                right,
                up,
                forward,
                resolved_key,
                resolved_fill,
                resolved_rim,
                rim,
                key_energy,
                fill_energy,
            )
            bpy.context.view_layer.update()

            exr = scratch / f"frame_{index:03d}.exr"
            _render_to(exr)
            raw = post.load(exr)
            frame, foreground_alpha = _compose_sprite(
                post,
                numpy,
                raw,
                size,
                background,
                inner,
                outer,
                exposure,
                bloom,
                bloom_threshold,
                look,
                contrast,
                saturation,
                vignette,
            )
            row, column = divmod(index, cols)
            sheet[row * size : (row + 1) * size, column * size : (column + 1) * size] = frame
            record = {
                "index": index,
                "yaw_degrees": round(math.degrees(yaw) % 360.0, 6),
                "target_m": [round(value, 5) for value in target],
                "distance_m": round(distance, 5),
                "frame_radius_m": round(frame_radius, 5),
                "ground_anchor_m": [round(value, 5) for value in ground_anchor],
                "ground_anchor_px": _project_sprite_point(
                    ground_anchor,
                    target,
                    distance,
                    (right, up, forward),
                    lens,
                    1.0,
                    size,
                ),
                "scale_px_per_m": round(scale_px_per_m, 5),
            }
            record.update(_foreground_alpha_metrics(numpy, foreground_alpha))
            frame_metrics.append(record)

        post.save(
            sheet,
            path,
            name="_bforge_sprite_out",
            premultiplied=background == "alpha",
        )
    finally:
        if scratch.exists():
            for exr in scratch.glob("*.exr"):
                exr.unlink(missing_ok=True)
            try:
                scratch.rmdir()
            except OSError:
                pass
        _cleanup_rig(lights + [camera] + ([floor] if floor is not None else []))
        for obj in hidden:
            obj.hide_render = False
        view.view_transform = previous_view["transform"]
        try:
            view.look = previous_view["look"]
        except TypeError:
            pass
        view.exposure = previous_view["exposure"]
        view.gamma = previous_view["gamma"]
        for key, value in previous_image.items():
            setattr(settings, key, value)
        for key, value in previous_render.items():
            setattr(scene.render, key, value)

    framing = {
        "target_m": [round(value, 5) for value in target],
        "distance_m": round(distance, 5),
        "ground_anchor_m": [round(value, 5) for value in ground_anchor],
        "ground_anchor_px": frame_metrics[0]["ground_anchor_px"],
        "scale_px_per_m": round(scale_px_per_m, 5),
    }

    result = {
        "path": str(path),
        "rel": ctx.rel(path),
        "object": object_name,
        "frames": views,
        "cols": cols,
        "rows": rows,
        "frame_px": size,
        "render_px": render_size,
        "supersample": supersample,
        "samples": samples,
        "fill_target": round(fill, 4),
        "subject_radius_m": round(subject_radius, 5),
        "budget": resource_plan["budget"],
        "framing": framing,
        "camera": {
            "azimuth": azimuth,
            "elevation": elevation,
            "lens_mm": lens,
            "distance_m": frame_metrics[0]["distance_m"],
        },
        "frame_metrics": frame_metrics,
        "background": background,
        "exposure": exposure,
        "bytes": path.stat().st_size,
    }
    if views > 1:
        sidecar_payload = {
            "frames": views,
            "cols": cols,
            "rows": rows,
            "frame_px": size,
            "render_px": render_size,
            "supersample": supersample,
            "samples": samples,
            "fill_target": round(fill, 4),
            "background": background,
            "exposure": exposure,
            "elevation": elevation,
            "lens_mm": lens,
            "object": object_name,
            "budget": resource_plan["budget"],
            "framing": framing,
            "camera_frames": frame_metrics,
        }
        _atomic_write_text(
            sidecar,
            json.dumps(sidecar_payload, indent=2) + "\n",
        )
        result["sidecar"] = ctx.rel(sidecar)
    else:
        # A successful single-view replacement must not leave the old
        # directional contract beside the new, non-sheet PNG.
        sidecar.unlink(missing_ok=True)
    result["analysis"] = _analyse(ctx, path)
    return result


def _compose_sprite(
    post,
    numpy,
    raw,
    size,
    background,
    inner,
    outer,
    exposure,
    bloom,
    bloom_threshold,
    look,
    contrast,
    saturation,
    vignette,
):
    """Scene-referred premultiplied RGBA -> a finished icon frame."""
    raw = post.downsample(raw, size, size)

    frame = post.bloom(
        raw,
        threshold=bloom_threshold,
        strength=bloom,
        radius=0.045,
        premultiplied=True,
    )
    foreground_alpha = frame[..., 3].copy()

    # Colour curves are nonlinear, so apply them to straight RGB and then
    # premultiply again. Applying ACES directly to premultiplied antialiasing
    # values creates bright or dark fringes around the cut-out.
    straight = post.unpremultiply(frame)
    straight[..., :3] = post.tonemap(straight[..., :3], look=look, exposure=exposure)

    if background == "alpha":
        straight[..., :3] = post.saturate(post.contrast(straight[..., :3], contrast), saturation)
        return (
            numpy.clip(post.premultiply(straight), 0.0, 1.0),
            foreground_alpha,
        )

    frame = post.premultiply(straight)
    height, width = frame.shape[:2]
    if background == "solid":
        backdrop = numpy.broadcast_to(
            numpy.array(inner[:3], dtype=numpy.float32), (height, width, 3)
        ).copy()
    else:
        backdrop = post.radial_backdrop(width, height, inner, outer)
    composed = post.over(frame, backdrop, premultiplied=True)
    composed[..., :3] = post.saturate(post.contrast(composed[..., :3], contrast), saturation)
    composed[..., :3] = post.vignette(composed[..., :3], vignette)
    return numpy.clip(composed, 0.0, 1.0), foreground_alpha


def _foreground_alpha_metrics(numpy, alpha):
    """Content bounds from foreground alpha, independent of the backdrop."""
    height, width = alpha.shape
    threshold = 1.0 / 255.0
    edge = numpy.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
    metrics = {
        "alpha_min": round(float(alpha.min()), 5),
        "alpha_max": round(float(alpha.max()), 5),
        "alpha_coverage": round(float((alpha > threshold).mean()), 5),
        "edge_alpha_max": round(float(edge.max()), 5),
        "clipped": bool((edge > threshold).any()),
    }
    ys, xs = numpy.nonzero(alpha > threshold)
    if not len(xs):
        metrics.update(
            {
                "content_bounds_px": None,
                "clearance_px": None,
                "bottom_center_px": None,
            }
        )
        return metrics
    left = int(xs.min())
    top = int(ys.min())
    right = int(xs.max()) + 1
    bottom = int(ys.max()) + 1
    metrics.update(
        {
            # right/bottom are exclusive, matching Python image slices.
            "content_bounds_px": [left, top, right, bottom],
            "clearance_px": [left, top, width - right, height - bottom],
            "bottom_center_px": [round((left + right - 1) * 0.5, 4), bottom - 1],
        }
    )
    return metrics
