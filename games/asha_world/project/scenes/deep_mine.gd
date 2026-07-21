extends Node3D
## The Deep — first vertical-slice 3D scene (ADR 0007, vertical-slice.md).
## A cavern of ore nodes. Walk to a node and mine it; each haul emits a
## ResourceExtracted WorldEvent that the server world-sim settles (bounded).
## Refinery/factory/battle are staged from the same HUD, closing the loop
## extraction -> economy -> production -> battle -> territory.

var SERVER_URL: String = AshaWorldConfig.ws_url()
const FACTION := "00000000-0000-0000-0000-000000000001"
const SECTOR := "00000000-0000-0000-0000-000000000002"
const DEEP_SECTOR := "00000000-0000-0000-0000-000000000003"
const ORE_PER_MINE := 100
const REFINE_RATIO := 10
const VEHICLE_COST := 10

var _transport: StudioWsTransport
var _seq := 0
var _idem := 0
var _player: CharacterBody3D
var _camera: Camera3D
var _hud_ore: Label
var _hud_alloy: Label
var _hud_status: Label
var _log: RichTextLabel
var _prompt: Label
var _focused_ore: Node3D = null
var _state := {"ore": 0, "alloy": 0, "vehicle": false, "territory": false}


func _ready() -> void:
	_build_world()
	_build_hud()
	_transport = StudioWsTransport.new()
	_transport.envelope_received.connect(_on_envelope)
	_transport.transport_error.connect(func(m): _log_line("[err] " + str(m)))
	_transport.connect_to(SERVER_URL)
	_log_line("connecting to world %s ..." % SERVER_URL)


func _process(delta: float) -> void:
	_transport.poll()
	_move_player(delta)
	_update_focus()


func _next_seq() -> int:
	_seq += 1
	return _seq


func _key() -> String:
	_idem += 1
	var hex := "000000000000" + ("%x" % _idem)
	hex = hex.substr(hex.length() - 12, 12)
	return "00000000-0000-0000-0000-" + hex


func _submit(event: Dictionary) -> void:
	_transport.send_envelope(StudioProtocol.world_event_submit(_next_seq(), event))


func _on_envelope(envelope: Dictionary) -> void:
	match str(envelope.get("type", "")):
		"hello_ack":
			_log_line("world session established")
			_transport.send_envelope(StudioProtocol.hello(_next_seq(), "asha_world-deep", "0.1.0"))
		"world_event_result":
			_log_line(("settled: " if bool(envelope.get("applied", false)) else "rejected: ") + str(envelope.get("summary", "")))


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("pause"):
		get_node("/root/Studio").router.go_to("res://scenes/main_menu.tscn")
	elif event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		if _focused_ore != null:
			_mine(_focused_ore)


# --- world construction ---------------------------------------------------

func _build_world() -> void:
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-60, -25, 0)
	light.shadow_enabled = true
	add_child(light)

	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.04, 0.05, 0.08)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.35, 0.4, 0.5)
	e.ambient_light_energy = 0.5
	env.environment = e
	add_child(env)

	var floor_mesh := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(40, 40)
	floor_mesh.mesh = plane
	var floor_mat := StandardMaterial3D.new()
	floor_mat.albedo_color = Color(0.12, 0.11, 0.14)
	floor_mesh.material_override = floor_mat
	add_child(floor_mesh)
	var floor_body := StaticBody3D.new()
	var floor_col := CollisionShape3D.new()
	var floor_shape := BoxShape3D.new()
	floor_shape.size = Vector3(40, 0.1, 40)
	floor_col.shape = floor_shape
	floor_body.add_child(floor_col)
	add_child(floor_body)

	# Ore nodes scattered through the cavern.
	var ore_positions := [
		Vector3(-6, 0.6, -5), Vector3(4, 0.6, -7), Vector3(7, 0.6, 3),
		Vector3(-4, 0.6, 6), Vector3(0, 0.6, -1), Vector3(-9, 0.6, 1),
	]
	for pos in ore_positions:
		_spawn_ore(pos)

	# Player: a capsule + camera, simple WASD controller.
	_player = CharacterBody3D.new()
	var cap := CapsuleShape3D.new()
	cap.radius = 0.4
	cap.height = 1.6
	var cap_col := CollisionShape3D.new()
	cap_col.shape = cap
	_player.add_child(cap_col)
	var body_mesh := MeshInstance3D.new()
	var cap_mesh := CapsuleMesh.new()
	cap_mesh.radius = 0.4
	cap_mesh.height = 1.6
	body_mesh.mesh = cap_mesh
	var body_mat := StandardMaterial3D.new()
	body_mat.albedo_color = Color(0.3, 0.5, 0.9)
	body_mesh.material_override = body_mat
	_player.add_child(body_mesh)
	_player.position = Vector3(0, 0.9, 8)
	add_child(_player)

	_camera = Camera3D.new()
	_camera.position = Vector3(0, 4.5, 8)
	_camera.look_at_from_position(_camera.position, Vector3(0, 1, 0), Vector3.UP)
	add_child(_camera)


