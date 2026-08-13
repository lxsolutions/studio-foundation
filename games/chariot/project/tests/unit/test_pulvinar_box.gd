extends StudioTestCase
## The Emperor's Box is placed by arithmetic, not by eye: the pulvinar sits at
## the home straight's midpoint, above the spina line, hanging off the podium
## face INSIDE the cavea's span. And the verdict is a state machine, not a
## moment: it fires once on the finish (the wire carries no wreck signal) and
## a new parade re-arms it. Both halves are pinned here so a spec move or a
## wiring slip fails loudly instead of shipping a floating booth or a silent
## emperor.

const EPS := 0.05


func test_box_centered_on_the_home_straight() -> void:
	# The home straight runs at z=-radius with s in [0, straight); the box sits
	# at its midpoint — x=0 on the near side, ahead of the finish post.
	assert_true(is_equal_approx(PulvinarBox.box_s(), TrackGeometry.straight_length() * 0.5),
		"the box centres on the home straight's midpoint")
	assert_true(PulvinarBox.box_s() < TrackGeometry.finish_s(),
		"the box stands mid-straight, before the finish line")
	var anchor: Transform3D = PulvinarBox.anchor_transform()
	assert_true(absf(anchor.origin.x) <= EPS,
		"the box is centred on the straight (x=%.3f)" % anchor.origin.x)
	var radius: float = TrackGeometry.turn_radius()
	assert_true(anchor.origin.z < -radius,
		"the box stands off the near (home) side of the sand (z=%.2f)" % anchor.origin.z)
	# Facing the sand: local -Z must point back toward the infield (+z world
	# on the home straight).
	var facing: Vector3 = -anchor.basis.z
	assert_true(facing.z > 0.9, "the box looks out over the track, not into the seats")


func test_box_within_the_cavea_span() -> void:
	# Off the sand, on the building: the platform must clear the outer rail and
	# stay inside the cavea's front-to-back run, with the floor above the
	# podium wall and below the seating's top course.
	var spec: Dictionary = TrackGeometry.spec()
	var stands: Dictionary = spec.get("stands", {})
	var outer_rail := (float(spec.rail_outer_offset_lanes) - 1.0) * float(spec.lane_width_m) + 1.1
	var podium := PulvinarBox.podium_offset()
	var cavea_back := podium + float(stands.get("tiers", 5)) * float(stands.get("tier_depth_m", 7.0))
	assert_true(PulvinarBox.front_offset() > outer_rail,
		"the platform clears the outer rail (%.1f vs %.1f)" % [PulvinarBox.front_offset(), outer_rail])
	assert_true(PulvinarBox.front_offset() < podium,
		"the platform projects off the podium face toward the sand")
	assert_true(PulvinarBox.back_offset() > podium and PulvinarBox.back_offset() < cavea_back,
		"the platform's rear embeds in the cavea, inside its span")
	var floor_h := PulvinarBox.floor_top()
	var podium_h := float(stands.get("podium_height_m", 3.4))
	var cavea_top := podium_h + float(stands.get("tiers", 5)) \
		* (float(stands.get("tier_rise_m", 4.2)) + float(stands.get("tier_riser_m", 2.2)))
	assert_true(floor_h > podium_h, "the floor rides above the podium wall")
	assert_true(floor_h < cavea_top, "the box stays below the cavea's top course")
	var anchor: Transform3D = PulvinarBox.anchor_transform()
	assert_true(absf(anchor.origin.y - floor_h) <= EPS, "the anchor sits on the box floor")


func _build_box() -> PulvinarBox:
	var box := PulvinarBox.new()
	# Not added to the tree: build() is the whole construction pass, mirroring
	# how the crowd tests drive CrowdDirector in isolation.
	box.build()
	return box


func test_emperor_rests_seated() -> void:
	var box := _build_box()
	assert_false(box.emperor_risen(), "the emperor opens the race on his throne")
	assert_false(box.is_posing(), "no verdict before the decisive beat")
	assert_eq(box.times_delivered, 0, "no verdict delivered at build")
	box.free()


