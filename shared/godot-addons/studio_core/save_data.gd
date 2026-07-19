class_name StudioSaveData
extends RefCounted
## Save-data interface: versioned envelopes, atomic writes, slot management.
## Local-file implementation; server-backed saves implement the same surface
## via StudioSession later. Never store secrets in saves.

const SCHEMA_VERSION: int = 1

var save_dir: String = "user://saves"


func slot_path(slot: String) -> String:
	return "%s/%s.json" % [save_dir, slot]


func save_slot(slot: String, data: Dictionary) -> Error:
	DirAccess.make_dir_recursive_absolute(save_dir)
	var envelope: Dictionary = {
		"schema_version": SCHEMA_VERSION,
		"saved_frame": Engine.get_process_frames(),
		"data": data,
	}
	var tmp_path: String = slot_path(slot) + ".tmp"
	var file: FileAccess = FileAccess.open(tmp_path, FileAccess.WRITE)
	if file == null:
		return FileAccess.get_open_error()
	file.store_string(JSON.stringify(envelope, "  "))
	file.close()
	# Atomic-ish replace: rename over the old file.
	var dir: DirAccess = DirAccess.open(save_dir)
	if dir == null:
		return ERR_CANT_OPEN
	if FileAccess.file_exists(slot_path(slot)):
		dir.remove(slot_path(slot).get_file())
	return dir.rename(tmp_path.get_file(), slot_path(slot).get_file())


func load_slot(slot: String) -> Dictionary:
	var path: String = slot_path(slot)
	if not FileAccess.file_exists(path):
		return {}
	var file: FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not (parsed is Dictionary):
		return {}
	var envelope: Dictionary = parsed
	var version: int = int(envelope.get("schema_version", 0))
	if version > SCHEMA_VERSION:
		push_warning("save %s from newer schema %d" % [slot, version])
		return {}
	# Migration hook: when SCHEMA_VERSION grows, upgrade older envelopes here.
	var data: Variant = envelope.get("data", {})
	return data if data is Dictionary else {}


func list_slots() -> PackedStringArray:
	var slots: PackedStringArray = []
	var dir: DirAccess = DirAccess.open(save_dir)
	if dir == null:
		return slots
	for file_name in dir.get_files():
		if file_name.ends_with(".json"):
			slots.append(file_name.trim_suffix(".json"))
	return slots


func delete_slot(slot: String) -> void:
	if FileAccess.file_exists(slot_path(slot)):
		DirAccess.remove_absolute(slot_path(slot))
