extends Control
## Default settings screen wired to studio_core systems: render profile,
## audio volumes, vsync, accessibility. Persistence goes through StudioConfig.

var _studio: Node


func _ready() -> void:
	_studio = get_node("/root/Studio")
	var box: VBoxContainer = VBoxContainer.new()
	box.set_anchors_preset(Control.PRESET_CENTER)
	box.custom_minimum_size = Vector2(360, 0)
	box.add_theme_constant_override("separation", 10)
	add_child(box)

	_label(box, "Settings", 26)

	_label(box, "Quality profile", 14)
	var profile_picker: OptionButton = OptionButton.new()
	var names: Array = _studio.profiles.profiles.keys()
	names.sort()
	for i in names.size():
		profile_picker.add_item(str(names[i]), i)
		if str(names[i]) == str(_studio.profiles.current_name):
			profile_picker.select(i)
	profile_picker.item_selected.connect(func(index: int) -> void:
		var chosen: String = profile_picker.get_item_text(index)
		_studio.profiles.apply(chosen, get_viewport(), _studio.get("platform"))
		_studio.graphics.set_and_save("profile", chosen, get_window()))
	box.add_child(profile_picker)

	for bus in ["Master", "Music", "SFX", "UI"]:
		_volume_slider(box, bus)

	_check(box, "V-Sync", _studio.graphics.vsync, func(on: bool) -> void:
		_studio.graphics.set_and_save("vsync", on, get_window()))
	_check(box, "Reduce motion", _studio.accessibility.reduce_motion, func(on: bool) -> void:
		_studio.accessibility.set_and_save("reduce_motion", on, get_tree()))
	_check(box, "Subtitles", _studio.accessibility.subtitles, func(on: bool) -> void:
		_studio.accessibility.set_and_save("subtitles", on))

	var back: Button = Button.new()
	back.text = "Back"
	back.custom_minimum_size = Vector2(0, 44)
	back.pressed.connect(func() -> void: _studio.router.go_to("res://scenes/main_menu.tscn"))
	box.add_child(back)


func _label(parent: Container, text: String, size: int) -> void:
	var label: Label = Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", size)
	parent.add_child(label)


func _volume_slider(parent: Container, bus: String) -> void:
	_label(parent, bus + " volume", 14)
	var slider: HSlider = HSlider.new()
	slider.min_value = 0.0
	slider.max_value = 1.0
	slider.step = 0.05
	slider.value = _studio.audio.get_volume(bus)
	slider.value_changed.connect(func(value: float) -> void:
		_studio.audio.set_volume(bus, value)
		_studio.audio.save())
	parent.add_child(slider)


func _check(parent: Container, text: String, initial: bool, on_toggle: Callable) -> void:
	var check: CheckBox = CheckBox.new()
	check.text = text
	check.button_pressed = initial
	check.toggled.connect(on_toggle)
	parent.add_child(check)
