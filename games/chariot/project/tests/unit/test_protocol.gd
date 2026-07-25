extends StudioTestCase
## Cross-language protocol contract: the SAME golden fixtures the Rust suite
## uses (synced into the addon by tools/godot/sync_addons.py).

const FIXTURES_DIR: String = "res://addons/studio_core/testing/fixtures"


func test_golden_fixtures() -> void:
	var dir: DirAccess = DirAccess.open(FIXTURES_DIR)
	assert_true(dir != null, "fixtures dir missing — run: just godot-sync-addons")
	if dir == null:
		return
	var checked: int = 0
	for file_name in dir.get_files():
		if not file_name.ends_with(".json"):
			continue
		var file: FileAccess = FileAccess.open(FIXTURES_DIR + "/" + file_name, FileAccess.READ)
		assert_true(file != null, "fixture unreadable: " + file_name)
		if file == null:
			continue
		var raw: String = file.get_as_text()
		var result: Dictionary = StudioProtocol.decode(raw)
		var expect_invalid: bool = file_name.begins_with("invalid_")
		if expect_invalid:
			assert_false(bool(result["ok"]), file_name + " must be rejected")
		else:
			assert_true(bool(result["ok"]), file_name + " must decode: " + str(result["error"]))
			if bool(result["ok"]):
				var reencoded: Variant = JSON.parse_string(StudioProtocol.encode(result["envelope"]))
				var original: Variant = JSON.parse_string(raw)
				assert_eq(reencoded, original, file_name + " re-encode mismatch")
		checked += 1
	assert_true(checked >= 5, "expected >=5 fixtures, checked %d" % checked)


func test_hello_builder_matches_version() -> void:
	var envelope: Dictionary = StudioProtocol.hello(1, "test", "0.0.0")
	assert_eq(int(envelope["v"]), StudioProtocol.PROTOCOL_VERSION)
	assert_eq(int(envelope["protocol"]), StudioProtocol.PROTOCOL_VERSION)
	var decoded: Dictionary = StudioProtocol.decode(StudioProtocol.encode(envelope))
	assert_true(bool(decoded["ok"]), "hello must round-trip")


func test_decode_rejects_garbage() -> void:
	assert_false(bool(StudioProtocol.decode("{nope")["ok"]))
	assert_false(bool(StudioProtocol.decode("[1,2,3]")["ok"]))
	assert_false(bool(StudioProtocol.decode("{\"v\":1}")["ok"]), "missing fields")
