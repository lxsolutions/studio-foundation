extends Node
## Render-stats probe: proves a scene is ACTUALLY DRAWING, independent of any
## screenshot.
##
## Why this exists: on a headless GPU host (Xvfb + headed Chrome) the WebGPU
## canvas cannot be composited back for readback — a screenshot, `drawImage`, or
## `getImageData` all return pure black even while the GPU renders correctly. A
## green-clear control proves that: it also reads [0,0,0,0]. So "the capture is
## black" is NOT evidence of a rendering failure, and treating it as such has
## already produced false conclusions in this project.
##
## The engine's own per-frame counters are the reliable signal. Register this as
## an autoload in the exported project and read the console:
##
##     [RPROBE] fps=60 draws=631 objects=693 prims=23015626 scene=Spectator visual3d=1086 camera=yes
##
## Read it as: `draws`/`prims` > 0 over several samples means geometry really is
## being submitted; `visual3d` is how much the scene built; `camera=NO` explains
## a genuinely empty frame. Combine with 0 `GPUValidationError` in the browser
## console for a complete verdict.
##
## Usage (in the project being verified, not in this repo):
##   1. Copy this file to `res://render_probe.gd`.
##   2. project.godot -> [autoload] -> RenderProbe="*res://render_probe.gd"
##   3. Export, run, read the console.
##
## GOTCHA: projects that treat GDScript warnings as errors (this repo's games do)
## reject `var x := <Variant>` with "The variable type is being inferred from a
## Variant value". The autoload then silently fails to register — the error is
## printed at IMPORT/EXPORT time, not at runtime, so the probe just never prints.
## Every local here is therefore explicitly typed; keep it that way.

## Seconds between samples.
const INTERVAL_SECONDS: float = 3.0
## Stop after this many samples so long runs do not spam the console.
const MAX_REPORTS: int = 4

var _elapsed: float = 0.0
var _reports: int = 0


func _process(delta: float) -> void:
	_elapsed += delta
	if _elapsed < INTERVAL_SECONDS or _reports >= MAX_REPORTS:
		return
	_elapsed = 0.0
	_reports += 1
	print("[RPROBE] " + _sample())


## Returns one line of render stats. Split out so tests can assert on it without
## waiting on frame timing.
func _sample() -> String:
	var draws: int = RenderingServer.get_rendering_info(
		RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME
	)
	var objects: int = RenderingServer.get_rendering_info(
		RenderingServer.RENDERING_INFO_TOTAL_OBJECTS_IN_FRAME
	)
	var primitives: int = RenderingServer.get_rendering_info(
		RenderingServer.RENDERING_INFO_TOTAL_PRIMITIVES_IN_FRAME
	)
	var scene_root: Node = get_tree().current_scene
	var scene_name: String = "<none>"
	if scene_root != null:
		scene_name = str(scene_root.name)
	var camera: Camera3D = get_viewport().get_camera_3d()
	var has_camera: String = "yes" if camera != null else "NO"
	return (
		"fps=%d draws=%d objects=%d prims=%d scene=%s visual3d=%d camera=%s"
		% [
			Engine.get_frames_per_second(),
			draws,
			objects,
			primitives,
			scene_name,
			count_visual_instances(scene_root),
			has_camera,
		]
	)


## Counts VisualInstance3D nodes below `node`. A high count with `draws=0` means
## the world built but nothing reached the GPU; both at 0 means the scene itself
## is empty. Note `--headless` always reports draws=0 (dummy renderer cannot
## rasterize) while still reporting a correct visual3d count.
static func count_visual_instances(node: Node) -> int:
	if node == null:
		return 0
	var total: int = 1 if node is VisualInstance3D else 0
	for child in node.get_children():
		total += count_visual_instances(child)
	return total
