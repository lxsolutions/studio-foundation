class_name StudioPerfOverlay
extends CanvasLayer
## Performance metrics overlay (F11). Debug builds only. Also the data source
## for benchmark captures (tools/benchmark reads the same counters).

var _label: Label
var _accumulator: float = 0.0


func _ready() -> void:
	if not OS.is_debug_build():
		queue_free()
		return
	layer = 95
	visible = false
	_label = Label.new()
	_label.position = Vector2(8, 8)
	_label.add_theme_color_override("font_color", Color(0.6, 1.0, 0.6))
	_label.add_theme_font_size_override("font_size", 13)
	add_child(_label)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("dev_perf_overlay"):
		visible = not visible
		get_viewport().set_input_as_handled()


static func snapshot() -> Dictionary:
	return {
		"fps": Performance.get_monitor(Performance.TIME_FPS),
		"frame_ms": Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0,
		"physics_ms": Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0,
		"draw_calls": Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),
		"objects_rendered": Performance.get_monitor(Performance.RENDER_TOTAL_OBJECTS_IN_FRAME),
		"primitives": Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME),
		"video_mem_mb": Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED) / 1048576.0,
		"static_mem_mb": Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0,
		"node_count": Performance.get_monitor(Performance.OBJECT_NODE_COUNT),
	}


func _process(delta: float) -> void:
	if not visible:
		return
	_accumulator += delta
	if _accumulator < 0.25:
		return
	_accumulator = 0.0
	var data: Dictionary = snapshot()
	_label.text = (
		"fps %d  frame %.2fms  physics %.2fms\ndraw %d  objects %d  prims %d\nvram %.1fMB  mem %.1fMB  nodes %d"
		% [
			int(data["fps"]), data["frame_ms"], data["physics_ms"],
			int(data["draw_calls"]), int(data["objects_rendered"]), int(data["primitives"]),
			data["video_mem_mb"], data["static_mem_mb"], int(data["node_count"]),
		]
	)
