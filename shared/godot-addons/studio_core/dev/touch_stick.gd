class_name StudioTouchStick
extends Control
## Minimal virtual joystick for touch platforms. Feeds the SAME input actions
## (move_left/right/up/down) via Input.action_press strength — game code never
## branches on touch. Add to any HUD; it hides itself on non-touch platforms.

@export var radius: float = 96.0
@export var dead_zone: float = 0.15

var _touch_index: int = -1
var _center: Vector2 = Vector2.ZERO
var _value: Vector2 = Vector2.ZERO


func _ready() -> void:
	custom_minimum_size = Vector2(radius, radius) * 2.0
	if not DisplayServer.is_touchscreen_available():
		visible = false
		set_process_input(false)


func _input(event: InputEvent) -> void:
	if event is InputEventScreenTouch:
		var touch: InputEventScreenTouch = event
		if touch.pressed and _touch_index == -1 and get_global_rect().has_point(touch.position):
			_touch_index = touch.index
			_center = touch.position
		elif not touch.pressed and touch.index == _touch_index:
			_touch_index = -1
			_apply(Vector2.ZERO)
	elif event is InputEventScreenDrag:
		var drag: InputEventScreenDrag = event
		if drag.index == _touch_index:
			var offset: Vector2 = (drag.position - _center) / radius
			_apply(offset.limit_length(1.0))


func _apply(value: Vector2) -> void:
	_value = value if value.length() > dead_zone else Vector2.ZERO
	Input.action_press("move_right", maxf(_value.x, 0.0))
	Input.action_press("move_left", maxf(-_value.x, 0.0))
	Input.action_press("move_down", maxf(_value.y, 0.0))
	Input.action_press("move_up", maxf(-_value.y, 0.0))
	if _value == Vector2.ZERO:
		for action in ["move_left", "move_right", "move_up", "move_down"]:
			Input.action_release(action)


func _draw() -> void:
	if not visible:
		return
	var center_local: Vector2 = size / 2.0
	draw_circle(center_local, radius, Color(1, 1, 1, 0.08))
	draw_circle(center_local + _value * radius * 0.6, radius * 0.25, Color(1, 1, 1, 0.25))
