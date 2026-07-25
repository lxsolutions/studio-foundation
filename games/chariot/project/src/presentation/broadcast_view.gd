class_name BroadcastView
extends Node3D

## The whole broadcast, built in code: environment, the colosseum, carceres
## stalls, a pool of rigged horses each drawing a racing biga with a standing
## charioteer, a follow camera, and the caption HUD. Renders exactly what
## RaceState holds; the only writes travel the other way as nothing at all,
## because spectators have no inputs.

# Imported GLBs load at runtime: preload would fail to parse on the very first
# --import pass, before the importer has seen the models.
const TRACK_MODEL := "res://assets/models/colosseum_track.glb"
const GATE_MODEL := "res://assets/models/carceres_gate.glb"
const HORSE_MODEL := "res://assets/models/racing_horse.glb"
const CHARIOT_MODEL := "res://assets/models/racing_chariot.glb"

const TICK_INTERVAL_S := 0.2
const TYPICAL_SPEED_MPS := 16.5
const CAMERA_BACK_M := 14.0
const CAMERA_SIDE_M := 9.0
const CAMERA_UP_M := 6.5
# The between-races shot is an establishing view: from beyond the attic rim
# (75.2m) at a shallower height, the whole bowl, banners, and sky read as a
# colosseum instead of the stripe soup the old inside-the-rim orbit gave.
const IDLE_ORBIT_RADIUS_M := 115.0
const IDLE_ORBIT_UP_M := 46.0

const EXHIBITION_FIELD := 6
const EXHIBITION_NAMES: Array[String] = ["Xanthos", "Balios", "Aithon", "Phlegon", "Podargos", "Kyllaros"]
const EXHIBITION_SILKS: Array[String] = ["#285a9e", "#2f7e43", "#c92b28", "#e8e2d3", "#e8ba32", "#843c8b"]
const EXHIBITION_BASE_MPS := 14.8
const EXHIBITION_CHASE_S := 22.0
const EXHIBITION_ORBIT_S := 10.0

# The chariot hangs off the horse node: pole to the rump, car behind, wheels
# turning from authoritative speed. The charioteer leans into the turns.
const CHARIOT_HITCH_M := 2.35
const WHEEL_RADIUS_M := 0.55
const DRIVER_LEAN_MAX_DEG := 13.0

const COAT_TINTS: Array[Color] = [
	Color(0.396, 0.263, 0.157), Color(0.243, 0.169, 0.118), Color(0.545, 0.402, 0.235),
	Color(0.639, 0.612, 0.576), Color(0.176, 0.153, 0.141), Color(0.545, 0.271, 0.153),
]
# Fallback liveries when the server sends no color: the four circus factions
# first — Blue, Green, Red, White — then the wider palette.
const LIVERY_FALLBACKS: Array[Color] = [
	Color(0.157, 0.353, 0.620), Color(0.184, 0.494, 0.263), Color(0.788, 0.169, 0.157),
	Color(0.910, 0.886, 0.827), Color(0.910, 0.729, 0.196), Color(0.518, 0.235, 0.545),
	Color(0.906, 0.451, 0.137), Color(0.129, 0.129, 0.141), Color(0.208, 0.639, 0.612),
	Color(0.686, 0.302, 0.482),
]

var state := RaceState.new()
var client: SpectatorClient
## Tests inject a capturing Callable; live builds fall through to the tree.
var scene_switcher: Callable = Callable()
## Tests pin this false where a deterministic empty arena matters.
var exhibition_enabled := true
var _ex_horses: Array[Dictionary] = []
var _ex_t := 0.0
## The rider view sets this to its own horse id: no banner in your own face.
var plate_hidden_id := ""
var _track_scene: PackedScene
var _gate_scene: PackedScene
var _horse_scene: PackedScene
var _chariot_scene: PackedScene

var _camera: Camera3D
var _crowd: CrowdDirector
var _tabula: TabulaBoard
var _leader_called := ""
var _stretch_called := false
var _banner: Label
var _phase_label: Label
var _rank_labels: Array[Label] = []
var _connection_label: Label
var _horses: Dictionary = {}
var _gates: Array[Node3D] = []
var _seconds_since_tick: float = 0.0
var _idle_angle: float = 0.0
var _countdown_ms: float = -1.0
var _results_panel: PanelContainer
var _results_box: VBoxContainer
var _parade_t: float = 0.0
var audio: RaceAudio

const PARADE_WALK_MPS := 1.6
const PARADE_SPAN_M := 30.0
const PARADE_STAGGER_M := 3.1


