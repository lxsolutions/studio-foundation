extends StudioTestCase

## The AAA feature set is easy to configure and easy to configure into the void:
## under the Mobile renderer, Environment.ssao_enabled and friends are accepted
## and then silently ignored. These tests pin what each render tier actually
## asks for, so a regression shows up here rather than as "the game looks flat
## again" three weeks later.
##
## They run headless with no GPU: an Environment is a resource, so its settings
## can be asserted without ever rasterising a frame. Hardware verification that
## the features RENDER is a separate job and needs a real GPU.


func test_desktop_enables_the_full_feature_set() -> void:
	var env := CinematicEnv.build("desktop_high")
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
		var env := CinematicEnv.build(str(profile))
		assert_true(
			env.tonemap_mode != Environment.TONE_MAPPER_LINEAR,
			"%s must not ship a linear tonemap" % profile
		)


func test_lower_tiers_drop_the_expensive_effects() -> void:
	var webgl := CinematicEnv.build("browser_webgl")
	assert_false(webgl.ssao_enabled, "webgl cannot afford SSAO")
	assert_false(webgl.sdfgi_enabled, "webgl cannot afford SDFGI")
	assert_false(webgl.volumetric_fog_enabled, "webgl cannot afford volumetrics")

	var low := CinematicEnv.build("mobile_low")
	assert_false(low.glow_enabled, "the lowest tier drops bloom too")


func test_webgpu_keeps_occlusion_but_not_global_illumination() -> void:
	# The browser WebGPU tier is the interesting middle: it can afford contact
	# shadows and haze, which carry most of the look, but not SDFGI.
	var env := CinematicEnv.build("browser_webgpu")
	assert_true(env.ssao_enabled, "webgpu should keep ambient occlusion")
	assert_true(env.volumetric_fog_enabled, "webgpu should keep atmosphere")
	assert_false(env.sdfgi_enabled, "webgpu must not pay for SDFGI")
	assert_false(env.ssil_enabled, "webgpu must not pay for SSIL")


func test_unknown_profile_falls_back_to_the_safe_tier() -> void:
	var env := CinematicEnv.build("no_such_profile")
	assert_false(env.sdfgi_enabled, "an unknown profile must not enable the expensive path")
	assert_true(env.glow_enabled, "but it should still look better than nothing")


func test_sun_has_angular_size_where_soft_shadows_are_affordable() -> void:
	# A zero-size sun casts stencil-hard shadows, which reads as untextured no
	# matter how good the albedo is.
	var desktop := CinematicEnv.build_sun("desktop_high")
	assert_true(desktop.light_angular_distance > 0.0, "desktop sun needs a penumbra")
	assert_true(desktop.shadow_enabled, "the sun must cast")

	var low := CinematicEnv.build_sun("mobile_low")
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
