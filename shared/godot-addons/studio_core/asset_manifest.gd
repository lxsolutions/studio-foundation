class_name StudioAssetManifest
extends RefCounted
## Asset bundle/version manifest: per-asset ids, content hashes, and the cook
## profile they were produced with. Written by `just asset-cook` (see
## tools/asset-pipeline). Games use it for integrity checks and streaming
## decisions; it is generated output, never edited.

const MANIFEST_PATH: String = "res://assets/generated/asset_manifest.json"

var manifest: Dictionary = {"schema": 1, "profile": "", "assets": {}}


func load_manifest(path: String = MANIFEST_PATH) -> bool:
	if not FileAccess.file_exists(path):
		return false
	var file: FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return false
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		manifest = parsed
		return true
	return false


func cooked_profile() -> String:
	return str(manifest.get("profile", ""))


func assets() -> Dictionary:
	var value: Variant = manifest.get("assets", {})
	return value if value is Dictionary else {}


func asset_hash(asset_id: String) -> String:
	var entry: Variant = assets().get(asset_id, {})
	if entry is Dictionary:
		return str((entry as Dictionary).get("source_hash", ""))
	return ""
