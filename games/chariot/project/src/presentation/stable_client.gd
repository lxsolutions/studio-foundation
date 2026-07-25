class_name StableClient
extends Node

## Thin HTTP carrier for StableActions requests. One request in flight at a
## time (the stable is a person tapping buttons, not a pipeline); the socket
## delivers the resulting state, so the only output here is ok/error per call.
## Offline (the test suite), requests are captured instead of sent.

signal settled(path: String, ok: bool, error: String)
signal projection(path: String, ok: bool, error: String, data: Dictionary)

var base_http_url: String = ""
var code: String = ""
var offline_captured: Array = []

var _http: HTTPRequest
var _busy_path: String = ""
var _offline := false


func _ready() -> void:
	_offline = OS.get_environment("RACING_SPECTATE_OFFLINE") == "1"
	_http = HTTPRequest.new()
	_http.timeout = 15.0
	add_child(_http)
	_http.request_completed.connect(_on_completed)


## Derive http(s):// from the socket base url once the code screen submits.
func configure(socket_base_url: String, owner_code: String) -> void:
	code = owner_code
	base_http_url = socket_base_url.replace("wss://", "https://").replace("ws://", "http://")


func send(request: Dictionary) -> bool:
	var path := str(request.get("path", ""))
	if _offline:
		offline_captured.append(request)
		settled.emit(path, true, "")
		return true
	if not _busy_path.is_empty() or base_http_url.is_empty():
		return false
	_busy_path = path
	_busy_is_projection = int(request.get("method", HTTPClient.METHOD_POST)) == HTTPClient.METHOD_GET or bool(request.get("wants_data", false))
	var err := _http.request(
		base_http_url + path,
		["Content-Type: application/json"],
		int(request.get("method", HTTPClient.METHOD_POST)),
		str(request.get("body", "")),
	)
	if err != OK:
		_busy_path = ""
		settled.emit(path, false, "Could not reach the race office.")
		return false
	return true


var _busy_is_projection := false


func _on_completed(result: int, status: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var path := _busy_path
	var was_projection := _busy_is_projection
	_busy_path = ""
	_busy_is_projection = false
	if result != HTTPRequest.RESULT_SUCCESS:
		settled.emit(path, false, "Could not reach the race office.")
		return
	var text := body.get_string_from_utf8()
	if was_projection:
		var folded_json := StableActions.fold_json(status, text)
		projection.emit(path, folded_json.get("ok", false), str(folded_json.get("error", "")), folded_json.get("data", {}))
		return
	var folded := StableActions.fold_response(status, text)
	settled.emit(path, folded.get("ok", false), str(folded.get("error", "")))
