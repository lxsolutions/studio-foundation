extends StudioTestCase
## Input-map baseline actions + feature flags.


func test_actions_ensured() -> void:
	var input_map: StudioInputMap = StudioInputMap.new()
	input_map.ensure_actions()
	for action_name in StudioInputMap.ACTIONS.keys():
		assert_true(InputMap.has_action(action_name), "missing action " + str(action_name))
		assert_true(
			InputMap.action_get_events(action_name).size() > 0,
			"no bindings for " + str(action_name)
		)


func test_ensure_respects_existing_bindings() -> void:
	var custom: InputEventKey = InputEventKey.new()
	custom.physical_keycode = KEY_J
	if not InputMap.has_action("interact"):
		InputMap.add_action("interact")
	InputMap.action_erase_events("interact")
	InputMap.action_add_event("interact", custom)
	var input_map: StudioInputMap = StudioInputMap.new()
	input_map.ensure_actions()
	var events: Array[InputEvent] = InputMap.action_get_events("interact")
	assert_eq(events.size(), 1, "must not stack defaults onto existing bindings")


func test_flags_config_env_and_override() -> void:
	var config: StudioConfig = StudioConfig.new()
	config.project_values = {"flags.from_config": true}
	var flags: StudioFeatureFlags = StudioFeatureFlags.new(config)
	assert_true(flags.is_enabled("from_config"))
	assert_false(flags.is_enabled("unknown_flag"))
	assert_true(flags.is_enabled("unknown_flag", true), "default honored")

	OS.set_environment("STUDIO_FLAG_FROM_ENV", "1")
	assert_true(flags.is_enabled("from_env"))
	OS.set_environment("STUDIO_FLAG_FROM_ENV", "")

	flags.set_override("from_config", false)
	assert_false(flags.is_enabled("from_config"), "override wins")
	flags.clear_override("from_config")
	assert_true(flags.is_enabled("from_config"))
