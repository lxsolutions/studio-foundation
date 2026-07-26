extends SceneTree
## Visual QA gate: renders a game's declared shots through Godot's REAL
## renderer, then measures what came back (StudioQaMeasure) instead of asking a
## human to squint at PNGs. The budget gate (audit_scene_budget.gd) checks what
## a scene ASKS the renderer for; this checks what the player actually SEES —
## exposure, palette, probe colors, and whether the HUD is on screen and
## touchable at phone scale.
##
## NOT --headless: the dummy driver cannot rasterize. On a GPU-less box use the
## ANGLE/D3D11 path (tools/godot/qa_capture.py picks it by default):
##   godot --path project --rendering-method gl_compatibility \
##     --rendering-driver opengl3_angle \
##     --script res://addons/studio_core/tools/qa_capture.gd -- [--options]
##
## The game declares its shots in res://tests/qa_shots.gd (see --driver), a
## RefCounted with:
##   func shots() -> Array            required; see SHOT KEYS below
##   func env() -> Dictionary         optional; env vars set before anything
##                                    loads (e.g. a client's offline seam), so
##                                    a still never depends on a live server
##   any setup/beat methods shots name, each taking the scene root
##
## SHOT KEYS (per Dictionary in shots()):
##   name       String, unique; the PNG basename
##   scene      res:// path to instantiate
##   devices    subset of DEVICES keys (default ["desktop", "phone"])
##   profile    render profile to apply before the scene builds (optional)
##   profiles   per-device profile map, e.g. {"phone": "mobile_high"} — wins
##              over `profile` for that device, so a phone still runs the
##              phone tier (honest crowd density, and far cheaper to build)
##   pre_setup  driver method called right after instantiate, BEFORE the scene
##              enters the tree — for flags _ready reads (boot routing, seeds)
##   setup      driver method called one frame AFTER the scene enters the
##              tree — _ready must have run, or fixtures land on a view whose
##              GLB scenes are still null and the still shows an empty field
##   run_s      seconds to let the scene run after setup (default 1.2)
##   then       driver method fired after run_s, for beats that are over
##              faster than a camera settles (a whip stroke)
##   settle_s   seconds after run_s / the then-beat before the grab (default 0.4)
##   frame      StudioQaMeasure.check_frame spec (luma/saturation/probes)
##   hud        StudioQaMeasure.check_controls spec (margin, min_tap_px);
##              controls come from the qa_hud group, tap targets from qa_tap
##
## Writes <out>/<shot>__<device>.png + <out>/report.json. The report carries
## measured luma/saturation for EVERY still, checked or not, so bounds can be
## pinned from a first calibration run instead of guessed.
##
## Exit codes: 0 conformant, 1 findings, 2 bad usage / tool failure.

const DEVICES := {
	"desktop": {"size": Vector2i(1280, 720), "touch": false},
	"tablet": {"size": Vector2i(1024, 768), "touch": true},
	"phone": {"size": Vector2i(390, 844), "touch": true},
}
const DEFAULT_DEVICES: Array[String] = ["desktop", "phone"]
const HUD_GROUP := "qa_hud"
const TAP_GROUP := "qa_tap"
## Frames allowed for the OS to actually apply a window resize before we give
## up and measure at whatever size stuck. Resizing is asynchronous on every
## desktop platform, which is exactly the bug that shipped captures at
## 1280x720 regardless of the requested size.
const RESIZE_FRAME_CAP := 30

enum Stage { RESIZE, SPAWN, SETUP, RUN, CAPTURE }

var _driver: RefCounted = null
var _jobs: Array[Dictionary] = []
var _job := 0
var _stage := Stage.RESIZE
var _stage_frames := 0
var _elapsed := 0.0
var _then_fired := false
var _view: Node = null
var _out_dir := "res://build/qa"
var _warn_only := false
var _as_json := false
var _results: Array[Dictionary] = []
var _tool_failures := 0


