class_name StudioGraphicsSettings
extends RefCounted
## User-facing graphics settings (window mode, vsync, fps cap, profile
## override). Quality itself lives in StudioRenderProfiles; this persists the
## user's choices and applies window-level toggles.

var config: StudioConfig


func _init(cfg: StudioConfig) -> void:
	config = cfg


var window_mode: String:
	get:
		return config.get_str("graphics.window_mode", "windowed")

var vsync: bool:
	get:
		return config.get_bool("graphics.vsync", true)

var fps_cap: int:
	get:
		return config.get_int("graphics.fps_cap", 0)

var profile_override: String:
	get:
		return config.get_str("graphics.profile", "")


func set_and_save(key: String, value: Variant, window: Window = null) -> void:
	config.set_user("graphics." + key, value)
	config.save_user()
	apply(window)


func apply(window: Window) -> void:
	Engine.max_fps = maxi(fps_cap, 0)
	DisplayServer.window_set_vsync_mode(
		DisplayServer.VSYNC_ENABLED if vsync else DisplayServer.VSYNC_DISABLED
	)
	if window == null:
		return
	match window_mode:
		"fullscreen":
			window.mode = Window.MODE_FULLSCREEN
		"borderless":
			window.mode = Window.MODE_MAXIMIZED
			window.borderless = true
		_:
			window.borderless = false
			window.mode = Window.MODE_WINDOWED
