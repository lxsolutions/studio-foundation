extends SceneTree
## Art-direction capture: put the camera where a driver sees the stands.
##
##   godot --path project --rendering-driver opengl3 \
##     --script res://tests/capture_crowd.gd -- --out user://captures/crowd.png
##
## The broadcast view's own establishing shot looks down from beyond the attic
## rim, which is the one angle that tells you nothing about whether the crowd
## reads. This drops the camera onto the sand looking up at the near tiers, and
## also prints the seat statistics so the crowd can be checked numerically
## rather than by squinting at a software render.

var _out_path := "user://captures/crowd.png"
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
		_report()
		_place_camera()
		return false
	if _instance != null and _frames >= 2 + _settle * 2:
		_save()
		return true
	if _frames > 600:
		printerr("[crowd] frame cap")
		quit(1)
		return true
	return false


## Numeric proof the house sits ON the stands: the seating surface runs from
## the podium out to the back wall, and every spectator must fall inside it.
func _report() -> void:
	var crowd := _instance.find_child("*", true, false)
	for child in _instance.get_children():
		if child is CrowdDirector:
			crowd = child
			break
	if crowd == null or not (crowd is CrowdDirector):
		printerr("[crowd] no CrowdDirector in the scene")
		return
	var director := crowd as CrowdDirector
	var seats: Array = director.seat_positions
	if seats.is_empty():
		printerr("[crowd] zero seats")
		return
	var lo_h := INF
	var hi_h := -INF
	var lo_r := INF
	var hi_r := -INF
	for seat in seats:
		var p: Vector3 = seat
		lo_h = minf(lo_h, p.y)
		hi_h = maxf(hi_h, p.y)
		var radial := Vector2(p.x, p.z).length()
		lo_r = minf(lo_r, radial)
		hi_r = maxf(hi_r, radial)
	var stands: Dictionary = director.stands_spec()
	var podium: float = director.podium_offset()
	var back: float = podium + float(stands.tiers) * float(stands.tier_depth_m)
	# The seating surface tops out at the last tread, one row-step below the
	# cavea's structural top (the arcade rises from there). A seat above it is
	# floating over the back wall — exactly the ship that made the house read
	# as hovering in mid-air.
	var top_tread: float = float(stands.podium_height_m) \
		+ float(stands.tiers) * (float(stands.tier_rise_m) + float(stands.tier_riser_m)) \
		- float(stands.tier_rise_m) / float(stands.rows_per_tier)
	print("[crowd] spectators=%d" % seats.size())
	print("[crowd] seat height  %.1f .. %.1f m   (treads %.1f .. %.1f m)"
		% [lo_h, hi_h, float(stands.podium_height_m) + float(stands.tier_riser_m), top_tread])
	print("[crowd] seat depth   %.1f .. %.1f m   (stands %.1f .. %.1f m from centre)"
		% [lo_r, hi_r, podium, back])
	if hi_h > top_tread + 0.3:
		printerr("[crowd] SEATS ABOVE THE STANDS by %.1f m — spectators are floating"
			% [hi_h - top_tread])


func _place_camera() -> void:
	var camera := _instance.find_child("Camera3D", true, false) as Camera3D
	if camera == null:
		for node in _instance.get_children():
			if node is Camera3D:
				camera = node
				break
	if camera == null:
		printerr("[crowd] no camera found")
		return
	# Stand on the sand near the outer rail, look up into the near tiers.
	var spec: Dictionary = TrackGeometry.spec()
	var s: float = float(spec.finish_s_m) - 40.0
	var outward: Vector3 = TrackGeometry.normal_at(s)
	var base: Vector3 = TrackGeometry.point_at(s)
	# Two useful vantages. "low" is the driver's eye — the shot that tells you
	# whether the crowd reads during a race. "face" looks squarely at the tiers
	# from mid-height, which is the only way to check that every course is
	# actually occupied rather than foreshortened into a stripe.
	var args := OS.get_cmdline_user_args()
	var eye: Vector3
	var target: Vector3
	if _opt(args, "--shot", "low") == "face":
		eye = base + outward * 10.0 + Vector3(0.0, 20.0, 0.0)
		target = base + outward * 58.0 + Vector3(0.0, 19.0, 0.0)
	else:
		eye = base + outward * 6.0 + Vector3(0.0, 2.4, 0.0)
		target = base + outward * 62.0 + Vector3(0.0, 22.0, 0.0)
	camera.global_position = eye
	camera.look_at(target, Vector3.UP)
	camera.fov = 60.0
	camera.set_process(false)
	if _instance.has_method("set_process"):
		_instance.set_process(false)


func _save() -> void:
	var texture := root.get_texture()
	var image: Image = texture.get_image() if texture != null else null
	if image == null:
		printerr("[crowd] no viewport image (headless dummy renderer?)")
		quit(1)
		return
	var global_path := ProjectSettings.globalize_path(_out_path)
	DirAccess.make_dir_recursive_absolute(global_path.get_base_dir())
	image.save_png(global_path)
	print("[crowd] wrote %s" % global_path)
	quit(0)


func _opt(args: PackedStringArray, name: String, fallback: String) -> String:
	var i := args.find(name)
	return args[i + 1] if i >= 0 and i + 1 < args.size() else fallback
