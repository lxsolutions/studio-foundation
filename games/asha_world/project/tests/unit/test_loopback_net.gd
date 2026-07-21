extends StudioTestCase
## Loopback transport + protocol codec working together (headless network test).


func test_loopback_roundtrip() -> void:
	var pair: Array = StudioLoopbackTransport.make_pair()
	var client: StudioLoopbackTransport = pair[0]
	var server: StudioLoopbackTransport = pair[1]

	var received: Array[Dictionary] = []
	server.envelope_received.connect(func(envelope: Dictionary) -> void:
		received.append(envelope))

	assert_eq(client.send_envelope(StudioProtocol.hello(1, "test", "0")), OK)
	server.poll()
	assert_eq(received.size(), 1)
	assert_eq(str(received[0]["type"]), "hello")

	# Server replies; client receives after ITS poll.
	var replies: Array[Dictionary] = []
	client.envelope_received.connect(func(envelope: Dictionary) -> void:
		replies.append(envelope))
	assert_eq(
		server.send_envelope(StudioProtocol.make_envelope("echo_ack", 1, {"text": "hi"})), OK
	)
	client.poll()
	assert_eq(replies.size(), 1)
	assert_eq(str(replies[0]["text"]), "hi")


func test_send_rejects_invalid_envelope() -> void:
	var pair: Array = StudioLoopbackTransport.make_pair()
	var client: StudioLoopbackTransport = pair[0]
	assert_eq(
		client.send_envelope({"v": 999, "seq": 1, "type": "ping", "nonce": 1}),
		ERR_INVALID_DATA,
		"wrong version must be rejected by the codec"
	)
	assert_eq(
		client.send_envelope({"v": 1, "seq": 1, "type": "nope"}),
		ERR_INVALID_DATA,
		"unknown type must be rejected"
	)


func test_close_propagates() -> void:
	var pair: Array = StudioLoopbackTransport.make_pair()
	var client: StudioLoopbackTransport = pair[0]
	var server: StudioLoopbackTransport = pair[1]
	var reasons: PackedStringArray = []
	server.disconnected.connect(func(reason: String) -> void:
		reasons.append(reason))
	client.close("test done")
	assert_false(client.is_open())
	assert_false(server.is_open())
	assert_eq(reasons.size(), 1)
