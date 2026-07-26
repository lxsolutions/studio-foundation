class_name CinematicEnv
extends RefCounted

## The AAA half of "looks like Gladiator".
##
## Assets are only half of it. The venue had good geometry, correct materials
## and 53,000 spectators, and still looked flat — because the scene shipped a
## sky, an ambient term and one directional light, with NO tonemapping, no
## ambient occlusion, no indirect light, no bloom and no atmosphere. A linear
## tonemap alone is why the stone read as chalk.
##
## Everything here is what actually produces the Diablo-IV/Gladiator look:
##
##   TONEMAP      Linear (the default) clips highlights and washes midtones.
##                ACES/AgX is the single biggest one-line improvement.
##   SSAO         Contact darkening where surfaces meet. This is what makes a
##                crowd sit IN the stands instead of floating on them, and what
##                gives 44,000 instanced figures visual weight.
##   SSIL         Indirect bounce. Sunlit sand kicking warm light up into the
##                shaded side of the spina is most of the "expensive" look.
##   GLOW         Sun bloom and emissive torches reading as light sources.
##   VOLUMETRIC   Air. Haze picks out shafts between the arcade columns and
##     FOG        separates the near stands from the far ones across 700 m.
##   SDFGI        Real-time GI. Desktop only; it is expensive.
##
## Every feature is gated on the active render profile AND on what the live
## renderer can actually do. Forward+ is required for SSAO/SSIL/SDFGI — under
## the Mobile renderer those calls are silently ignored, and volumetric fog on
## the Compatibility renderer is worse than ignored: it ERRORS every build
## (environment_set_volumetric_fog), which a QA capture over ANGLE runs into
## immediately. Wanting a feature (TIERS) and having it (METHOD_CAPS) are
## different facts; the environment asks for their intersection.

## Feature sets per profile. Anything absent is simply off for that tier.
const TIERS := {
	"desktop_high": {
		"ssao": true, "ssil": true, "sdfgi": true, "volumetric": true,
		"glow": true, "ssr": true, "shadow_soft": true,
	},
	"browser_webgpu": {
		"ssao": true, "ssil": false, "sdfgi": false, "volumetric": true,
		"glow": true, "ssr": false, "shadow_soft": true,
	},
	"browser_webgl": {
		"ssao": false, "ssil": false, "sdfgi": false, "volumetric": false,
		"glow": true, "ssr": false, "shadow_soft": false,
	},
	"mobile_high": {
		"ssao": false, "ssil": false, "sdfgi": false, "volumetric": false,
		"glow": true, "ssr": false, "shadow_soft": false,
	},
	"mobile_low": {
		"ssao": false, "ssil": false, "sdfgi": false, "volumetric": false,
		"glow": false, "ssr": false, "shadow_soft": false,
	},
}


## What each rendering method HAS, independent of what a profile WANTS.
## Mobile supports bloom and penumbra suns but none of the screen-space or GI
## features; Compatibility keeps bloom only (4.3+). Anything else — the dummy
## renderer under --headless, or a method this table has never heard of —
## gets nothing fancy, which is the safe reading.
const METHOD_CAPS := {
	"forward_plus": {
		"ssao": true, "ssil": true, "sdfgi": true, "volumetric": true,
		"glow": true, "ssr": true, "shadow_soft": true,
	},
	"mobile": {"glow": true, "shadow_soft": true},
	"gl_compatibility": {"glow": true},
}


static func features_for(profile: String) -> Dictionary:
	return TIERS.get(profile, TIERS["browser_webgl"])


## The intersection of what `profile` wants and what `method` can render.
static func effective_features(profile: String, method: String) -> Dictionary:
	var wanted := features_for(profile)
	var caps: Dictionary = METHOD_CAPS.get(method, {})
	var out := {}
	for key in wanted:
		out[key] = bool(wanted[key]) and bool(caps.get(key, false))
	return out


static func _live_method() -> String:
	return RenderingServer.get_current_rendering_method()


