class_name StudioTestCase
extends RefCounted
## Minimal headless test harness base. Test scripts extend this, define
## `func test_*() -> void` methods, and use the assert_* helpers. The runner
## (res://tests/run_tests.gd) discovers scripts at runtime via load() so a
## parse error in one test file reports as a failure instead of hanging the
## suite (hard-won lesson: preload-chain parse errors fail silently).
##
## GdUnit4 adoption is tracked in docs/adr/0011 — this harness is intentionally
## tiny and dependency-free for bootstrap; its assert surface is a subset of
## GdUnit4's so migration is mechanical.

var _failures: PackedStringArray = []
var _assert_count: int = 0


func failures() -> PackedStringArray:
	return _failures


func assert_count() -> int:
	return _assert_count


func fail(message: String) -> void:
	_failures.append(message)


func assert_true(condition: bool, message: String = "expected true") -> void:
	_assert_count += 1
	if not condition:
		_failures.append(message)


func assert_false(condition: bool, message: String = "expected false") -> void:
	assert_true(not condition, message)


func assert_eq(actual: Variant, expected: Variant, message: String = "") -> void:
	_assert_count += 1
	if not _deep_eq(actual, expected):
		var detail: String = "expected `%s` == `%s`" % [str(actual), str(expected)]
		_failures.append(message + " — " + detail if not message.is_empty() else detail)


func assert_ne(actual: Variant, expected: Variant, message: String = "") -> void:
	_assert_count += 1
	if _deep_eq(actual, expected):
		var detail: String = "expected `%s` != `%s`" % [str(actual), str(expected)]
		_failures.append(message + " — " + detail if not message.is_empty() else detail)


func assert_has(container: Variant, key: Variant, message: String = "") -> void:
	_assert_count += 1
	var has_it: bool = false
	if container is Dictionary:
		has_it = (container as Dictionary).has(key)
	elif container is Array:
		has_it = (container as Array).has(key)
	elif container is String:
		has_it = (container as String).contains(str(key))
	if not has_it:
		var detail: String = "expected container to include `%s`" % str(key)
		_failures.append(message + " — " + detail if not message.is_empty() else detail)


## JSON-ish deep equality that treats int/float numerics loosely (JSON parses
## all numbers as float — mirrors the Rust Value comparison semantics).
func _deep_eq(a: Variant, b: Variant) -> bool:
	if a is Dictionary and b is Dictionary:
		var da: Dictionary = a
		var db: Dictionary = b
		if da.size() != db.size():
			return false
		for key in da.keys():
			if not db.has(key) or not _deep_eq(da[key], db[key]):
				return false
		return true
	if a is Array and b is Array:
		var aa: Array = a
		var ab: Array = b
		if aa.size() != ab.size():
			return false
		for i in aa.size():
			if not _deep_eq(aa[i], ab[i]):
				return false
		return true
	if (a is int or a is float) and (b is int or b is float):
		return is_equal_approx(float(a), float(b))
	return a == b
