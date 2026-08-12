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
# The exhibition field leads with the four faction silks (CircusFactions
# FACTIONS colors), then gold and purple from the shared fallback palette.
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
# Fallback liveries when the server sends no color live in CircusFactions
# (SILK_FALLBACKS): the four circus factions first, then the wider palette.
# The tally resolves from the same palette, so the color a horse wears and
# the faction it scores for can never disagree.

var state := RaceState.new()
var client: SpectatorClient
## Tests inject a capturing Callable; live builds fall through to the tree.
var scene_switcher: Callable = Callable()
## Tests pin this false where a deterministic empty arena matters.
var exhibition_enabled := true
var _ex_horses: Array[Dictionary] = []
var _ex_t := 0.0
# The armed challenge ghost: a recorded run replaying on the sand. Held OUT of
# _horses and _ex_horses on purpose — the live field, the tally, and the
# exhibition leader logic must never feel it (nothing here collides; every
# body on the track is transform-driven, so sharing no collection is the whole
# non-interference story).
var _ghost_run: GhostRun = null
var _ghost: Dictionary = {}
var _ghost_t := 0.0
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
var _rank_strip: PanelContainer
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

## The smallest design-unit area the HUD must keep visible when phone-sized
## windows scale the UI up (StudioUiScale): the rider input bar is the widest
## must-fit block at 504 units (3 x 104 + 150 + 3 x 14 separation), the
## sign-in gate the tallest at ~340.
const UI_MIN_VISIBLE := Vector2(520.0, 640.0)


func _ready() -> void:
	_apply_ui_scale()
	get_window().size_changed.connect(_apply_ui_scale)
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


