class_name StudioBuildInfo
extends RefCounted
## Build/version info. res://build_info.json is stamped by export tooling
## (tools/godot/export_game.py); dev runs fall back to sane defaults.

var version: String = "0.0.0-dev"
var git_commit: String = "uncommitted"
var built_at: String = "dev"
var channel: String = "dev"


func load_info(path: String = "res://build_info.json") -> void:
	if not FileAccess.file_exists(path):
		return
	var file: FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		var info: Dictionary = parsed
		version = str(info.get("version", version))
		git_commit = str(info.get("git_commit", git_commit))
		built_at = str(info.get("built_at", built_at))
		channel = str(info.get("channel", channel))


func describe() -> String:
	return "%s (%s, %s) godot %s" % [
		version, git_commit.substr(0, 9), channel, Engine.get_version_info().get("string", "?")
	]
