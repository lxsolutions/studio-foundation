extends StudioTestCase
## The identity bridge: ghost-by-URL handoff parsing (SsoExchange), the
## challenge-link builder, and the StudioClient transport mapping — over a
## loopback pair with a fake server, plus the parked-bridge offline fallback.
##
## The headless runner never idles, so no test body may genuinely suspend:
## requests are FIRED through the reply-Callable entry points (submit_now /
## fetch_now / request) and their outcomes land inside client.pump(), which
## the test drives by hand. The coroutine wrappers the GhostStore seam awaits
## are covered where they cannot suspend: the parked bridge and the
## off-the-wire refusal.

## The far end of a StudioLoopbackTransport pair: answers the hello handshake
## and the two ghost payloads exactly like the Rust server does, and records
## every application payload it was handed.
class FakeStudioServer:
	extends RefCounted

	var payloads: Array[Dictionary] = []
	var _transport: StudioLoopbackTransport

	func _init(transport: StudioLoopbackTransport) -> void:
		_transport = transport
		_transport.envelope_received.connect(_on_envelope)

	func _on_envelope(envelope: Dictionary) -> void:
		match str(envelope.get("type", "")):
			"hello":
				_transport.send_envelope(StudioProtocol.make_envelope("hello_ack", 1, {
					"server": "fake-studio",
					"protocol": StudioProtocol.PROTOCOL_VERSION,
					"session": "00000000-0000-0000-0000-000000000000",
				}))
			"application_request":
				var parsed: Variant = JSON.parse_string(str(envelope.get("payload_json", "{}")))
				var payload: Dictionary = parsed if typeof(parsed) == TYPE_DICTIONARY else {}
				payloads.append(payload)
				var reply := _answer(payload)
				_transport.send_envelope(StudioProtocol.make_envelope("application_result", 1, {
					"accepted": bool(reply.get("ok", false)),
					"summary": JSON.stringify(reply),
				}))

	func _answer(payload: Dictionary) -> Dictionary:
		match str(payload.get("kind", "")):
			"ghost_submit":
				return {"ok": true, "kind": "ghost.submit", "id": "g-1"}
			"ghost_fetch":
				return {"ok": true, "kind": "ghost.fetch", "ghost": {"id": str(payload.get("id", ""))}}
		return {"ok": false, "error": "unknown kind"}

	func of_kind(kind: String) -> Array[Dictionary]:
		var found: Array[Dictionary] = []
		for payload in payloads:
			if str(payload.get("kind", "")) == kind:
				found.append(payload)
		return found


## [client, server, server_transport], wired but not yet connected.
func _bridge() -> Array:
	var pair: Array = StudioLoopbackTransport.make_pair()
	var server := FakeStudioServer.new(pair[1])
	var client := StudioClient.new()
	client.inject_transport(pair[0])
	client.base_url = "loopback://test"
	return [client, server, pair[1]]


func _drive(client: StudioClient, server_transport: StudioLoopbackTransport) -> void:
	for i in range(8):
		server_transport.poll()
		client.pump(0.05)


func _submit_payload() -> Dictionary:
	return {
		"kind": "ghost_submit",
		"member": "Xanthos",
		"faction": "blue",
		"handle": "Xanthos",
		"totalMs": 92000,
		"distanceM": 1800.0,
		"ticks": [],
	}


func _recorded_run() -> GhostRun:
	var run := GhostRun.new()
	run.begin("Xanthos", "blue", 1800.0)
	for i in range(12):
		run.ticks.append({"t": float(i) * 8000.0, "pos": float(i) * 132.0, "lane": 2.0, "speed": 16.5})
	run.finish(92000)
	return run


# ── The ?ghost= handoff ──────────────────────────────────────────────────────

func test_extract_ghost_id() -> void:
	assert_eq(SsoExchange.extract_ghost_id("?ghost=g-7"), "g-7")
	assert_eq(SsoExchange.extract_ghost_id("ghost=g-7"), "g-7", "a bare query parses too")
	assert_eq(SsoExchange.extract_ghost_id("?t=tok&ghost=g-7"), "g-7", "the token param is ignored")
	assert_eq(SsoExchange.extract_ghost_id("?t=tok"), "", "no ghost, no id")
	assert_eq(SsoExchange.extract_ghost_id(""), "")
	assert_eq(SsoExchange.extract_ghost_id("?ghost=g-1&ghost=g-2"), "g-1", "first ghost wins")
	assert_eq(SsoExchange.extract_ghost_id("?ghost=g%2D7"), "g-7", "values arrive uri-decoded")


func test_scrubbed_ghost_query_keeps_the_rest() -> void:
	assert_eq(SsoExchange.scrubbed_ghost_query("?ghost=g-7"), "")
	assert_eq(SsoExchange.scrubbed_ghost_query("?a=1&ghost=g-7&b=2"), "a=1&b=2", "order and values survive")
	# The two scrubs compose: a link carrying sign-in AND a challenge sheds both.
	var query := "?t=tok&ghost=g-7"
	assert_eq(SsoExchange.extract_ghost_id(SsoExchange.scrubbed_query(query)), "g-7",
		"taking the token leaves the ghost for the views")
	assert_eq(SsoExchange.scrubbed_ghost_query(SsoExchange.scrubbed_query(query)), "",
		"and taking the ghost finishes the scrub")


