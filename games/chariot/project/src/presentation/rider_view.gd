class_name RiderView
extends BroadcastView

## The Phase 2 rider: the whole broadcast, plus a signed-in owner, a chase
## camera behind their horse, and the three race inputs the protocol allows.
## Inputs are encouragements sent to the authoritative sim; nothing here
## predicts an outcome. WHIP during the gate phase is the free break.

const CHASE_BACK_M := 7.5
const CHASE_SIDE_M := 1.6
const CHASE_UP_M := 3.4
const TAP_THROTTLE_S := 0.2

var rider := RiderState.new()
var training := TrainingState.new()
var stable_client: StableClient

var _code_panel: PanelContainer
var _code_edit: LineEdit
var _code_error: Label
var _recovery_button: LinkButton
var _stands_button: LinkButton
var _faction_id: String = ""
var _faction_buttons: Array[Button] = []
var _post_label: Label
var _post_tick_s: float = 0.0
var _join_button: Button
var _gate_status: Label
var _gate_http: HTTPRequest
var _gate_flow: String = ""
var _pending_code: String = ""
var handoff_captured: Array = []
var _input_bar: HBoxContainer
var _whip_button: Button
var _guide_in_button: Button
var _guide_out_button: Button
var _block_button: Button
var _energy_bar: ProgressBar
var _my_line: Label
var _since_tap := 1.0
var _training_panel: PanelContainer
var _training_needle: TrainingNeedle
var _training_score: Label
var _training_result: Label
var _surge_was := false
var _stable_button: Button
var _stable_panel: PanelContainer
var _stable_horses_box: VBoxContainer
var _stable_races_box: VBoxContainer
var _stable_status: Label
var _selected_horse_id: String = ""


## The needle strip: effort marker over the drifting gold zone, drawn rather
## than assembled, because it is one rectangle away from being a chart.
class TrainingNeedle:
	extends Control
	var effort: float = 0.0
	var zone_lo: float = 0.0
	var zone_hi: float = 100.0
	var surge: bool = false

	func _init() -> void:
		custom_minimum_size = Vector2(300.0, 30.0)

	func _draw() -> void:
		var r := get_rect().size
		draw_rect(Rect2(Vector2.ZERO, r), Color(0.11, 0.10, 0.08, 0.9))
		var lo_x := r.x * zone_lo / 100.0
		var hi_x := r.x * zone_hi / 100.0
		var zone_color := Color(0.957, 0.808, 0.463, 0.55) if not surge else Color(0.98, 0.92, 0.55, 0.95)
		draw_rect(Rect2(Vector2(lo_x, 0.0), Vector2(maxf(hi_x - lo_x, 2.0), r.y)), zone_color)
		var needle_x := clampf(r.x * effort / 100.0, 1.0, r.x - 1.0)
		draw_rect(Rect2(Vector2(needle_x - 2.0, -3.0), Vector2(4.0, r.y + 6.0)), Color(0.976, 0.949, 0.878))

	func show_tick(state: TrainingState) -> void:
		effort = state.effort
		zone_lo = state.zone_lo
		zone_hi = state.zone_hi
		surge = state.surge
		queue_redraw()


func _create_client() -> SpectatorClient:
	return RiderClient.new()


func _ready() -> void:
	super._ready()
	stable_client = StableClient.new()
	stable_client.name = "StableClient"
	stable_client.settled.connect(_on_stable_settled)
	stable_client.projection.connect(_on_stable_projection)
	add_child(stable_client)
	_gate_http = HTTPRequest.new()
	_gate_http.timeout = 15.0
	_gate_http.request_completed.connect(_on_gate_request_completed)
	add_child(_gate_http)
	_build_code_panel()
	_build_rider_hud()
	_build_training_overlay()
	_build_stable_overlay()
	_build_post_line()
	_boot_sign_in()


## The Derby-cabinet answer to "what now": under the idle caption, name the
## race the rider is entered in and count down to post.
func _build_post_line() -> void:
	_post_label = Label.new()
	_post_label.name = "PostLine"
	_post_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_post_label.add_theme_font_size_override("font_size", 15)
	_post_label.add_theme_color_override("font_color", Color(0.957, 0.808, 0.463))
	_post_label.visible = false
	get_node("Hud/TopPanel/TopBox").add_child(_post_label)


func _update_post_line() -> void:
	if state.phase != RaceState.PHASE_IDLE and state.phase != RaceState.PHASE_FINISHED:
		_post_label.visible = false
		return
	var ids: Array = []
	for horse in rider.my_horses:
		if typeof(horse) == TYPE_DICTIONARY:
			ids.append(str(horse.get("id", "")))
	var line := PostTime.status_line(
		rider.open_races(), ids, int(Time.get_unix_time_from_system() * 1000.0)
	)
	_post_label.text = line
	_post_label.visible = not line.is_empty()


func _rider_client() -> RiderClient:
	return client as RiderClient


# ── Sign-in ──────────────────────────────────────────────────────────────────

