class_name StudioInputMap
extends RefCounted
## Input abstraction: one canonical action set across keyboard/mouse, gamepad,
## and touch. Actions are ensured at runtime so shared code can rely on them
## even in projects that forgot to declare one. Games add their own actions in
## project settings; these are the studio-wide baseline.

const ACTIONS: Dictionary = {
	"move_left": {"keys": [KEY_A, KEY_LEFT], "axis": [JOY_AXIS_LEFT_X, -1.0]},
	"move_right": {"keys": [KEY_D, KEY_RIGHT], "axis": [JOY_AXIS_LEFT_X, 1.0]},
	"move_up": {"keys": [KEY_W, KEY_UP], "axis": [JOY_AXIS_LEFT_Y, -1.0]},
	"move_down": {"keys": [KEY_S, KEY_DOWN], "axis": [JOY_AXIS_LEFT_Y, 1.0]},
	"interact": {"keys": [KEY_E, KEY_ENTER], "buttons": [JOY_BUTTON_A]},
	"pause": {"keys": [KEY_ESCAPE], "buttons": [JOY_BUTTON_START]},
	"dev_console": {"keys": [KEY_F12]},
	"dev_perf_overlay": {"keys": [KEY_F11]},
}

## Touch input arrives through StudioTouchStick (see dev/touch_stick.gd), which
## injects the same actions via Input.action_press — no game code branches.


func ensure_actions() -> void:
	for action_name in ACTIONS.keys():
		var spec: Dictionary = ACTIONS[action_name]
		if not InputMap.has_action(action_name):
			InputMap.add_action(action_name)
		if not InputMap.action_get_events(action_name).is_empty():
			continue # project already bound it; respect project settings
		var keys: Array = spec.get("keys", [])
		for key in keys:
			var key_event: InputEventKey = InputEventKey.new()
			key_event.physical_keycode = key
			InputMap.action_add_event(action_name, key_event)
		var buttons: Array = spec.get("buttons", [])
		for button in buttons:
			var pad_event: InputEventJoypadButton = InputEventJoypadButton.new()
			pad_event.button_index = button
			InputMap.action_add_event(action_name, pad_event)
		var axis: Array = spec.get("axis", [])
		if axis.size() == 2:
			var motion: InputEventJoypadMotion = InputEventJoypadMotion.new()
			motion.axis = axis[0]
			motion.axis_value = axis[1]
			InputMap.action_add_event(action_name, motion)


## Unified planar movement (WASD / left stick / touch stick all included).
static func move_vector() -> Vector2:
	return Input.get_vector("move_left", "move_right", "move_up", "move_down")
