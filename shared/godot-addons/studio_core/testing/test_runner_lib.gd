class_name StudioTestRunnerLib
extends RefCounted
## Shared runner logic used by every project's res://tests/run_tests.gd.
## Discovers res://tests/**/test_*.gd at RUNTIME (load(), not preload) so a
## parse error in one file becomes a reported failure, never a silent hang.


static func discover(root: String = "res://tests") -> PackedStringArray:
	var found: PackedStringArray = []
	_walk(root, found)
	found.sort()
	return found


static func _walk(dir_path: String, found: PackedStringArray) -> void:
	var dir: DirAccess = DirAccess.open(dir_path)
	if dir == null:
		return
	dir.list_dir_begin()
	var entry: String = dir.get_next()
	while not entry.is_empty():
		var full: String = dir_path + "/" + entry
		if dir.current_is_dir() and not entry.begins_with("."):
			_walk(full, found)
		elif entry.begins_with("test_") and entry.ends_with(".gd"):
			found.append(full)
		entry = dir.get_next()
	dir.list_dir_end()


## Runs all tests. Returns {files, methods, asserts, failures: Array[String]}.
static func run_all(paths: PackedStringArray) -> Dictionary:
	var totals: Dictionary = {"files": 0, "methods": 0, "asserts": 0, "failures": []}
	var failures: Array = totals["failures"]
	for path in paths:
		totals["files"] = int(totals["files"]) + 1
		var script: Variant = load(path)
		if script == null or not (script is GDScript):
			failures.append("%s: FAILED TO LOAD (parse error?)" % path)
			continue
		var gd: GDScript = script
		if not gd.can_instantiate():
			failures.append("%s: cannot instantiate (must extend StudioTestCase)" % path)
			continue
		var instance: Variant = gd.new()
		if not (instance is StudioTestCase):
			failures.append("%s: does not extend StudioTestCase" % path)
			continue
		var case: StudioTestCase = instance
		for method in gd.get_script_method_list():
			var method_name: String = str(method.get("name", ""))
			if not method_name.begins_with("test_"):
				continue
			totals["methods"] = int(totals["methods"]) + 1
			var before: int = case.failures().size()
			@warning_ignore("unsafe_method_access")
			case.call(method_name)
			var after: PackedStringArray = case.failures()
			for i in range(before, after.size()):
				failures.append("%s::%s — %s" % [path.get_file(), method_name, after[i]])
			print("  %s %s::%s" % ["PASS" if after.size() == before else "FAIL", path.get_file(), method_name])
		totals["asserts"] = int(totals["asserts"]) + case.assert_count()
	return totals
