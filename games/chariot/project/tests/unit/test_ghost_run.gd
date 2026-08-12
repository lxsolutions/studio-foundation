extends StudioTestCase
## Ghost time-trial runs ("beat my lap"): recording from the tick stream,
## millisecond normalization, serialization round-trips, replay
## interpolation, the win/loss settle, the shared bounds, and the local store.


func _tick_horses(pos: float, lane: float = 2.0, speed: float = 16.5) -> Array:
	return [
		{"horseId": "h1", "pos": pos, "lane": lane, "speed": speed},
		{"horseId": "h2", "pos": pos - 4.0, "lane": lane + 1.0, "speed": speed},
	]


## A full sane run: 12 samples over a 92-second race clock (in seconds, like
## the wire carries), finished with the official timeMs.
func _recorded_run() -> GhostRun:
	var run := GhostRun.new()
	run.begin("Xanthos", "blue", 1800.0)
	for i in range(12):
		run.sample(float(i) * 8.0, _tick_horses(float(i) * 132.0), "h1")
	run.finish(92000)
	return run


func test_record_samples_the_named_horse_only() -> void:
	var run := GhostRun.new()
	run.begin("Xanthos", "blue", 1800.0)
	assert_true(run.sample(0.0, _tick_horses(10.0), "h1"))
	assert_eq(run.ticks.size(), 1)
	assert_eq(float(run.ticks[0].get("pos", 0.0)), 10.0)
	assert_false(run.sample(0.2, _tick_horses(13.0), "h9"), "a horse outside the stream samples nothing")
	assert_eq(run.ticks.size(), 1)
	assert_false(run.sample(0.2, _tick_horses(13.0), ""), "no horse id, no sample")


func test_record_drops_a_backwards_clock() -> void:
	var run := GhostRun.new()
	run.begin("Xanthos", "blue", 1800.0)
	run.sample(4.0, _tick_horses(60.0), "h1")
	assert_false(run.sample(3.9, _tick_horses(59.0), "h1"), "time never runs backwards")
	assert_eq(run.ticks.size(), 1)


func test_finish_normalizes_seconds_to_milliseconds() -> void:
	var run := _recorded_run()
	assert_eq(run.tick_scale_ms, 1000.0, "a tick clock ~1000x under the official time was seconds")
	assert_eq(float(run.ticks[-1].get("t", 0.0)), 88000.0, "ticks now ride the millisecond clock")
	assert_true(run.is_valid(), "the recorded run passes the shared bounds: " + run.validation_error())


func test_finish_keeps_an_already_millisecond_clock() -> void:
	var run := GhostRun.new()
	run.begin("Xanthos", "blue", 1800.0)
	for i in range(12):
		run.sample(float(i) * 8000.0, _tick_horses(float(i) * 132.0), "h1")
	run.finish(92000)
	assert_eq(run.tick_scale_ms, 1.0)
	assert_true(run.is_valid())


func test_serialization_round_trip() -> void:
	var run := _recorded_run()
	var parsed := GhostRun.from_dict(run.to_dict())
	assert_true(parsed != null, "a stored run parses back")
	assert_eq(parsed.handle, "Xanthos")
	assert_eq(parsed.faction, "blue")
	assert_eq(parsed.total_ms, 92000)
	assert_eq(parsed.distance_m, 1800.0)
	assert_eq(parsed.tick_scale_ms, 1000.0)
	assert_eq(parsed.ticks.size(), run.ticks.size())
	assert_eq(parsed.ticks[5], run.ticks[5], "the tick stream survives verbatim")
	assert_true(parsed.is_valid())


func test_from_dict_rejects_garbage() -> void:
	assert_eq(GhostRun.from_dict("not a run"), null)
	assert_eq(GhostRun.from_dict({}), null, "no schema, no run")
	assert_eq(GhostRun.from_dict({"schema": 999, "ticks": []}), null, "wrong schema")
	assert_eq(GhostRun.from_dict({"schema": 1}), null, "no tick stream")
	assert_eq(GhostRun.from_dict({"schema": 1, "ticks": ["garbage"]}), null, "every tick is a dictionary")


func test_position_at_interpolates_between_ticks() -> void:
	var run := _recorded_run()
	# Samples sit 8s (8000ms) apart, 132m between them: halfway reads 66m on.
	var mark: Dictionary = run.position_at(12000.0)
	assert_eq(float(mark.get("pos", 0.0)), 198.0, "lerped between the 8000 and 16000 marks")
	assert_eq(float(mark.get("lane", 0.0)), 2.0)
	assert_eq(float(mark.get("speed", 0.0)), 16.5)


func test_position_at_clamps_both_ends() -> void:
	var run := _recorded_run()
	var before: Dictionary = run.position_at(0.0)
	assert_eq(float(before.get("pos", 99.0)), 0.0, "the ghost waits at the gate")
	assert_eq(float(before.get("speed", 99.0)), 0.0)
	var after: Dictionary = run.position_at(200000.0)
	assert_eq(float(after.get("pos", 0.0)), 1452.0, "past the wire it stands at its final mark")
	assert_eq(float(after.get("speed", 99.0)), 0.0, "and its speed is bled to zero")


