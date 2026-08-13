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


## Which arm of the loop a world point belongs to: the near straight runs at
## z=-radius, the far at +radius, and each turn wraps its own centre at
## x=±half the straight — never the origin.
func _segment_of(p: Vector3) -> String:
	var half: float = TrackGeometry.straight_length() / 2.0
	if absf(p.x) <= half:
		return "near_straight" if p.z < 0.0 else "far_straight"
	return "east_turn" if p.x > 0.0 else "west_turn"


func test_house_rings_the_whole_loop() -> void:
	# The far-end float shipped because only the near straight was ever
	# eyeballed: seat math and mesh must agree on ALL FOUR arms of the loop.
	# Bucket every seat by arm; each arm must hold its share of the house and
	# every seat in it must sit on a tread inside that tread's lateral span.
	var director := _build_director()
	var treads := _treads(director)
	var buckets := {
		"near_straight": 0, "far_straight": 0, "east_turn": 0, "west_turn": 0,
	}
	var astray := {}
	for segment in buckets:
		astray[segment] = 0
	for seat in director.seat_positions:
		var segment := _segment_of(seat)
		buckets[segment] = int(buckets[segment]) + 1
		var on_tread := false
		for tread in treads:
			if absf(seat.y - float(tread.height)) <= HEIGHT_EPS:
				var off := _lateral_offset(seat)
				on_tread = off >= float(tread.lo) - DEPTH_EPS and off <= float(tread.hi) + DEPTH_EPS
				break
		if not on_tread:
			astray[segment] = int(astray[segment]) + 1
	var total := director.seat_positions.size()
	for segment in buckets:
		var share := float(buckets[segment]) / float(total)
		# Straights are 21% of the loop each, the turns 29%; demand 15%+
		# everywhere so a whole arm can never silently lose its house again.
		assert_true(share > 0.15,
			"%s holds %.1f%% of the house — a whole arm of the loop is unseated"
				% [segment, share * 100.0])
		assert_eq(int(astray[segment]), 0,
			"%s: spectators off every tread on this arm of the loop" % segment)
	director.free()


func test_every_seat_lies_within_the_cavea_span() -> void:
	# The reported bug in one assertion: the seating surface runs from the
	# podium front to the back wall — a seat outside that span floats over the
	# sand or behind the building, wherever on the loop it sits.
	var director := _build_director()
	var stands: Dictionary = director.stands_spec()
	var podium: float = director.podium_offset()
	var back := podium + float(stands.tiers) * float(stands.tier_depth_m)
	var outside := 0
	var worst_lo := INF
	var worst_hi := -INF
	for seat in director.seat_positions:
		var off := _lateral_offset(seat)
		worst_lo = minf(worst_lo, off)
		worst_hi = maxf(worst_hi, off)
		if off < podium - DEPTH_EPS or off > back + DEPTH_EPS:
			outside += 1
	assert_eq(outside, 0,
		"seats outside the cavea span (%.1f .. %.1f m): depth %.1f .. %.1f m"
			% [podium, back, worst_lo, worst_hi])
	director.free()


func test_shipped_mesh_matches_the_spec_oval() -> void:
	# The root cause of the floating crowd: the mesh was built from an OLD
	# track_spec (380 m straight / 110 m turn) while every runtime read the
	# new one (95/42) — seat math was right and the building was simply
	# somewhere else. Pin the shipped GLB's footprint to the spec so a stale
	# rebuild can never ship quietly again.
	var packed: PackedScene = load("res://assets/models/colosseum_track.glb")
	assert_true(packed != null, "colosseum_track.glb must load")
	var node: Node = packed.instantiate()
	var mesh_instance := node.find_child("*", true, false) as MeshInstance3D
	if mesh_instance == null and node is MeshInstance3D:
		mesh_instance = node
	assert_true(mesh_instance != null, "the track scene carries a mesh")
	var aabb: AABB = mesh_instance.get_aabb()
	node.free()
	var spec: Dictionary = TrackGeometry.spec()
	var stands: Dictionary = spec.get("stands", {})
	var podium := (float(spec.rail_outer_offset_lanes) - 1.0) * float(spec.lane_width_m) \
		+ float(stands.get("podium_extra_m", 15.0))
	var stand_back := podium \
		+ float(stands.get("tiers", 5)) * float(stands.get("tier_depth_m", 7.0))
	var back_wall := float(stands.get("back_thickness_m", 3.4))
	# The outermost stone in each axis is the cavea's back wall: half the
	# straight plus turn radius plus the full stand depth down x, turn radius
	# plus the full stand depth across z. A stale mesh misses by hundreds of
	# meters; the tolerance only absorbs the arcade's decorative flare.
	var radius: float = TrackGeometry.turn_radius()
	var expected_x := TrackGeometry.straight_length() / 2.0 + radius + stand_back + back_wall
	var expected_z := radius + stand_back + back_wall
	assert_true(absf(aabb.size.x / 2.0 - expected_x) <= 4.0,
		"mesh x half-extent %.1f vs the spec's %.1f m — rebuild build_hippodrome.py"
			% [aabb.size.x / 2.0, expected_x])
	assert_true(absf(aabb.size.z / 2.0 - expected_z) <= 4.0,
		"mesh z half-extent %.1f vs the spec's %.1f m — rebuild build_hippodrome.py"
			% [aabb.size.z / 2.0, expected_z])
	assert_true(absf(aabb.get_center().x) <= 1.0 and absf(aabb.get_center().z) <= 1.0,
		"the arena is centred on the origin")
	var height := aabb.position.y + aabb.size.y
	assert_true(height > 45.0 and height < 75.0,
		"mesh height %.1f m — the cavea plus arcade plus masts stands ~61 m" % height)