func _ready() -> void:
	_track_scene = load(TRACK_MODEL)
	_gate_scene = load(GATE_MODEL)
	_horse_scene = load(HORSE_MODEL)
	_chariot_scene = load(CHARIOT_MODEL)
	_build_world()
	_build_hud()
	client = _create_client()
	client.name = "SpectatorClient"
	client.spectate_event.connect(_on_spectate_event)
	client.state_changed.connect(_on_connection_state)
	add_child(client)
	audio = RaceAudio.new()
	audio.name = "RaceAudio"
	add_child(audio)
	_apply_phase_visuals()


## Subclasses swap the transport (the rider uses the authed main namespace)
## while the whole rendering path stays shared.
func _create_client() -> SpectatorClient:
	return SpectatorClient.new()


func _switch_scene(path: String) -> void:
	if scene_switcher.is_valid():
		scene_switcher.call(path)
		return
	get_tree().change_scene_to_file.call_deferred(path)


func _build_world() -> void:
	# A Mediterranean afternoon: warm sky, golden haze at the horizon, and
	# sun the color of travertine.
	# Tonemapping, ambient occlusion, indirect bounce, bloom and atmosphere —
	# see cinematic_env.gd. The scene previously shipped a sky, a flat ambient
	# term and one hard-shadowed sun with a LINEAR tonemap, which is why good
	# geometry and correct materials still read as chalk.
	var profile: String = Studio.profiles.current_name
	var environment := WorldEnvironment.new()
	environment.name = "Cinematic"
	environment.environment = CinematicEnv.build(profile)
	add_child(environment)
	add_child(CinematicEnv.build_sun(profile))

	var track: Node3D = _track_scene.instantiate()
	track.name = "Track"
	add_child(track)
	_crowd = CrowdDirector.new()
	_crowd.name = "Crowd"
	add_child(_crowd)
	_tabula = TabulaBoard.new()
	_tabula.name = "Tabula"
	# The board stands on the infield by the finish and faces the stands:
	# looking_at points -Z at the infield, so the lettered +Z face looks out.
	_tabula.transform = Transform3D.IDENTITY.looking_at(-TabulaBoard.face_direction(), Vector3.UP).translated(TabulaBoard.stand_position())
	add_child(_tabula)
	_tabula.set_board(Announcer.for_transition(RaceState.PHASE_IDLE, "", ""), _tabula_detail())
	_build_infield_show()

	_camera = Camera3D.new()
	_camera.far = 4000.0
	add_child(_camera)
	_place_idle_camera(0.0)


func _build_hud() -> void:
	var hud := CanvasLayer.new()
	hud.name = "Hud"
	add_child(hud)

	var top := PanelContainer.new()
	top.name = "TopPanel"
	top.set_anchors_preset(Control.PRESET_CENTER_TOP)
	top.position.y = 12.0
	top.self_modulate = Color(0.071, 0.063, 0.043, 0.82)
	hud.add_child(top)
	var top_box := VBoxContainer.new()
	top_box.name = "TopBox"
	top_box.alignment = BoxContainer.ALIGNMENT_CENTER
	top.add_child(top_box)
	_banner = Label.new()
	_banner.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_banner.add_theme_font_size_override("font_size", 30)
	_banner.add_theme_color_override("font_color", Color(0.957, 0.808, 0.463))
	top_box.add_child(_banner)
	_phase_label = Label.new()
	_phase_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_phase_label.add_theme_font_size_override("font_size", 17)
	_phase_label.add_theme_color_override("font_color", Color(0.847, 0.780, 0.635))
	top_box.add_child(_phase_label)

	var strip := PanelContainer.new()
	strip.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	strip.position += Vector2(12.0, -12.0)
	strip.self_modulate = Color(0.071, 0.063, 0.043, 0.82)
	hud.add_child(strip)
	var strip_box := VBoxContainer.new()
	strip.add_child(strip_box)
	for i in range(5):
		var row := Label.new()
		row.add_theme_font_size_override("font_size", 18)
		row.add_theme_color_override("font_color", Color(0.949, 0.925, 0.847))
		strip_box.add_child(row)
		_rank_labels.append(row)

	_connection_label = Label.new()
	_connection_label.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
	_connection_label.position += Vector2(-160.0, -24.0)
	_connection_label.add_theme_font_size_override("font_size", 13)
	_connection_label.add_theme_color_override("font_color", Color(0.847, 0.780, 0.635, 0.8))
	hud.add_child(_connection_label)

	_results_panel = PanelContainer.new()
	_results_panel.set_anchors_preset(Control.PRESET_CENTER)
	_results_panel.self_modulate = Color(0.071, 0.063, 0.043, 0.92)
	_results_panel.visible = false
	hud.add_child(_results_panel)
	_results_box = VBoxContainer.new()
	_results_box.custom_minimum_size = Vector2(460.0, 0.0)
	_results_box.add_theme_constant_override("separation", 6)
	_results_panel.add_child(_results_box)