func _spawn_ore(pos: Vector3) -> void:
	var ore := StaticBody3D.new()
	ore.position = pos
	var mesh := MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = 0.7
	mesh.mesh = sphere
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.85, 0.55, 0.15)
	mat.emission_enabled = true
	mat.emission = Color(0.6, 0.35, 0.05)
	mat.emission_energy_multiplier = 0.6
	mesh.material_override = mat
	ore.add_child(mesh)
	var col := CollisionShape3D.new()
	var shape := SphereShape3D.new()
	shape.radius = 0.7
	col.shape = shape
	ore.add_child(col)
	ore.set_meta("ore", true)
	add_child(ore)


func _move_player(delta: float) -> void:
	var dir := Vector3.ZERO
	var move: Vector2 = StudioInputMap.move_vector()
	dir.x = move.x
	dir.z = move.y
	if dir != Vector3.ZERO:
		dir = dir.normalized() * 6.0
	_player.velocity.x = dir.x
	_player.velocity.z = dir.z
	_player.velocity.y = -9.8 * delta * 60.0 if not _player.is_on_floor() else 0.0
	_player.move_and_slide()
	# Camera follows loosely.
	_camera.position = _camera.position.lerp(_player.position + Vector3(0, 4.5, 7), delta * 5.0)
	_camera.look_at(_player.position + Vector3(0, 1, 0), Vector3.UP)


func _update_focus() -> void:
	_focused_ore = null
	var best := 3.0
	for child in get_children():
		if child is StaticBody3D and child.has_meta("ore"):
			var d: float = _player.position.distance_to(child.position)
			if d < best:
				best = d
				_focused_ore = child
	_prompt.visible = _focused_ore != null


func _mine(ore: Node3D) -> void:
	_state["ore"] += ORE_PER_MINE
	_log_line("mined %d ore from The Deep" % ORE_PER_MINE)
	_submit({
		"ResourceExtracted": {
			"faction": FACTION, "sector": SECTOR,
			"resource": "RawOre", "units": ORE_PER_MINE, "idempotency_key": _key(),
		},
	})
	ore.queue_free()
	_focused_ore = null
	_refresh_hud()


# --- staged loop (refine/build/battle/territory) ---------------------------

func _on_refine() -> void:
	if _state["ore"] < REFINE_RATIO:
		_log_line("need at least %d ore to refine" % REFINE_RATIO)
		return
	var refined: int = _state["ore"] / REFINE_RATIO
	_state["alloy"] += refined
	_state["ore"] = 0
	_log_line("refinery produced %d alloy" % refined)
	_submit({
		"ResourceExtracted": {
			"faction": FACTION, "sector": SECTOR,
			"resource": "RefinedAlloy", "units": refined, "idempotency_key": _key(),
		},
	})
	_refresh_hud()


func _on_build() -> void:
	if _state["alloy"] < VEHICLE_COST:
		_log_line("need %d alloy to build a vehicle" % VEHICLE_COST)
		return
	_state["alloy"] -= VEHICLE_COST
	_state["vehicle"] = true
	_log_line("factory built an armored vehicle")
	_submit({
		"FactoryCompleted": {
			"faction": FACTION, "sector": SECTOR,
			"item": "armored_vehicle", "refined_units": VEHICLE_COST, "idempotency_key": _key(),
		},
	})
	_refresh_hud()


func _on_territory() -> void:
	if not _state["vehicle"]:
		_log_line("build a vehicle before contesting the outpost")
		return
	_log_line("deploying the vehicle to the outpost ...")
	# The battle is fought in 3D, not auto-won: drive the vehicle to the outpost.
	get_node("/root/Studio").router.go_to("res://scenes/battle_outpost.tscn")


# --- hud ------------------------------------------------------------------

func _build_hud() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var panel := VBoxContainer.new()
	panel.position = Vector2(12, 12)
	layer.add_child(panel)

	_hud_ore = Label.new()
	_hud_alloy = Label.new()
	_hud_status = Label.new()
	for l in [_hud_ore, _hud_alloy, _hud_status]:
		l.add_theme_font_size_override("font_size", 16)
		panel.add_child(l)

	var btn_row := HBoxContainer.new()
	panel.add_child(btn_row)
	for spec in [["Refine", _on_refine], ["Build Vehicle", _on_build], ["Capture Outpost", _on_territory]]:
		var b := Button.new()
		b.text = spec[0]
		b.pressed.connect(spec[1])
		btn_row.add_child(b)

	_prompt = Label.new()
	_prompt.text = "LMB: mine ore"
	_prompt.add_theme_font_size_override("font_size", 18)
	_prompt.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	_prompt.position = Vector2(-60, -40)
	_prompt.visible = false
	layer.add_child(_prompt)

	_log = RichTextLabel.new()
	_log.size = Vector2(560, 200)
	_log.position = Vector2(12, 480)
	_log.scroll_following = true
	layer.add_child(_log)
	_refresh_hud()


func _refresh_hud() -> void:
	_hud_ore.text = "Ore: %d" % _state["ore"]
	_hud_alloy.text = "Alloy: %d" % _state["alloy"]
	_hud_status.text = "Vehicle: %s   Territory: %s" % [str(_state["vehicle"]), str(_state["territory"])]


func _log_line(text: String) -> void:
	_log.append_text(text + "\n")
