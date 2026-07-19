class_name StudioAccessibility
extends RefCounted
## Accessibility settings: persisted via StudioConfig, applied engine-wide.
## Game systems must query `reduce_motion`/`screen_shake` etc. before effects.

var config: StudioConfig


func _init(cfg: StudioConfig) -> void:
	config = cfg


var ui_scale: float:
	get:
		return config.get_float("a11y.ui_scale", 1.0)

var reduce_motion: bool:
	get:
		return config.get_bool("a11y.reduce_motion", false)

var screen_shake: bool:
	get:
		return config.get_bool("a11y.screen_shake", true)

var subtitles: bool:
	get:
		return config.get_bool("a11y.subtitles", true)

var colorblind_mode: String:
	get:
		return config.get_str("a11y.colorblind_mode", "off")


func set_and_save(key: String, value: Variant, tree: SceneTree = null) -> void:
	config.set_user("a11y." + key, value)
	config.save_user()
	if tree != null:
		apply(tree)


func apply(tree: SceneTree) -> void:
	if tree == null or tree.root == null:
		return
	tree.root.content_scale_factor = clampf(ui_scale, 0.75, 2.0)
