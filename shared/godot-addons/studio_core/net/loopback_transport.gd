class_name StudioLoopbackTransport
extends StudioTransport
## In-memory transport pair for headless tests and deterministic replay.
## Usage:
##   var pair: Array = StudioLoopbackTransport.make_pair()
##   var client: StudioLoopbackTransport = pair[0]
##   var server: StudioLoopbackTransport = pair[1]

var _out_queue: Array[Dictionary] = []
var _peer: StudioLoopbackTransport = null
var _open: bool = false


static func make_pair() -> Array:
	var a: StudioLoopbackTransport = StudioLoopbackTransport.new()
	var b: StudioLoopbackTransport = StudioLoopbackTransport.new()
	a._peer = b
	b._peer = a
	a._open = true
	b._open = true
	return [a, b]


func connect_to(_url: String) -> Error:
	connected.emit()
	return OK


func send_envelope(envelope: Dictionary) -> Error:
	if not _open or _peer == null:
		return ERR_CONNECTION_ERROR
	if not envelope.has("seq"):
		envelope["seq"] = seq()
	# Encode/decode through the real codec so tests cover it.
	var decoded: Dictionary = StudioProtocol.decode(StudioProtocol.encode(envelope))
	if not bool(decoded.get("ok", false)):
		return ERR_INVALID_DATA
	_peer._out_queue.append(decoded["envelope"])
	return OK


func poll() -> void:
	while not _out_queue.is_empty():
		var envelope: Dictionary = _out_queue.pop_front()
		envelope_received.emit(envelope)


func close(reason: String = "client closing") -> void:
	if _open:
		_open = false
		disconnected.emit(reason)
		if _peer != null and _peer._open:
			_peer._open = false
			_peer.disconnected.emit("peer closed")


func is_open() -> bool:
	return _open
