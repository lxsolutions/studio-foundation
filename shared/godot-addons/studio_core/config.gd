class_name StudioConfig
extends RefCounted
## Layered configuration: res://studio.config.json (project defaults, committed)
## overlaid by user settings (user://settings.cfg). Keys are dotted strings
## ("net.api_base_url"). Never stores secrets.

const PROJECT_CONFIG_PATH: String = "res://studio.config.json"
const USER_SETTINGS_SECTION: String = "overrides"

var project_values: Dictionary = {}
var user_values: Dictionary = {}
var user_settings_path: String = "user://settings.cfg"


func load_all(project_path: String = PROJECT_CONFIG_PATH) -> void:
	project_values = _load_json(project_path)
	_load_user()


func _load_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var file: FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	return parsed if parsed is Dictionary else {}


func _load_user() -> void:
	user_values.clear()
	var cfg: ConfigFile = ConfigFile.new()
	if cfg.load(user_settings_path) != OK:
		return
	for key in cfg.get_section_keys(USER_SETTINGS_SECTION) if cfg.has_section(USER_SETTINGS_SECTION) else []:
		user_values[key] = cfg.get_value(USER_SETTINGS_SECTION, key)


func get_value(key: String, default_value: Variant = null) -> Variant:
	if user_values.has(key):
		return user_values[key]
	if project_values.has(key):
		return project_values[key]
	return default_value


func get_str(key: String, default_value: String = "") -> String:
	var value: Variant = get_value(key, default_value)
	return str(value)


func get_int(key: String, default_value: int = 0) -> int:
	var value: Variant = get_value(key, default_value)
	return int(value) if (value is int or value is float or (value is String and String(value).is_valid_int())) else default_value


func get_float(key: String, default_value: float = 0.0) -> float:
	var value: Variant = get_value(key, default_value)
	return float(value) if (value is int or value is float) else default_value


func get_bool(key: String, default_value: bool = false) -> bool:
	var value: Variant = get_value(key, default_value)
	return bool(value) if value is bool else default_value


func set_user(key: String, value: Variant) -> void:
	user_values[key] = value


func save_user() -> Error:
	var cfg: ConfigFile = ConfigFile.new()
	var _ignored: Error = cfg.load(user_settings_path) # keep unrelated sections
	for key in user_values.keys():
		cfg.set_value(USER_SETTINGS_SECTION, key, user_values[key])
	return cfg.save(user_settings_path)
