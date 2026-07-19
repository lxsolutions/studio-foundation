extends Control
## Empty main menu: navigation shell only, no game mechanics. UI is built in
## code so the template stays diff-friendly; real games replace this scene.

var _studio: Node


func _ready() -> void:
	_studio = get_node("/root/Studio")
	var box: VBoxContainer = VBoxContainer.new()
	box.set_anchors_preset(Control.PRESET_CENTER)
	box.custom_minimum_size = Vector2(280, 0)
	box.add_theme_constant_override("separation", 12)
	add_child(box)

	var title: Label = Label.new()
	title.text = ProjectSettings.get_setting("application/config/name", "Game")
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 32)
	box.add_child(title)

	var version: Label = Label.new()
	version.text = _studio.build_info.describe()
	version.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	version.add_theme_font_size_override("font_size", 11)
	version.modulate = Color(1, 1, 1, 0.5)
	box.add_child(version)

	_button(box, "Play", func() -> void: _studio.router.go_to("res://scenes/game.tscn"))
	_button(box, "Settings", func() -> void: _studio.router.go_to("res://scenes/settings_menu.tscn"))
	if OS.is_debug_build() and _studio.flags.is_enabled("show_health_screen", true):
		_button(box, "Health (dev)", func() -> void: _studio.router.go_to("res://scenes/health_screen.tscn"))
	if not bool((_studio.get("platform") as Dictionary).get("web", false)):
		_button(box, "Quit", func() -> void: get_tree().quit())


func _button(parent: Container, label: String, on_pressed: Callable) -> void:
	var button: Button = Button.new()
	button.text = label
	button.custom_minimum_size = Vector2(0, 44)
	button.pressed.connect(on_pressed)
	parent.add_child(button)