func _build_code_panel() -> void:
	_code_panel = PanelContainer.new()
	_code_panel.name = "SignInGate"
	_code_panel.set_anchors_preset(Control.PRESET_CENTER)
	# Grow both ways or the preset pins the panel's top-left AT screen center
	# and the whole gate hangs down-right — 98 units off a phone's edge,
	# measured by the QA gate.
	_code_panel.grow_horizontal = Control.GROW_DIRECTION_BOTH
	_code_panel.grow_vertical = Control.GROW_DIRECTION_BOTH
	_code_panel.self_modulate = Color(0.071, 0.063, 0.043, 0.94)
	_code_panel.add_to_group("qa_hud")
	(get_node("Hud") as CanvasLayer).add_child(_code_panel)
	var box := VBoxContainer.new()
	# 400, not 340: the faction row below needs 4 × 90 + separations = 384,
	# and a phone canvas still clears it inside the 520-unit must-fit width.
	box.custom_minimum_size = Vector2(400.0, 0.0)
	_code_panel.add_child(box)
	var title := Label.new()
	title.text = "Drive for your stable"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 24)
	title.add_theme_color_override("font_color", Color(0.957, 0.808, 0.463))
	box.add_child(title)
	_gate_status = Label.new()
	_gate_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_gate_status.add_theme_font_size_override("font_size", 14)
	_gate_status.add_theme_color_override("font_color", Color(0.957, 0.808, 0.463))
	box.add_child(_gate_status)
	_code_edit = LineEdit.new()
	_code_edit.name = "OwnerCode"
	_code_edit.placeholder_text = "Owner code"
	_code_edit.max_length = 12
	_code_edit.alignment = HORIZONTAL_ALIGNMENT_CENTER
	# 60 design units keeps every sign-in control above the 44 px touch floor
	# at the ~0.75 px/unit a phone window settles at (measured by the QA
	# gate, not eyeballed).
	_code_edit.custom_minimum_size = Vector2(0.0, 60.0)
	_code_edit.text_submitted.connect(func(_text: String) -> void: _submit_code())
	_code_edit.add_to_group("qa_hud")
	_code_edit.add_to_group("qa_tap")
	box.add_child(_code_edit)
	_join_button = Button.new()
	_join_button.name = "TakeTheReins"
	_join_button.text = "Take the reins"
	_join_button.custom_minimum_size = Vector2(0.0, 60.0)
	_join_button.pressed.connect(_submit_code)
	_join_button.add_to_group("qa_hud")
	_join_button.add_to_group("qa_tap")
	box.add_child(_join_button)
	# First entry is where a rider declares for a faction: four buttons, one
	# choice, persisted by AuthStore. Local-only until the wire carries a
	# faction key — see AuthStore.saved_faction.
	_faction_id = AuthStore.saved_faction()
	if _faction_id.is_empty():
		_faction_id = CircusFactions.ids()[0]
	var faction_label := Label.new()
	faction_label.text = "Ride for a faction"
	faction_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	faction_label.add_theme_font_size_override("font_size", 14)
	faction_label.add_theme_color_override("font_color", Color(0.847, 0.780, 0.635))
	box.add_child(faction_label)
	var faction_row := HBoxContainer.new()
	faction_row.alignment = BoxContainer.ALIGNMENT_CENTER
	faction_row.add_theme_constant_override("separation", 8)
	box.add_child(faction_row)
	for faction_id in CircusFactions.ids():
		var button := Button.new()
		button.name = "Faction%s" % CircusFactions.name_for(faction_id)
		button.text = CircusFactions.name_for(faction_id).to_upper()
		button.toggle_mode = true
		button.custom_minimum_size = Vector2(90.0, 60.0)
		button.focus_mode = Control.FOCUS_NONE
		button.add_theme_color_override("font_color", CircusFactions.color_for(faction_id).lightened(0.25))
		var picked: String = faction_id
		button.pressed.connect(func() -> void: _pick_faction(picked))
		button.add_to_group("qa_hud")
		button.add_to_group("qa_tap")
		faction_row.add_child(button)
		_faction_buttons.append(button)
	_refresh_faction_buttons()
	_code_error = Label.new()
	_code_error.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_code_error.add_theme_font_size_override("font_size", 14)
	_code_error.add_theme_color_override("font_color", Color(0.910, 0.451, 0.353))
	box.add_child(_code_error)
	_recovery_button = LinkButton.new()
	_recovery_button.name = "RecoverCode"
	_recovery_button.text = "Lost your code? Recover at the stables office"
	_recovery_button.underline = LinkButton.UNDERLINE_MODE_ON_HOVER
	_recovery_button.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_recovery_button.add_theme_font_size_override("font_size", 13)
	_recovery_button.custom_minimum_size = Vector2(0.0, 60.0)
	_recovery_button.pressed.connect(_open_recovery)
	_recovery_button.add_to_group("qa_hud")
	_recovery_button.add_to_group("qa_tap")
	box.add_child(_recovery_button)
	_stands_button = LinkButton.new()
	_stands_button.name = "WatchInstead"
	_stands_button.text = "Watch from the stands instead"
	_stands_button.underline = LinkButton.UNDERLINE_MODE_ON_HOVER
	_stands_button.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_stands_button.add_theme_font_size_override("font_size", 13)
	_stands_button.custom_minimum_size = Vector2(0.0, 60.0)
	_stands_button.pressed.connect(func() -> void: _switch_scene("res://scenes/spectator.tscn"))
	_stands_button.add_to_group("qa_hud")
	_stands_button.add_to_group("qa_tap")
	box.add_child(_stands_button)


## Priority at the gate: an explicit env code, then a Plaza handoff token,
## then the remembered code (auto-entered on the web like the DOM stables,
## prefilled elsewhere), then the empty code box.
func _boot_sign_in() -> void:
	var env_code := OS.get_environment("RACING_CODE")
	if not env_code.is_empty():
		_code_edit.text = env_code
		_submit_code()
		return
	var token := WebHandoff.take_token()
	if not token.is_empty():
		_begin_sso(token)
		return
	var saved := AuthStore.saved_code()
	if saved.is_empty():
		return
	if OS.has_feature("web"):
		_begin_auto_login(saved)
	else:
		_code_edit.text = saved


## Exchange the Plaza token for our owner code. On failure the gate simply
## reopens (an expired token is routine); the rider can still type a code.
func _begin_sso(token: String) -> void:
	_set_gate_busy("Signing you in from the Plaza…")
	_send_gate_request("sso", SsoExchange.exchange_request(token))


## Re-enter with the remembered code, validated over REST first so an explicit
## rejection can forget it while a lockout or network trouble keeps it.
func _begin_auto_login(code: String) -> void:
	_pending_code = code
	_set_gate_busy("Returning to your stable…")
	_send_gate_request("auto", SsoExchange.login_request(code))


func _send_gate_request(flow: String, request: Dictionary) -> void:
	if OS.get_environment("RACING_SPECTATE_OFFLINE") == "1":
		handoff_captured.append(request)
		return
	_gate_flow = flow
	var url := SsoExchange.http_base(_rider_client().base_url) + str(request.get("path", ""))
	var error := _gate_http.request(
		url,
		PackedStringArray(["Content-Type: application/json"]),
		int(request.get("method", HTTPClient.METHOD_POST)),
		str(request.get("body", "")),
	)
	if error != OK:
		_gate_flow = ""
		_restore_gate("")


func _on_gate_request_completed(
	result: int, status: int, _headers: PackedStringArray, body: PackedByteArray
) -> void:
	var flow := _gate_flow
	_gate_flow = ""
	if result != HTTPRequest.RESULT_SUCCESS:
		_restore_gate("")
		return
	var body_text := body.get_string_from_utf8()
	if flow == "sso":
		var exchange := SsoExchange.fold_exchange(status, body_text)
		if bool(exchange.get("ok")):
			var code := str(exchange.get("code"))
			AuthStore.save(code)
			_enter_with_code(code)
		else:
			_restore_gate("")
		return
	var login := StableActions.fold_response(status, body_text)
	if bool(login.get("ok")):
		_enter_with_code(_pending_code)
	elif SsoExchange.should_forget(status):
		AuthStore.forget()
		_code_edit.text = ""
		_restore_gate("")
	else:
		_restore_gate(str(login.get("error")))
	_pending_code = ""


