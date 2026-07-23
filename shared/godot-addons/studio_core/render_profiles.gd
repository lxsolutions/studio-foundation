class_name StudioRenderProfiles
extends RefCounted
## Runtime quality profiles. Platform differences are absorbed here —
## games query budgets (`budget("particle_budget")`) instead of sniffing platforms.

const PROFILES_PATH: String = "res://addons/studio_core/profiles.json"
const REQUIRED_KEYS: Array[String] = [
	"resolution_scale", "shadow_quality", "shadow_distance", "shadow_atlas_size",
	"texture_profile", "mesh_lod_bias", "vegetation_density", "particle_budget",
	"dynamic_light_budget", "anim_update_distance", "physics_detail",
	"post_processing", "msaa_3d", "actor_limit",
]

var profiles: Dictionary = {}
var current_name: String = ""
var current: Dictionary = {}


func load_profiles(path: String = PROFILES_PATH) -> bool:
	profiles = {}
	if not FileAccess.file_exists(path):
		return false
	var file: FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return false
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		profiles = parsed
	return not profiles.is_empty()


func validate() -> Array[String]:
	var problems: Array[String] = []
	for profile_name in profiles.keys():
		var profile: Dictionary = profiles[profile_name]
		for key in REQUIRED_KEYS:
			if not profile.has(key):
				problems.append("%s missing %s" % [profile_name, key])
	return problems


func auto_select(platform: Dictionary) -> String:
	if platform.get("web", false):
		return "browser_webgpu" if platform.get("webgpu", false) else "browser_webgl"
	if platform.get("mobile", false):
		var cpu: int = int(platform.get("cpu_count", 4))
		var mem: int = int(platform.get("memory_mb", 4096))
		return "mobile_high" if (cpu >= 6 and mem >= 3500) else "mobile_low"
	return "desktop_high"


## Applies what the engine can change at runtime; records the rest as budgets
## for game systems (vegetation, particles, actor caps) to consume.
func apply(profile_name: String, viewport: Viewport, platform: Dictionary = {}) -> bool:
	if not profiles.has(profile_name):
		return false
	current_name = profile_name
	current = profiles[profile_name]
	if viewport == null or platform.get("headless", false):
		return true # headless: budgets only
	viewport.scaling_3d_scale = float(current.get("resolution_scale", 1.0))
	var msaa: int = int(current.get("msaa_3d", 0))
	viewport.msaa_3d = clampi(msaa, 0, 3) as Viewport.MSAA
	var atlas: int = int(current.get("shadow_atlas_size", 2048))
	viewport.positional_shadow_atlas_size = atlas
	RenderingServer.directional_shadow_atlas_set_size(atlas, true)
	return true


func budget(key: String, default_value: float = 0.0) -> float:
	var value: Variant = current.get(key, default_value)
	return float(value) if (value is int or value is float) else default_value


func flag(key: String, default_value: bool = false) -> bool:
	var value: Variant = current.get(key, default_value)
	return bool(value) if value is bool else default_value
