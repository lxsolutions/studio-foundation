extends Node
## The `Studio` autoload: composes every studio_core subsystem and runs the boot
## sequence. Subsystems are plain RefCounted objects (constructible without the
## scene tree) so headless tests can exercise them directly.

signal boot_completed
signal boot_failed(reason: String)

var log: StudioLog = StudioLog.new()
var config: StudioConfig = StudioConfig.new()
var build_info: StudioBuildInfo = StudioBuildInfo.new()
var platform: Dictionary = {}
var profiles: StudioRenderProfiles = StudioRenderProfiles.new()
var input_map: StudioInputMap = StudioInputMap.new()
var flags: StudioFeatureFlags
var rng: StudioRng = StudioRng.new()
var save_data: StudioSaveData = StudioSaveData.new()
var i18n: StudioLocalization = StudioLocalization.new()
var accessibility: StudioAccessibility
var audio: StudioAudioSettings
var graphics: StudioGraphicsSettings
var crash: StudioCrashReport
var content: StudioContentManifest = StudioContentManifest.new()
var assets: StudioAssetManifest = StudioAssetManifest.new()
var replay: StudioReplay = StudioReplay.new()
var api: StudioApiClient
var session: StudioSession
var net: StudioTransport = null # active transport, if any
var router: StudioSceneRouter

var booted: bool = false
var _console: CanvasLayer = null
var _overlay: CanvasLayer = null


func _ready() -> void:
	boot()


func boot() -> void:
	if booted:
		return
	# Order matters: config -> platform -> profile -> subsystems that read them.
	config.load_all()
	log.min_level = StudioLog.Level.DEBUG if OS.is_debug_build() else StudioLog.Level.INFO
	build_info.load_info()
	platform = StudioPlatform.detect()
	crash = StudioCrashReport.new(log)
	crash.install()
	flags = StudioFeatureFlags.new(config)
	profiles.load_profiles()
	var profile_name: String = config.get_str("graphics.profile", "")
	if profile_name.is_empty():
		profile_name = profiles.auto_select(platform)
	profiles.apply(profile_name, get_viewport(), platform)
	input_map.ensure_actions()
	rng.set_run_seed(int(config.get_int("debug.fixed_seed", 0)))
	i18n.initialize(config.get_str("i18n.default_locale", "en"))
	accessibility = StudioAccessibility.new(config)
	accessibility.apply(get_tree())
	audio = StudioAudioSettings.new(config)
	audio.apply()
	graphics = StudioGraphicsSettings.new(config)
	graphics.apply(get_window() if not platform.get("headless", false) else null)
	content.load_manifest()
	assets.load_manifest()
	api = StudioApiClient.new(self, config.get_str("net.api_base_url", "http://127.0.0.1:8080"))
	session = StudioSession.new(api, log)
	router = StudioSceneRouter.new(self)
	if OS.is_debug_build() and not platform.get("headless", false):
		_install_dev_tools()
	booted = true
	log.info("studio", "boot completed", {
		"version": build_info.version,
		"platform": platform.get("os", "?"),
		"profile": profiles.current_name,
	})
	boot_completed.emit()


func _install_dev_tools() -> void:
	var console_scene: GDScript = load("res://addons/studio_core/dev/dev_console.gd")
	var overlay_scene: GDScript = load("res://addons/studio_core/dev/perf_overlay.gd")
	if console_scene != null:
		_console = console_scene.new()
		add_child(_console)
	if overlay_scene != null:
		_overlay = overlay_scene.new()
		add_child(_overlay)


func _process(_delta: float) -> void:
	if net != null:
		net.poll()