func _enter_with_code(code: String) -> void:
	_code_edit.text = code
	_restore_gate("")
	_submit_code()


## D2-A: recovery is the DOM stables' own reset flow, one tap away. The
## button never blocks the gate; it just opens the stables office.
func _open_recovery() -> void:
	OS.shell_open(SsoExchange.recovery_url(WebHandoff.page_origin()))


func _submit_code() -> void:
	var code := _code_edit.text.strip_edges()
	if code.is_empty():
		_code_error.text = "The stable code is on your card."
		return
	_code_error.text = ""
	_set_gate_busy("Taking the reins…")
	_rider_client().start_with_code(code)
	stable_client.configure(_rider_client().base_url, _rider_client().code)


func _set_gate_busy(line: String) -> void:
	_code_panel.visible = true
	_code_edit.editable = false
	_join_button.disabled = true
	_gate_status.text = line
	_code_error.text = ""


func _restore_gate(error_line: String) -> void:
	_code_edit.editable = true
	_join_button.disabled = false
	_gate_status.text = ""
	_code_error.text = error_line


func _save_code(code: String) -> void:
	AuthStore.save(code)


## Declaring for a faction is one tap, persisted immediately; the rider's
## line wears it from then on. The pick survives a forgotten owner code on
## purpose — the code was rejected, not the colors.
func _pick_faction(faction_id: String) -> void:
	if not CircusFactions.is_valid_id(faction_id):
		return
	_faction_id = faction_id
	AuthStore.save_faction(faction_id)
	audio.oneshot("ui_tick")
	_refresh_faction_buttons()
	_refresh_rider_line()


func _refresh_faction_buttons() -> void:
	for i in range(_faction_buttons.size()):
		_faction_buttons[i].button_pressed = CircusFactions.ids()[i] == _faction_id


# ── Rider HUD and inputs ─────────────────────────────────────────────────────

func _build_rider_hud() -> void:
	var hud := get_node("Hud") as CanvasLayer

	_my_line = Label.new()
	_my_line.name = "MyLine"
	_my_line.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	# Grow both ways or the label's LEFT edge pins at the anchor and the
	# rider's own line sits off-center right (the neighbouring bar and strip
	# hand-compensate with x offsets; a text label cannot).
	_my_line.grow_horizontal = Control.GROW_DIRECTION_BOTH
	# The drive stack reads bottom-up: input bar (-96, 64 tall), energy bar,
	# own line. Spacing is set by MEASURED heights — a ProgressBar renders at
	# its themed ~27 units, not the 14 its custom_minimum_size declares, and
	# the overlap check caught its bottom 9 units under the input bar.
	_my_line.position += Vector2(0.0, -152.0)
	_my_line.add_theme_font_size_override("font_size", 20)
	_my_line.add_theme_color_override("font_color", Color(0.976, 0.949, 0.878))
	# qa_hud: the visual QA gate checks these stay on screen at every device
	# size; qa_tap (on the buttons) adds the physical tap-size floor.
	_my_line.add_to_group("qa_hud")
	hud.add_child(_my_line)

	_energy_bar = ProgressBar.new()
	_energy_bar.name = "EnergyBar"
	_energy_bar.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	# Grow both ways instead of a hand-computed x offset: the input bar below
	# carried a stale -210 for a 504-wide row (it was sized for narrower
	# buttons once), which pushed BLOCK 52 units off a phone's edge and sat
	# the whole bar off-center everywhere. Measured by the QA gate.
	_energy_bar.grow_horizontal = Control.GROW_DIRECTION_BOTH
	_energy_bar.position += Vector2(0.0, -124.0)
	_energy_bar.custom_minimum_size = Vector2(220.0, 14.0)
	_energy_bar.min_value = 0.0
	_energy_bar.max_value = 100.0
	_energy_bar.show_percentage = false
	_energy_bar.add_to_group("qa_hud")
	hud.add_child(_energy_bar)

	_input_bar = HBoxContainer.new()
	_input_bar.name = "InputBar"
	_input_bar.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	_input_bar.grow_horizontal = Control.GROW_DIRECTION_BOTH
	_input_bar.position += Vector2(0.0, -96.0)
	_input_bar.add_theme_constant_override("separation", 14)
	_input_bar.add_to_group("qa_hud")
	hud.add_child(_input_bar)

	_guide_in_button = _make_input_button("◀ INSIDE", func() -> void: _send_guide("in"))
	_whip_button = _make_input_button("WHIP", _send_whip)
	_whip_button.custom_minimum_size = Vector2(150.0, 64.0)
	_guide_out_button = _make_input_button("WIDE ▶", func() -> void: _send_guide("out"))
	_block_button = _make_input_button("BLOCK", Callable())
	_block_button.toggle_mode = true
	_block_button.toggled.connect(_send_block)

	# On a narrow canvas the centered input bar reaches the left edge where
	# the broadcast's running order sits (a 101x64-unit collision, measured).
	# Lift the strip clear of the whole drive stack there.
	if get_viewport().get_visible_rect().size.x < 640.0:
		_rank_strip.position.y -= 178.0

	_set_rider_hud_visible(false)


func _make_input_button(label: String, on_press: Callable) -> Button:
	var button := Button.new()
	button.name = label.to_pascal_case()
	button.text = label
	button.custom_minimum_size = Vector2(104.0, 64.0)
	button.focus_mode = Control.FOCUS_NONE
	button.add_to_group("qa_hud")
	button.add_to_group("qa_tap")
	if not on_press.is_null():
		button.pressed.connect(on_press)
	_input_bar.add_child(button)
	return button


func _set_rider_hud_visible(shown: bool) -> void:
	_input_bar.visible = shown
	_energy_bar.visible = shown
	_my_line.visible = shown


# ── Training overlay ─────────────────────────────────────────────────────────

