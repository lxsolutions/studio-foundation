class_name StudioProtocol
extends RefCounted
## GDScript mirror of services/shared-protocol (Rust). Spec:
## shared/protocol/PROTOCOL.md. CI runs BOTH implementations against the golden
## fixtures — if you change one side, you must change the other and the fixtures.

const PROTOCOL_VERSION: int = 1

const KNOWN_TYPES: PackedStringArray = [
	"hello", "hello_ack", "ping", "pong", "echo", "echo_ack", "bye", "error",
]

const ERROR_CODES: PackedStringArray = [
	"version_mismatch", "malformed", "unexpected", "internal",
]


static func make_envelope(type: String, seq: int, body: Dictionary = {}) -> Dictionary:
	var envelope: Dictionary = {"v": PROTOCOL_VERSION, "seq": seq, "type": type}
	envelope.merge(body)
	return envelope


static func hello(seq: int, client: String, build: String) -> Dictionary:
	return make_envelope("hello", seq, {
		"client": client, "build": build, "protocol": PROTOCOL_VERSION,
	})


static func encode(envelope: Dictionary) -> String:
	return JSON.stringify(envelope)


## Returns { ok: bool, envelope: Dictionary, error: String }.
## Mirrors Rust decode(): rejects wrong version, unknown type, missing fields.
static func decode(text: String) -> Dictionary:
	var parsed: Variant = JSON.parse_string(text)
	if not (parsed is Dictionary):
		return {"ok": false, "envelope": {}, "error": "malformed"}
	var envelope: Dictionary = parsed
	for field in ["v", "seq", "type"]:
		if not envelope.has(field):
			return {"ok": false, "envelope": {}, "error": "malformed: missing " + field}
	if int(envelope["v"]) != PROTOCOL_VERSION:
		return {"ok": false, "envelope": envelope, "error": "version_mismatch"}
	var type_name: String = str(envelope["type"])
	if not type_name in KNOWN_TYPES:
		return {"ok": false, "envelope": envelope, "error": "malformed: unknown type " + type_name}
	if not _has_required_fields(type_name, envelope):
		return {"ok": false, "envelope": envelope, "error": "malformed: missing fields for " + type_name}
	return {"ok": true, "envelope": envelope, "error": ""}


static func _has_required_fields(type_name: String, envelope: Dictionary) -> bool:
	var required: PackedStringArray = []
	match type_name:
		"hello":
			required = ["client", "build", "protocol"]
		"hello_ack":
			required = ["server", "protocol", "session"]
		"ping", "pong":
			required = ["nonce"]
		"echo", "echo_ack":
			required = ["text"]
		"error":
			required = ["code", "message"]
		"bye":
			required = []
	for field in required:
		if not envelope.has(field):
			return false
	if type_name == "error" and not str(envelope["code"]) in ERROR_CODES:
		return false
	return true
