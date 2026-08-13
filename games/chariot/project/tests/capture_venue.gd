extends SceneTree
## Whole-venue diagnostic capture: establishing, far-end and spina-level shots.
## Cloned from capture_crowd.gd — same boot, different camera placements.
##
##   godot --path project --rendering-driver opengl3 \
##     --script res://tests/capture_venue.gd -- --shot wide --out user://captures/venue.png
##
## Shots:
##   wide   — high establishing shot over the whole oval from above the finish.
##   far    — from the sand at the finish looking down the straight at the FAR turn.
##   farend — outside the far turn looking back at its cavea from the east.
##   spina  — driver's eye on the home straight, spina wall on the left.
##   top    — straight down from above the centre: plan view of track vs stands.

var _out_path := "user://captures/venue.png"
var _instance: Node = null
var _frames := 0
var _settle := 10


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	_out_path = _opt(args, "--out", _out_path)
	_settle = int(_opt(args, "--frames", "10"))
	var size := _opt(args, "--size", "1280x720").split("x")
	if size.size() == 2:
		root.size = Vector2i(int(size[0]), int(size[1]))


func _process(_delta: float) -> bool:
	_frames += 1
	if _frames == 2:
		var packed: PackedScene = load("res://scenes/spectator.tscn")
		_instance = packed.instantiate()
		if "boot_route_enabled" in _instance:
			_instance.set("boot_route_enabled", false)
		root.add_child(_instance)
		return false
	if _instance != null and _frames == 2 + _settle:
		_place_camera()
		return false
	if _instance != null and _frames >= 2 + _settle * 2:
		_save()
		return true
	if _frames > 600:
		printerr("[venue] frame cap")
		quit(1)
		return true
	return false


func _place_camera() -> void:
	var camera := _instance.find_child("Camera3D", true, false) as Camera3D
	if camera == null:
		for node in _instance.get_children():
			if node is Camera3D:
				camera = node
				break
	if camera == null:
		printerr("[venue] no camera found")
		return
	var args := OS.get_cmdline_user_args()
	var shot := _opt(args, "--shot", "wide")
	var spec: Dictionary = TrackGeometry.spec()
	var straight := float(spec.straight_m)
	var radius := float(spec.turn_radius_m)
	var half := straight / 2.0
	var eye: Vector3
	var target: Vector3
	match shot:
		"wide":
			# High over the finish line, looking across the whole bowl.
			eye = Vector3(0.0, 150.0, -radius - 150.0)
			target = Vector3(0.0, 0.0, 20.0)
		"far":
			# On the sand at the finish, looking down the home straight at the far turn.
			eye = Vector3(-half + 20.0, 3.0, -radius - 6.0)
			target = Vector3(half + radius, 12.0, 0.0)
		"farend":
			# Outside the far (east) turn, looking back at its cavea.
			eye = Vector3(half + radius + 150.0, 60.0, 0.0)
			target = Vector3(half, 10.0, 0.0)
		"spina":
			# Driver's eye on the home straight; the spina runs down the infield.
			eye = Vector3(-half - 10.0, 3.0, -radius - 10.0)
			target = Vector3(half, 2.0, -radius + 20.0)
		"top":
			# Plan view straight down over the centre.
			eye = Vector3(0.0, 320.0, 0.0)
			target = Vector3(0.0, 0.0, 0.01)
		_:
			eye = Vector3(0.0, 150.0, -radius - 150.0)
			target = Vector3(0.0, 0.0, 20.0)
	camera.global_position = eye
	camera.look_at(target, Vector3.UP)
	camera.far = 6000.0
	camera.fov = 70.0
	camera.set_process(false)
	if _instance.has_method("set_process"):
		_instance.set_process(false)


func _save() -> void:
	var texture := root.get_texture()
	var image: Image = texture.get_image() if texture != null else null
	if image == null:
		printerr("[venue] no viewport image (headless dummy renderer?)")
		quit(1)
		return
	var global_path := ProjectSettings.globalize_path(_out_path)
	DirAccess.make_dir_recursive_absolute(global_path.get_base_dir())
	image.save_png(global_path)
	print("[venue] wrote %s" % global_path)
	quit(0)


func _opt(args: PackedStringArray, name: String, fallback: String) -> String:
	var i := args.find(name)
	return args[i + 1] if i >= 0 and i + 1 < args.size() else fallback
