extends SceneTree
## Headless test runner:
##   godot --headless --path project --script res://tests/run_tests.gd
## Prints a first-line marker immediately (a preload parse error elsewhere can
## otherwise hang silently), discovers tests at runtime, exits 0/1.


func _initialize() -> void:
	print("[tests] runner alive")
	var lib_script: Variant = load("res://addons/studio_core/testing/test_runner_lib.gd")
	if lib_script == null:
		push_error("[tests] studio_core addon missing — run: just godot-sync-addons")
		quit(2)
		return
	var paths: PackedStringArray = StudioTestRunnerLib.discover("res://tests")
	print("[tests] discovered %d test files" % paths.size())
	var totals: Dictionary = StudioTestRunnerLib.run_all(paths)
	var failures: Array = totals["failures"]
	print("[tests] files=%d methods=%d asserts=%d failures=%d" % [
		totals["files"], totals["methods"], totals["asserts"], failures.size(),
	])
	for failure in failures:
		printerr("[tests] FAIL " + str(failure))
	quit(1 if failures.size() > 0 else 0)