## Build the Environment for a sunlit Mediterranean afternoon.
## `method` defaults to the live renderer; tests pass one explicitly because
## headless runs report a method with no capabilities at all.
static func build(profile: String, method: String = "") -> Environment:
	var features := effective_features(profile, method if not method.is_empty() else _live_method())
	var env := Environment.new()

	var sky := Sky.new()
	var sky_material := ProceduralSkyMaterial.new()
	sky_material.sky_top_color = Color(0.216, 0.404, 0.729)
	sky_material.sky_horizon_color = Color(0.855, 0.808, 0.686)
	sky_material.ground_bottom_color = Color(0.318, 0.271, 0.208)
	sky_material.ground_horizon_color = Color(0.706, 0.639, 0.514)
	# A visible sun disc gives the bloom something to bloom from.
	sky_material.sun_angle_max = 12.0
	sky_material.energy_multiplier = 1.0
	sky.sky_material = sky_material
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	# Measured, not guessed: at 0.75 the venue read at 0.58 linear mean with
	# near-white stone (check.image on an in-game capture), against ~0.20 for a
	# properly exposed scene. Ambient this strong is also what removes every
	# shadow and makes a 700 m building look like a flat card.
	env.ambient_light_energy = 0.35
	env.reflected_light_source = Environment.REFLECTION_SOURCE_SKY

	# --- tonemapping: the single biggest one-line win -------------------
	env.tonemap_mode = Environment.TONE_MAPPER_ACES
	# 0.72, not 1.0: a Forward+ hardware capture measured 0.357 linear mean
	# against ~0.20 for a properly exposed scene. Pale limestone under a midday
	# sun sits high by nature, so the venue needs pulling down rather than the
	# albedo being darkened away from what travertine actually is.
	env.tonemap_exposure = 0.72
	env.tonemap_white = 6.0

	# --- contact shadows ------------------------------------------------
	if features.get("ssao", false):
		env.ssao_enabled = true
		env.ssao_radius = 1.4
		env.ssao_intensity = 2.6
		env.ssao_power = 1.6
		env.ssao_detail = 0.6
		env.ssao_horizon = 0.08
		env.ssao_light_affect = 0.15

	# --- indirect bounce -------------------------------------------------
	if features.get("ssil", false):
		env.ssil_enabled = true
		env.ssil_radius = 6.0
		env.ssil_intensity = 1.1
		env.ssil_sharpness = 0.98
		env.ssil_normal_rejection = 1.0

	if features.get("ssr", false):
		env.ssr_enabled = true
		env.ssr_max_steps = 32
		env.ssr_fade_in = 0.2
		env.ssr_fade_out = 2.0

	# --- global illumination ---------------------------------------------
	if features.get("sdfgi", false):
		env.sdfgi_enabled = true
		env.sdfgi_use_occlusion = true
		env.sdfgi_bounce_feedback = 0.5
		env.sdfgi_cascades = 4
		env.sdfgi_min_cell_size = 0.4
		env.sdfgi_energy = 1.0

	# --- bloom ------------------------------------------------------------
	if features.get("glow", false):
		env.glow_enabled = true
		env.glow_intensity = 0.5
		env.glow_strength = 1.0
		env.glow_bloom = 0.08
		env.glow_blend_mode = Environment.GLOW_BLEND_MODE_SOFTLIGHT
		env.glow_hdr_threshold = 1.1
		env.glow_hdr_scale = 2.0

	# --- atmosphere --------------------------------------------------------
	if features.get("volumetric", false):
		env.volumetric_fog_enabled = true
		# VERY thin. A hippodrome is 700 m long, so density compounds fast: at
		# 0.008 a hardware capture came back with the sky fogged to solid tan and
		# every form flattened. 0.002 still separates the near stands from the
		# far ones without eating the scene.
		env.volumetric_fog_density = 0.002
		env.volumetric_fog_albedo = Color(0.94, 0.89, 0.79)
		env.volumetric_fog_emission = Color(0.10, 0.09, 0.07)
		env.volumetric_fog_emission_energy = 0.4
		env.volumetric_fog_anisotropy = 0.35
		env.volumetric_fog_length = 512.0
		env.volumetric_fog_gi_inject = 1.0

	# --- grade -------------------------------------------------------------
	env.adjustment_enabled = true
	env.adjustment_contrast = 1.06
	env.adjustment_saturation = 1.10
	env.adjustment_brightness = 1.0

	return env


## The sun. Angular size is what gives shadows a real penumbra; a zero-size
## sun produces the hard stencil edges that make a scene look untextured.
static func build_sun(profile: String, method: String = "") -> DirectionalLight3D:
	var features := effective_features(profile, method if not method.is_empty() else _live_method())
	var sun := DirectionalLight3D.new()
	sun.name = "Sun"
	sun.rotation_degrees = Vector3(-48.0, -32.0, 0.0)
	sun.light_color = Color(1.0, 0.945, 0.855)
	sun.light_energy = 1.35
	sun.light_indirect_energy = 1.2
	sun.shadow_enabled = true
	sun.shadow_bias = 0.04
	sun.shadow_normal_bias = 1.4
	sun.directional_shadow_max_distance = 400.0
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_4_SPLITS
	sun.directional_shadow_blend_splits = true
	if features.get("shadow_soft", false):
		sun.light_angular_distance = 0.6
	return sun
