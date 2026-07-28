extends Node
class_name StudioRenderCounters

## Publishes the engine's own per-frame render counters to the browser, so an
## automated probe can corroborate "a frame rendered" with something other than
## pixels.
##
## Pixels alone are not sufficient evidence. A loading screen, a 2D error
## overlay and a gradient background all produce varied pixels, and a compositor
## can produce an image the game did not draw. Worse, the reverse also happens:
## on this studio's own Chrome/Xvfb host a canvas readback returned solid black
## while the game was demonstrably rendering, which turned a verification probe
## into a source of false negatives.
##
## The engine's draw / object / primitive counts come from the renderer itself
## and are not subject to either failure. They are the corroboration a
## first-frame claim needs.
##
## Web-only, and deliberately cheap: one JavaScriptBridge call per interval, not
## per frame. Does nothing on other platforms and nothing when disabled.

const GLOBAL := "__studioRenderProbe"

## Seconds between publishes. Frequent enough for a probe that waits tens of
## seconds; rare enough not to distort what it measures.
@export var interval_seconds: float = 0.5

var _accum: float = 0.0
var _frames: int = 0
var _enabled: bool = false


func _ready() -> void:
	# Only on web, where a browser probe can read it. `JavaScriptBridge` exists
	# on other platforms but has no window to publish into.
	_enabled = OS.has_feature("web") and JavaScriptBridge.get_interface("window") != null
	set_process(_enabled)


func _process(delta: float) -> void:
	_frames += 1
	_accum += delta
	if _accum < interval_seconds:
		return
	_accum = 0.0
	_publish()


func snapshot() -> Dictionary:
	## The counters as the renderer reports them, plus enough context that a
	## report can say which renderer produced them.
	return {
		"frames": _frames,
		"draws": RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME),
		"objects": RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_OBJECTS_IN_FRAME),
		"primitives": RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_PRIMITIVES_IN_FRAME),
		"video_mem": RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_VIDEO_MEM_USED),
		"renderer": ProjectSettings.get_setting("rendering/renderer/rendering_method", ""),
		"adapter": RenderingServer.get_video_adapter_name(),
		"fps": Engine.get_frames_per_second(),
	}


func _publish() -> void:
	if not _enabled:
		return
	var data: Dictionary = snapshot()
	# JSON round-trip rather than building a JS object field by field: one eval,
	# and no chance of an unescaped adapter name breaking the expression.
	var payload: String = JSON.stringify(data)
	JavaScriptBridge.eval("globalThis.%s = %s;" % [GLOBAL, payload], true)
