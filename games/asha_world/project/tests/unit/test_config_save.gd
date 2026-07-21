extends StudioTestCase
## Configuration loading + save-data interface (serialization tests).


func test_config_layering_and_types() -> void:
	var config: StudioConfig = StudioConfig.new()
	config.user_settings_path = "user://test_settings.cfg"
	config.load_all("res://studio.config.json")
	assert_eq(config.get_str("game.id", ""), "asha_world")
	assert_eq(config.get_int("missing.key", 42), 42)
	assert_eq(config.get_bool("flags.show_health_screen", false), true)

	config.set_user("net.api_base_url", "http://127.0.0.1:9999")
	assert_eq(config.get_str("net.api_base_url", ""), "http://127.0.0.1:9999", "user layer wins")
	assert_eq(config.save_user(), OK)

	var reloaded: StudioConfig = StudioConfig.new()
	reloaded.user_settings_path = "user://test_settings.cfg"
	reloaded.load_all("res://studio.config.json")
	assert_eq(reloaded.get_str("net.api_base_url", ""), "http://127.0.0.1:9999", "persisted override")
	DirAccess.remove_absolute("user://test_settings.cfg")


func test_save_roundtrip_and_slots() -> void:
	var saves: StudioSaveData = StudioSaveData.new()
	saves.save_dir = "user://test_saves"
	var payload: Dictionary = {"level": 3, "gold": 120.0, "name": "tester"}
	assert_eq(saves.save_slot("slot_a", payload), OK)
	assert_eq(saves.load_slot("slot_a"), payload, "roundtrip")
	assert_true(saves.list_slots().has("slot_a"))
	saves.delete_slot("slot_a")
	assert_false(saves.list_slots().has("slot_a"))
	assert_eq(saves.load_slot("slot_a"), {}, "missing slot loads empty")


func test_save_rejects_newer_schema() -> void:
	var saves: StudioSaveData = StudioSaveData.new()
	saves.save_dir = "user://test_saves"
	DirAccess.make_dir_recursive_absolute(saves.save_dir)
	var file: FileAccess = FileAccess.open(saves.slot_path("future"), FileAccess.WRITE)
	file.store_string(JSON.stringify({"schema_version": 999, "data": {"x": 1}}))
	file.close()
	assert_eq(saves.load_slot("future"), {}, "newer schema must not load")
	saves.delete_slot("future")
