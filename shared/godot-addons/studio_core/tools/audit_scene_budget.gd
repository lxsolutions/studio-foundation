extends SceneTree
## Scene budget conformance gate.
##
## `profiles.json` has always declared what a render profile may spend --
## `dynamic_light_budget: 8` for the browser, `particle_budget: 2000`,
## `actor_limit: 120` -- and `render_profiles.gd` hands those numbers to game
## code on request. Nothing ever checked whether a scene actually stays inside
## them, so a level could ask for forty lights against a browser profile that
## allows eight and no gate anywhere would notice. Declared budgets that are
## never measured are documentation, not engineering.
##
## This walks a scene headlessly and measures it against a profile, so a
## performance regression fails a build instead of being discovered on a phone.
## It is deliberately static: it counts what the scene *asks the renderer for*,
## which is knowable without a GPU and is what actually regresses when someone
## drops a light rig into a level.
##
## By default it measures the scene *after letting it run*, because these games
## build their worlds in code: Chariot's colosseum and its 53,800 instanced
## spectators exist only after `_ready()`, so auditing the packed scene file
## reports zero of everything and passes every budget vacuously. `--static`
## keeps the cheap scene-file-only reading when that is genuinely what you want.
##
## Usage:
##   godot --headless --path <project> --script \
##       res://addons/studio_core/tools/audit_scene_budget.gd -- \
##       --scene=res://scenes/arena.tscn --profile=browser_webgpu \
##       [--frames=30] [--static] [--json] [--warn-only]
##
## Exit codes: 0 conformant, 1 over budget, 2 bad usage.

const PROFILES_PATH := "res://addons/studio_core/profiles.json"

## Triangle ceilings per profile. profiles.json has no triangle key -- it
## describes quality knobs, not scene weight -- but an unbounded triangle count
## is the most common way a browser build dies, so the gate carries its own.
##
## CALIBRATION (2026-07-25). The first numbers here were guesses and were wrong:
## they flagged Chariot at 4.3x over while it was in fact holding a locked 60 fps.
## Measured on a Tesla P40 (Pascal, ~GTX 1080 class), Chrome/WebGPU, Forward
## Mobile, 1280x1024, via tools/wgpu perf probe:
##
##   5,190,816 triangles -> 60 fps locked, median 16.67 ms, p95 16.67-33.33 ms,
##   GPU utilisation 27-40% (mean ~37%), 194 MiB VRAM, 60 W of 250 W.
##
## So ~5.2M triangles costs about a third of a P40. Extrapolating to saturation
## gives roughly 14M, and desktop_high is set to a 60%-of-that sustained target.
##
## HONESTY NOTE: only desktop_high is measurement-backed. The browser and mobile
## ceilings are derived from the P40 figure by assuming an integrated GPU is
## roughly a fifth of its raster throughput -- a reasonable engineering guess,
## NOT a measurement. Calibrating those needs a laptop-class device; until then
## treat a browser/mobile violation as a prompt to measure, not as fact.
const TRIANGLE_BUDGETS := {
	"desktop_high": 8000000,
	"browser_webgpu": 2500000,
	"browser_webgl": 800000,
	"mobile_high": 1000000,
	"mobile_low": 400000,
}

var _scene_path: String = ""
var _profile_name: String = ""
var _profile: Dictionary = {}
var _as_json: bool = false
var _warn_only: bool = false
var _instance: Node = null
var _frames_left: int = 0
var _pending_attach: bool = false


func _initialize() -> void:
	var args := _parse_args()
	if args.is_empty():
		_usage()
		quit(2)
		return

	var scene_path: String = args.get("scene", "")
	var profile_name: String = args.get("profile", "browser_webgpu")
	var as_json: bool = args.has("json")
	var warn_only: bool = args.has("warn-only")

	if scene_path.is_empty():
		printerr("audit_scene_budget: --scene=res://... is required")
		_usage()
		quit(2)
		return

	var profiles := _load_profiles()
	if profiles.is_empty():
		printerr("audit_scene_budget: could not read %s" % PROFILES_PATH)
		quit(2)
		return
	if not profiles.has(profile_name):
		printerr("audit_scene_budget: unknown profile '%s' (have: %s)"
			% [profile_name, ", ".join(PackedStringArray(profiles.keys()))])
		quit(2)
		return

	if not ResourceLoader.exists(scene_path):
		printerr("audit_scene_budget: no such scene %s" % scene_path)
		quit(2)
		return
	var packed := ResourceLoader.load(scene_path) as PackedScene
	if packed == null:
		printerr("audit_scene_budget: %s is not a PackedScene" % scene_path)
		quit(2)
		return
	# EDIT_STATE_DISABLED keeps this honest: we measure what ships, not what the
	# editor would additionally instantiate.
	var instance := packed.instantiate(PackedScene.GEN_EDIT_STATE_DISABLED)
	if instance == null:
		printerr("audit_scene_budget: could not instantiate %s" % scene_path)
		quit(2)
		return

	_scene_path = scene_path
	_profile_name = profile_name
	_profile = profiles[profile_name]
	_as_json = as_json
	_warn_only = warn_only
	_instance = instance

	if args.has("static"):
		# Scene-file reading only: nothing has run, so this counts authored nodes.
		_finish(_measure(instance))
		return

	_frames_left = int(args.get("frames", 30))
	# Attaching is deferred to the first frame so the Studio autoload exists and
	# the requested profile can be applied BEFORE the scene builds itself. Without
	# that the audit compares against a profile it never actually applied -- the
	# game boots on its own auto-selected profile, every tier reports identical
	# numbers, and profile-dependent scaling can never be validated.
	_pending_attach = true