## The laurel board: placings, the race clock, and what each drive earned.
func _rebuild_results_board() -> void:
	for child in _results_box.get_children():
		child.queue_free()
	var title := Label.new()
	title.text = "THE LAUREL BOARD"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 22)
	title.add_theme_color_override("font_color", Color(0.957, 0.808, 0.463))
	_results_box.add_child(title)
	for result in state.results:
		if typeof(result) != TYPE_DICTIONARY:
			continue
		var row := Label.new()
		var pieces: Array[String] = ["%d" % int(result.get("pos", 0)), str(result.get("horseName", "?"))]
		var stable := str(result.get("stableName", ""))
		if not stable.is_empty():
			pieces.append("(%s)" % stable)
		if int(result.get("timeMs", 0)) > 0:
			pieces.append(RaceState.format_time_ms(int(result.get("timeMs", 0))))
		if int(result.get("earned", 0)) > 0:
			pieces.append("+%dc" % int(result.get("earned", 0)))
		row.text = "  ".join(pieces)
		row.add_theme_font_size_override("font_size", 17)
		row.add_theme_color_override("font_color", Color(0.949, 0.925, 0.847) if int(result.get("pos", 0)) > 1 else Color(0.98, 0.88, 0.55))
		_results_box.add_child(row)


func _on_connection_state(connection: String) -> void:
	_connection_label.text = connection


func _on_spectate_event(event_name: String, data: Variant) -> void:
	var was_phase := state.phase
	if not state.apply(event_name, data):
		return
	if event_name == "race:tick":
		_seconds_since_tick = 0.0
	if event_name != "race:tick" and (state.phase != was_phase or event_name == "spectate:hello"):
		_rebuild_field()
	if state.phase != was_phase:
		var cues := AudioCues.for_transition(state.phase, was_phase)
		audio.apply(cues)
		for cue in cues:
			if str((cue as Dictionary).get("play", "")) == "crowd_swell":
				_crowd.roar()
		_leader_called = ""
		_stretch_called = false
		var headline := Announcer.for_transition(state.phase, was_phase, state.race_name())
		if state.phase == RaceState.PHASE_FINISHED and not state.results.is_empty():
			headline = Announcer.victory_line(state.results)
		_tabula.set_board(headline, _tabula_detail())
	elif event_name == "race:tick":
		_call_the_race()
		_tabula.set_board("", _tabula_detail())
	_apply_phase_visuals()


## The tabula's story of the moment: the first team to show the way, every
## change of lead, and the one final-stretch call per race.
func _call_the_race() -> void:
	if state.phase != RaceState.PHASE_RUNNING:
		return
	var leader_name := str(state.entry_for(state.leader_id()).get("horseName", ""))
	var call := Announcer.leader_line(leader_name, _leader_called)
	if not call.is_empty():
		_leader_called = leader_name
		_tabula.set_board(call, _tabula_detail())
	if not _stretch_called:
		var remaining := _leader_remaining_m()
		if remaining >= 0.0 and remaining < 200.0:
			_stretch_called = true
			_tabula.set_board(Announcer.stretch_line(leader_name), _tabula_detail())


func _leader_remaining_m() -> float:
	for horse in state.tick_horses:
		if typeof(horse) == TYPE_DICTIONARY and int(horse.get("rank", 0)) == 1:
			return state.race_distance() - float(horse.get("pos", 0.0))
	return -1.0


func _tabula_detail() -> String:
	match state.phase:
		RaceState.PHASE_PARADING, RaceState.PHASE_GATE:
			var names: Array[String] = []
			for horse_id: String in state.entries_by_horse:
				if names.size() >= 6:
					break
				var entry: Dictionary = state.entries_by_horse[horse_id]
				names.append("%s %s" % [str(entry.get("number", "")), str(entry.get("horseName", ""))])
			return "  ·  ".join(names)
		RaceState.PHASE_RUNNING:
			return "
".join(state.ranked_names(5))
		RaceState.PHASE_FINISHED:
			var lines: Array[String] = []
			for result in state.results:
				if lines.size() >= 3:
					break
				if typeof(result) != TYPE_DICTIONARY:
					continue
				var piece := "%d  %s" % [int(result.get("pos", 0)), str(result.get("horseName", "?"))]
				if int(result.get("timeMs", 0)) > 0:
					piece += "   " + RaceState.format_time_ms(int(result.get("timeMs", 0)))
				lines.append(piece)
			return "
".join(lines)
		_:
			return "Exhibition laps between race days"



