extends StudioTestCase
## Render-quality profiles: presence, schema, selection rules, budgets.

const EXPECTED: Array[String] = [
	"desktop_high", "browser_webgpu", "browser_webgl", "mobile_high", "mobile_low",
]


func _loaded() -> StudioRenderProfiles:
	var profiles: StudioRenderProfiles = StudioRenderProfiles.new()
	var ok: bool = profiles.load_profiles()
	assert_true(ok, "profiles.json must load")
	return profiles


func test_all_profiles_present_and_valid() -> void:
	var profiles: StudioRenderProfiles = _loaded()
	for name in EXPECTED:
		assert_has(profiles.profiles, name)
	assert_eq(profiles.validate(), [] as Array[String], "schema violations")


func test_auto_select_rules() -> void:
	var profiles: StudioRenderProfiles = _loaded()
	assert_eq(profiles.auto_select({"web": true, "webgpu": true}), "browser_webgpu")
	assert_eq(profiles.auto_select({"web": true, "webgpu": false}), "browser_webgl")
	assert_eq(profiles.auto_select({"mobile": true, "cpu_count": 8, "memory_mb": 6000}), "mobile_high")
	assert_eq(profiles.auto_select({"mobile": true, "cpu_count": 4, "memory_mb": 2000}), "mobile_low")
	assert_eq(profiles.auto_select({"desktop": true}), "desktop_high")


func test_apply_headless_and_budgets() -> void:
	var profiles: StudioRenderProfiles = _loaded()
	assert_true(profiles.apply("browser_webgl", null, {"headless": true}))
	assert_eq(profiles.current_name, "browser_webgl")
	assert_true(profiles.budget("particle_budget") > 0.0)
	assert_true(profiles.budget("particle_budget") < profiles.profiles["desktop_high"]["particle_budget"],
		"webgl budget must be below desktop")
	assert_false(profiles.flag("post_processing"), "webgl disables post")
	assert_false(profiles.apply("nonexistent", null, {}), "unknown profile rejected")
