extends StudioTestCase
## The crowd sits ON the cavea, never above it. The mesh generator
## (art_source/build_hippodrome.py, cavea_profile) sweeps the seating surface
## from the stands block of track_spec.json; the director must seat every
## figure — origin at the mesh's bottom pivot — exactly on one of those
## treads. This shipped wrong once: stale offsets (+1.2 m outward, a half-row
## fraction mismatch, +0.55 m of lift) left the whole house hovering in front
## of the stands, the top row above the back wall. The fix is arithmetic, so
## the pin is arithmetic: height on a tread top, depth inside the tread run
## of the SAME tier.

const HEIGHT_EPS := 0.02
const DEPTH_EPS := 0.02


## The tread surfaces exactly as cavea_profile cuts them: one entry per row,
## { tier, height, lo, hi } where [lo, hi] is the lateral run the tread spans
## (front edge to back edge) measured from the lane-1 centerline.
func _treads(director: CrowdDirector) -> Array[Dictionary]:
	var stands: Dictionary = director.stands_spec()
	var podium: float = director.podium_offset()
	var depth := float(stands.tier_depth_m)
	var rise := float(stands.tier_rise_m)
	var riser := float(stands.tier_riser_m)
	var rows := int(stands.rows_per_tier)
	var out: Array[Dictionary] = []
	for tier in int(stands.tiers):
		var floor_h := float(stands.podium_height_m) + tier * (rise + riser) + riser
		for row in rows:
			out.append({
				"tier": tier,
				"height": floor_h + row * rise / rows,
				"lo": podium + tier * depth + row * depth / rows,
				"hi": podium + tier * depth + (row + 1) * depth / rows,
			})
	return out


## A seat's lateral distance from the lane-1 centerline, recovered from its
## world position. The centerline is a stadium (two straights, two
## semicircles); every seat lies outward of it, so the distance is exact.
func _lateral_offset(p: Vector3) -> float:
	var radius: float = TrackGeometry.turn_radius()
	var half: float = TrackGeometry.straight_length() / 2.0
	var x := absf(p.x)
	if x <= half:
		return absf(p.z) - radius
	return Vector2(x - half, p.z).length() - radius


func _build_director() -> CrowdDirector:
	var director := CrowdDirector.new()
	# Not added to the tree: build() is the whole seating pass, and an
	# isolated director reads a full house (crowd_density falls back to 1.0).
	director.build()
	return director


func test_house_is_not_empty() -> void:
	var director := _build_director()
	assert_true(director.seat_positions.size() > 1000,
		"a full house seats thousands, got %d" % director.seat_positions.size())
	director.free()


func test_every_seat_sits_on_a_tread() -> void:
	var director := _build_director()
	var treads := _treads(director)
	var heights: Array[float] = []
	for tread in treads:
		heights.append(float(tread.height))
	var unmatched := 0
	for seat in director.seat_positions:
		var on_a_tread := false
		for h in heights:
			if absf(seat.y - h) <= HEIGHT_EPS:
				on_a_tread = true
				break
		if not on_a_tread:
			unmatched += 1
	assert_eq(unmatched, 0,
		"spectators floating off every tread top (first at y=%.3f, nearest treads %.3f/%.3f)"
		% [
			(director.seat_positions[0] as Vector3).y if not director.seat_positions.is_empty() else -1.0,
			heights[0], heights[heights.size() - 1],
		])
	director.free()


func test_every_seat_lies_within_its_own_tiers_run() -> void:
	var director := _build_director()
	var treads := _treads(director)
	var astray := 0
	for seat in director.seat_positions:
		# Every (tier, row) tread top is a distinct height — tier bands never
		# overlap and rows step rise/rows apart — so a seat's height names
		# exactly one tread, and its lateral offset must fall inside THAT
		# tread's span. This is what the old +1.2 m drift broke: the figure
		# hung past the tread's front edge, over the drop.
		var found := false
		var lo := 0.0
		var hi := 0.0
		for tread in treads:
			if absf(seat.y - float(tread.height)) <= HEIGHT_EPS:
				found = true
				lo = float(tread.lo)
				hi = float(tread.hi)
				break
		if not found:
			astray += 1
			continue
		var off := _lateral_offset(seat)
		if off < lo - DEPTH_EPS or off > hi + DEPTH_EPS:
			astray += 1
	assert_eq(astray, 0,
		"spectators seated outside the span of the tread their height names")
	director.free()


func test_first_and_last_tread_match_the_generator_profile() -> void:
	# The two ends of the profile pin the formula itself: the first course
	# tops the podium wall plus one riser; the last sits one row-step below
	# the cavea top — never above it, where the top row used to hover.
	var director := _build_director()
	var treads := _treads(director)
	var stands: Dictionary = director.stands_spec()
	var podium_h := float(stands.podium_height_m)
	var riser := float(stands.tier_riser_m)
	assert_true(is_equal_approx(float(treads[0].height), podium_h + riser),
		"first tread tops the podium wall plus one riser")
	var tiers := float(stands.tiers)
	var rise := float(stands.tier_rise_m)
	var rows := float(stands.rows_per_tier)
	var cavea_top := podium_h + tiers * (rise + riser)
	var last_tread := float(treads[treads.size() - 1].height)
	assert_true(is_equal_approx(last_tread, cavea_top - rise / rows),
		"last tread is one row-step below the cavea top")
	var highest := -INF
	for seat in director.seat_positions:
		highest = maxf(highest, seat.y)
	assert_true(highest <= cavea_top - rise / rows + HEIGHT_EPS,
		"no spectator above the cavea's seating surface (highest %.3f, top tread %.3f)"
			% [highest, last_tread])
	director.free()
