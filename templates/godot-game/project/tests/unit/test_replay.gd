extends StudioTestCase
## Replay/event-recording foundation.


func test_record_save_load_roundtrip() -> void:
	var replay: StudioReplay = StudioReplay.new()
	replay.begin(4242, {"scene": "test"})
	replay.record("spawn", {"id": 1})
	replay.record("move", {"id": 1, "x": 2.0})
	var path: String = replay.end_and_save("test_replay")
	assert_ne(path, "", "save path")

	var loaded: Dictionary = replay.load_replay(path)
	assert_true(loaded.has("header"), "header present")
	var header: Dictionary = loaded["header"]
	assert_eq(int(header["run_seed"]), 4242)
	var events: Array = loaded["events"]
	assert_eq(events.size(), 2)
	assert_eq(str((events[0] as Dictionary)["type"]), "spawn")
	DirAccess.remove_absolute(path)


func test_not_recording_ignores_events() -> void:
	var replay: StudioReplay = StudioReplay.new()
	replay.record("orphan", {})
	assert_eq(replay.events.size(), 0)


func test_load_rejects_wrong_schema() -> void:
	var dir: String = "user://replays"
	DirAccess.make_dir_recursive_absolute(dir)
	var path: String = dir + "/bad_schema.json"
	var file: FileAccess = FileAccess.open(path, FileAccess.WRITE)
	file.store_string(JSON.stringify({"header": {"schema": 999}, "events": []}))
	file.close()
	var replay: StudioReplay = StudioReplay.new()
	assert_eq(replay.load_replay(path), {}, "wrong schema must not load")
	DirAccess.remove_absolute(path)
