class_name StudioReplay
extends RefCounted
## Replay/event-recording foundation. Records (frame, type, data) events plus
## the run seed; deterministic systems can be re-driven from a loaded replay.
## This is the *foundation* — per-game determinism contracts live with games.

const REPLAY_DIR: String = "user://replays"
const SCHEMA: int = 1

var recording: bool = false
var header: Dictionary = {}
var events: Array[Dictionary] = []


func begin(run_seed: int, meta: Dictionary = {}) -> void:
	recording = true
	events.clear()
	header = {
		"schema": SCHEMA,
		"run_seed": run_seed,
		"meta": meta,
		"engine": Engine.get_version_info().get("string", "?"),
	}


func record(event_type: String, data: Dictionary = {}) -> void:
	if not recording:
		return
	events.append({
		"frame": Engine.get_physics_frames(),
		"type": event_type,
		"data": data,
	})


func end_and_save(replay_name: String = "") -> String:
	recording = false
	if replay_name.is_empty():
		replay_name = "replay_%d" % Time.get_ticks_msec()
	DirAccess.make_dir_recursive_absolute(REPLAY_DIR)
	var path: String = "%s/%s.json" % [REPLAY_DIR, replay_name]
	var file: FileAccess = FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return ""
	file.store_string(JSON.stringify({"header": header, "events": events}))
	return path


## Returns { header: Dictionary, events: Array } or {} on failure.
func load_replay(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var file: FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not (parsed is Dictionary):
		return {}
	var replay: Dictionary = parsed
	var replay_header: Variant = replay.get("header", {})
	if not (replay_header is Dictionary) or int((replay_header as Dictionary).get("schema", 0)) != SCHEMA:
		return {}
	return replay