func _apply_profile(root: Node) -> void:
	var studio: Node = root.get_node_or_null(^"/root/Studio")
	if studio == null:
		printerr("audit_scene_budget: no /root/Studio autoload; measuring the "
			+ "scene's default profile, NOT '%s'" % _profile_name)
		return
	var raw: Variant = studio.get("profiles")
	if raw == null or not (raw is StudioRenderProfiles):
		printerr("audit_scene_budget: Studio has no render profiles; measuring "
			+ "the scene's default profile, NOT '%s'" % _profile_name)
		return
	var profiles: StudioRenderProfiles = raw
	if profiles.profiles.is_empty():
		profiles.load_profiles()
	# headless=true: budgets only, no viewport writes -- which is all the scene
	# needs to read crowd_density, particle_budget and friends.
	if not profiles.apply(_profile_name, null, {"headless": true}):
		printerr("audit_scene_budget: could not apply profile '%s'" % _profile_name)


func _process(_delta: float) -> bool:
	if _instance == null:
		return true
	if _pending_attach:
		_pending_attach = false
		_apply_profile(root)
		root.add_child(_instance)
		return false
	if _frames_left > 0:
		_frames_left -= 1
		return false
	var usage := _measure(_instance)
	_finish(usage)
	return true


func _finish(usage: Dictionary) -> void:
	var findings := _compare(usage, _profile, _profile_name)
	if _as_json:
		print(JSON.stringify({
			"scene": _scene_path,
			"profile": _profile_name,
			"usage": usage,
			"findings": findings,
			"conformant": findings.is_empty(),
		}, "  "))
	else:
		_report(_scene_path, _profile_name, usage, _profile, findings)
	_instance = null
	quit(0 if (findings.is_empty() or _warn_only) else 1)


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


func _usage() -> void:
	print("usage: --scene=res://path.tscn [--profile=browser_webgpu] [--json] [--warn-only]")