func _rebuild_field() -> void:
	for horse in _horses.values():
		(horse["node"] as Node3D).queue_free()
	_horses.clear()
	for gate in _gates:
		gate.queue_free()
	_gates.clear()
	if state.race.is_empty():
		return
	var distance := state.race_distance()
	var start_s := TrackGeometry.start_offset(distance)
	var index := 0
	for horse_id: String in state.entries_by_horse:
		var entry: Dictionary = state.entries_by_horse[horse_id]
		var gate_lane := float(entry.get("gate", index + 1))
		var horse_node: Node3D = _horse_scene.instantiate()
		horse_node.name = "Horse_%s" % horse_id
		add_child(horse_node)
		var chariot_node: Node3D = _chariot_scene.instantiate()
		chariot_node.name = "Chariot"
		horse_node.add_child(chariot_node)
		chariot_node.position = Vector3(0.0, 0.0, CHARIOT_HITCH_M)
		_tint_entry(horse_node, chariot_node, entry, index)
		var plate := _label_horse(horse_node, entry)
		var start_transform := TrackGeometry.horse_transform(0.0, gate_lane, distance)
		horse_node.transform = start_transform
		_horses[horse_id] = {
			"node": horse_node,
			"pos": 0.0,
			"lane": gate_lane,
			"speed": 0.0,
			"finished": false,
			"anim": _find_animation(horse_node),
			"plate": plate,
			"wheel_l": chariot_node.find_child("WheelL", true, false) as Node3D,
			"wheel_r": chariot_node.find_child("WheelR", true, false) as Node3D,
			"driver": chariot_node.find_child("Charioteer", true, false) as Node3D,
			"wheel_spin": 0.0,
			"lean": 0.0,
		}
		var gate_node: Node3D = _gate_scene.instantiate()
		add_child(gate_node)
		gate_node.transform = Transform3D(start_transform.basis, TrackGeometry.lane_point(start_s - 2.6, gate_lane))
		_gates.append(gate_node)
		index += 1


func _tint_entry(horse_node: Node3D, chariot_node: Node3D, entry: Dictionary, index: int) -> void:
	var coat := COAT_TINTS[int(entry.get("tint", index)) % COAT_TINTS.size()]
	var livery_value := str(entry.get("silk", ""))
	var livery := Color.from_string(livery_value, LIVERY_FALLBACKS[index % LIVERY_FALLBACKS.size()])
	var horse_mesh := horse_node.find_child("Horse", true, false) as MeshInstance3D
	if horse_mesh != null:
		_tint_mesh(horse_mesh, {
			"Coat": coat,
			"Sock": coat.darkened(0.25),
			"Cloth": livery,
			"Plume": livery,
		})
	# The livery rides the chariot: tunic, helmet crest, and the car's front
	# panel all take the stable color.
	for mesh_name in ["Car", "Charioteer"]:
		var mesh := chariot_node.find_child(mesh_name, true, false) as MeshInstance3D
		if mesh != null:
			_tint_mesh(mesh, {
				"CarFront": livery,
				"Tunic": livery,
				"Crest": livery,
			})


func _tint_mesh(mesh: MeshInstance3D, tints: Dictionary) -> void:
	for surface in range(mesh.get_surface_override_material_count()):
		var base := mesh.mesh.surface_get_material(surface) as BaseMaterial3D
		if base == null:
			continue
		if not tints.has(base.resource_name):
			continue
		var override := base.duplicate() as BaseMaterial3D
		override.albedo_color = tints[base.resource_name]
		mesh.set_surface_override_material(surface, override)


func _label_horse(horse_node: Node3D, entry: Dictionary) -> Label3D:
	var label := Label3D.new()
	label.text = "%s  %s" % [str(entry.get("number", "")), str(entry.get("horseName", ""))]
	label.font_size = 64
	label.pixel_size = 0.012
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	label.no_depth_test = true
	label.modulate = Color(0.976, 0.949, 0.878)
	label.outline_size = 18
	label.outline_modulate = Color(0.071, 0.063, 0.043, 0.9)
	label.position = Vector3(0.0, 2.9, 0.0)
	horse_node.add_child(label)
	return label


func _find_animation(horse_node: Node3D) -> AnimationPlayer:
	return horse_node.find_child("AnimationPlayer", true, false) as AnimationPlayer


func _process(delta: float) -> void:
	_seconds_since_tick += delta
	_update_horses(delta)
	_update_exhibition(delta)
	_update_infield_show(delta)
	_update_camera(delta)
	_update_plates()
	_update_countdown(delta)