func _build_training_overlay() -> void:
	_training_panel = PanelContainer.new()
	_training_panel.name = "TrainingBoard"
	_training_panel.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	# Grow both ways, not a hand-computed x offset (the same stale-arithmetic
	# trap the QA gate measured on the input bar) — and grow UP from a bottom
	# margin: anchored at a fixed top, the board's own growth ran its
	# dismiss button 16 units off the bottom of the screen (measured).
	_training_panel.grow_horizontal = Control.GROW_DIRECTION_BOTH
	_training_panel.grow_vertical = Control.GROW_DIRECTION_BEGIN
	_training_panel.position += Vector2(0.0, -20.0)
	_training_panel.self_modulate = Color(0.071, 0.063, 0.043, 0.9)
	_training_panel.add_to_group("qa_hud")
	(get_node("Hud") as CanvasLayer).add_child(_training_panel)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 8)
	_training_panel.add_child(box)
	var title := Label.new()
	title.text = "Training session"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 18)
	title.add_theme_color_override("font_color", Color(0.957, 0.808, 0.463))
	box.add_child(title)
	_training_needle = TrainingNeedle.new()
	box.add_child(_training_needle)
	_training_score = Label.new()
	_training_score.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_training_score.add_theme_font_size_override("font_size", 15)
	_training_score.add_theme_color_override("font_color", Color(0.949, 0.925, 0.847))
	box.add_child(_training_score)
	var buttons := HBoxContainer.new()
	buttons.alignment = BoxContainer.ALIGNMENT_CENTER
	buttons.add_theme_constant_override("separation", 14)
	box.add_child(buttons)
	for label_and_type: Array in [["DRIVE (W)", "drive"], ["EASE (S)", "ease"]]:
		var button := Button.new()
		button.text = label_and_type[0]
		# 60 units clears the 44 px touch floor at phone scale.
		button.custom_minimum_size = Vector2(130.0, 60.0)
		button.focus_mode = Control.FOCUS_NONE
		button.add_to_group("qa_hud")
		button.add_to_group("qa_tap")
		var input_type: String = label_and_type[1]
		button.pressed.connect(func() -> void: _send_training(input_type))
		buttons.add_child(button)
	_training_result = Label.new()
	_training_result.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_training_result.add_theme_font_size_override("font_size", 14)
	_training_result.add_theme_color_override("font_color", Color(0.847, 0.780, 0.635))
	box.add_child(_training_result)
	var dismiss := Button.new()
	dismiss.name = "BackToStable"
	dismiss.text = "Back to the stable"
	dismiss.custom_minimum_size = Vector2(0.0, 60.0)
	dismiss.focus_mode = Control.FOCUS_NONE
	dismiss.add_to_group("qa_hud")
	dismiss.add_to_group("qa_tap")
	dismiss.pressed.connect(_dismiss_training)
	box.add_child(dismiss)
	_training_panel.visible = false


func _send_training(input_type: String) -> void:
	if not training.active():
		return
	_rider_client().send_event("training:input", { "sessionId": training.session_id, "type": input_type })


## Back to the stable ALWAYS works. Dismissing a live session abandons it:
## the session id is remembered and its remaining ticks (and eventual result)
## are swallowed, so the panel cannot resurrect itself — the trap a rider hit
## live on 2026-07-19, stuck training sprints until post time.
var _abandoned_session := ""

func _dismiss_training() -> void:
	if training.active():
		_abandoned_session = training.session_id
	training.clear()
	_training_panel.visible = false


# ── The stable ───────────────────────────────────────────────────────────────

const STABLE_SECTIONS: Array[String] = ["YARD", "BLOODSTOCK", "EXCHANGE", "HONOURS", "CIRCUIT"]
const CONFIRM_WINDOW_MS := 4000

var _stable_section: String = "YARD"
var _yard_box: VBoxContainer
var _races_title: Label
var _section_box: VBoxContainer
var _armed_key: String = ""
var _armed_deadline_ms: int = 0
var _sire_pick: OptionButton
var _dam_pick: OptionButton


func _build_stable_overlay() -> void:
	var hud := get_node("Hud") as CanvasLayer
	_stable_button = Button.new()
	_stable_button.name = "StableDoor"
	_stable_button.text = "STABLE"
	_stable_button.custom_minimum_size = Vector2(110.0, 60.0)
	_stable_button.focus_mode = Control.FOCUS_NONE
	_stable_button.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	_stable_button.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	# Below the centered title panel on a narrow canvas, same as the stands'
	# reins door — but LOWER than the stands' 100: the rider's panel also
	# carries the post line, and at 100 the door still clipped its bottom by
	# 8 units (measured).
	var door_y := 124.0 if get_viewport().get_visible_rect().size.x < 660.0 else 14.0
	_stable_button.position += Vector2(-126.0, door_y)
	_stable_button.add_to_group("qa_hud")
	_stable_button.add_to_group("qa_tap")
	_stable_button.pressed.connect(_toggle_stable)
	_stable_button.visible = false
	hud.add_child(_stable_button)

	_stable_panel = PanelContainer.new()
	_stable_panel.name = "StableBoard"
	_stable_panel.set_anchors_preset(Control.PRESET_CENTER)
	# CENTER without grow-both hung the whole board down-right of the screen
	# center — off-center on desktop and entirely OFF a phone's canvas.
	_stable_panel.grow_horizontal = Control.GROW_DIRECTION_BOTH
	_stable_panel.grow_vertical = Control.GROW_DIRECTION_BOTH
	_stable_panel.self_modulate = Color(0.071, 0.063, 0.043, 0.94)
	_stable_panel.visible = false
	_stable_panel.add_to_group("qa_hud")
	hud.add_child(_stable_panel)
	var box := VBoxContainer.new()
	# 500, not 560: a phone canvas settles at 520 visible units and the board
	# must fit inside it with the panel's own padding.
	box.custom_minimum_size = Vector2(500.0, 0.0)
	box.add_theme_constant_override("separation", 8)
	_stable_panel.add_child(box)
	var title := Label.new()
	title.text = "Your stable"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 22)
	title.add_theme_color_override("font_color", Color(0.957, 0.808, 0.463))
	box.add_child(title)

	var sections := HBoxContainer.new()
	sections.alignment = BoxContainer.ALIGNMENT_CENTER
	sections.add_theme_constant_override("separation", 6)
	box.add_child(sections)
	for section in STABLE_SECTIONS:
		var tab := Button.new()
		tab.text = section
		# The tap floor judges the SMALLEST dimension: "YARD" sized itself
		# ~50 units wide (37 px on a phone) even at full height.
		tab.custom_minimum_size = Vector2(64.0, 60.0)
		tab.focus_mode = Control.FOCUS_NONE
		tab.add_to_group("qa_hud")
		tab.add_to_group("qa_tap")
		tab.pressed.connect(func() -> void: _open_section(section))
		sections.add_child(tab)

	_yard_box = VBoxContainer.new()
	_yard_box.add_theme_constant_override("separation", 6)
	box.add_child(_yard_box)
	_stable_horses_box = VBoxContainer.new()
	_stable_horses_box.add_theme_constant_override("separation", 4)
	_yard_box.add_child(_stable_horses_box)
	_races_title = Label.new()
	_races_title.text = "Open races"
	_races_title.add_theme_font_size_override("font_size", 17)
	_races_title.add_theme_color_override("font_color", Color(0.957, 0.808, 0.463))
	_yard_box.add_child(_races_title)
	_stable_races_box = VBoxContainer.new()
	_stable_races_box.add_theme_constant_override("separation", 4)
	_yard_box.add_child(_stable_races_box)

	_section_box = VBoxContainer.new()
	_section_box.add_theme_constant_override("separation", 4)
	box.add_child(_section_box)

	_stable_status = Label.new()
	_stable_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_stable_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_stable_status.add_theme_font_size_override("font_size", 14)
	_stable_status.add_theme_color_override("font_color", Color(0.847, 0.780, 0.635))
	box.add_child(_stable_status)
	var close := Button.new()
	close.name = "CloseStable"
	close.text = "Close"
	close.custom_minimum_size = Vector2(0.0, 60.0)
	close.focus_mode = Control.FOCUS_NONE
	close.add_to_group("qa_hud")
	close.add_to_group("qa_tap")
	close.pressed.connect(_toggle_stable)
	box.add_child(close)


