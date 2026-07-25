extends StudioTestCase
## Deterministic random seed support.


func test_same_seed_same_sequence() -> void:
	var a: StudioRng = StudioRng.new()
	var b: StudioRng = StudioRng.new()
	a.set_run_seed(1234)
	b.set_run_seed(1234)
	for stream_name in ["combat", "loot"]:
		for i in 5:
			assert_eq(
				a.stream(stream_name).randi(),
				b.stream(stream_name).randi(),
				"stream %s draw %d diverged" % [stream_name, i]
			)


func test_streams_are_independent() -> void:
	var a: StudioRng = StudioRng.new()
	a.set_run_seed(99)
	var first_loot: int = a.stream("loot").randi()

	var b: StudioRng = StudioRng.new()
	b.set_run_seed(99)
	# Draw from a DIFFERENT stream first; loot stream must be unaffected.
	var _combat_draw: int = b.stream("combat").randi()
	assert_eq(b.stream("loot").randi(), first_loot, "cross-stream interference")


func test_state_restore_roundtrip() -> void:
	var a: StudioRng = StudioRng.new()
	a.set_run_seed(7)
	var _burn: int = a.stream("x").randi()
	var snapshot: Dictionary = a.state()
	var next_expected: int = a.stream("x").randi()

	var restored: StudioRng = StudioRng.new()
	restored.restore(snapshot)
	assert_eq(restored.stream("x").randi(), next_expected, "restored stream diverged")


func test_zero_seed_randomizes() -> void:
	var a: StudioRng = StudioRng.new()
	a.set_run_seed(0)
	assert_ne(a.run_seed, 0, "seed 0 must be replaced with a random seed")