# Name plates read from the stands, not pressed against your face: hidden
# inside PLATE_NEAR_M (a neighbor two lanes over needs no banner), faded in
# and out across the band, gone past PLATE_FAR_M. The rider's own horse never
# shows one to its own driver (plate_hidden_id).
const PLATE_NEAR_M := 14.0
const PLATE_FAR_M := 150.0

func _update_plates() -> void:
	for horse_id: String in _horses:
		_update_plate(_horses[horse_id], str(horse_id) == plate_hidden_id)
	for horse in _ex_horses:
		_update_plate(horse, false)


func _update_plate(horse: Dictionary, force_hidden: bool) -> void:
	var plate: Label3D = horse.get("plate")
	if plate == null:
		return
	if force_hidden:
		plate.visible = false
		return
	var d := _camera.global_position.distance_to((horse["node"] as Node3D).global_position)
	if d < PLATE_NEAR_M or d > PLATE_FAR_M:
		plate.visible = false
		return
	plate.visible = true
	var fade_in := clampf((d - PLATE_NEAR_M) / 18.0, 0.0, 1.0)
	var fade_out := clampf((PLATE_FAR_M - d) / 30.0, 0.0, 1.0)
	plate.modulate.a = fade_in * fade_out


# ── The exhibition ───────────────────────────────────────────────────────────
# Between real cards the colosseum never sleeps: six faction bigas run
# scripted laps, Derby-cabinet style. Pure presentation, local only; the
# moment the wire speaks (parade, gate, race, results) they yield the sand.

func _update_exhibition(delta: float) -> void:
	var resting: bool = state.phase in [RaceState.PHASE_IDLE, RaceState.PHASE_FINISHED] \
		and state.race.is_empty()
	if not exhibition_enabled or not resting:
		if not _ex_horses.is_empty():
			_end_exhibition()
		return
	if _ex_horses.is_empty():
		_begin_exhibition()
	_ex_t += delta
	var index := 0
	for horse in _ex_horses:
		var speed := EXHIBITION_BASE_MPS + float(index) * 0.35 \
			+ sin(_ex_t * 0.31 + float(index) * 2.1) * 1.1
		horse["speed"] = speed
		horse["pos"] = float(horse["pos"]) + speed * delta
		var node: Node3D = horse["node"]
		node.transform = TrackGeometry.horse_transform(float(horse["pos"]), float(horse["lane"]), 1800.0)
		var s := TrackGeometry.start_offset(1800.0) + float(horse["pos"])
		_update_chariot(horse, speed, s, true, delta)
		var anim: AnimationPlayer = horse["anim"]
		if anim != null:
			if not anim.is_playing():
				anim.play("Gallop")
			anim.speed_scale = clampf(speed / TYPICAL_SPEED_MPS, 0.5, 1.8)
		index += 1


func _begin_exhibition() -> void:
	for index in range(EXHIBITION_FIELD):
		var entry := {
			"name": EXHIBITION_NAMES[index],
			"silk": EXHIBITION_SILKS[index],
			"tint": index,
		}
		var horse_node: Node3D = _horse_scene.instantiate()
		horse_node.name = "Exhibition_%d" % index
		add_child(horse_node)
		var chariot_node: Node3D = _chariot_scene.instantiate()
		chariot_node.name = "Chariot"
		horse_node.add_child(chariot_node)
		chariot_node.position = Vector3(0.0, 0.0, CHARIOT_HITCH_M)
		_tint_entry(horse_node, chariot_node, entry, index)
		var plate := _label_horse(horse_node, entry)
		_ex_horses.append({
			"node": horse_node,
			"pos": float(index) * -9.0,
			"lane": float(index) + 1.0,
			"speed": 0.0,
			"finished": false,
			"anim": _find_animation(horse_node),
			"plate": plate,
			"wheel_l": chariot_node.find_child("WheelL", true, false) as Node3D,
			"wheel_r": chariot_node.find_child("WheelR", true, false) as Node3D,
			"driver": chariot_node.find_child("Charioteer", true, false) as Node3D,
			"wheel_spin": 0.0,
			"lean": 0.0,
		})


func _end_exhibition() -> void:
	for horse in _ex_horses:
		(horse["node"] as Node3D).queue_free()
	_ex_horses.clear()
	_ex_t = 0.0


## Parade progress → position relative to the start line: the march covers
## PARADE_SPAN_M approaching from behind and holds 2.5m short of the gates.
func _parade_offset(progress: float) -> float:
	return minf(progress, PARADE_SPAN_M) - PARADE_SPAN_M - 2.5