func _toggle_stable() -> void:
	# One desk at a time: walking to the stable abandons a live gallop and
	# clears a finished card — never a locked door.
	if training.active() or training.finished():
		_dismiss_training()
	_stable_panel.visible = not _stable_panel.visible
	if _stable_panel.visible:
		_refresh_stable()


func _open_section(section: String) -> void:
	_stable_section = section
	_armed_key = ""
	_refresh_stable()
	match section:
		"EXCHANGE":
			_fetch_projection(StableActions.exchange_fetch(stable_client.code))
		"HONOURS":
			_fetch_projection(StableActions.honours_fetch(stable_client.code))
		"CIRCUIT":
			_fetch_projection(StableActions.circuit_fetch(stable_client.code))


func _fetch_projection(request: Dictionary) -> void:
	_section_note("Asking the race office…")
	stable_client.send(request)


func _refresh_stable() -> void:
	_yard_box.visible = _stable_section == "YARD"
	_section_box.visible = not _yard_box.visible
	for child in _section_box.get_children():
		child.queue_free()
	for child in _stable_horses_box.get_children():
		child.queue_free()
	for child in _stable_races_box.get_children():
		child.queue_free()
	if _selected_horse_id.is_empty() and not rider.my_horses.is_empty():
		_selected_horse_id = str((rider.my_horses[0] as Dictionary).get("id", ""))
	match _stable_section:
		"YARD":
			_render_yard()
		"BLOODSTOCK":
			_render_bloodstock()
		_:
			pass


func _render_yard() -> void:
	for horse in rider.my_horses:
		_stable_horses_box.add_child(_horse_row(horse))
	var open := rider.open_races()
	if open.is_empty():
		var none := Label.new()
		none.text = "No races are posted right now."
		none.add_theme_font_size_override("font_size", 14)
		_stable_races_box.add_child(none)
	# Program races (with a post time) first, soonest post on top; legacy
	# schedule-less races sink to the bottom where they can't trap anyone.
	var ordered := open.duplicate()
	ordered.sort_custom(func(a, b) -> bool:
		var at := int((a as Dictionary).get("scheduledFor", 0))
		var bt := int((b as Dictionary).get("scheduledFor", 0))
		if (at > 0) != (bt > 0):
			return at > 0
		return at < bt)
	for race in ordered:
		_stable_races_box.add_child(_race_row(race))


# ── Bloodstock: breed, sell, retire ──────────────────────────────────────────

## Two taps for anything that moves coins or careers: the first arms the
## button (its label turns to CONFIRM), the second within the window fires.
func _confirm_action(key: String, fire: Callable) -> void:
	var now := Time.get_ticks_msec()
	if _armed_key == key and now < _armed_deadline_ms:
		_armed_key = ""
		audio.oneshot("ui_confirm")
		fire.call()
		return
	_armed_key = key
	_armed_deadline_ms = now + CONFIRM_WINDOW_MS
	audio.oneshot("ui_tick")
	_refresh_stable()


func _action_label(key: String, base: String) -> String:
	if _armed_key == key and Time.get_ticks_msec() < _armed_deadline_ms:
		return "CONFIRM"
	return base


func _render_bloodstock() -> void:
	var pair := HBoxContainer.new()
	pair.add_theme_constant_override("separation", 8)
	_section_box.add_child(pair)
	_sire_pick = _horse_option_button("Sire", ["colt", "stallion"])
	_dam_pick = _horse_option_button("Dam", ["filly", "mare"])
	pair.add_child(_sire_pick)
	pair.add_child(_dam_pick)
	var preview := Button.new()
	preview.text = "PREVIEW"
	preview.focus_mode = Control.FOCUS_NONE
	preview.pressed.connect(func() -> void:
		_send_stable(StableActions.breed_preview(_picked_id(_sire_pick), _picked_id(_dam_pick), stable_client.code), "Reading the bloodlines…"))
	pair.add_child(preview)
	var breed := Button.new()
	breed.text = _action_label("breed", "BREED (300c)")
	breed.focus_mode = Control.FOCUS_NONE
	breed.pressed.connect(func() -> void:
		_confirm_action("breed", func() -> void:
			_send_stable(StableActions.breed(_picked_id(_sire_pick), _picked_id(_dam_pick), stable_client.code), "At the covering shed…")))
	pair.add_child(breed)

	for horse in rider.my_horses:
		var horse_id := str(horse.get("id", ""))
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 8)
		var line := Label.new()
		line.text = "%s  ·  %s  ·  %s" % [str(horse.get("name", "?")), str(horse.get("grade", "?")), str(horse.get("sex", ""))]
		line.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(line)
		var sell := Button.new()
		sell.text = _action_label("sell:" + horse_id, "SELL")
		sell.focus_mode = Control.FOCUS_NONE
		sell.pressed.connect(func() -> void:
			_confirm_action("sell:" + horse_id, func() -> void:
				_send_stable(StableActions.sell(horse_id, stable_client.code), "At the sales ring…")))
		row.add_child(sell)
		var retire := Button.new()
		retire.text = _action_label("retire:" + horse_id, "RETIRE")
		retire.focus_mode = Control.FOCUS_NONE
		retire.pressed.connect(func() -> void:
			_confirm_action("retire:" + horse_id, func() -> void:
				_send_stable(StableActions.retire(horse_id, stable_client.code), "One last lap of honour…")))
		row.add_child(retire)
		_section_box.add_child(row)


