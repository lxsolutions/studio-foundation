class_name AshaWorldConfig
extends RefCounted
## World-server endpoint resolution for asha_world (proprietary game config).
## Order: `net.ws_url` project setting -> browser `?ws=` query param (web) ->
## localhost dev default. Lets a hosted WebGPU build point at a public world
## server without a re-export.

const DEFAULT_WS_URL := "ws://127.0.0.1:8081"


static func ws_url() -> String:
	# 1. Project setting (set in project.godot or via export override).
	var url: String = ProjectSettings.get_setting("asha_world/net_ws_url", "")
	if url != "":
		return url
	# 2. Browser query param ?ws=ws://host:port (or wss://...).
	if OS.has_feature("web"):
		var qp: Dictionary = AshaWorldConfig._query_params()
		if qp.has("ws"):
			return str(qp["ws"])
	# 3. Local dev default.
	return DEFAULT_WS_URL


static func _query_params() -> Dictionary:
	var out: Dictionary = {}
	if not OS.has_feature("web"):
		return out
	var js := "window.location.search.substring(1)"
	var raw: String = str(JavaScriptBridge.eval(js, true))
	for pair in raw.split("&", false):
		var kv: PackedStringArray = pair.split("=", false, 2)
		if kv.size() == 2:
			out[kv[0].uri_decode()] = kv[1].uri_decode()
	return out
