class_name SpectateProtocol
extends RefCounted

## Pure engine.io v4 / socket.io v4 text-frame codec for the READ-ONLY
## /spectate namespace documented in the racing server's docs/PROTOCOL.md.
## No sockets here: strings in, typed dictionaries out, so the whole protocol
## surface is testable headless without a network.

const NAMESPACE := "/spectate"

const KIND_EIO_OPEN := "eio_open"
const KIND_PING := "ping"
const KIND_PONG := "pong"
const KIND_CONNECTED := "sio_connected"
const KIND_EVENT := "sio_event"
const KIND_SIO_ERROR := "sio_error"
const KIND_CLOSE := "eio_close"
const KIND_IGNORED := "ignored"
const KIND_MALFORMED := "malformed"


static func handshake_path() -> String:
	return "/socket.io/?EIO=4&transport=websocket"


static func connect_frame() -> String:
	return "40%s," % NAMESPACE


## Main-namespace connect with the owner code as socket.io auth payload,
## matching the DOM client's io({ auth: { code } }).
static func auth_connect_frame(code: String) -> String:
	return "40" + JSON.stringify({ "code": code })


## Outbound event on the main namespace, e.g. race:input and resync.
static func event_frame(event_name: String, data: Variant = null) -> String:
	var parts: Array = [event_name]
	if data != null:
		parts.append(data)
	return "42" + JSON.stringify(parts)


static func pong_frame() -> String:
	return "3"


## Parse one websocket text frame into { kind, ... }.
static func parse_frame(frame: String) -> Dictionary:
	if frame.is_empty():
		return { "kind": KIND_MALFORMED }
	var eio := frame[0]
	var rest := frame.substr(1)
	match eio:
		"0":
			var open_payload: Variant = JSON.parse_string(rest)
			if typeof(open_payload) != TYPE_DICTIONARY:
				return { "kind": KIND_MALFORMED }
			return {
				"kind": KIND_EIO_OPEN,
				"sid": str(open_payload.get("sid", "")),
				"ping_interval_ms": int(open_payload.get("pingInterval", 25000)),
				"ping_timeout_ms": int(open_payload.get("pingTimeout", 20000)),
			}
		"1":
			return { "kind": KIND_CLOSE }
		"2":
			return { "kind": KIND_PING }
		"3":
			return { "kind": KIND_PONG }
		"4":
			return _parse_socketio(rest)
	return { "kind": KIND_IGNORED }


static func _parse_socketio(packet: String) -> Dictionary:
	if packet.is_empty():
		return { "kind": KIND_MALFORMED }
	var sio := packet[0]
	var rest := packet.substr(1)
	var nsp := "/"
	if rest.begins_with("/"):
		var comma := rest.find(",")
		if comma == -1:
			nsp = rest
			rest = ""
		else:
			nsp = rest.substr(0, comma)
			rest = rest.substr(comma + 1)
	match sio:
		"0":
			return { "kind": KIND_CONNECTED, "namespace": nsp }
		"2":
			var event_payload: Variant = JSON.parse_string(rest)
			if typeof(event_payload) != TYPE_ARRAY or (event_payload as Array).is_empty():
				return { "kind": KIND_MALFORMED }
			var parts: Array = event_payload
			var event_name := str(parts[0])
			var data: Variant = parts[1] if parts.size() > 1 else null
			return { "kind": KIND_EVENT, "namespace": nsp, "event": event_name, "data": data }
		"4":
			return { "kind": KIND_SIO_ERROR, "namespace": nsp, "detail": rest }
	return { "kind": KIND_IGNORED }