## The covering-shed disclosure, rendered exactly as the server discloses it:
## eligibility, grade band, and the honest per-stat ranges, never potential.
func _render_breed_preview(analysis: Dictionary) -> void:
	_stable_status.text = ""
	var eligibility: Dictionary = analysis.get("eligibility", {}) if typeof(analysis.get("eligibility")) == TYPE_DICTIONARY else {}
	var lines: Array[String] = []
	if not eligibility.is_empty():
		lines.append("Eligible" if bool(eligibility.get("ok", eligibility.get("eligible", false))) else "Not eligible: %s" % str(eligibility.get("reason", "")))
	if analysis.has("gradeBand"):
		lines.append("Expected grade band: %s" % str(analysis.get("gradeBand")))
	var ranges: Dictionary = analysis.get("ranges", {}) if typeof(analysis.get("ranges")) == TYPE_DICTIONARY else {}
	for stat: String in ranges:
		var band: Variant = ranges[stat]
		if typeof(band) == TYPE_DICTIONARY:
			lines.append("%s %d–%d" % [stat, int(band.get("lo", band.get("min", 0))), int(band.get("hi", band.get("max", 0)))])
		elif typeof(band) == TYPE_ARRAY and (band as Array).size() >= 2:
			lines.append("%s %d–%d" % [stat, int(band[0]), int(band[1])])
	if lines.is_empty():
		lines.append("The stud book keeps its counsel on this pairing.")
	_stable_status.text = "  ·  ".join(lines)


func _horse_option_button(placeholder: String, sexes: Array[String]) -> OptionButton:
	var pick := OptionButton.new()
	pick.focus_mode = Control.FOCUS_NONE
	pick.add_item(placeholder)
	pick.set_item_disabled(0, true)
	for horse in rider.my_horses:
		if typeof(horse) != TYPE_DICTIONARY:
			continue
		if str(horse.get("sex", "")) in sexes:
			pick.add_item(str(horse.get("name", "?")))
			pick.set_item_metadata(pick.item_count - 1, str(horse.get("id", "")))
	return pick


func _picked_id(pick: OptionButton) -> String:
	if pick == null or pick.selected <= 0:
		return ""
	return str(pick.get_item_metadata(pick.selected))


# ── Projections: exchange, honours, circuit ──────────────────────────────────

func _on_stable_projection(path: String, ok: bool, error: String, data: Dictionary) -> void:
	if not ok:
		_section_note(error)
		return
	if path.begins_with("/api/breed/preview"):
		_render_breed_preview(data.get("analysis", {}) if typeof(data.get("analysis")) == TYPE_DICTIONARY else {})
	elif path.begins_with("/api/exchange"):
		_render_exchange(data.get("exchange", {}) if typeof(data.get("exchange")) == TYPE_DICTIONARY else {})
	elif path.begins_with("/api/honours"):
		_render_honours(data.get("honours", {}) if typeof(data.get("honours")) == TYPE_DICTIONARY else {})
	elif path.begins_with("/api/circuit"):
		_render_circuit(data.get("circuit", {}) if typeof(data.get("circuit")) == TYPE_DICTIONARY else {})


func _section_note(text: String) -> void:
	for child in _section_box.get_children():
		child.queue_free()
	var note := Label.new()
	note.text = text
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	note.add_theme_font_size_override("font_size", 14)
	_section_box.add_child(note)


func _section_line(text: String, gold: bool = false) -> void:
	var line := Label.new()
	line.text = text
	line.add_theme_font_size_override("font_size", 15)
	if gold:
		line.add_theme_color_override("font_color", Color(0.957, 0.808, 0.463))
	_section_box.add_child(line)


func _render_exchange(exchange: Dictionary) -> void:
	for child in _section_box.get_children():
		child.queue_free()
	_section_line("Purse: %dc" % int(exchange.get("purse", 0)), true)
	var listings: Variant = exchange.get("listings", [])
	if typeof(listings) != TYPE_ARRAY or (listings as Array).is_empty():
		_section_line("No horses are consigned right now.")
	else:
		for listing in listings:
			if typeof(listing) != TYPE_DICTIONARY:
				continue
			var listing_id := str(listing.get("id", ""))
			var mine := bool(listing.get("mine", false)) or str(listing.get("stableName", "")) == rider.stable_name()
			var row := HBoxContainer.new()
			row.add_theme_constant_override("separation", 8)
			var line := Label.new()
			line.text = "%s  ·  %s  ·  %s  ·  %dc" % [
				str(listing.get("horseName", "?")), str(listing.get("grade", "?")),
				str(listing.get("stableName", "?")), int(listing.get("price", 0)),
			]
			line.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			row.add_child(line)
			var action := Button.new()
			action.focus_mode = Control.FOCUS_NONE
			if mine:
				action.text = _action_label("delist:" + listing_id, "WITHDRAW")
				action.pressed.connect(func() -> void:
					_confirm_action("delist:" + listing_id, func() -> void:
						_send_stable(StableActions.exchange_delist(listing_id, stable_client.code), "Withdrawing the consignment…")))
			else:
				action.text = _action_label("buy:" + listing_id, "BUY")
				action.pressed.connect(func() -> void:
					_confirm_action("buy:" + listing_id, func() -> void:
						_send_stable(StableActions.exchange_buy(listing_id, stable_client.code), "Raising a hand at the sales…")))
			row.add_child(action)
			_section_box.add_child(row)
	var consign_note := Label.new()
	consign_note.text = "Consign from the yard: pick a horse, then LIST at a fixed price (50–25000c)."
	consign_note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	consign_note.add_theme_font_size_override("font_size", 12)
	_section_box.add_child(consign_note)
	var consign := HBoxContainer.new()
	consign.add_theme_constant_override("separation", 8)
	var price := SpinBox.new()
	price.min_value = 50
	price.max_value = 25000
	price.step = 10
	price.value = 500
	consign.add_child(price)
	var list_button := Button.new()
	list_button.text = _action_label("list", "LIST %s" % _selected_horse_name())
	list_button.focus_mode = Control.FOCUS_NONE
	list_button.disabled = _selected_horse_id.is_empty()
	list_button.pressed.connect(func() -> void:
		_confirm_action("list", func() -> void:
			_send_stable(StableActions.exchange_list(_selected_horse_id, int(price.value), stable_client.code), "Consigning…")))
	consign.add_child(list_button)
	_section_box.add_child(consign)


func _selected_horse_name() -> String:
	for horse in rider.my_horses:
		if typeof(horse) == TYPE_DICTIONARY and str(horse.get("id", "")) == _selected_horse_id:
			return str(horse.get("name", ""))
	return "…"