func test_verdict_fires_once_per_race_and_rearms() -> void:
	var box := _build_box()
	box.note_phase(RaceState.PHASE_PARADING)
	box.note_phase(RaceState.PHASE_RUNNING)
	assert_eq(box.times_delivered, 0, "the build-up never triggers the verdict")
	box.note_phase(RaceState.PHASE_FINISHED)
	assert_eq(box.times_delivered, 1, "the finish delivers the verdict")
	assert_true(box.emperor_risen(), "the emperor rises for the verdict")
	assert_true(box.is_posing(), "the pose holds while the laurel board is up")
	# A repeated finished signal (phase re-announce, hello replay) must not
	# fire it again.
	box.note_phase(RaceState.PHASE_FINISHED)
	assert_eq(box.times_delivered, 1, "the verdict fires once per race")
	# The next race's parade re-arms it, and the emperor is seated again.
	box.note_phase(RaceState.PHASE_PARADING)
	assert_false(box.emperor_risen(), "a new parade settles the emperor back")
	box.note_phase(RaceState.PHASE_RUNNING)
	box.note_phase(RaceState.PHASE_FINISHED)
	assert_eq(box.times_delivered, 2, "the next race gets its own verdict")
	box.free()


func test_the_front_rows_break_for_the_box() -> void:
	# The notch and the masonry are the same arithmetic: tier-0 seats inside
	# the box's arc on the home straight must not exist, and the same rows
	# just outside the arc must — an empty house would pass a vacuous pin.
	var podium := PulvinarBox.podium_offset()
	var spec: Dictionary = TrackGeometry.spec()
	var stands: Dictionary = spec.get("stands", {})
	var tier_depth := float(stands.get("tier_depth_m", 7.0))
	assert_true(PulvinarBox.blocks_seat(PulvinarBox.box_s(), podium + tier_depth * 0.5),
		"the box's own seat is blocked")
	assert_false(PulvinarBox.blocks_seat(PulvinarBox.box_s() + 20.0, podium + tier_depth * 0.5),
		"the front rows resume twenty metres along the straight")
	assert_false(PulvinarBox.blocks_seat(PulvinarBox.box_s(), podium + tier_depth + 1.0),
		"the second tier seats above the box")
	var director := CrowdDirector.new()
	director.build()
	var blocked := 0
	var neighbours := 0
	var loop := TrackGeometry.loop_length()
	for seat in director.seat_positions:
		var off: float = _lateral_offset(seat)
		# Only tier-0 heights concern the notch.
		if off < podium - 0.1 or off > podium + tier_depth + 0.1:
			continue
		var s := _arc_length_on_home_straight(seat)
		if s < 0.0:
			continue
		var ds := absf(fposmod(s - PulvinarBox.box_s() + loop * 0.5, loop) - loop * 0.5)
		if ds < PulvinarBox.SEAT_NOTCH_HALF_WIDTH_M - 0.2:
			blocked += 1
		elif ds < PulvinarBox.SEAT_NOTCH_HALF_WIDTH_M + 8.0:
			neighbours += 1
	assert_eq(blocked, 0, "no spectator sits where the pulvinar stands")
	assert_true(neighbours > 20,
		"the rows flank the box — the notch is a break, not an empty straight (got %d)" % neighbours)
	director.free()


## A seat's lateral distance from the lane-1 centerline — the same recovery
## test_crowd_seating.gd uses.
func _lateral_offset(p: Vector3) -> float:
	var radius: float = TrackGeometry.turn_radius()
	var half: float = TrackGeometry.straight_length() / 2.0
	var x := absf(p.x)
	if x <= half:
		return absf(p.z) - radius
	return Vector2(x - half, p.z).length() - radius


## Arc length along the loop for a seat ON the home straight, or -1 for
## anywhere else (the far straight and the turns).
func _arc_length_on_home_straight(p: Vector3) -> float:
	var half: float = TrackGeometry.straight_length() / 2.0
	if absf(p.x) > half or p.z > 0.0:
		return -1.0
	return p.x + half
