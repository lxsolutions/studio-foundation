class_name StudioSceneRouter
extends RefCounted
## Scene transition management with async loading and a fade curtain.

signal scene_changed(path: String)

var _host: Node
var _curtain: CanvasLayer = null
var current_path: String = ""


func _init(host: Node) -> void:
	_host = host


func go_to(scene_path: String, fade_seconds: float = 0.15) -> void:
	if _host == null or _host.get_tree() == null:
		return
	var tree: SceneTree = _host.get_tree()
	await _fade(true, fade_seconds)
	# Threaded load with a poll loop; falls back to blocking load on error.
	ResourceLoader.load_threaded_request(scene_path)
	var status: ResourceLoader.ThreadLoadStatus = ResourceLoader.load_threaded_get_status(scene_path)
	while status == ResourceLoader.THREAD_LOAD_IN_PROGRESS:
		await tree.process_frame
		status = ResourceLoader.load_threaded_get_status(scene_path)
	var packed: PackedScene = null
	if status == ResourceLoader.THREAD_LOAD_LOADED:
		packed = ResourceLoader.load_threaded_get(scene_path)
	else:
		packed = load(scene_path)
	if packed == null:
		push_error("StudioSceneRouter: failed to load %s" % scene_path)
		await _fade(false, fade_seconds)
		return
	tree.change_scene_to_packed(packed)
	current_path = scene_path
	await tree.process_frame
	await _fade(false, fade_seconds)
	scene_changed.emit(scene_path)


func _fade(to_black: bool, seconds: float) -> void:
	if seconds <= 0.0:
		return
	if _curtain == null:
		_curtain = CanvasLayer.new()
		_curtain.layer = 100
		var rect: ColorRect = ColorRect.new()
		rect.name = "Fade"
		rect.color = Color(0, 0, 0, 0)
		rect.set_anchors_preset(Control.PRESET_FULL_RECT)
		rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
		_curtain.add_child(rect)
		_host.add_child(_curtain)
	var fade_rect: ColorRect = _curtain.get_node("Fade")
	var tween: Tween = _host.create_tween()
	tween.tween_property(fade_rect, "color:a", 1.0 if to_black else 0.0, seconds)
	await tween.finished