func _initialize() -> void:
	print("[qa] runner alive")
	var args := _parse_args()
	var driver_path := str(args.get("driver", "res://tests/qa_shots.gd"))
	_out_dir = str(args.get("out", _out_dir))
	_warn_only = args.has("warn-only")
	_as_json = args.has("json")

	if not ResourceLoader.exists(driver_path):
		printerr("[qa] no driver at %s — the game declares its shots there" % driver_path)
		quit(2)
		return
	var driver_script := load(driver_path) as GDScript
	if driver_script == null or not driver_script.can_instantiate():
		printerr("[qa] driver failed to load: %s" % driver_path)
		quit(2)
		return
	_driver = driver_script.new()
	if not _driver.has_method("shots"):
		printerr("[qa] driver has no shots() method: %s" % driver_path)
		quit(2)
		return

	# The env hook runs before any scene exists so clients read their offline
	# seams at _ready and a capture never photographs a live server's state.
	if _driver.has_method("env"):
		var env_vars: Dictionary = _driver.call("env")
		for key in env_vars:
			OS.set_environment(str(key), str(env_vars[key]))

	var shots: Array = _driver.call("shots")
	if args.has("list"):
		for shot in shots:
			print("  %s (%s)" % [str((shot as Dictionary).get("name", "?")),
				", ".join(PackedStringArray(_devices_of(shot)))])
		quit(0)
		return

	var only_shots := _csv(str(args.get("shots", "")))
	var only_devices := _csv(str(args.get("devices", "")))
	for shot in shots:
		var shot_dict: Dictionary = shot
		if not only_shots.is_empty() and not only_shots.has(str(shot_dict.get("name", ""))):
			continue
		for device in _devices_of(shot_dict):
			if not only_devices.is_empty() and not only_devices.has(device):
				continue
			if not DEVICES.has(device):
				printerr("[qa] unknown device '%s' in shot '%s'" % [device, shot_dict.get("name", "?")])
				_tool_failures += 1
				continue
			_jobs.append({"shot": shot_dict, "device": device})
	if _jobs.is_empty():
		printerr("[qa] nothing to run")
		quit(2)
		return

	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_out_dir))
	print("[qa] %d job(s), renderer=%s/%s" % [
		_jobs.size(),
		RenderingServer.get_current_rendering_method(),
		RenderingServer.get_current_rendering_driver_name(),
	])


func _devices_of(shot: Dictionary) -> Array:
	return shot.get("devices", DEFAULT_DEVICES) as Array


func _csv(raw: String) -> Array:
	var out: Array = []
	for piece in raw.split(",", false):
		out.append(piece.strip_edges())
	return out


func _parse_args() -> Dictionary:
	var out := {}
	for raw in OS.get_cmdline_user_args():
		var arg := String(raw)
		if not arg.begins_with("--"):
			continue
		arg = arg.substr(2)
		var eq := arg.find("=")
		if eq == -1:
			out[arg] = true
		else:
			out[arg.substr(0, eq)] = arg.substr(eq + 1)
	return out


func _process(_delta: float) -> bool:
	if _driver == null:
		return true
	if _job >= _jobs.size():
		return _finish()
	var job := _jobs[_job]
	var shot: Dictionary = job["shot"]
	var device: Dictionary = DEVICES[job["device"]]
	match _stage:
		Stage.RESIZE:
			_stage_resize(device)
		Stage.SPAWN:
			_stage_spawn(shot, str(job["device"]))
		Stage.SETUP:
			_stage_setup(shot)
		Stage.RUN:
			_stage_run(shot, _delta)
		Stage.CAPTURE:
			_stage_capture(job, shot, device)
	return false


## Window resizes land asynchronously; ask once, then wait until the OS agrees
## (or the frame cap expires and we record whatever stuck).
func _stage_resize(device: Dictionary) -> void:
	var target: Vector2i = device["size"]
	if _stage_frames == 0:
		root.mode = Window.MODE_WINDOWED
		root.borderless = true
		root.position = Vector2i(40, 40)
		root.size = target
	_stage_frames += 1
	if root.size == target or _stage_frames > RESIZE_FRAME_CAP:
		_stage = Stage.SPAWN
		_stage_frames = 0


