extends Node3D
## Battle for the outpost — the vertical slice's payoff (vertical-slice.md).
## The vehicle you built in The Deep is driven onto a small battlefield. Reach
## the outpost with it to win; winning flips the sector (TerritoryChanged),
## unlocking the deeper mine. Server world-sim is authoritative.

var SERVER_URL: String = ""
const FACTION := "00000000-0000-0000-0000-000000000001"
const DEEP_SECTOR := "00000000-0000-0000-0000-000000000003"
const OUTPOST_POS := Vector3(0, 0, -14)
const CAPTURE_RADIUS := 3.0

var _transport: StudioWsTransport
var _seq := 0
var _idem := 0
var _vehicle: CharacterBody3D
var _camera: Camera3D
var _outpost: Node3D
var _hud: Label
var _log: RichTextLabel
var _won := false


func _ready() -> void:
	_build_world()
	_build_hud()
	SERVER_URL = AshaWorldConfig.ws_url()
	_transport = StudioWsTransport.new()
	_transport.envelope_received.connect(_on_envelope)
	_transport.transport_error.connect(func(m): _log_line("[err] " + str(m)))
	_transport.connect_to(SERVER_URL)
	_log_line("connecting to world %s ..." % SERVER_URL)


func _process(delta: float) -> void:
	_transport.poll()
	_drive(delta)
	_check_capture()


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
			_transport.send_envelope(StudioProtocol.hello(_next_seq(), "asha_world-battle", "0.1.0"))
		"world_event_result":
			_log_line(("settled: " if bool(envelope.get("applied", false)) else "rejected: ") + str(envelope.get("summary", "")))


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("pause"):
		get_node("/root/Studio").router.go_to("res://scenes/main_menu.tscn")


# --- world ----------------------------------------------------------------

func _build_world() -> void:
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-55, -20, 0)
	light.shadow_enabled = true
	add_child(light)
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.08, 0.09, 0.12)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.5, 0.55, 0.65)
	e.ambient_light_energy = 0.6
	env.environment = e
	add_child(env)

	var floor_mesh := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(50, 50)
	floor_mesh.mesh = plane
	var floor_mat := StandardMaterial3D.new()
	floor_mat.albedo_color = Color(0.16, 0.18, 0.2)
	floor_mesh.material_override = floor_mat
	add_child(floor_mesh)
	var floor_body := StaticBody3D.new()
	var fc := CollisionShape3D.new()
	var fs := BoxShape3D.new()
	fs.size = Vector3(50, 0.1, 50)
	fc.shape = fs
	floor_body.add_child(fc)
	add_child(floor_body)

	# The outpost: a contested structure to reach.
	_outpost = StaticBody3D.new()
	_outpost.position = OUTPOST_POS
	var tower := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = Vector3(2.4, 4.0, 2.4)
	tower.mesh = box
	var tower_mat := StandardMaterial3D.new()
	tower_mat.albedo_color = Color(0.7, 0.2, 0.2)
	tower_mat.emission_enabled = true
	tower_mat.emission = Color(0.4, 0.05, 0.05)
	tower_mat.emission_energy_multiplier = 0.5
	tower.material_override = tower_mat
	tower.position = Vector3(0, 2.0, 0)
	_outpost.add_child(tower)
	add_child(_outpost)

	# Player vehicle (the one built from mined alloy): boxy APC.
	_vehicle = CharacterBody3D.new()
	var vcol := CollisionShape3D.new()
	var vshape := BoxShape3D.new()
	vshape.size = Vector3(1.6, 1.2, 2.6)
	vcol.shape = vshape
	vcol.position = Vector3(0, 0.8, 0)
	_vehicle.add_child(vcol)
	var vmesh := MeshInstance3D.new()
	var vbox := BoxMesh.new()
	vbox.size = Vector3(1.6, 1.2, 2.6)
	vmesh.mesh = vbox
	var vmat := StandardMaterial3D.new()
	vmat.albedo_color = Color(0.25, 0.45, 0.3)
	vmesh.material_override = vmat
	vmesh.position = Vector3(0, 0.8, 0)
	_vehicle.add_child(vmesh)
	_vehicle.position = Vector3(0, 0.6, 12)
	add_child(_vehicle)

	_camera = Camera3D.new()
	_camera.position = Vector3(0, 6, 18)
	_camera.look_at_from_position(_camera.position, Vector3(0, 1, 0), Vector3.UP)
	add_child(_camera)


func _drive(delta: float) -> void:
	if _won:
		return
	var move: Vector2 = StudioInputMap.move_vector()
	var dir := Vector3(move.x, 0, move.y)
	if dir != Vector3.ZERO:
		dir = dir.normalized() * 9.0
	_vehicle.velocity.x = dir.x
	_vehicle.velocity.z = dir.z
	_vehicle.velocity.y = -9.8 * delta * 60.0 if not _vehicle.is_on_floor() else 0.0
	_vehicle.move_and_slide()
	_camera.position = _camera.position.lerp(_vehicle.position + Vector3(0, 6, 9), delta * 5.0)
	_camera.look_at(_vehicle.position + Vector3(0, 1, 0), Vector3.UP)


func _check_capture() -> void:
	if _won:
		return
	if _vehicle.position.distance_to(_outpost.position) <= CAPTURE_RADIUS:
		_win()


func _win() -> void:
	_won = true
	_log_line("outpost reached — battle won! sector flips; deeper mine unlocked.")
	_hud.text = "VICTORY — outpost captured"
	_submit({
		"TerritoryChanged": {
			"sector": DEEP_SECTOR, "new_controller": FACTION, "idempotency_key": _key(),
		},
	})
	# Visual consequence: outpost turns to our color.
	for child in _outpost.get_children():
		if child is MeshInstance3D and child.material_override is StandardMaterial3D:
			var m: StandardMaterial3D = child.material_override
			m.albedo_color = Color(0.2, 0.7, 0.3)
			m.emission = Color(0.05, 0.4, 0.1)


# --- hud ------------------------------------------------------------------

func _build_hud() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	_hud = Label.new()
	_hud.text = "Drive (WASD) to the outpost"
	_hud.add_theme_font_size_override("font_size", 18)
	_hud.position = Vector2(12, 12)
	layer.add_child(_hud)
	_log = RichTextLabel.new()
	_log.size = Vector2(560, 200)
	_log.position = Vector2(12, 480)
	_log.scroll_following = true
	layer.add_child(_log)

	# Touch: virtual joystick drives the same move_* actions (self-hides on desktop).
	var stick := StudioTouchStick.new()
	stick.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	stick.position = Vector2(24, -216)
	layer.add_child(stick)


func _log_line(text: String) -> void:
	_log.append_text(text + "\n")
