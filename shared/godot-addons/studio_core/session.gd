class_name StudioSession
extends RefCounted
## Account/session interface. Backed by the control API's stub endpoints today;
## real auth replaces the internals, not the surface. Tokens (when they exist)
## live in memory only — never written to saves or config.

signal signed_in(account: Dictionary)
signal signed_out
signal sign_in_failed(reason: String)

var api: StudioApiClient
var log: StudioLog
var account_id: String = ""
var session_id: String = ""
var display_name: String = ""


func _init(api_client: StudioApiClient, logger: StudioLog) -> void:
	api = api_client
	log = logger


func is_signed_in() -> bool:
	return not session_id.is_empty()


func guest_login() -> bool:
	var res: Dictionary = await api.post_json("/v1/session/guest")
	if not bool(res.get("ok", false)):
		var reason: String = "guest login failed (status %d)" % int(res.get("status", 0))
		log.warn("session", reason)
		sign_in_failed.emit(reason)
		return false
	var body: Variant = res.get("body")
	if not (body is Dictionary):
		sign_in_failed.emit("malformed session response")
		return false
	var payload: Dictionary = body
	account_id = str(payload.get("account_id", ""))
	session_id = str(payload.get("session_id", ""))
	display_name = str(payload.get("display_name", ""))
	log.info("session", "signed in", {"account": account_id, "name": display_name})
	signed_in.emit(payload)
	return true


func sign_out() -> void:
	account_id = ""
	session_id = ""
	display_name = ""
	signed_out.emit()