func _load_profiles() -> Dictionary:
	if not FileAccess.file_exists(PROFILES_PATH):
		return {}
	var file := FileAccess.open(PROFILES_PATH, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	return parsed if parsed is Dictionary else {}


## Walk the tree once, counting everything the renderer will be asked for.
func _measure(root: Node) -> Dictionary:
	var usage := {
		"dynamic_lights": 0,
		"directional_lights": 0,
		"shadow_casting_lights": 0,
		"particles": 0,
		"particle_nodes": 0,
		"actors": 0,
		"mesh_instances": 0,
		"triangles": 0,
		"multimesh_nodes": 0,
		"multimesh_instances": 0,
		"unique_meshes": 0,
	}
	var seen_meshes := {}
	var stack: Array[Node] = [root]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		for child in node.get_children():
			stack.push_back(child)

		if node is OmniLight3D or node is SpotLight3D:
			usage["dynamic_lights"] += 1
			if (node as Light3D).shadow_enabled:
				usage["shadow_casting_lights"] += 1
		elif node is DirectionalLight3D:
			usage["directional_lights"] += 1
			if (node as Light3D).shadow_enabled:
				usage["shadow_casting_lights"] += 1
		elif node is GPUParticles3D:
			usage["particle_nodes"] += 1
			usage["particles"] += (node as GPUParticles3D).amount
		elif node is GPUParticles2D:
			usage["particle_nodes"] += 1
			usage["particles"] += (node as GPUParticles2D).amount
		elif node is MultiMeshInstance3D:
			# One draw call regardless of count, so it does not consume the mesh
			# budget -- but the instance count still drives vertex work, so report it.
			usage["multimesh_nodes"] += 1
			var mm := (node as MultiMeshInstance3D).multimesh
			if mm != null:
				usage["multimesh_instances"] += mm.instance_count
				if mm.mesh != null:
					usage["triangles"] += _mesh_triangles(mm.mesh, seen_meshes) * mm.instance_count
		elif node is MeshInstance3D:
			var mesh := (node as MeshInstance3D).mesh
			if mesh != null:
				usage["mesh_instances"] += 1
				usage["triangles"] += _mesh_triangles(mesh, seen_meshes)

		if node is CharacterBody3D or node is RigidBody3D or node.is_in_group("actors"):
			usage["actors"] += 1

	usage["unique_meshes"] = seen_meshes.size()
	return usage


## Triangle count for a mesh, cached per resource so a mesh reused across fifty
## instances is not re-walked fifty times.
func _mesh_triangles(mesh: Mesh, cache: Dictionary) -> int:
	var key := mesh.get_rid().get_id()
	if cache.has(key):
		return cache[key]
	var tris := 0
	for surface in mesh.get_surface_count():
		var arrays: Array = mesh.surface_get_arrays(surface)
		if arrays.is_empty():
			continue
		var indices: Variant = arrays[Mesh.ARRAY_INDEX] if arrays.size() > Mesh.ARRAY_INDEX else null
		if indices != null and indices is PackedInt32Array:
			tris += (indices as PackedInt32Array).size() / 3
			continue
		var verts: Variant = arrays[Mesh.ARRAY_VERTEX] if arrays.size() > Mesh.ARRAY_VERTEX else null
		if verts != null and verts is PackedVector3Array:
			tris += (verts as PackedVector3Array).size() / 3
	cache[key] = tris
	return tris


func _compare(usage: Dictionary, profile: Dictionary, profile_name: String) -> Array:
	var findings := []

	var light_budget := int(profile.get("dynamic_light_budget", 0))
	if light_budget > 0 and int(usage["dynamic_lights"]) > light_budget:
		findings.append(_finding(
			"dynamic_lights", usage["dynamic_lights"], light_budget,
			"Cull or bake lights, or raise dynamic_light_budget for this profile."))

	var particle_budget := int(profile.get("particle_budget", 0))
	if particle_budget > 0 and int(usage["particles"]) > particle_budget:
		findings.append(_finding(
			"particles", usage["particles"], particle_budget,
			"Lower GPUParticles amount, or gate emitters on RenderProfiles.budget()."))

	var actor_limit := int(profile.get("actor_limit", 0))
	if actor_limit > 0 and int(usage["actors"]) > actor_limit:
		findings.append(_finding(
			"actors", usage["actors"], actor_limit,
			"Spawn actors through a pool that honours actor_limit."))

	var tri_budget := int(TRIANGLE_BUDGETS.get(profile_name, 0))
	if tri_budget > 0 and int(usage["triangles"]) > tri_budget:
		findings.append(_finding(
			"triangles", usage["triangles"], tri_budget,
			"Add LODs (gameready.lod), or reduce instance counts."))

	return findings


func _finding(metric: String, actual: int, budget: int, fix: String) -> Dictionary:
	return {
		"metric": metric,
		"actual": actual,
		"budget": budget,
		"over_by": actual - budget,
		"fix": fix,
	}


func _report(scene: String, profile_name: String, usage: Dictionary,
		profile: Dictionary, findings: Array) -> void:
	print("scene budget audit")
	print("  scene   : %s" % scene)
	print("  profile : %s" % profile_name)
	print("")
	_line("dynamic lights", usage["dynamic_lights"], int(profile.get("dynamic_light_budget", 0)))
	_line("particles", usage["particles"], int(profile.get("particle_budget", 0)))
	_line("actors", usage["actors"], int(profile.get("actor_limit", 0)))
	_line("triangles", usage["triangles"], int(TRIANGLE_BUDGETS.get(profile_name, 0)))
	print("  %-16s %s (%d nodes, %d instances)" % [
		"multimesh", "-", usage["multimesh_nodes"], usage["multimesh_instances"]])
	print("  %-16s %d across %d unique meshes" % [
		"mesh instances", usage["mesh_instances"], usage["unique_meshes"]])
	print("  %-16s %d" % ["directional", usage["directional_lights"]])
	print("  %-16s %d" % ["shadow casters", usage["shadow_casting_lights"]])
	print("")
	if findings.is_empty():
		print("CONFORMANT: within every budget for '%s'." % profile_name)
		return
	print("OVER BUDGET: %d violation(s) for '%s'" % [findings.size(), profile_name])
	for f in findings:
		print("  %s: %d vs budget %d (over by %d)" % [f["metric"], f["actual"], f["budget"], f["over_by"]])
		print("    -> %s" % f["fix"])


func _line(label: String, actual: Variant, budget: int) -> void:
	if budget <= 0:
		print("  %-16s %d (no budget)" % [label, int(actual)])
		return
	var mark := "ok" if int(actual) <= budget else "OVER"
	print("  %-16s %d / %d  %s" % [label, int(actual), budget, mark])
