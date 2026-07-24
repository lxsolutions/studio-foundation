extends Node3D
## Studio Foundation — WebGPU 3D showcase.
##
## A lit, shadow-casting, animated 3D scene rendered entirely through the
## WebGPU backend (Godot Forward Mobile) in the browser. It uses only core
## Godot 3D features on the verified render path (patches 0009-0013): the same
## per-stage sampler visibility that patch 0013 fixed is what lets the lit
## scene shader and its shadow atlas run inside WebGPU's per-stage limits.
##
## Everything is built in code — no external assets — so the demo is a single
## self-contained scene anyone can rebuild and re-verify.

const RING_RADIUS := 3.2

var _spinners: Array[MeshInstance3D] = []
var _camera: Camera3D
var _t := 0.0

func _ready() -> void:
	_build_environment()
	_build_sun()
	_build_ground()
	_build_ring()
	_build_camera()

func _build_environment() -> void:
	var world_env := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.055, 0.07, 0.11)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.34, 0.41, 0.55)
	env.ambient_light_energy = 0.55
	world_env.environment = env
	add_child(world_env)

func _build_sun() -> void:
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-52.0, -38.0, 0.0)
	sun.light_energy = 1.35
	sun.light_color = Color(1.0, 0.96, 0.9)
	sun.shadow_enabled = true
	add_child(sun)

func _build_ground() -> void:
	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(40.0, 40.0)
	ground.mesh = plane
	ground.position = Vector3(0.0, -1.15, 0.0)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.10, 0.12, 0.16)
	mat.roughness = 0.92
	mat.metallic = 0.0
	ground.material_override = mat
	add_child(ground)

func _build_ring() -> void:
	var meshes: Array[Mesh] = [
		BoxMesh.new(), SphereMesh.new(), CylinderMesh.new(),
		TorusMesh.new(), PrismMesh.new(), CapsuleMesh.new(),
	]
	var palette := [
		Color(0.96, 0.55, 0.20), # orange
		Color(0.28, 0.66, 0.96), # blue
		Color(0.44, 0.86, 0.46), # green
		Color(0.93, 0.34, 0.56), # magenta
		Color(0.92, 0.82, 0.30), # gold
		Color(0.63, 0.44, 0.93), # violet
	]
	var count := meshes.size()
	for i in count:
		var mi := MeshInstance3D.new()
		mi.mesh = meshes[i]
		var angle := TAU * float(i) / float(count)
		mi.position = Vector3(cos(angle) * RING_RADIUS, 0.0, sin(angle) * RING_RADIUS)
		var mat := StandardMaterial3D.new()
		mat.albedo_color = palette[i]
		mat.metallic = 0.25
		mat.roughness = 0.32
		mi.material_override = mat
		add_child(mi)
		_spinners.append(mi)

func _build_camera() -> void:
	_camera = Camera3D.new()
	_camera.position = Vector3(0.0, 3.2, 8.0)
	_camera.look_at_from_position(_camera.position, Vector3.ZERO)
	add_child(_camera)

func _process(delta: float) -> void:
	_t += delta
	var cam_angle := _t * 0.32
	var cam_radius := 8.0
	_camera.position = Vector3(
		cos(cam_angle) * cam_radius,
		3.1 + sin(_t * 0.5) * 0.6,
		sin(cam_angle) * cam_radius)
	_camera.look_at(Vector3(0.0, 0.15, 0.0), Vector3.UP)
	for i in _spinners.size():
		var mi := _spinners[i]
		mi.rotation.y += delta * (0.8 + 0.16 * float(i))
		mi.rotation.x += delta * 0.4
		var base := TAU * float(i) / float(_spinners.size())
		mi.position.y = sin(_t * 1.2 + base) * 0.35
