extends Node3D
## Deterministic asset/turntable viewer. Used by `just asset-preview`, visual
## regression, and manual inspection. Reads the asset path from
## --asset=res://... (cmdline) or falls back to the sample crate. Fixed camera,
## fixed lights, fixed rotation rate: identical frames across runs (GPU noise
## aside), which is what visual regression needs.

const DEFAULT_ASSET: String = "res://assets/generated/props/crate_a/crate_a.glb"

var _pivot: Node3D


func _ready() -> void:
	var light: DirectionalLight3D = DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-45, -35, 0)
	light.shadow_enabled = true
	add_child(light)

	var fill: OmniLight3D = OmniLight3D.new()
	fill.position = Vector3(-2, 1.5, 2)
	fill.light_energy = 0.4
	add_child(fill)

	var environment: WorldEnvironment = WorldEnvironment.new()
	var env: Environment = Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.13, 0.13, 0.16)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.6, 0.6, 0.65)
	environment.environment = env
	add_child(environment)

	var camera: Camera3D = Camera3D.new()
	camera.position = Vector3(0, 1.1, 3.0)
	camera.look_at_from_position(camera.position, Vector3(0, 0.45, 0))
	add_child(camera)

	_pivot = Node3D.new()
	add_child(_pivot)

	var asset_path: String = DEFAULT_ASSET
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--asset="):
			asset_path = arg.trim_prefix("--asset=")
	if ResourceLoader.exists(asset_path):
		var packed: PackedScene = load(asset_path)
		_pivot.add_child(packed.instantiate())
	else:
		push_warning("asset_view: %s not found, showing box" % asset_path)
		var box: MeshInstance3D = MeshInstance3D.new()
		box.mesh = BoxMesh.new()
		box.position = Vector3(0, 0.5, 0)
		_pivot.add_child(box)


func _process(delta: float) -> void:
	_pivot.rotate_y(delta * 0.8)