# ── The infield show ─────────────────────────────────────────────────────────
# The open sand hosts a pair of gladiators sparring for the crowd: circling,
# alternating lunges on a slow beat, always facing each other. Pure ambience,
# deterministic, running whatever the wire is doing — the duel is far from
# the rail and belongs to the house, not the race.
const DUEL_CENTER_FRACTION := 0.45
const DUEL_RING_M := 1.7
const DUEL_CIRCLE_RAD_S := 0.35
const DUEL_LUNGE_EVERY_S := 3.4
const DUEL_TUNICS: Array[Color] = [Color(0.72, 0.16, 0.14), Color(0.13, 0.42, 0.47)]

## Tests pin this false where a deterministic empty infield matters.
var infield_show_enabled := true
var _duel: Array[Node3D] = []
var _duel_t := 0.0


func _build_infield_show() -> void:
	if not infield_show_enabled:
		return
	var center := _duel_center()
	for i in 2:
		var chariot: Node3D = _chariot_scene.instantiate()
		var figure := chariot.find_child("Charioteer", true, false)
		if figure == null:
			chariot.queue_free()
			return
		var fighter := figure.duplicate() as MeshInstance3D
		fighter.name = "Gladiator_%d" % i
		add_child(fighter)
		_tint_mesh(fighter, {
			"Tunic": DUEL_TUNICS[i],
			"Crest": DUEL_TUNICS[i].lightened(0.25),
		})
		fighter.position = center + Vector3(1.0 if i == 0 else -1.0, 0.0, 0.0) * DUEL_RING_M
		_duel.append(fighter)
		chariot.queue_free()


func _duel_center() -> Vector3:
	return Vector3(0.0, 0.0, TrackGeometry.turn_radius() * DUEL_CENTER_FRACTION)


func _update_infield_show(delta: float) -> void:
	if _duel.size() < 2:
		return
	_duel_t += delta
	var center := _duel_center()
	var angle := _duel_t * DUEL_CIRCLE_RAD_S
	var beat := fmod(_duel_t, DUEL_LUNGE_EVERY_S)
	var attacker := int(fmod(_duel_t / DUEL_LUNGE_EVERY_S, 2.0))
	for i in 2:
		var side := 1.0 if i == 0 else -1.0
		var offset := Vector3(cos(angle), 0.0, sin(angle)) * DUEL_RING_M * side
		var pos := center + offset
		if i == attacker and beat < 0.7:
			pos -= offset.normalized() * sin((beat / 0.7) * PI) * DUEL_RING_M * 0.62
		pos.y = 0.04 * absf(sin(_duel_t * 2.6 + float(i) * 2.1))
		var fighter := _duel[i]
		fighter.position = pos
		var rival := _duel[1 - i]
		if fighter.global_position.distance_to(rival.global_position) > 0.05:
			fighter.look_at(rival.global_position + Vector3.UP * 1.2, Vector3.UP)


func _exhibition_leader() -> Dictionary:
	var best: Dictionary = {}
	for horse in _ex_horses:
		if best.is_empty() or float(horse["pos"]) > float(best["pos"]):
			best = horse
	return best


## The cabinet rhythm: ride with the pack most of the time, then pull back to
## the establishing orbit so the whole colosseum gets its moment.
func _place_exhibition_camera(delta: float) -> void:
	var leader := _exhibition_leader()
	if leader.is_empty():
		return
	var s := TrackGeometry.start_offset(1800.0) + float(leader["pos"])
	var heading := TrackGeometry.heading_at(s)
	var outward := TrackGeometry.normal_at(s)
	var anchor := TrackGeometry.lane_point(s, float(leader["lane"]))
	var target_pos := anchor - heading * CAMERA_BACK_M + outward * CAMERA_SIDE_M + Vector3.UP * CAMERA_UP_M
	_camera.position = _camera.position.lerp(target_pos, minf(1.0, 4.0 * delta))
	_camera.look_at(anchor + heading * 10.0 + Vector3.UP * 1.2, Vector3.UP)


