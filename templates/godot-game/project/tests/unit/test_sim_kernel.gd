extends StudioTestCase
## StudioSimKernel — the parts that hold on every platform.
##
## The browser half is proven where it actually runs, by
## tests/browser/sim-kernel-host.mjs, which drives the same
## addons/studio_core/sim/sim_kernel_host.js this class injects. What is left to
## check headlessly is the part that has no platform in it: the backend
## decision, the one result shape every host is normalized into, and the refusals
## a caller meets before anything is loaded.


func test_backend_follows_the_platform() -> void:
	assert_eq(StudioSimKernel.backend_for({"web": true}), StudioSimKernel.BACKEND_WEB)
	assert_eq(StudioSimKernel.backend_for({"web": false}), StudioSimKernel.BACKEND_NATIVE)
	assert_eq(
		StudioSimKernel.backend_for({}),
		StudioSimKernel.BACKEND_NATIVE,
		"an unknown platform must not be assumed to be a browser"
	)


func test_parse_result_passes_a_kernel_result_through() -> void:
	var parsed: Dictionary = StudioSimKernel.parse_result(
		'{"state_hash": "abc", "navigation": {"gate": false}}'
	)
	assert_eq(parsed.get("state_hash"), "abc")
	assert_false(parsed.has("code"), "a good result must not gain an error code")


func test_parse_result_preserves_a_kernel_rejection() -> void:
	## The kernel's own codes must survive untouched — a host that rewrote them
	## would make conformance fixtures unverifiable from Godot.
	var parsed: Dictionary = StudioSimKernel.parse_result(
		'{"error": "seed must be an integer", "code": "bad_seed"}'
	)
	assert_eq(parsed.get("code"), "bad_seed")


func test_parse_result_reports_non_json_output_as_a_host_failure() -> void:
	## What a crashed runner or an HTML error page looks like. It must not be
	## mistaken for the kernel disagreeing about a replay.
	var parsed: Dictionary = StudioSimKernel.parse_result("<!doctype html><h1>502</h1>")
	assert_eq(parsed.get("code"), "host_bad_output")
	assert_has(str(parsed.get("error")), "502", "the failure should quote what it saw")


func test_parse_result_rejects_json_that_is_not_an_object() -> void:
	for raw in ["[1, 2, 3]", "42", '"a string"', "null"]:
		assert_eq(
			StudioSimKernel.parse_result(raw).get("code"),
			"host_bad_output",
			"non-object JSON must be refused: " + raw
		)


func test_parse_result_reports_empty_output() -> void:
	assert_eq(StudioSimKernel.parse_result("").get("code"), "host_empty_output")
	assert_eq(StudioSimKernel.parse_result("   \n ").get("code"), "host_empty_output")


func test_running_before_loading_is_answered_not_crashed() -> void:
	var kernel: StudioSimKernel = StudioSimKernel.new()
	var result: Dictionary = kernel.run('{"sim_replay": "0.1"}')
	assert_eq(result.get("code"), "host_not_ready")
	assert_false(kernel.is_ready(), "an unloaded kernel is not ready")


func test_a_native_backend_without_a_runner_says_how_to_get_one() -> void:
	var kernel: StudioSimKernel = StudioSimKernel.new()
	if StudioSimKernel.backend_for(StudioPlatform.detect()) != StudioSimKernel.BACKEND_NATIVE:
		return  # web build: the browser suite covers this path
	assert_eq(kernel.load_kernel(""), StudioSimKernel.STATUS_UNAVAILABLE)
	assert_has(kernel.error_text(), "cargo build -p sim-kernel")


func test_a_missing_runner_path_is_reported_not_silently_pending() -> void:
	var kernel: StudioSimKernel = StudioSimKernel.new()
	if StudioSimKernel.backend_for(StudioPlatform.detect()) != StudioSimKernel.BACKEND_NATIVE:
		return
	assert_eq(
		kernel.load_kernel("user://definitely-not-a-runner"),
		StudioSimKernel.STATUS_UNAVAILABLE
	)
	assert_has(kernel.error_text(), "not found")


func test_the_browser_host_script_ships_with_the_addon() -> void:
	## A .js file is not a Godot resource: it reaches an export only through the
	## preset's include_filter. If this fails in an exported build, the web
	## backend cannot load at all — so fail here, where the cause is legible.
	var source: String = FileAccess.get_file_as_string(StudioSimKernel.HOST_JS)
	assert_false(source.is_empty(), "%s did not ship" % StudioSimKernel.HOST_JS)
	assert_has(source, StudioSimKernel.HOST_NAMESPACE, "host script must register the namespace")
	assert_has(
		source,
		"contract: %d" % StudioSimKernel.HOST_CONTRACT,
		"host script contract must match HOST_CONTRACT"
	)
