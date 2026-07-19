extends SceneTree
## Headless client -> control-api -> (PostgreSQL) and client -> dedicated-server
## connectivity proof. Run by tools/godot/demo_connectivity.py:
##   godot --headless --path project --script res://tests/connectivity_check.gd
## Env: STUDIO_API_BASE (default http://127.0.0.1:8080),
##      STUDIO_WS_URL (default ws://127.0.0.1:8081)
## Prints one CONNECTIVITY_RESULT json line and exits 0 on full success.

const TIMEOUT_MS: int = 8000


func _initialize() -> void:
	print("[connectivity] starting")
	var api_base: String = OS.get_environment("STUDIO_API_BASE")
	if api_base.is_empty():
		api_base = "http://127.0.0.1:8080"
	var ws_url: String = OS.get_environment("STUDIO_WS_URL")
	if ws_url.is_empty():
		ws_url = "ws://127.0.0.1:8081"

	var result: Dictionary = {
		"api_health": false,
		"api_status": {},
		"db_roundtrip": false,
		"ws_handshake": false,
		"session": "",
	}

	var health: Dictionary = _http(api_base, "GET", "/healthz")
	result["api_health"] = int(health.get("status", 0)) == 200

	var status: Dictionary = _http(api_base, "GET", "/v1/status")
	var status_body: Variant = JSON.parse_string(str(status.get("body", "")))
	if status_body is Dictionary:
		result["api_status"] = status_body

	var check: Dictionary = _http(api_base, "POST", "/v1/bootstrap-check")
	var check_body: Variant = JSON.parse_string(str(check.get("body", "")))
	if check_body is Dictionary:
		result["db_roundtrip"] = bool((check_body as Dictionary).get("roundtrip_ok", false))

	var handshake: Dictionary = _ws_handshake(ws_url)
	result["ws_handshake"] = bool(handshake.get("ok", false))
	result["session"] = str(handshake.get("session", ""))

	print("CONNECTIVITY_RESULT " + JSON.stringify(result))
	var ok: bool = bool(result["api_health"]) and bool(result["ws_handshake"])
	quit(0 if ok else 1)


func _http(base: String, method: String, path: String) -> Dictionary:
	var host: String = base.trim_prefix("http://")
	var port: int = 80
	if ":" in host:
		var parts: PackedStringArray = host.split(":")
		host = parts[0]
		port = int(parts[1])
	var client: HTTPClient = HTTPClient.new()
	if client.connect_to_host(host, port) != OK:
		return {"status": 0, "body": ""}
	var deadline: int = Time.get_ticks_msec() + TIMEOUT_MS
	while client.get_status() in [HTTPClient.STATUS_CONNECTING, HTTPClient.STATUS_RESOLVING]:
		client.poll()
		OS.delay_msec(10)
		if Time.get_ticks_msec() > deadline:
			return {"status": 0, "body": "connect timeout"}
	if client.get_status() != HTTPClient.STATUS_CONNECTED:
		return {"status": 0, "body": "connect failed"}
	var http_method: HTTPClient.Method = HTTPClient.METHOD_GET if method == "GET" else HTTPClient.METHOD_POST
	if client.request(http_method, path, ["Accept: application/json"], "") != OK:
		return {"status": 0, "body": "request failed"}
	while client.get_status() == HTTPClient.STATUS_REQUESTING:
		client.poll()
		OS.delay_msec(10)
		if Time.get_ticks_msec() > deadline:
			return {"status": 0, "body": "request timeout"}
	if not client.has_response():
		return {"status": 0, "body": ""}
	var body: PackedByteArray = PackedByteArray()
	while client.get_status() == HTTPClient.STATUS_BODY:
		client.poll()
		var chunk: PackedByteArray = client.read_response_body_chunk()
		if chunk.size() > 0:
			body.append_array(chunk)
		else:
			OS.delay_msec(5)
		if Time.get_ticks_msec() > deadline:
			break
	return {"status": client.get_response_code(), "body": body.get_string_from_utf8()}


func _ws_handshake(url: String) -> Dictionary:
	var peer: WebSocketPeer = WebSocketPeer.new()
	if peer.connect_to_url(url) != OK:
		return {"ok": false}
	var deadline: int = Time.get_ticks_msec() + TIMEOUT_MS
	var sent_hello: bool = false
	while Time.get_ticks_msec() < deadline:
		peer.poll()
		var state: WebSocketPeer.State = peer.get_ready_state()
		if state == WebSocketPeer.STATE_OPEN and not sent_hello:
			sent_hello = true
			peer.send_text(StudioProtocol.encode(
				StudioProtocol.hello(1, "connectivity-check", "bootstrap")
			))
		if state == WebSocketPeer.STATE_OPEN and peer.get_available_packet_count() > 0:
			var packet: PackedByteArray = peer.get_packet()
			var decoded: Dictionary = StudioProtocol.decode(packet.get_string_from_utf8())
			if bool(decoded.get("ok", false)):
				var envelope: Dictionary = decoded["envelope"]
				if str(envelope.get("type", "")) == "hello_ack":
					peer.close(1000, "done")
					return {"ok": true, "session": str(envelope.get("session", ""))}
				return {"ok": false, "unexpected": envelope}
		if state == WebSocketPeer.STATE_CLOSED:
			return {"ok": false, "close_code": peer.get_close_code()}
		OS.delay_msec(10)
	return {"ok": false, "timeout": true}
