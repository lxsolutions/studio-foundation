class_name StudioSimKernel
extends RefCounted
## Godot's view onto the deterministic simulation kernel (ADR 0019).
##
## The kernel is compiled Rust — one rule set for client and server, proven
## identical across hosts by `just sim-parity`. This class lets a Godot client
## drive it, including in the browser, which is the case that usually stops here.
##
## A Godot web export cannot ship C#/.NET, because Godot's Emscripten build and
## the .NET runtime both need to BE the page's one WebAssembly main module.
## `sim_kernel.wasm` never enters that argument: it imports nothing (enforced by
## tools/sim/host_abi.py), so it is an ordinary module a running page loads
## beside Godot's, not a runtime competing to boot it. Compiled gameplay logic
## reaches the browser by not asking for the slot.
##
## Two backends, one API:
##   web     JavaScriptBridge injects addons/studio_core/sim/sim_kernel_host.js
##           and instantiates the wasm in the page.
##   native  the `sim-kernel` binary is executed per replay (editor, desktop,
##           headless tests, dedicated server).
##
## Only loading is asynchronous. Once `status()` reads "ready", `run()` is a
## synchronous call that returns in the same frame — it is a simulation, not a
## request, so a long replay costs frame time. Budget it like physics.
##
##     var kernel := StudioSimKernel.new()
##     kernel.load_kernel("sim_kernel.wasm")     # url on web, binary path native
##     await kernel.until_ready(get_tree())
##     var result := kernel.run(replay_text)
##     print(result["state_hash"])

const HOST_JS: String = "res://addons/studio_core/sim/sim_kernel_host.js"
## Bumped whenever the GDScript/JS contract changes; the host reports its own.
const HOST_CONTRACT: int = 1
const HOST_NAMESPACE: String = "__studio_sim_kernel"

const STATUS_IDLE: String = "idle"
const STATUS_LOADING: String = "loading"
const STATUS_READY: String = "ready"
const STATUS_ERROR: String = "error"
## No backend can run here: a native build with no runner path configured.
const STATUS_UNAVAILABLE: String = "unavailable"

const BACKEND_WEB: String = "web"
const BACKEND_NATIVE: String = "native"

const _TEMP_REPLAY: String = "user://.sim_kernel_replay.json"

var _status: String = STATUS_IDLE
var _error: String = ""
var _backend: String = ""
var _interface: Variant = null  ## JavaScriptObject, web only
var _runner: String = ""  ## native runner path


## Which backend this platform uses. Pure, so headless tests can check the
## decision without being on the platform it decides about.
static func backend_for(platform: Dictionary) -> String:
	return BACKEND_WEB if bool(platform.get("web", false)) else BACKEND_NATIVE


## Normalize any host's raw output into one dictionary shape.
##
## The kernel answers with either a result or `{error, code}`; a host that fails
## before the kernel is even reached answers with a `host_` code. Callers get one
## parse path and one place to look for what went wrong — including when the
## output is not JSON at all, which is what a crashed runner or an HTML error
## page looks like.
static func parse_result(raw: String) -> Dictionary:
	var trimmed: String = raw.strip_edges()
	if trimmed.is_empty():
		return {"code": "host_empty_output", "error": "the kernel host returned nothing"}
	var parsed: Variant = JSON.parse_string(trimmed)
	if parsed == null or not (parsed is Dictionary):
		return {
			"code": "host_bad_output",
			"error": "the kernel host returned output that is not a JSON object: %s"
			% trimmed.substr(0, 200),
		}
	return parsed as Dictionary


func status() -> String:
	if _status == STATUS_LOADING and _backend == BACKEND_WEB and _interface != null:
		# The browser owns the truth while loading; mirror it rather than
		# tracking a second copy that can disagree.
		_status = str(_interface.status())
		if _status == STATUS_ERROR:
			_error = str(_interface.error())
	return _status


func is_ready() -> bool:
	return status() == STATUS_READY


func error_text() -> String:
	return _error


func backend() -> String:
	return _backend


