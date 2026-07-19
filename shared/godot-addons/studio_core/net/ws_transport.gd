class_name StudioWsTransport
extends StudioTransport
## WebSocket transport over WebSocketPeer. Works on desktop, mobile, and web
## exports (browser WS). Poll-driven; the Studio autoload polls the active
## transport each frame.

var _peer: WebSocketPeer = WebSocketPeer.new()
var _state: int = WebSocketPeer.STATE_CLOSED
var _was_open: bool = false


func connect_to(url: String) -> Error:
	var err: Error = _peer.connect_to_url(url)
	if err != OK:
		transport_error.emit("connect_to_url failed: %d" % err)
		return err
	_state = WebSocketPeer.STATE_CONNECTING
	return OK


func send_envelope(envelope: Dictionary) -> Error:
	if _peer.get_ready_state() != WebSocketPeer.STATE_OPEN:
		return ERR_CONNECTION_ERROR
	if not envelope.has("seq"):
		envelope["seq"] = seq()
	return _peer.send_text(StudioProtocol.encode(envelope))


func poll() -> void:
	_peer.poll()
	var state: int = _peer.get_ready_state()
	if state == WebSocketPeer.STATE_OPEN and not _was_open:
		_was_open = true
		connected.emit()
	while state == WebSocketPeer.STATE_OPEN and _peer.get_available_packet_count() > 0:
		var packet: PackedByteArray = _peer.get_packet()
		var decoded: Dictionary = StudioProtocol.decode(packet.get_string_from_utf8())
		if bool(decoded.get("ok", false)):
			envelope_received.emit(decoded["envelope"])
		else:
			transport_error.emit(str(decoded.get("error", "decode failure")))
	if state == WebSocketPeer.STATE_CLOSED and _was_open:
		_was_open = false
		disconnected.emit("closed (code %d)" % _peer.get_close_code())
	_state = state


func close(reason: String = "client closing") -> void:
	if _peer.get_ready_state() == WebSocketPeer.STATE_OPEN or _peer.get_ready_state() == WebSocketPeer.STATE_CONNECTING:
		_peer.close(1000, reason)


func is_open() -> bool:
	return _peer.get_ready_state() == WebSocketPeer.STATE_OPEN
