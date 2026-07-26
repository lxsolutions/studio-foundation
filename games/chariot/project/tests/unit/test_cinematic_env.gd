extends StudioTestCase

## The AAA feature set is easy to configure and easy to configure into the void:
## under the Mobile renderer, Environment.ssao_enabled and friends are accepted
## and then silently ignored — and volumetric fog on the Compatibility renderer
## ERRORS on every build. These tests pin what each render tier actually asks
## for, AND that a feature is only requested where the live renderer can honour
## it, so a regression shows up here rather than as "the game looks flat again"
## three weeks later.
##
## They run headless with no GPU: an Environment is a resource, so its settings
## can be asserted without ever rasterising a frame. Every build() call passes
## the renderer method explicitly because the headless dummy has no
## capabilities at all — which is itself pinned below. Hardware verification
## that the features RENDER is a separate job and needs a real GPU.


func test_desktop_enables_the_full_feature_set() -> void:
	var env := CinematicEnv.build("desktop_high", "forward_plus")
	assert_true(env.ssao_enabled, "desktop must have ambient occlusion")
	assert_true(env.ssil_enabled, "desktop must have indirect bounce")
	assert_true(env.sdfgi_enabled, "desktop must have global illumination")
	assert_true(env.volumetric_fog_enabled, "desktop must have atmosphere")
	assert_true(env.glow_enabled, "desktop must have bloom")


func test_tonemapping_is_never_linear() -> void:
	# A linear tonemap clips highlights and washes midtones. It is the single
	# biggest reason correct geometry and correct materials still look like
	# chalk, and it is the default.
	for profile in CinematicEnv.TIERS.keys():
		var env := CinematicEnv.build(str(profile), "forward_plus")
		assert_true(
			env.tonemap_mode != Environment.TONE_MAPPER_LINEAR,
			"%s must not ship a linear tonemap" % profile
		)


func test_lower_tiers_drop_the_expensive_effects() -> void:
	var webgl := CinematicEnv.build("browser_webgl", "forward_plus")
	assert_false(webgl.ssao_enabled, "webgl cannot afford SSAO")
	assert_false(webgl.sdfgi_enabled, "webgl cannot afford SDFGI")
	assert_false(webgl.volumetric_fog_enabled, "webgl cannot afford volumetrics")

	var low := CinematicEnv.build("mobile_low", "forward_plus")
	assert_false(low.glow_enabled, "the lowest tier drops bloom too")


func test_webgpu_keeps_occlusion_but_not_global_illumination() -> void:
	# The browser WebGPU tier is the interesting middle: it can afford contact
	# shadows and haze, which carry most of the look, but not SDFGI.
	var env := CinematicEnv.build("browser_webgpu", "forward_plus")
	assert_true(env.ssao_enabled, "webgpu should keep ambient occlusion")
	assert_true(env.volumetric_fog_enabled, "webgpu should keep atmosphere")
	assert_false(env.sdfgi_enabled, "webgpu must not pay for SDFGI")
	assert_false(env.ssil_enabled, "webgpu must not pay for SSIL")


func test_unknown_profile_falls_back_to_the_safe_tier() -> void:
	var env := CinematicEnv.build("no_such_profile", "forward_plus")
	assert_false(env.sdfgi_enabled, "an unknown profile must not enable the expensive path")
	assert_true(env.glow_enabled, "but it should still look better than nothing")


func test_compatibility_renderer_is_never_asked_for_what_it_lacks() -> void:
	# The Compatibility renderer does not just ignore volumetric fog — it
	# errors on every environment build. A desktop_high profile forced onto it
	# (a GPU-less QA capture over ANGLE) must degrade, not spam.
	var env := CinematicEnv.build("desktop_high", "gl_compatibility")
	assert_false(env.volumetric_fog_enabled, "no volumetrics on Compatibility")
	assert_false(env.ssao_enabled, "no SSAO on Compatibility")
	assert_false(env.sdfgi_enabled, "no SDFGI on Compatibility")
	assert_true(env.glow_enabled, "bloom survives — Compatibility has it")


func test_mobile_method_drops_the_screen_space_features() -> void:
	# The renderer handbrake, stated as capability: Forward Mobile accepts the
	# SSAO/volumetric setters and ignores them, so asking is a lie the report
	# would repeat. The intersection must say no.
	var features := CinematicEnv.effective_features("browser_webgpu", "mobile")
	assert_false(bool(features["ssao"]), "mobile method cannot SSAO")
	assert_false(bool(features["volumetric"]), "mobile method cannot volumetric fog")
	assert_true(bool(features["glow"]), "mobile method keeps bloom")


func test_headless_dummy_gets_nothing_fancy() -> void:
	# --headless reports a method METHOD_CAPS has never heard of; the safe
	# reading is no capabilities, so audits never ask a dummy renderer for fog.
	var features := CinematicEnv.effective_features("desktop_high", "dummy")
	for key in features:
		assert_false(bool(features[key]), "dummy renderer must get no '%s'" % key)


func test_sun_has_angular_size_where_soft_shadows_are_affordable() -> void:
	# A zero-size sun casts stencil-hard shadows, which reads as untextured no
	# matter how good the albedo is.
	var desktop := CinematicEnv.build_sun("desktop_high", "forward_plus")
	assert_true(desktop.light_angular_distance > 0.0, "desktop sun needs a penumbra")
	assert_true(desktop.shadow_enabled, "the sun must cast")

	var low := CinematicEnv.build_sun("mobile_low", "forward_plus")
	assert_eq(low.light_angular_distance, 0.0, "the lowest tier uses hard shadows")


func test_every_profile_in_profiles_json_has_a_tier() -> void:
	# A profile with no entry silently gets the fallback, which is how a
	# platform quietly loses its whole feature set.
	var profiles := StudioRenderProfiles.new()
	assert_true(profiles.load_profiles(), "profiles.json must load")
	for name in profiles.profiles.keys():
		assert_true(
			CinematicEnv.TIERS.has(name),
			"render profile '%s' has no cinematic tier" % name
		)
