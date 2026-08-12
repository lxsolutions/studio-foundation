class_name StandsView
extends BroadcastView

## The stands are the web export's front door. A rider with a Plaza handoff
## token or a remembered owner code never sees them: boot walks them straight
## to the rider's gate (rider_view consumes the token and scrubs the URL).
## Everyone else watches the broadcast, with the reins one tap away.

const RIDER_SCENE := "res://scenes/rider.tscn"

## Tests pin this false to exercise the broadcast without boot routing.
var boot_route_enabled := true

## The challenge-ghost arm for spectators: a ?ghost=<id> link loads over the
## studio bridge (tokenless — a ghost is public to anyone holding the id) and
## replays on the sand, the local store as the fallback.
var ghost_store: GhostStore = GhostStore.new()
var _studio: StudioClient = null


func _ready() -> void:
	if boot_route_enabled and FrontGate.boot_destination(
		WebHandoff.token_waiting(), not AuthStore.saved_code().is_empty()
	) == FrontGate.DEST_RIDER:
		set_process(false)
		_switch_scene(RIDER_SCENE)
		return
	super()
	_build_reins_door()
	_studio = StudioClient.new()
	_studio.name = "StudioClient"
	add_child(_studio)
	ghost_store.transport = _studio.transport_mapping
	await _boot_ghost_challenge()


## The inbound half of a shared challenge: read the id out of the URL
## (scrubbing it like the handoff token), load the run, arm it. A miss stays
## quiet — the stands simply show the exhibition.
func _boot_ghost_challenge() -> void:
	var ghost_id := WebHandoff.take_ghost_id()
	if ghost_id.is_empty():
		return
	var run := await ghost_store.load_ghost(ghost_id)
	if run != null:
		arm_ghost(run)


func _build_reins_door() -> void:
	var door := PanelContainer.new()
	door.name = "ReinsDoor"
	door.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	door.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	door.position += Vector2(-12.0, _door_y())
	door.self_modulate = Color(0.071, 0.063, 0.043, 0.82)
	(get_node("Hud") as CanvasLayer).add_child(door)
	var button := Button.new()
	button.name = "TakeTheReins"
	button.text = "Take the reins"
	# The door into the whole game: the QA gate measured it at 10 physical px
	# on a phone. 60 design units clears the 44 px touch floor at the scale
	# StudioUiScale settles on for a 390 px window.
	button.custom_minimum_size = Vector2(0.0, 60.0)
	button.add_theme_font_size_override("font_size", 18)
	button.add_theme_color_override("font_color", Color(0.957, 0.808, 0.463))
	button.pressed.connect(func() -> void: _switch_scene(RIDER_SCENE))
	button.add_to_group("qa_hud")
	button.add_to_group("qa_tap")
	door.add_child(button)


## On a phone-width canvas the centered title panel and this door collide at
## the top edge (seen on a 390 px capture), so the door drops below the panel
## there. Computed at build time: the canvas width for a session is set by
## the window it opened in.
func _door_y() -> float:
	return 100.0 if get_viewport().get_visible_rect().size.x < 660.0 else 12.0
