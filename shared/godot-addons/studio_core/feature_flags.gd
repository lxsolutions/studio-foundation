class_name StudioFeatureFlags
extends RefCounted
## Feature flags: project config defaults ("flags.<name>"), overridable per
## machine via environment (STUDIO_FLAG_<NAME>=1/0) for dev and CI.

var config: StudioConfig
var _overrides: Dictionary = {}


func _init(cfg: StudioConfig) -> void:
	config = cfg


func is_enabled(flag_name: String, default_value: bool = false) -> bool:
	if _overrides.has(flag_name):
		return bool(_overrides[flag_name])
	var env_value: String = OS.get_environment("STUDIO_FLAG_" + flag_name.to_upper())
	if not env_value.is_empty():
		return env_value == "1" or env_value.to_lower() == "true"
	return config.get_bool("flags." + flag_name, default_value)


## Runtime override (dev console); not persisted.
func set_override(flag_name: String, enabled: bool) -> void:
	_overrides[flag_name] = enabled


func clear_override(flag_name: String) -> void:
	_overrides.erase(flag_name)