func _update_horses(delta: float) -> void:
	if state.phase == RaceState.PHASE_PARADING:
		# The grand parade is pure ambience: the sim sends no positions while
		# the teams walk the gate area, so this claims nothing about the race.
		_parade_t += delta
		var distance := state.race_distance()
		var index := 0
		for horse_id: String in _horses:
			var horse: Dictionary = _horses[horse_id]
			# March up FROM BEHIND the carceres and settle just short of the
			# line: the field must never parade ahead of the gates before the
			# break (and the old fmod wrap teleported settled teams back,
			# which read as horses "pulling up" mid-parade).
			var walk_raw := _parade_t * PARADE_WALK_MPS + float(index) * PARADE_STAGGER_M
			var walking := walk_raw < PARADE_SPAN_M
			horse["parade_moving"] = walking
			var walk := _parade_offset(walk_raw)
			var node: Node3D = horse["node"]
			node.transform = TrackGeometry.horse_transform(walk, float(horse["lane"]), distance, false)
			_update_chariot(horse, PARADE_WALK_MPS if walking else 0.0, 0.0, false, delta)
			index += 1
		return
	_parade_t = 0.0
	var running := state.phase == RaceState.PHASE_RUNNING
	for tick_horse in state.tick_horses:
		if typeof(tick_horse) != TYPE_DICTIONARY:
			continue
		var horse_id := str(tick_horse.get("horseId", ""))
		if not _horses.has(horse_id):
			continue
		var horse: Dictionary = _horses[horse_id]
		horse["speed"] = float(tick_horse.get("speed", 0.0))
		horse["finished"] = bool(tick_horse.get("finished", false))
		var authoritative := float(tick_horse.get("pos", 0.0))
		if bool(horse["finished"]):
			# The server stops moving a finished horse; keep predicting off a
			# stale speed and the chariot rubber-bands on the wire. Snap.
			horse["pos"] = authoritative
			horse["speed"] = 0.0
		else:
			var predicted: float = authoritative + float(horse["speed"]) * minf(_seconds_since_tick, TICK_INTERVAL_S * 2.0)
			horse["pos"] = lerpf(float(horse["pos"]), predicted, minf(1.0, 10.0 * delta))
		horse["lane"] = lerpf(float(horse["lane"]), float(tick_horse.get("lane", horse["lane"])), minf(1.0, 6.0 * delta))
	var distance := state.race_distance()
	for horse_id: String in _horses:
		var horse: Dictionary = _horses[horse_id]
		var node: Node3D = horse["node"]
		node.transform = TrackGeometry.horse_transform(float(horse["pos"]), float(horse["lane"]), distance)
		var moving := running and not bool(horse["finished"]) and float(horse["speed"]) > 0.5
		var s := TrackGeometry.start_offset(distance) + float(horse["pos"])
		_update_chariot(horse, float(horse["speed"]) if moving else 0.0, s, moving, delta)
		var anim: AnimationPlayer = horse["anim"]
		if anim == null:
			continue
		if moving:
			if not anim.is_playing():
				anim.play("Gallop")
			anim.speed_scale = clampf(float(horse["speed"]) / TYPICAL_SPEED_MPS, 0.5, 1.8)
		elif state.phase == RaceState.PHASE_PARADING and bool(horse.get("parade_moving", true)):
			if not anim.is_playing():
				anim.play("Gallop")
			anim.speed_scale = 0.25
		else:
			anim.stop()


## Wheels turn with the ground actually covered; the charioteer leans toward
## the infield through the turns and stands tall on the straights.
func _update_chariot(horse: Dictionary, ground_speed: float, s: float, racing: bool, delta: float) -> void:
	horse["wheel_spin"] = fmod(float(horse["wheel_spin"]) + ground_speed / WHEEL_RADIUS_M * delta, TAU)
	for wheel_key in ["wheel_l", "wheel_r"]:
		var wheel: Node3D = horse[wheel_key]
		if wheel != null:
			wheel.rotation.x = float(horse["wheel_spin"])
	var lean_target := 0.0
	if racing and TrackGeometry.in_turn(s):
		lean_target = DRIVER_LEAN_MAX_DEG * clampf(ground_speed / TYPICAL_SPEED_MPS, 0.0, 1.2)
	horse["lean"] = lerpf(float(horse["lean"]), lean_target, minf(1.0, 5.0 * delta))
	var driver: Node3D = horse["driver"]
	if driver != null:
		# Local +X on the horse's basis points at the infield; rolling the
		# charioteer negative about local Z tips them exactly that way.
		driver.rotation_degrees.z = -float(horse["lean"])


func _update_camera(delta: float) -> void:
	if state.phase == RaceState.PHASE_PARADING and not _horses.is_empty():
		_place_parade_camera(delta)
		return
	if state.phase == RaceState.PHASE_GATE and not _horses.is_empty():
		_place_gate_camera(delta)
		return
	var leader_id := state.leader_id()
	if state.phase in [RaceState.PHASE_IDLE, RaceState.PHASE_FINISHED] or not _horses.has(leader_id):
		if not _ex_horses.is_empty() \
			and fmod(_ex_t, EXHIBITION_CHASE_S + EXHIBITION_ORBIT_S) < EXHIBITION_CHASE_S:
			_place_exhibition_camera(delta)
			return
		_idle_angle += delta * 0.05
		_place_idle_camera(_idle_angle)
		return
	var leader: Dictionary = _horses[leader_id]
	var distance := state.race_distance()
	var s := TrackGeometry.start_offset(distance) + float(leader["pos"])
	var heading := TrackGeometry.heading_at(s)
	var outward := TrackGeometry.normal_at(s)
	var anchor := TrackGeometry.lane_point(s, float(leader["lane"]))
	var target_pos := anchor - heading * CAMERA_BACK_M + outward * CAMERA_SIDE_M + Vector3.UP * CAMERA_UP_M
	_camera.position = _camera.position.lerp(target_pos, minf(1.0, 4.0 * delta))
	var look := anchor + heading * 10.0 + Vector3.UP * 1.2
	_camera.look_at(look, Vector3.UP)