func _render_honours(honours: Dictionary) -> void:
	for child in _section_box.get_children():
		child.queue_free()
	var items: Variant = honours.get("honours", [])
	if typeof(items) != TYPE_ARRAY or (items as Array).is_empty():
		_section_line("The trophy shelf waits for its first laurel.")
		return
	for item in items:
		if typeof(item) != TYPE_DICTIONARY:
			continue
		var honour_id := str(item.get("id", ""))
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 8)
		var line := Label.new()
		line.text = "%s  ·  %d / %d%s" % [
			str(item.get("name", item.get("title", honour_id))),
			int(item.get("current", 0)), int(item.get("target", 0)),
			"  ·  earned" if bool(item.get("earned", false)) else "",
		]
		line.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(line)
		if bool(item.get("claimable", false)):
			var claim := Button.new()
			claim.text = "CLAIM"
			claim.focus_mode = Control.FOCUS_NONE
			claim.pressed.connect(func() -> void:
				_send_stable(StableActions.honours_claim(honour_id, stable_client.code), "Accepting the honour…"))
			row.add_child(claim)
		_section_box.add_child(row)


func _render_circuit(circuit: Dictionary) -> void:
	for child in _section_box.get_children():
		child.queue_free()
	var season: Dictionary = circuit.get("season", {}) if typeof(circuit.get("season")) == TYPE_DICTIONARY else {}
	_section_line("Crown Circuit  ·  %s" % str(season.get("id", "")), true)
	var mine: Dictionary = circuit.get("myStable", {}) if typeof(circuit.get("myStable")) == TYPE_DICTIONARY else {}
	if not mine.is_empty():
		_section_line("Your stable: rank %s  ·  %s pts  ·  %s" % [str(mine.get("rank", "-")), str(mine.get("points", 0)), str(mine.get("title", ""))])
		if str(mine.get("nextGoal", "")) != "":
			_section_line("Next goal: %s" % str(mine.get("nextGoal", "")))
	var standings: Variant = circuit.get("stableStandings", [])
	if typeof(standings) == TYPE_ARRAY:
		var shown := 0
		for stand in standings:
			if shown >= 6 or typeof(stand) != TYPE_DICTIONARY:
				break
			shown += 1
			_section_line("%d  %s  ·  %d pts  ·  %d wins" % [shown, str(stand.get("stableName", "?")), int(stand.get("points", 0)), int(stand.get("wins", 0))])


func _horse_row(horse: Dictionary) -> HBoxContainer:
	var horse_id := str(horse.get("id", ""))
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	var pick := Button.new()
	pick.toggle_mode = true
	pick.button_pressed = horse_id == _selected_horse_id
	pick.focus_mode = Control.FOCUS_NONE
	var record: Dictionary = horse.get("record", {}) if typeof(horse.get("record")) == TYPE_DICTIONARY else {}
	pick.text = "%s  ·  %s  ·  cond %d  ·  bond %d  ·  %d-%d" % [
		str(horse.get("name", "?")), str(horse.get("grade", "?")),
		int(horse.get("condition", 0)), int(horse.get("bond", 0)),
		int(record.get("wins", 0)), int(record.get("starts", 0)),
	]
	pick.pressed.connect(func() -> void:
		_selected_horse_id = horse_id
		_refresh_stable())
	pick.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	# The text column bends, the row does not: without clipping, one long
	# stat line forced the whole board 40 units off each phone edge.
	pick.clip_text = true
	row.add_child(pick)
	row.add_child(_menu_button("FEED", StableActions.MEALS, func(meal: String) -> void:
		_send_stable(StableActions.care(horse_id, meal, stable_client.code), "Feeding %s…" % str(horse.get("name", "")))))
	row.add_child(_menu_button("TRAIN", StableActions.FOCUSES, func(focus: String) -> void:
		_send_stable(StableActions.train(horse_id, focus, stable_client.code), "Saddling up for %s…" % focus)))
	return row


func _race_row(race: Dictionary) -> HBoxContainer:
	var race_id := str(race.get("id", ""))
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	var line := Label.new()
	var entries: Variant = race.get("entries", [])
	var field := (entries as Array).size() if typeof(entries) == TYPE_ARRAY else 0
	line.text = "%s  ·  %dm %s  ·  %d entered" % [
		str(race.get("name", "?")), int(race.get("distance", 0)),
		str(race.get("surface", "")), field,
	]
	var post_at := int(race.get("scheduledFor", 0))
	if post_at > 0:
		var left := post_at - int(Time.get_unix_time_from_system() * 1000.0)
		line.text += "  ·  post %s" % ("any moment" if left <= 0 else PostTime.clock(left))
	else:
		line.text += "  ·  awaiting the stewards"
		line.add_theme_color_override("font_color", Color(0.62, 0.57, 0.47))
	line.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	line.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	row.add_child(line)
	var entered_race := rider.entered_open_race(_selected_horse_id)
	var action := Button.new()
	action.focus_mode = Control.FOCUS_NONE
	if entered_race == race_id:
		action.text = "WITHDRAW"
		action.pressed.connect(func() -> void:
			_send_stable(StableActions.withdraw(_selected_horse_id, race_id, stable_client.code), "Withdrawing…"))
	else:
		action.text = "ENTER"
		action.disabled = _selected_horse_id.is_empty() or not entered_race.is_empty()
		action.pressed.connect(func() -> void:
			_send_stable(StableActions.enter(_selected_horse_id, race_id, stable_client.code), "Declaring…"))
	row.add_child(action)
	return row


func _menu_button(label: String, options: Array[String], on_pick: Callable) -> MenuButton:
	var menu := MenuButton.new()
	menu.text = label
	menu.focus_mode = Control.FOCUS_NONE
	for i in range(options.size()):
		menu.get_popup().add_item(options[i], i)
	menu.get_popup().id_pressed.connect(func(id: int) -> void: on_pick.call(options[id]))
	return menu


func _send_stable(request: Dictionary, doing: String) -> void:
	_stable_status.text = doing
	stable_client.send(request)


func _on_stable_settled(_path: String, ok: bool, error: String) -> void:
	_stable_status.text = "" if ok else error
	if _stable_panel.visible:
		_refresh_stable()


func _refresh_training() -> void:
	_training_panel.visible = training.active() or training.finished()
	# The idle "waiting for your race" line lives where the board stands, and
	# the board already names the horse — one of them at a time (a 300x28-unit
	# overlap, measured). Re-shown by _refresh_rider_line once the board goes.
	if rider.signed_in() and not rider.riding():
		_my_line.visible = not _training_panel.visible
	if not _training_panel.visible:
		return
	if _stable_panel != null:
		_stable_panel.visible = false
	if training.surge and not _surge_was:
		audio.oneshot("surge_chime")
	_surge_was = training.surge
	_training_needle.show_tick(training)
	if training.finished():
		_training_score.text = "Final score %d" % int(training.result.get("score", 0))
		_training_result.text = ("%s\n%s" % [training.result_line(), training.programme_line]).strip_edges()
	else:
		_training_score.text = "Score %d  ·  %ds left%s" % [int(training.score), int(training.seconds_left), "  ·  SURGE" if training.surge else ""]
		_training_result.text = ""


