class_name StudioPlatform
extends RefCounted
## Platform detection. THE single place that answers "where are we running?".
## Game code must branch on this (or on render profiles) — never on raw
## OS.get_name() checks scattered through gameplay, and never on fork-only APIs
## (ADR 0002).


static func detect() -> Dictionary:
	var os_name: String = OS.get_name()
	var headless: bool = DisplayServer.get_name() == "headless"
	var web: bool = OS.has_feature("web")
	var mobile: bool = os_name == "Android" or os_name == "iOS"
	var driver: String = ""
	if not headless:
		driver = str(ProjectSettings.get_setting_with_override("rendering/rendering_device/driver"))
		var method: String = str(RenderingServer.get_current_rendering_method())
		if not method.is_empty():
			driver = method + "/" + RenderingServer.get_current_rendering_driver_name()
	var webgpu: bool = web and driver.findn("webgpu") != -1
	return {
		"os": os_name,
		"headless": headless,
		"web": web,
		"webgpu": webgpu,
		"mobile": mobile,
		"desktop": not web and not mobile,
		"touch": DisplayServer.is_touchscreen_available() if not headless else false,
		"driver": driver,
		"cpu_count": OS.get_processor_count(),
		"memory_mb": int(OS.get_memory_info().get("physical", 0) / 1048576.0),
		"debug_build": OS.is_debug_build(),
	}