func _stage_spawn(shot: Dictionary, device_name: String) -> void:
	var per_device: Dictionary = shot.get("profiles", {})
	var profile := str(per_device.get(device_name, shot.get("profile", "")))
	if not profile.is_empty():
		_apply_profile(profile)
	var scene_path := str(shot.get("scene", ""))
	var packed := load(scene_path) as PackedScene
	if packed == null:
		printerr("[qa] cannot load scene %s (shot '%s')" % [scene_path, shot.get("name", "?")])
		_tool_failures += 1
		_advance()
		return
	_view = packed.instantiate()
	_call_driver(str(shot.get("pre_setup", "")), shot)
	root.add_child(_view)
	_stage = Stage.SETUP


## One frame after add_child: the tree has run _ready, so fixtures meet a view
## whose scenes and racks exist (injecting earlier photographs an empty field).
func _stage_setup(shot: Dictionary) -> void:
	_call_driver(str(shot.get("setup", "")), shot)
	_elapsed = 0.0
	_then_fired = false
	_stage = Stage.RUN


func _stage_run(shot: Dictionary, delta: float) -> void:
	_elapsed += delta
	var run_s := float(shot.get("run_s", 1.2))
	var settle_s := float(shot.get("settle_s", 0.4))
	if not _then_fired and _elapsed >= run_s:
		_then_fired = true
		_call_driver(str(shot.get("then", "")), shot)
	if _elapsed >= run_s + settle_s:
		_stage = Stage.CAPTURE


func _stage_capture(job: Dictionary, shot: Dictionary, device: Dictionary) -> void:
	var name := str(shot.get("name", "shot"))
	var device_name := str(job["device"])
	var texture := root.get_texture()
	var image: Image = texture.get_image() if texture != null else null
	if image == null:
		printerr("[qa] no viewport image — dummy renderer cannot rasterize; run through tools/godot/qa_capture.py")
		quit(2)
		return

	var findings: Array[Dictionary] = []
	var requested: Vector2i = device["size"]
	if Vector2i(image.get_width(), image.get_height()) != requested:
		findings.append({
			"check": "capture_size", "actual": float(image.get_width()),
			"bound": float(requested.x),
			"fix": "OS clamped the window to %dx%d (asked %dx%d) — measurements below are at the clamped size." % [
				image.get_width(), image.get_height(), requested.x, requested.y],
		})

	findings.append_array(StudioQaMeasure.check_frame(image, shot.get("frame", {}) as Dictionary))
	findings.append_array(_check_hud(shot, bool(device["touch"])))

	var png_path := "%s/%s__%s.png" % [_out_dir, name, device_name]
	var err := image.save_png(ProjectSettings.globalize_path(png_path))
	if err != OK:
		printerr("[qa] save failed (%s) -> %s" % [err, png_path])
		_tool_failures += 1

	var result := {
		"shot": name,
		"device": device_name,
		"size": [image.get_width(), image.get_height()],
		"png": png_path,
		"luma": snappedf(StudioQaMeasure.luma_mean(image), 0.01),
		"saturation": snappedf(StudioQaMeasure.saturation_mean(image), 0.001),
		"profile": str((shot.get("profiles", {}) as Dictionary).get(
			device_name, shot.get("profile", ""))),
		"findings": findings,
	}
	_results.append(result)
	var verdict := "ok" if findings.is_empty() else "%d finding(s)" % findings.size()
	print("[qa] %s__%s  luma=%.1f sat=%.3f  %s" % [
		name, device_name, result["luma"], result["saturation"], verdict])
	for finding in findings:
		print("[qa]    %s (%s): %.2f vs %.2f — %s" % [
			finding["check"], str(finding.get("label", "-")),
			float(finding["actual"]), float(finding["bound"]), finding["fix"]])
	_advance()