func test_position_at_survives_a_rewound_query() -> void:
	# The exhibition loop wraps its clock; the replay cursor must rewind with it.
	var run := _recorded_run()
	run.position_at(80000.0)
	var mark: Dictionary = run.position_at(4000.0)
	assert_eq(float(mark.get("pos", 999.0)), 66.0, "a wrapped clock replays from the start")


func test_verdict_settles_the_duel() -> void:
	var win: Dictionary = GhostRun.verdict(91000, 92000)
	assert_eq(str(win.get("outcome", "")), "win", "the lower time takes it")
	assert_eq(int(win.get("marginMs", 0)), 1000)
	var loss: Dictionary = GhostRun.verdict(93400, 92000)
	assert_eq(str(loss.get("outcome", "")), "loss")
	assert_eq(int(loss.get("marginMs", 0)), 1400)
	var tie: Dictionary = GhostRun.verdict(92000, 92000)
	assert_eq(str(tie.get("outcome", "")), "tie", "a dead heat is a tie")


func test_bounds_reject_implausible_runs() -> void:
	var run := _recorded_run()
	run.handle = ""
	assert_ne(run.validation_error(), "", "a ghost needs a handle")
	run = _recorded_run()
	run.faction = "gold"
	assert_ne(run.validation_error(), "", "ghosts ride for a real faction")
	run = _recorded_run()
	run.total_ms = 5000
	assert_ne(run.validation_error(), "", "five seconds is not a lap")
	run = _recorded_run()
	run.total_ms = 99999999
	assert_ne(run.validation_error(), "", "nor is a whole day")
	run = _recorded_run()
	run.ticks = run.ticks.slice(0, 4)
	assert_ne(run.validation_error(), "", "a handful of samples is not a run")
	run = _recorded_run()
	run.distance_m = 0.0
	assert_ne(run.validation_error(), "", "a run needs its distance")
	run = _recorded_run()
	run.ticks[3]["t"] = 0.0
	assert_ne(run.validation_error(), "", "tick times never run backwards")
	run = _recorded_run()
	run.ticks[3]["lane"] = 99.0
	assert_ne(run.validation_error(), "", "lanes stay in the field")
	run = _recorded_run()
	run.ticks[3]["pos"] = -1.0
	assert_ne(run.validation_error(), "", "positions stay on the course")


func test_store_save_load_round_trip() -> void:
	var store := GhostStore.new()
	var run := _recorded_run()
	var id := store.save(run)
	assert_ne(id, "", "a valid run saves")
	assert_true(id.begins_with("ghost_"), "a local id carries the local prefix")
	var loaded := store.load_ghost(id)
	assert_true(loaded != null)
	assert_eq(loaded.handle, "Xanthos")
	assert_eq(loaded.total_ms, 92000)
	assert_eq(loaded.ticks.size(), 12)
	assert_true(loaded.is_valid(), "the stored run still passes the bounds")
	DirAccess.remove_absolute("user://ghosts/%s.json" % id)


func test_store_lists_newest_first() -> void:
	var store := GhostStore.new()
	var first := store.save(_recorded_run())
	var second_run := _recorded_run()
	second_run.handle = "Balios"
	var second := store.save(second_run)
	var listed := store.list_local()
	var ids: Array = []
	for entry in listed:
		ids.append(str(entry.get("id", "")))
	assert_true(ids.has(first) and ids.has(second))
	assert_true(ids.find(second) < ids.find(first), "newest ghost on top")
	for id in [first, second]:
		DirAccess.remove_absolute("user://ghosts/%s.json" % id)


func test_store_refuses_the_invalid_and_the_unknown() -> void:
	var store := GhostStore.new()
	var run := _recorded_run()
	run.total_ms = 100
	assert_eq(store.save(run), "", "an invalid run never reaches the shelf")
	assert_eq(store.load_ghost("ghost_nope"), null, "no ghost answers to an unknown id")
	assert_eq(store.load_ghost("../rider"), null, "an id is never a path")
	assert_eq(store.load_ghost(""), null)


func test_store_transport_seam_submits_and_fetches() -> void:
	# The server path lands when the client grows a studio-protocol transport;
	# a fake one proves the seam: saves take the server id, loads fall through
	# to fetch, and a server copy mirrors locally.
	var submitted: Array = []
	var store := GhostStore.new()
	store.transport = func(payload: Dictionary) -> Dictionary:
		submitted.append(payload)
		if str(payload.get("kind", "")) == "ghost_submit":
			return {"ok": true, "id": "g-7"}
		if str(payload.get("kind", "")) == "ghost_fetch" and str(payload.get("id", "")) == "g-9":
			return {"ok": true, "ghost": _recorded_run().to_dict()}
		return {"ok": false}
	var id := store.save(_recorded_run())
	assert_eq(id, "g-7", "the server's id wins when the transport answers")
	assert_eq(submitted.size(), 1)
	assert_eq(str((submitted[0] as Dictionary).get("kind", "")), "ghost_submit")
	assert_true(FileAccess.file_exists("user://ghosts/g-7.json"), "the server copy mirrors locally")
	var fetched := store.load_ghost("g-9")
	assert_true(fetched != null, "a fetch miss locally falls through to the server")
	assert_true(fetched.is_valid())
	DirAccess.remove_absolute("user://ghosts/g-7.json")
	DirAccess.remove_absolute("user://ghosts/g-9.json")