## Phone-sized windows render the 1280-unit canvas at ~30% under canvas_items
## stretch — 10 px tap targets, measured by the QA gate. Scale the UI back up,
## bounded by what must stay visible; desktop is untouched (factor 1.0).
func _apply_ui_scale() -> void:
	var window := get_window()
	var design := Vector2(
		float(ProjectSettings.get_setting("display/window/size/viewport_width", 1280)),
		float(ProjectSettings.get_setting("display/window/size/viewport_height", 720)))
	window.content_scale_factor = StudioUiScale.content_scale_for(
		window.size, design, UI_MIN_VISIBLE)


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
	# The preset alone does not center: it pins the panel's LEFT edge at the
	# anchor and containers grow rightward, so the title block sat off-center
	# right on every device since it was built (measured by the QA gate at
	# phone width, where it ran off the edge entirely). Grow both ways.
	top.grow_horizontal = Control.GROW_DIRECTION_BOTH
	top.position.y = 12.0
	top.self_modulate = Color(0.071, 0.063, 0.043, 0.82)
	# qa_hud: the visual QA gate (studio_core qa_capture) checks members stay
	# on screen at every device size. Tag the panels, whose rects are the
	# thing that must fit.
	top.add_to_group("qa_hud")
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

	_rank_strip = PanelContainer.new()
	_rank_strip.name = "RunningOrder"
	_rank_strip.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	_rank_strip.position += Vector2(12.0, -12.0)
	# The preset anchors the strip's TOP at the bottom edge and containers grow
	# downward, so a filled running order ran 132 px off the bottom of the
	# screen (measured by the QA gate). Grow upward from the anchored corner.
	_rank_strip.grow_vertical = Control.GROW_DIRECTION_BEGIN
	_rank_strip.self_modulate = Color(0.071, 0.063, 0.043, 0.82)
	_rank_strip.add_to_group("qa_hud")
	hud.add_child(_rank_strip)
	var strip_box := VBoxContainer.new()
	_rank_strip.add_child(strip_box)
	for i in range(5):
		var row := Label.new()
		row.add_theme_font_size_override("font_size", 18)
		row.add_theme_color_override("font_color", Color(0.949, 0.925, 0.847))
		strip_box.add_child(row)
		_rank_labels.append(row)

	_connection_label = Label.new()
	_connection_label.name = "ConnectionState"
	_connection_label.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
	_connection_label.position += Vector2(-160.0, -24.0)
	_connection_label.add_theme_font_size_override("font_size", 13)
	_connection_label.add_theme_color_override("font_color", Color(0.847, 0.780, 0.635, 0.8))
	_connection_label.add_to_group("qa_hud")
	hud.add_child(_connection_label)

	_results_panel = PanelContainer.new()
	_results_panel.name = "LaurelBoard"
	_results_panel.set_anchors_preset(Control.PRESET_CENTER)
	# Same preset trap as the TopPanel: without growing both ways the board
	# hangs down-right from the screen center instead of sitting on it.
	_results_panel.grow_horizontal = Control.GROW_DIRECTION_BOTH
	_results_panel.grow_vertical = Control.GROW_DIRECTION_BOTH
	_results_panel.self_modulate = Color(0.071, 0.063, 0.043, 0.92)
	_results_panel.visible = false
	_results_panel.add_to_group("qa_hud")
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
	# The faction tally closes the board: every race accrues to the four.
	if not state.results.is_empty():
		var faction_title := Label.new()
		faction_title.text = "THE FACTIONS"
		faction_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		faction_title.add_theme_font_size_override("font_size", 18)
		faction_title.add_theme_color_override("font_color", Color(0.957, 0.808, 0.463))
		_results_box.add_child(faction_title)
		for faction_id in CircusFactions.ordered_ids(state.faction_points):
			var faction_row := Label.new()
			faction_row.text = "%s  ·  %d" % [
				CircusFactions.name_for(faction_id), int(state.faction_points.get(faction_id, 0)),
			]
			faction_row.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
			faction_row.add_theme_font_size_override("font_size", 16)
			faction_row.add_theme_color_override("font_color", CircusFactions.color_for(faction_id).lightened(0.25))
			_results_box.add_child(faction_row)


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
			if not state.results.is_empty():
				lines.append(CircusFactions.tally_line(state.faction_points))
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
	var livery := Color.from_string(str(entry.get("silk", "")), CircusFactions.fallback_livery(index))
	# The big readable surfaces wear the faction kit (nearest faction to the
	# stable's silk — the same resolution the points tally uses); the plume
	# and crest keep the stable's own color as the accent.
	var faction := CircusFactions.color_for(CircusFactions.nearest_to_color(livery))
	var horse_mesh := horse_node.find_child("Horse", true, false) as MeshInstance3D
	if horse_mesh != null:
		_tint_mesh(horse_mesh, {
			"Coat": coat,
			"Sock": coat.darkened(0.25),
			"Cloth": faction,
			"Plume": livery,
		})
	# The livery rides the chariot: tunic and the car's front panel take the
	# faction color, the helmet crest keeps the stable silk.
	for mesh_name in ["Car", "Charioteer"]:
		var mesh := chariot_node.find_child(mesh_name, true, false) as MeshInstance3D
		if mesh != null:
			_tint_mesh(mesh, {
				"CarFront": faction,
				"Tunic": faction,
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
	_update_ghost(delta)
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
	if not _ghost.is_empty():
		_update_plate(_ghost, false)


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


# ── The ghost ────────────────────────────────────────────────────────────────
# An armed challenge ghost replays a recorded run on the sand: spectral (tint
# only, no new art), scored by nobody, never in the live field's collections.
# During a race it runs against the live tick clock; between races it loops
# its lap with the exhibition so there is always something to chase.

## The spectral wash: the ghost's faction color, lifted toward white and
## mostly see-through, with a faint self-glow so it reads at distance.
const GHOST_ALPHA := 0.45
const GHOST_GLOW := 0.6


## Arm a recorded run (the rider view's "race a ghost"). Invalid runs are
## refused silently — the caller validated before offering the button.
func arm_ghost(run: GhostRun) -> void:
	stand_down_ghost()
	if run == null or not run.is_valid():
		return
	_ghost_run = run
	_spawn_ghost()


func stand_down_ghost() -> void:
	_ghost_run = null
	_ghost_t = 0.0
	if not _ghost.is_empty():
		(_ghost["node"] as Node3D).queue_free()
		_ghost = {}


func armed_ghost() -> GhostRun:
	return _ghost_run


func _spawn_ghost() -> void:
	var horse_node: Node3D = _horse_scene.instantiate()
	horse_node.name = "Ghost"
	add_child(horse_node)
	var chariot_node: Node3D = _chariot_scene.instantiate()
	chariot_node.name = "Chariot"
	horse_node.add_child(chariot_node)
	chariot_node.position = Vector3(0.0, 0.0, CHARIOT_HITCH_M)
	_tint_ghost(horse_node)
	var plate := Label3D.new()
	plate.text = "GHOST · %s" % _ghost_run.handle
	plate.font_size = 64
	plate.pixel_size = 0.012
	plate.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	plate.no_depth_test = true
	plate.modulate = _ghost_color()
	plate.outline_size = 18
	plate.outline_modulate = Color(0.071, 0.063, 0.043, 0.9)
	plate.position = Vector3(0.0, 2.9, 0.0)
	horse_node.add_child(plate)
	_ghost = {
		"node": horse_node,
		"pos": 0.0,
		"lane": 1.0,
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
	horse_node.visible = false


## Every surface of horse and biga takes the spectral wash — the faction color
## of the rider who set the run, so a Blues ghost can never pass for a Reds
## one. Shadows off: the dead do not cast them.
func _tint_ghost(horse_node: Node3D) -> void:
	var spectral := _ghost_color()
	for mesh_instance in horse_node.find_children("*", "MeshInstance3D", true, false):
		var mesh := mesh_instance as MeshInstance3D
		mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		if mesh.mesh == null:
			continue
		for surface in range(mesh.mesh.get_surface_count()):
			var base := mesh.mesh.surface_get_material(surface) as BaseMaterial3D
			var override := (base.duplicate() as BaseMaterial3D) if base != null else StandardMaterial3D.new()
			override.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
			override.albedo_color = Color(spectral, GHOST_ALPHA)
			override.emission_enabled = true
			override.emission = spectral
			override.emission_energy_multiplier = GHOST_GLOW
			mesh.set_surface_override_material(surface, override)


func _ghost_color() -> Color:
	if _ghost_run != null and CircusFactions.is_valid_id(_ghost_run.faction):
		return CircusFactions.color_for(_ghost_run.faction).lightened(0.45)
	return Color(0.75, 0.9, 1.0)


func _update_ghost(delta: float) -> void:
	if _ghost.is_empty() or _ghost_run == null:
		return
	var node: Node3D = _ghost["node"]
	var t_ms := -1.0
	var distance := _ghost_run.distance_m
	if state.phase == RaceState.PHASE_RUNNING:
		# Live: run the ghost against the same race clock the field answers to.
		t_ms = state.tick_t * _ghost_run.tick_scale_ms
		if state.race_distance() > 0.0:
			distance = state.race_distance()
	else:
		var resting: bool = state.phase in [RaceState.PHASE_IDLE, RaceState.PHASE_FINISHED] \
			and state.race.is_empty()
		if resting and exhibition_enabled:
			_ghost_t = fmod(_ghost_t + delta, _ghost_run.total_s())
			t_ms = _ghost_t * 1000.0
	if t_ms < 0.0:
		node.visible = false
		return
	var mark: Dictionary = _ghost_run.position_at(t_ms)
	node.visible = true
	_ghost["pos"] = float(mark.get("pos", 0.0))
	_ghost["lane"] = float(mark.get("lane", 1.0))
	_ghost["speed"] = float(mark.get("speed", 0.0))
	node.transform = TrackGeometry.horse_transform(float(_ghost["pos"]), float(_ghost["lane"]), distance)
	var s := TrackGeometry.start_offset(distance) + float(_ghost["pos"])
	var moving := float(_ghost["speed"]) > 0.5
	_update_chariot(_ghost, float(_ghost["speed"]) if moving else 0.0, s, moving, delta)
	var anim: AnimationPlayer = _ghost["anim"]
	if anim != null:
		if moving:
			if not anim.is_playing():
				anim.play("Gallop")
			anim.speed_scale = clampf(float(_ghost["speed"]) / TYPICAL_SPEED_MPS, 0.5, 1.8)
		else:
			anim.stop()


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
	var order_live := not board \
		and (state.phase == RaceState.PHASE_RUNNING or state.phase == RaceState.PHASE_FINISHED)
	# The panel too, not just its labels: a visible strip of empty labels
	# renders as a collapsed dark sliver in every non-race phase.
	_rank_strip.visible = order_live
	for i in range(_rank_labels.size()):
		_rank_labels[i].visible = order_live
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
			# The wire can carry administrative statuses this view does not
			# stage ("cancelled" when a race voids for want of entries). Raw
			# state under the title read as a broken build on the live demo;
			# to a spectator every such status means the same thing: no race
			# right now.
			_banner.text = "The Chariot Club"
			_phase_label.text = "The colosseum waits for the next race"
	var ranks := state.ranked_names(_rank_labels.size())
	for i in range(_rank_labels.size()):
		_rank_labels[i].text = ranks[i] if i < ranks.size() else ""


func _countdown_text(prefix: String) -> String:
	if _countdown_ms < 0.0:
		return prefix
	return "%s  ·  %ds" % [prefix, int(ceil(_countdown_ms / 1000.0))]
