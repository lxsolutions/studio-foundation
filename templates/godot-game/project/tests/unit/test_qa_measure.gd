extends StudioTestCase

## The arithmetic that decides whether a visual QA capture FAILS a build, run
## against synthetic images so it needs no renderer. The capture runner
## (qa_capture.gd) is a thin shell around these functions; if they are right,
## the gate's verdicts are right.


func _flat(width: int, height: int, color: Color) -> Image:
	var image := Image.create_empty(width, height, false, Image.FORMAT_RGBA8)
	image.fill(color)
	return image


func test_luma_of_extremes() -> void:
	assert_eq(StudioQaMeasure.luma_mean(_flat(24, 24, Color.BLACK), 1), 0.0)
	var white := StudioQaMeasure.luma_mean(_flat(24, 24, Color.WHITE), 1)
	assert_true(absf(white - 255.0) < 0.5, "white frame must read ~255, got %f" % white)


func test_luma_weighs_green_over_blue() -> void:
	# Rec.709: green carries most of perceived brightness. A checker of pure
	# green must read brighter than the same of pure blue.
	var green := StudioQaMeasure.luma_mean(_flat(16, 16, Color(0, 1, 0)), 1)
	var blue := StudioQaMeasure.luma_mean(_flat(16, 16, Color(0, 0, 1)), 1)
	assert_true(green > blue * 3.0, "green %f should dwarf blue %f" % [green, blue])


func test_saturation_of_gray_is_zero_and_of_red_is_one() -> void:
	assert_eq(StudioQaMeasure.saturation_mean(_flat(16, 16, Color(0.5, 0.5, 0.5)), 1), 0.0)
	var red := StudioQaMeasure.saturation_mean(_flat(16, 16, Color(1, 0, 0)), 1)
	assert_true(absf(red - 1.0) < 0.01, "pure red must be fully saturated")


func test_probe_reads_the_right_region() -> void:
	var image := _flat(40, 40, Color.BLACK)
	image.fill_rect(Rect2i(20, 0, 20, 40), Color(1, 0, 0))
	var left := StudioQaMeasure.probe_color(image, Vector2(0.2, 0.5), 2)
	var right := StudioQaMeasure.probe_color(image, Vector2(0.8, 0.5), 2)
	assert_true(left.r < 0.1, "left probe must be black")
	assert_true(right.r > 0.9, "right probe must be red")


func test_probe_box_average_survives_one_hot_pixel() -> void:
	# A probe defeated by a single antialiased or sparkly pixel is a flaky
	# gate; the box average is the flake-proofing.
	var image := _flat(30, 30, Color(0, 0, 1))
	image.set_pixel(15, 15, Color(1, 1, 1))
	var probe := StudioQaMeasure.probe_color(image, Vector2(0.5, 0.5), 2)
	assert_true(probe.b > 0.9, "one white pixel must not flip a blue probe")


func test_check_frame_bounds_and_probes() -> void:
	var dark := _flat(24, 24, Color(0.02, 0.02, 0.02))
	var findings := StudioQaMeasure.check_frame(dark, {"luma_min": 40.0})
	assert_eq(findings.size(), 1)
	assert_eq(str(findings[0]["check"]), "luma_low")

	var white := _flat(24, 24, Color.WHITE)
	findings = StudioQaMeasure.check_frame(white, {"luma_max": 200.0, "sat_min": 0.05})
	assert_eq(findings.size(), 2, "a white frame is both too bright and a gray wash")

	var blue := _flat(24, 24, Color(0, 0, 1))
	findings = StudioQaMeasure.check_frame(blue, {
		"probes": [{"at": [0.5, 0.5], "expect": [0, 0, 255], "tol": 20, "label": "sky"}],
	})
	assert_eq(findings.size(), 0, "matching probe must pass")
	findings = StudioQaMeasure.check_frame(blue, {
		"probes": [{"at": [0.5, 0.5], "expect": [255, 120, 0], "tol": 40, "label": "sand"}],
	})
	assert_eq(findings.size(), 1, "a blue frame is not sand")
	assert_eq(str(findings[0]["label"]), "sand")


func test_check_frame_empty_spec_checks_nothing() -> void:
	var findings := StudioQaMeasure.check_frame(_flat(8, 8, Color.BLACK), {})
	assert_eq(findings.size(), 0, "no declared intent, no findings")