func _unhandled_input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key == null or not key.pressed or key.echo:
		return
	if training.active():
		match key.physical_keycode:
			KEY_W:
				_send_training("drive")
			KEY_S:
				_send_training("ease")
		return
	if not rider.riding():
		return
	match key.physical_keycode:
		KEY_SPACE:
			_send_whip()
		KEY_A, KEY_LEFT:
			_send_guide("in")
		KEY_D, KEY_RIGHT:
			_send_guide("out")
		KEY_S:
			_block_button.button_pressed = not _block_button.button_pressed


func _send_whip() -> void:
	if _since_tap < TAP_THROTTLE_S or not rider.riding():
		return
	_since_tap = 0.0
	if _rider_client().send_event("race:input", { "type": "whip" }):
		audio.oneshot("whip_crack")


func _send_guide(dir: String) -> void:
	if _since_tap < TAP_THROTTLE_S or not rider.riding():
		return
	_since_tap = 0.0
	_rider_client().send_event("race:input", { "type": "guide", "dir": dir })


func _send_block(on: bool) -> void:
	if not rider.riding():
		return
	_rider_client().send_event("race:input", { "type": "block", "on": on })


# ── Event fold ───────────────────────────────────────────────────────────────

func _on_connection_state(connection: String) -> void:
	super._on_connection_state(connection)
	# An invalid code gets auth:error then a hard server disconnect; on some
	# platforms the reset discards the buffered error frame, so surface a
	# generic line whenever we are dropped while still signed out.
	if connection == "disconnected" and not rider.signed_in() and not _rider_client().code.is_empty():
		_code_panel.visible = true
		var line := _code_error.text
		if line.is_empty():
			line = "The club turned us away. Check the code and try again."
		_restore_gate(line)


func _on_spectate_event(event_name: String, data: Variant) -> void:
	if training.apply(event_name, data):
		if not _abandoned_session.is_empty():
			if training.session_id == _abandoned_session:
				training.clear()
				return
			_abandoned_session = ""
		_refresh_training()
		return
	if rider.apply(event_name, data):
		match event_name:
			"auth:ok":
				_restore_gate("")
				_code_panel.visible = false
				_save_code(_rider_client().code)
				_stable_button.visible = true
			"auth:error":
				_code_panel.visible = true
				_restore_gate(rider.auth_error)
				_stable_button.visible = false
			"horses:update":
				# The race picture may have arrived before the stable list.
				rider.track_my_entry(state.entries_by_horse)
				_set_rider_hud_visible(rider.riding())
				if _stable_panel.visible:
					_refresh_stable()
			"races:update":
				if _stable_panel.visible:
					_refresh_stable()
			"toast":
				if _stable_panel.visible:
					_stable_status.text = str(rider.last_toast.get("message", ""))
		_refresh_rider_line()
		return
	super._on_spectate_event(event_name, data)
	match event_name:
		"spectate:hello", "race:phase":
			rider.track_my_entry(state.entries_by_horse)
			_set_rider_hud_visible(rider.riding())
			if rider.riding():
				# Race time: the stable waits.
				_stable_panel.visible = false
				_stable_button.visible = false
			elif rider.signed_in():
				_stable_button.visible = true
		"race:tick":
			rider.fold_tick(state.tick_horses)
			if typeof(data) == TYPE_DICTIONARY:
				_refresh_rider_line(rider.my_remaining_m(data))
			_energy_bar.value = rider.my_energy()


func _refresh_rider_line(remaining_m: float = -1.0) -> void:
	if not rider.riding():
		if rider.signed_in():
			_my_line.visible = true
			_my_line.text = "%s · the %s · waiting for your race" % [
				rider.stable_name(), CircusFactions.name_for(_faction_id),
			]
		return
	var entry := state.entry_for(rider.my_race_horse_id)
	var pieces: Array[String] = ["%s %s" % [str(entry.get("number", "")), str(entry.get("horseName", ""))]]
	if rider.my_rank() > 0:
		pieces.append("P%d" % rider.my_rank())
	if remaining_m >= 0.0:
		pieces.append("%dm to go" % int(remaining_m))
	if rider.my_finished():
		pieces.append("finished")
	_my_line.text = "  ·  ".join(pieces)


# ── Chase camera ─────────────────────────────────────────────────────────────

func _update_camera(delta: float) -> void:
	if not rider.riding() or not _horses.has(rider.my_race_horse_id):
		super._update_camera(delta)
		return
	var mine: Dictionary = _horses[rider.my_race_horse_id]
	var distance := state.race_distance()
	var s := TrackGeometry.start_offset(distance) + float(mine["pos"])
	var heading := TrackGeometry.heading_at(s)
	var outward := TrackGeometry.normal_at(s)
	var anchor := TrackGeometry.lane_point(s, float(mine["lane"]))
	var target_pos := anchor - heading * CHASE_BACK_M + outward * CHASE_SIDE_M + Vector3.UP * CHASE_UP_M
	_camera.position = _camera.position.lerp(target_pos, minf(1.0, 6.0 * delta))
	_camera.look_at(anchor + heading * 14.0 + Vector3.UP * 1.4, Vector3.UP)


func _process(delta: float) -> void:
	_since_tap += delta
	plate_hidden_id = rider.my_race_horse_id if rider.riding() else ""
	super._process(delta)
	_post_tick_s += delta
	if _post_tick_s >= 0.5:
		_post_tick_s = 0.0
		_update_post_line()


## At the gates the rider sits WITH their biga: a low three-quarter shot
## beside their own stall looking down the running line, instead of being
## parked behind the carceres staring at stall roofs.
func _place_gate_camera(delta: float) -> void:
	if not _horses.has(rider.my_race_horse_id):
		super._place_gate_camera(delta)
		return
	var mine: Dictionary = _horses[rider.my_race_horse_id]
	var start_s := TrackGeometry.start_offset(state.race_distance())
	var heading := TrackGeometry.heading_at(start_s)
	var outward := TrackGeometry.normal_at(start_s)
	var anchor := TrackGeometry.lane_point(start_s, float(mine["lane"]))
	var target := anchor + outward * 6.5 - heading * 5.0 + Vector3.UP * 2.6
	_camera.position = _camera.position.lerp(target, minf(1.0, 3.0 * delta))
	_camera.look_at(anchor + heading * 26.0 + Vector3.UP * 1.2, Vector3.UP)