func test_ghost_challenge_url() -> void:
	assert_eq(
		SsoExchange.ghost_challenge_url("https://racing.ashaarena.com", "g-7"),
		"https://racing.ashaarena.com/?ghost=g-7")
	assert_eq(
		SsoExchange.ghost_challenge_url("https://racing.ashaarena.com/", "g-7"),
		"https://racing.ashaarena.com/?ghost=g-7", "a trailing slash never doubles")
	assert_eq(
		SsoExchange.ghost_challenge_url("", "g-7"),
		"https://racing.ashaarena.com/?ghost=g-7", "off the web the racing origin stands in")
	assert_eq(
		SsoExchange.ghost_challenge_url("not-a-url", "g-7"),
		"https://racing.ashaarena.com/?ghost=g-7", "junk origins fall back too")


# ── The transport mapping ────────────────────────────────────────────────────

func test_submit_carries_the_plaza_token() -> void:
	var parts := _bridge()
	var client: StudioClient = parts[0]
	var server: FakeStudioServer = parts[1]
	client.token = "plaza-token-1"
	var replies: Array[Dictionary] = []
	client.submit_now(_submit_payload(), func(reply: Dictionary) -> void: replies.append(reply))
	_drive(client, parts[2])
	var sent := server.of_kind("ghost_submit")
	assert_eq(sent.size(), 1, "the submit crossed the wire")
	assert_eq(str(sent[0].get("token", "")), "plaza-token-1", "the plaza token rides the submit")
	assert_eq(str(sent[0].get("member", "")), "Xanthos", "the claim still goes along")
	assert_eq(replies.size(), 1, "the reply settled")
	assert_true(bool(replies[0].get("ok", false)))
	assert_eq(str(replies[0].get("id", "")), "g-1", "the summary json is unfolded")
	client.free()


func test_submit_without_a_token_sends_none() -> void:
	var parts := _bridge()
	var client: StudioClient = parts[0]
	var server: FakeStudioServer = parts[1]
	var replies: Array[Dictionary] = []
	client.submit_now(_submit_payload(), func(reply: Dictionary) -> void: replies.append(reply))
	_drive(client, parts[2])
	var sent := server.of_kind("ghost_submit")
	assert_eq(sent.size(), 1)
	assert_false(sent[0].has("token"), "no token is invented for a code-signed rider")
	assert_eq(replies.size(), 1)
	assert_true(bool(replies[0].get("ok", false)))
	client.free()


func test_fetch_maps_ghost_fetch() -> void:
	var parts := _bridge()
	var client: StudioClient = parts[0]
	var server: FakeStudioServer = parts[1]
	var replies: Array[Dictionary] = []
	client.fetch_now({"kind": "ghost_fetch", "id": "g-9"}, func(reply: Dictionary) -> void: replies.append(reply))
	_drive(client, parts[2])
	var sent := server.of_kind("ghost_fetch")
	assert_eq(sent.size(), 1)
	assert_eq(str(sent[0].get("id", "")), "g-9")
	assert_eq(replies.size(), 1)
	assert_true(bool(replies[0].get("ok", false)))
	assert_eq(str((replies[0].get("ghost", {}) as Dictionary).get("id", "")), "g-9")
	client.free()


func test_mapping_refuses_an_unknown_kind_off_wire() -> void:
	var parts := _bridge()
	var client: StudioClient = parts[0]
	var server: FakeStudioServer = parts[1]
	# transport_mapping for an unknown kind answers before any connect attempt,
	# so this await resolves in-line.
	var reply: Dictionary = await client.transport_mapping.call({"kind": "standings_fetch"})
	assert_false(bool(reply.get("ok", true)))
	assert_true(server.payloads.is_empty(), "nothing crossed the wire")
	client.free()


func test_parked_bridge_falls_back_to_local_synchronously() -> void:
	# The parked posture: no server URL at all. save() must answer in-line
	# (the whole point of the local fallback) with a local id.
	OS.set_environment("RACING_STUDIO_URL", "")
	var client := StudioClient.new()
	var store := GhostStore.new()
	store.transport = client.transport_mapping
	var id := await store.save(_recorded_run())
	assert_true(id.begins_with("ghost_"), "a parked bridge yields the local id: " + id)
	var loaded := await store.load_ghost(id)
	assert_true(loaded != null, "and the local shelf answers")
	DirAccess.remove_absolute("user://ghosts/%s.json" % id)
	OS.unset_environment("RACING_STUDIO_URL")
	client.free()


func test_a_drop_settles_the_backlog_and_parks() -> void:
	var parts := _bridge()
	var client: StudioClient = parts[0]
	var server_transport: StudioLoopbackTransport = parts[2]
	var replies: Array[Dictionary] = []
	client.submit_now(_submit_payload(), func(reply: Dictionary) -> void: replies.append(reply))
	# The socket dies before the handshake completed: the waiting request
	# settles with an error, never a hang, and the bridge stays parked.
	server_transport.close("server going away")
	assert_eq(replies.size(), 1)
	assert_false(bool(replies[0].get("ok", true)), "a dropped bridge answers not-ok")
	assert_ne(str(replies[0].get("error", "")), "")
	client.submit_now(_submit_payload(), func(reply: Dictionary) -> void: replies.append(reply))
	assert_eq(replies.size(), 2, "a parked bridge answers immediately")
	assert_false(bool(replies[1].get("ok", true)))
	client.free()
