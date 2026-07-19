class_name StudioCrashReport
extends RefCounted
## Crash/error reporting interface. Default sink: breadcrumb ring + a local
## user:// report file. No telemetry leaves the machine — a future opt-in
## uploader implements `submit()` behind explicit user consent (see
## docs/security/). Game code calls breadcrumb()/capture(); it never cares
## where reports go.

const REPORT_PATH: String = "user://crash/last_run.json"
const BREADCRUMB_MAX: int = 100

var log: StudioLog
var breadcrumbs: Array[Dictionary] = []
var installed: bool = false


func _init(logger: StudioLog) -> void:
	log = logger


func install() -> void:
	installed = true
	breadcrumb("crash-report installed")


func breadcrumb(message: String, data: Dictionary = {}) -> void:
	breadcrumbs.append({
		"frame": Engine.get_process_frames(),
		"msg": message,
		"data": data,
	})
	if breadcrumbs.size() > BREADCRUMB_MAX:
		breadcrumbs.pop_front()


func capture(kind: String, message: String, extra: Dictionary = {}) -> void:
	log.error("crash", "%s: %s" % [kind, message], extra)
	var report: Dictionary = {
		"kind": kind,
		"message": message,
		"extra": extra,
		"breadcrumbs": breadcrumbs.duplicate(),
		"engine": Engine.get_version_info().get("string", "?"),
		"os": OS.get_name(),
	}
	DirAccess.make_dir_recursive_absolute(REPORT_PATH.get_base_dir())
	var file: FileAccess = FileAccess.open(REPORT_PATH, FileAccess.WRITE)
	if file != null:
		file.store_string(JSON.stringify(report, "  "))


## Reserved for a consent-gated uploader; intentionally a no-op today.
func submit() -> bool:
	return false