func _check_hud(shot: Dictionary, touch: bool) -> Array[Dictionary]:
	var spec: Dictionary = (shot.get("hud", {}) as Dictionary).duplicate()
	var visible_rect := root.get_visible_rect()
	if visible_rect.size.x > 0.0:
		spec["px_per_unit"] = float(root.size.x) / visible_rect.size.x
	var nodes: Array[Control] = []
	var controls: Array = []
	for node in get_nodes_in_group(HUD_GROUP):
		if not (node is Control):
			continue
		var control := node as Control
		if _view == null or not (_view.is_ancestor_of(control)):
			continue
		if not control.is_visible_in_tree():
			continue
		nodes.append(control)
		controls.append({
			"name": str(_view.get_path_to(control)),
			"rect": control.get_global_rect(),
			# Tap floors only mean anything where a finger is the pointer.
			"tap": touch and control.is_in_group(TAP_GROUP),
		})
	var findings := StudioQaMeasure.check_controls(controls, visible_rect, spec)
	# Overlap is judged between top-level blocks only: a tagged button INSIDE
	# a tagged panel is containment, not collision.
	var top_level: Array = []
	for i in nodes.size():
		var nested := false
		for j in nodes.size():
			if i != j and nodes[j].is_ancestor_of(nodes[i]):
				nested = true
				break
		if not nested:
			top_level.append(controls[i])
	findings.append_array(StudioQaMeasure.check_overlaps(top_level, spec))
	return findings


func _call_driver(method: String, shot: Dictionary) -> void:
	if method.is_empty():
		return
	if _driver.has_method(method):
		_driver.call(method, _view)
		return
	# A typo'd setup method must fail the run, not silently photograph the
	# wrong state.
	printerr("[qa] driver has no method '%s' (shot '%s')" % [method, shot.get("name", "?")])
	_tool_failures += 1


func _apply_profile(profile_name: String) -> void:
	var studio: Node = root.get_node_or_null(^"/root/Studio")
	var profiles_raw: Variant = studio.get("profiles") if studio != null else null
	if profiles_raw == null or not (profiles_raw is StudioRenderProfiles):
		printerr("[qa] no /root/Studio render profiles; shot runs on the boot profile, NOT '%s'" % profile_name)
		_tool_failures += 1
		return
	var profiles: StudioRenderProfiles = profiles_raw
	if profiles.profiles.is_empty():
		profiles.load_profiles()
	if not profiles.apply(profile_name, root, {}):
		printerr("[qa] could not apply profile '%s'" % profile_name)
		_tool_failures += 1


func _advance() -> void:
	if _view != null:
		# The final view is deliberately NOT freed: tearing down a desktop-tier
		# world (100k+ instances) on the software GL device intermittently
		# access-violates, killing the process between the last capture and the
		# report write. The process is about to exit; the OS reclaims it.
		if _job + 1 < _jobs.size():
			_view.queue_free()
		_view = null
	_job += 1
	_stage = Stage.RESIZE
	_stage_frames = 0


func _finish() -> bool:
	var total_findings := 0
	for result in _results:
		total_findings += (result["findings"] as Array).size()
	var report := {
		"renderer_method": RenderingServer.get_current_rendering_method(),
		"renderer_driver": RenderingServer.get_current_rendering_driver_name(),
		"results": _results,
		"findings": total_findings,
		"tool_failures": _tool_failures,
	}
	var report_path := ProjectSettings.globalize_path(_out_dir + "/report.json")
	var file := FileAccess.open(report_path, FileAccess.WRITE)
	if file != null:
		file.store_string(JSON.stringify(report, "  "))
		file.close()
	if _as_json:
		print(JSON.stringify(report, "  "))
	if _tool_failures > 0:
		print("[qa] TOOL FAILURE: %d job(s) could not run honestly" % _tool_failures)
		quit(2)
		return true
	if total_findings == 0:
		print("[qa] CONFORMANT: %d still(s), report at %s" % [_results.size(), report_path])
		quit(0)
		return true
	print("[qa] %d finding(s) across %d still(s), report at %s" % [
		total_findings, _results.size(), report_path])
	quit(1 if not _warn_only else 0)
	return true
