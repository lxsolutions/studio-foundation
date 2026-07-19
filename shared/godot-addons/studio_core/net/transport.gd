class_name StudioTransport
extends RefCounted
## Networking transport interface (mirror of the Rust `Transport` trait).
## Implementations: StudioWsTransport (WebSocket, works in browsers),
## StudioLoopbackTransport (tests). WebTransport/QUIC implement this same
## surface later — game code must depend only on this class (ADR 0002/0010).

signal connected
signal disconnected(reason: String)
signal envelope_received(envelope: Dictionary)
signal transport_error(message: String)

var next_seq: int = 0


func seq() -> int:
	next_seq += 1
	return next_seq


## Begin connecting; emits `connected` or `disconnected`.
func connect_to(_url: String) -> Error:
	push_error("StudioTransport.connect_to not implemented")
	return ERR_UNCONFIGURED


func send_envelope(_envelope: Dictionary) -> Error:
	push_error("StudioTransport.send_envelope not implemented")
	return ERR_UNCONFIGURED


## Must be called every frame (the Studio autoload does this for `Studio.net`).
func poll() -> void:
	pass


func close(_reason: String = "client closing") -> void:
	pass


func is_open() -> bool:
	return false
