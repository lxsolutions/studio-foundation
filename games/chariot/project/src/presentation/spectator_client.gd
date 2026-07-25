class_name SpectatorClient
extends Node

## Read-only websocket client for the /spectate namespace. Owns the transport
## and the engine.io/socket.io handshake; every decoded protocol event is
## re-emitted as a signal. All framing logic lives in SpectateProtocol so this
## node stays a thin pump that the test suite never needs to run.

signal state_changed(state: String)
signal spectate_event(event_name: String, data: Variant)

const DEFAULT_BASE_URL := "wss://racing.ashaarena.com"
const RECONNECT_MIN_S := 2.0
const RECONNECT_MAX_S := 30.0

var base_url: String = DEFAULT_BASE_URL
var _socket: WebSocketPeer
var _state: String = "disconnected"
var _reconnect_in: float = 0.0
var _reconnect_backoff: float = RECONNECT_MIN_S


func _ready() -> void:
	if _offline_requested():
		# The test suite (and web ?spectate_offline=1, used for previews and
		# headless captures) runs the full scene with the transport parked;
		# frames reach the view through the same codec path via direct injection.
		_enter_state("offline")
		set_process(false)
		return
	var override := OS.get_environment("RACING_SPECTATE_URL")
	if not override.is_empty():
		base_url = override
	_connect_socket()


func _offline_requested() -> bool:
	if OS.get_environment("RACING_SPECTATE_OFFLINE") == "1":
		return true
	if OS.has_feature("web"):
		var query := str(JavaScriptBridge.eval("window.location.search||''", true))
		return query.find("spectate_offline=1") != -1
	return false


func _connect_socket() -> void:
	_socket = WebSocketPeer.new()
	var url := base_url + SpectateProtocol.handshake_path()
	var err := _socket.connect_to_url(url)
	if err != OK:
		_enter_state("error")
		_schedule_reconnect()
		return
	_enter_state("connecting")


func _process(delta: float) -> void:
	if _socket == null:
		_reconnect_in -= delta
		if _reconnect_in <= 0.0:
			_connect_socket()
		return
	_socket.poll()
	match _socket.get_ready_state():
		WebSocketPeer.STATE_OPEN:
			while _socket.get_available_packet_count() > 0:
				var packet := _socket.get_packet()
				if _socket.was_string_packet():
					_handle_frame(packet.get_string_from_utf8())
		WebSocketPeer.STATE_CLOSED:
			# Frames can still be buffered when the state flips (the racing
			# server emits auth:error and disconnects in one breath).
			while _socket != null and _socket.get_available_packet_count() > 0:
				var packet := _socket.get_packet()
				if _socket.was_string_packet():
					_handle_frame(packet.get_string_from_utf8())
			_socket = null
			_enter_state("disconnected")
			_schedule_reconnect()


func _handle_frame(frame: String) -> void:
	var parsed := SpectateProtocol.parse_frame(frame)
	match parsed.get("kind"):
		SpectateProtocol.KIND_EIO_OPEN:
			_socket.send_text(SpectateProtocol.connect_frame())
		SpectateProtocol.KIND_PING:
			_socket.send_text(SpectateProtocol.pong_frame())
		SpectateProtocol.KIND_CONNECTED:
			if parsed.get("namespace") == SpectateProtocol.NAMESPACE:
				_reconnect_backoff = RECONNECT_MIN_S
				_enter_state("connected")
		SpectateProtocol.KIND_EVENT:
			if parsed.get("namespace") == SpectateProtocol.NAMESPACE:
				spectate_event.emit(str(parsed.get("event")), parsed.get("data"))
		SpectateProtocol.KIND_CLOSE, SpectateProtocol.KIND_SIO_ERROR:
			if _socket != null:
				_socket.close()


func _schedule_reconnect() -> void:
	_reconnect_in = _reconnect_backoff
	_reconnect_backoff = minf(_reconnect_backoff * 1.7, RECONNECT_MAX_S)


func _enter_state(next: String) -> void:
	if next == _state:
		return
	_state = next
	state_changed.emit(next)
