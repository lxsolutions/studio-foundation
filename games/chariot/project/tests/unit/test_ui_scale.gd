extends StudioTestCase

## StudioUiScale decides how hard a phone-sized window scales the UI back up.
## Wrong in one direction the HUD renders at 30% with 10 px tap targets
## (measured, shipped); wrong in the other the widest HUD block no longer
## fits. These pin the arithmetic at the three device classes the QA gate
## photographs.

const DESIGN := Vector2(1280.0, 720.0)
const MIN_VISIBLE := Vector2(480.0, 640.0)


func test_desktop_is_untouched() -> void:
	var factor := StudioUiScale.content_scale_for(Vector2i(1280, 720), DESIGN, MIN_VISIBLE)
	assert_eq(factor, 1.0, "authored size on the authored window")


func test_large_desktop_never_scales_down() -> void:
	var factor := StudioUiScale.content_scale_for(Vector2i(2560, 1440), DESIGN, MIN_VISIBLE)
	assert_eq(factor, 1.0, "a big monitor keeps factor 1 — expand grows the canvas instead")


func test_phone_scales_up_but_keeps_min_visible() -> void:
	var window := Vector2i(390, 844)
	var factor := StudioUiScale.content_scale_for(window, DESIGN, MIN_VISIBLE)
	assert_true(factor > 2.5, "a 390 px window needs a strong lift, got %f" % factor)
	# Physical pixels per design unit, after the lift.
	var base := minf(window.x / DESIGN.x, window.y / DESIGN.y)
	var px_per_unit := base * factor
	assert_true(px_per_unit >= 0.8, "UI must land near authored size, got %f" % px_per_unit)
	# The visible design area may not shrink below what the HUD needs.
	var visible_x := window.x / px_per_unit
	assert_true(visible_x >= MIN_VISIBLE.x - 0.5,
		"visible width %f may not undercut the widest HUD block" % visible_x)


func test_tablet_lands_at_authored_size() -> void:
	var window := Vector2i(1024, 768)
	var factor := StudioUiScale.content_scale_for(window, DESIGN, MIN_VISIBLE)
	var base := minf(window.x / DESIGN.x, window.y / DESIGN.y)
	assert_true(absf(base * factor - 1.0) < 0.01,
		"a tablet can afford authored-size UI exactly")


func test_degenerate_inputs_fall_back_to_one() -> void:
	assert_eq(StudioUiScale.content_scale_for(Vector2i(0, 0), DESIGN, MIN_VISIBLE), 1.0)
	assert_eq(StudioUiScale.content_scale_for(Vector2i(390, 844), Vector2.ZERO, MIN_VISIBLE), 1.0)
	assert_eq(StudioUiScale.content_scale_for(Vector2i(390, 844), DESIGN, Vector2.ZERO), 1.0)