## Start the kernel. `source` is the wasm URL on web and the `sim-kernel` binary
## path on every other platform. Safe to call twice; the second call is ignored.
func load_kernel(source: String) -> String:
	if _status in [STATUS_LOADING, STATUS_READY]:
		return _status
	_backend = backend_for(StudioPlatform.detect())
	_error = ""
	if _backend == BACKEND_WEB:
		_load_web(source)
	else:
		_load_native(source)
	return _status


## Await readiness without hand-rolling a poll loop in every caller.
## Returns true once ready; false on error or timeout, with `error_text()` set.
func until_ready(tree: SceneTree, timeout_seconds: float = 30.0) -> bool:
	var deadline: int = Time.get_ticks_msec() + int(timeout_seconds * 1000.0)
	while status() == STATUS_LOADING:
		if Time.get_ticks_msec() > deadline:
			_status = STATUS_ERROR
			_error = "kernel did not finish loading within %.0fs" % timeout_seconds
			return false
		await tree.process_frame
	return _status == STATUS_READY


## Run one replay and return the kernel's result (or a `code`/`error` pair).
func run(replay_text: String) -> Dictionary:
	if status() != STATUS_READY:
		var detail: String = (": " + _error) if not _error.is_empty() else ""
		return {
			"code": "host_not_ready",
			"error": "kernel status is '%s'%s" % [_status, detail],
		}
	if _backend == BACKEND_WEB:
		return parse_result(str(_interface.run(replay_text)))
	return _run_native(replay_text)


func _fail(message: String) -> void:
	_status = STATUS_ERROR
	_error = message
	push_error("StudioSimKernel: " + message)


func _load_web(url: String) -> void:
	if not Engine.has_singleton("JavaScriptBridge"):
		_fail("JavaScriptBridge is unavailable in this build")
		return
	var bridge: Object = Engine.get_singleton("JavaScriptBridge")
	var source: String = FileAccess.get_file_as_string(HOST_JS)
	if source.is_empty():
		# The commonest cause by far: the export preset's include_filter does not
		# carry *.js, so the host script never made it into the PCK. Say that,
		# rather than letting it surface later as "kernel never became ready".
		var advice: String = (
			"%s is missing or empty. A .js file is not a Godot resource, so it only "
			+ "ships if the export preset's include_filter names it (the web presets "
			+ "in export_presets.cfg use \"*.js\")."
		)
		_fail(advice % HOST_JS)
		return
	bridge.call("eval", source, true)
	_interface = bridge.call("get_interface", HOST_NAMESPACE)
	if _interface == null:
		_fail("the kernel host script did not register %s" % HOST_NAMESPACE)
		return
	var contract: int = int(_interface.contract)
	if contract != HOST_CONTRACT:
		var mismatch: String = (
			"kernel host contract mismatch: sim_kernel_host.js reports %d, this build "
			+ "expects %d. Re-run `just godot-sync-addons`."
		)
		_fail(mismatch % [contract, HOST_CONTRACT])
		return
	_interface.load(url)
	_status = STATUS_LOADING


func _load_native(runner: String) -> void:
	if runner.is_empty():
		_status = STATUS_UNAVAILABLE
		_error = (
			"no sim-kernel runner configured. Build it with "
			+ "`cargo build -p sim-kernel --release` and pass the binary path."
		)
		return
	var path: String = ProjectSettings.globalize_path(runner)
	if not FileAccess.file_exists(path):
		_status = STATUS_UNAVAILABLE
		_error = "sim-kernel runner not found at %s" % path
		return
	_runner = path
	_status = STATUS_READY


func _run_native(replay_text: String) -> Dictionary:
	var file: FileAccess = FileAccess.open(_TEMP_REPLAY, FileAccess.WRITE)
	if file == null:
		return {
			"code": "host_write_failed",
			"error": "cannot write %s (error %d)" % [_TEMP_REPLAY, FileAccess.get_open_error()],
		}
	# Raw text, never re-serialized: conformance fixtures include deliberately
	# unparseable JSON, and re-encoding would repair what the kernel must reject.
	file.store_string(replay_text)
	file.close()
	var output: Array = []
	var code: int = OS.execute(
		_runner, [ProjectSettings.globalize_path(_TEMP_REPLAY)], output, true
	)
	if code < 0:
		return {"code": "host_exec_failed", "error": "could not execute %s" % _runner}
	return parse_result("\n".join(PackedStringArray(output)))