func _place_idle_camera(angle: float) -> void:
	var focus := TrackGeometry.point_at(TrackGeometry.finish_s())
	_camera.position = focus + Vector3(sin(angle), 0.0, cos(angle)) * IDLE_ORBIT_RADIUS_M + Vector3.UP * IDLE_ORBIT_UP_M
	_camera.look_at(focus + Vector3.UP * 6.0, Vector3.UP)


## Alongside the walking pack, from just beyond the outer rail.
func _place_parade_camera(delta: float) -> void:
	var start_s := TrackGeometry.start_offset(state.race_distance())
	var mid := start_s + _parade_offset(_parade_t * PARADE_WALK_MPS + PARADE_SPAN_M * 0.35)
	var anchor := TrackGeometry.lane_point(mid, 5.0)
	var outward := TrackGeometry.normal_at(mid)
	var target := TrackGeometry.lane_point(mid, 13.5) + outward * 4.0 + Vector3.UP * 3.2
	_camera.position = _camera.position.lerp(target, minf(1.0, 2.5 * delta))
	_camera.look_at(anchor + Vector3.UP * 1.4, Vector3.UP)


## The anticipation shot: square behind the gates, looking down the running line.
func _place_gate_camera(delta: float) -> void:
	var start_s := TrackGeometry.start_offset(state.race_distance())
	var heading := TrackGeometry.heading_at(start_s)
	var anchor := TrackGeometry.lane_point(start_s, 5.0)
	var target := anchor - heading * 18.0 + Vector3.UP * 7.0
	_camera.position = _camera.position.lerp(target, minf(1.0, 3.0 * delta))
	_camera.look_at(anchor + heading * 40.0 + Vector3.UP * 1.0, Vector3.UP)


func _update_countdown(delta: float) -> void:
	if state.starts_in_ms >= 0:
		if _countdown_ms < 0.0 or absf(_countdown_ms - float(state.starts_in_ms)) > 1500.0:
			_countdown_ms = float(state.starts_in_ms)
		_countdown_ms = maxf(0.0, _countdown_ms - delta * 1000.0)
	else:
		_countdown_ms = -1.0
	_apply_caption_text()


func _apply_phase_visuals() -> void:
	var board := state.phase == RaceState.PHASE_FINISHED and not state.results.is_empty()
	_results_panel.visible = board
	if board:
		_rebuild_results_board()
	for i in range(_rank_labels.size()):
		_rank_labels[i].visible = not board and (state.phase == RaceState.PHASE_RUNNING or state.phase == RaceState.PHASE_FINISHED)
	_apply_caption_text()


func _apply_caption_text() -> void:
	match state.phase:
		RaceState.PHASE_IDLE:
			_banner.text = "The Chariot Club"
			_phase_label.text = "The colosseum waits for the next race"
		RaceState.PHASE_PARADING:
			_banner.text = state.race_name()
			# The wire carries paradeEndsAt as starts_in_ms here: never leave
			# a rider guessing how long the ceremony holds them.
			_phase_label.text = _countdown_text("The grand parade  ·  gates in")
		RaceState.PHASE_GATE:
			_banner.text = state.race_name()
			_phase_label.text = _countdown_text("They load the carceres")
		RaceState.PHASE_RUNNING:
			_banner.text = state.race_name()
			_phase_label.text = "%.0fm  ·  %s  ·  %s" % [state.race_distance(), str(state.race.get("surface", "")), str(state.race.get("weather", ""))]
		RaceState.PHASE_FINISHED:
			_banner.text = state.race_name()
			_phase_label.text = "Official result"
		_:
			_banner.text = "The Chariot Club"
			_phase_label.text = state.phase
	var ranks := state.ranked_names(_rank_labels.size())
	for i in range(_rank_labels.size()):
		_rank_labels[i].text = ranks[i] if i < ranks.size() else ""


func _countdown_text(prefix: String) -> String:
	if _countdown_ms < 0.0:
		return prefix
	return "%s  ·  %ds" % [prefix, int(ceil(_countdown_ms / 1000.0))]