func test_controls_inside_pass_and_overhang_fails() -> void:
	var viewport := Rect2(0, 0, 1280, 720)
	var findings := StudioQaMeasure.check_controls([
		{"name": "Banner", "rect": Rect2(400, 10, 480, 60), "tap": false},
	], viewport)
	assert_eq(findings.size(), 0)

	findings = StudioQaMeasure.check_controls([
		{"name": "RunningOrder", "rect": Rect2(20, 700, 200, 90), "tap": false},
	], viewport)
	assert_eq(findings.size(), 1, "a control off the bottom edge must be flagged")
	assert_eq(str(findings[0]["check"]), "hud_offscreen")
	assert_eq(float(findings[0]["actual"]), 70.0, "overhang is 700+90-720")


func test_controls_margin_tolerates_small_overhang() -> void:
	var viewport := Rect2(0, 0, 100, 100)
	var controls := [{"name": "Edge", "rect": Rect2(-3, 10, 20, 20), "tap": false}]
	assert_eq(StudioQaMeasure.check_controls(controls, viewport, {"margin": 4.0}).size(), 0)
	assert_eq(StudioQaMeasure.check_controls(controls, viewport, {"margin": 1.0}).size(), 1)


func test_collapsed_control_is_its_own_finding() -> void:
	var findings := StudioQaMeasure.check_controls([
		{"name": "Ghost", "rect": Rect2(10, 10, 0, 0), "tap": false},
	], Rect2(0, 0, 100, 100))
	assert_eq(findings.size(), 1)
	assert_eq(str(findings[0]["check"]), "hud_empty")


func test_tap_targets_are_judged_in_physical_pixels() -> void:
	# The phone bug this exists for: a HUD authored in 1280-wide canvas units
	# rendered on a 390 px window puts ~0.3 physical px on every canvas unit,
	# so a 50-unit button is a 15 px target. px_per_unit carries that scale.
	var viewport := Rect2(0, 0, 1280, 720)
	var controls := [{"name": "Whip", "rect": Rect2(600, 600, 50, 50), "tap": true}]
	var findings := StudioQaMeasure.check_controls(controls, viewport, {"px_per_unit": 0.3})
	assert_eq(findings.size(), 1, "a 15 px tap target must fail")
	assert_eq(str(findings[0]["check"]), "tap_target_small")
	findings = StudioQaMeasure.check_controls(controls, viewport, {"px_per_unit": 1.0})
	assert_eq(findings.size(), 0, "the same control at desktop scale is fine")


func test_untouched_controls_skip_the_tap_floor() -> void:
	var findings := StudioQaMeasure.check_controls([
		{"name": "StatusDot", "rect": Rect2(10, 10, 8, 8), "tap": false},
	], Rect2(0, 0, 100, 100), {"px_per_unit": 1.0})
	assert_eq(findings.size(), 0, "non-tap HUD may be small")


func test_sibling_overlap_is_flagged_and_separation_is_not() -> void:
	# The first real catch: a centered title panel and a corner door colliding
	# at phone width. Same-level HUD blocks may not share pixels.
	var findings := StudioQaMeasure.check_overlaps([
		{"name": "TopPanel", "rect": Rect2(104, 12, 311, 70)},
		{"name": "ReinsDoor", "rect": Rect2(358, 12, 150, 70)},
	])
	assert_eq(findings.size(), 1, "a 57-unit collision must be flagged")
	assert_eq(str(findings[0]["check"]), "hud_overlap")

	findings = StudioQaMeasure.check_overlaps([
		{"name": "TopPanel", "rect": Rect2(104, 12, 311, 70)},
		{"name": "ReinsDoor", "rect": Rect2(358, 100, 150, 70)},
	])
	assert_eq(findings.size(), 0, "the dropped door clears the panel")


func test_overlap_margin_tolerates_a_kiss() -> void:
	# Stacked bars may touch by a unit or two without being a layout bug.
	var controls := [
		{"name": "MyLine", "rect": Rect2(0, 898, 200, 28)},
		{"name": "EnergyBar", "rect": Rect2(0, 924, 220, 14)},
	]
	assert_eq(StudioQaMeasure.check_overlaps(controls).size(), 0,
		"a 2-unit kiss sits inside the default margin")
	assert_eq(StudioQaMeasure.check_overlaps(controls, {"overlap_margin": 0.5}).size(), 1,
		"a strict margin flags the same pair")
