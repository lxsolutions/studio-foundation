class_name RiderClient
extends SpectatorClient

## Authed main-namespace client for owners. Same transport pump as the
## spectator; the differences are the connect payload (the owner code), the
## namespace ("/" instead of "/spectate"), and the ability to send events.
## The first thing sent after auth is a resync so the server replays its
## snapshot events (horses:update, races:update) to this socket.

var code: String = ""
var _authed_namespace_open := false


## Unlike the broadcast, the rider waits for an owner code before touching the
## network; the base reconnect loop stays parked until start_with_code.
func _ready() -> void:
	if OS.get_environment("RACING_SPECTATE_OFFLINE") == "1":
		_enter_state("offline")
		set_process(false)
		return
	var override := OS.get_environment("RACING_SPECTATE_URL")
	if not override.is_empty():
		base_url = override
	set_process(false)


func start_with_code(owner_code: String) -> void:
	code = owner_code.strip_edges().to_upper()
	set_process(true)
	_connect_socket()


func _handle_frame(frame: String) -> void:
	var parsed := SpectateProtocol.parse_frame(frame)
	match parsed.get("kind"):
		SpectateProtocol.KIND_EIO_OPEN:
			_authed_namespace_open = false
			_socket.send_text(SpectateProtocol.auth_connect_frame(code))
		SpectateProtocol.KIND_PING:
			_socket.send_text(SpectateProtocol.pong_frame())
		SpectateProtocol.KIND_CONNECTED:
			if parsed.get("namespace") == "/":
				_authed_namespace_open = true
				_reconnect_backoff = RECONNECT_MIN_S
				_enter_state("connected")
				send_event("resync", {})
		SpectateProtocol.KIND_EVENT:
			if parsed.get("namespace") == "/":
				spectate_event.emit(str(parsed.get("event")), parsed.get("data"))
		SpectateProtocol.KIND_CLOSE, SpectateProtocol.KIND_SIO_ERROR:
			if _socket != null:
				_socket.close()


## Send a main-namespace event; drops silently when the socket is not open,
## because inputs are encouragements and a stale one must never queue up.
func send_event(event_name: String, data: Variant = null) -> bool:
	if _socket == null or not _authed_namespace_open:
		return false
	if _socket.get_ready_state() != WebSocketPeer.STATE_OPEN:
		return false
	_socket.send_text(SpectateProtocol.event_frame(event_name, data))
	return true
