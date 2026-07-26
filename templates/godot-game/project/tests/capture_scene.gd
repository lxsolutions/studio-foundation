extends SceneTree
## Headless scene capture:
##   godot --headless --path project --script res://tests/capture_scene.gd -- \
##     --scene res://scenes/main_menu.tscn --out user://captures/main_menu.png [--frames 5] [--size 1280x720]
## Loads a scene off-screen, lets it settle a few frames, and writes a PNG.
## Deterministic enough for visual-regression baselines (fixed seed via
## project settings; agents should capture with the same --size every time).
##
## For MEASURED captures (exposure, probes, HUD checks) use the QA gate
## instead: tools/godot/qa_capture.py with res://tests/qa_shots.gd.

var _scene_path := ""
var _out_path := "user://captures/capture.png"
var _settle_frames := 8
var _target_size := Vector2i.ZERO
var _size_settled := false
var _instance: Node = null
var _frames_seen := 0


func _initialize() -> void:
	print("[capture] alive")
	var args := OS.get_cmdline_user_args()
	_scene_path = _opt(args, "--scene", "")
	_out_path = _opt(args, "--out", _out_path)
	_settle_frames = int(_opt(args, "--frames", "8"))
	var size := _opt(args, "--size", "1280x720")
	if _scene_path.is_empty():
		printerr("[capture] missing --scene <res://...>")
		quit(2)
		return
	var parts := size.split("x")
	if parts.size() == 2:
		_target_size = Vector2i(int(parts[0]), int(parts[1]))


func _process(_delta: float) -> bool:
	_frames_seen += 1
	# Window resizes land asynchronously, and a size set during _initialize is
	# silently overridden when the window first shows — captures came back at
	# the project default no matter what --size asked. Ask on the first frame,
	# then hold until the OS agrees (or a short cap expires).
	if not _size_settled:
		if _target_size == Vector2i.ZERO:
			_size_settled = true
			_frames_seen = 0
			return false
		if _frames_seen == 1:
			root.mode = Window.MODE_WINDOWED
			root.borderless = true
			root.size = _target_size
			return false
		if root.size != _target_size and _frames_seen < 40:
			return false
		_size_settled = true
		_frames_seen = 0
		return false
	# Defer scene instantiation until autoloads and the tree are active.
	if _frames_seen == 1:
		var packed: Variant = load(_scene_path)
		if packed == null or not (packed is PackedScene):
			printerr("[capture] cannot load scene: " + _scene_path)
			quit(2)
			return true
		_instance = (packed as PackedScene).instantiate()
		root.add_child(_instance)
		return false
	if _instance != null and _frames_seen >= 1 + _settle_frames:
		_save()
		return true
	# Safety cap: never run forever even if something stalls.
	if _frames_seen > 600:
		printerr("[capture] frame cap reached without capture")
		quit(1)
		return true
	return false


func _save() -> void:
	# NOTE: with the headless/dummy rendering driver there is no rasterized
	# viewport to read back, so this path only works when a real renderer is
	# attached (e.g. non-headless --display-driver or editor). For CI
	# screenshots use the browser capture tool (tools/screenshots/capture_web.py)
	# which drives a real GPU through Playwright instead.
	var texture := root.get_texture()
	var image: Image = texture.get_image() if texture != null else null
	if image == null:
		printerr("[capture] no viewport image — headless dummy renderer cannot rasterize; use just capture-web")
		quit(1)
		return
	var global_path := ProjectSettings.globalize_path(_out_path)
	DirAccess.make_dir_recursive_absolute(global_path.get_base_dir())
	var err := image.save_png(global_path)
	if err != OK:
		printerr("[capture] save failed (%s) -> %s" % [err, global_path])
		quit(1)
		return
	print("[capture] wrote %s (%dx%d)" % [global_path, image.get_width(), image.get_height()])
	quit(0)


func _opt(args: PackedStringArray, name: String, fallback: String) -> String:
	var i := args.find(name)
	return args[i + 1] if i >= 0 and i + 1 < args.size() else fallback
