extends Node3D
## Empty gameplay scene: a lit 3D stage that instances the cooked sample asset
## (proof of the Blender -> GLB -> Godot chain). NO game mechanics here.

const SAMPLE_GLB: String = "res://assets/generated/props/crate_a/crate_a.glb"


func _ready() -> void:
	var light: DirectionalLight3D = DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-50, -30, 0)
	light.shadow_enabled = true
	add_child(light)

	var environment: WorldEnvironment = WorldEnvironment.new()
	var env: Environment = Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.11, 0.14, 0.19)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.55, 0.6, 0.7)
	env.ambient_light_energy = 0.6
	environment.environment = env
	add_child(environment)

	var camera: Camera3D = Camera3D.new()
	camera.position = Vector3(2.5, 2.0, 4.0)
	camera.look_at_from_position(camera.position, Vector3(0, 0.5, 0))
	add_child(camera)

	var floor_mesh: MeshInstance3D = MeshInstance3D.new()
	var plane: PlaneMesh = PlaneMesh.new()
	plane.size = Vector2(12, 12)
	floor_mesh.mesh = plane
	var floor_material: StandardMaterial3D = StandardMaterial3D.new()
	floor_material.albedo_color = Color(0.22, 0.25, 0.3)
	floor_mesh.material_override = floor_material
	add_child(floor_mesh)

	_spawn_sample()

	var hint: Label = Label.new()
	hint.text = "empty gameplay scene — Esc: menu"
	hint.position = Vector2(12, 12)
	var layer: CanvasLayer = CanvasLayer.new()
	layer.add_child(hint)
	add_child(layer)


func _spawn_sample() -> void:
	if not ResourceLoader.exists(SAMPLE_GLB):
		push_warning("sample asset missing (run: just asset-cook) — showing placeholder box")
		var box: MeshInstance3D = MeshInstance3D.new()
		box.mesh = BoxMesh.new()
		box.position = Vector3(0, 0.5, 0)
		add_child(box)
		return
	var packed: PackedScene = load(SAMPLE_GLB)
	var instance: Node3D = packed.instantiate()
	instance.position = Vector3(0, 0, 0)
	add_child(instance)


func _process(delta: float) -> void:
	var pan: Vector2 = StudioInputMap.move_vector()
	if pan != Vector2.ZERO:
		rotate_y(-pan.x * delta)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("pause"):
		var studio: Node = get_node("/root/Studio")
		studio.router.go_to("res://scenes/main_menu.tscn")
