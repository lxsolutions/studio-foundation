extends StudioTestCase
## The spina is stone, not a suggestion. Every runner on the sand is
## transform-driven — there is no physics body anywhere in the client, so
## nothing bounces a chariot off the central barrier — which makes
## TrackGeometry's keep-out the whole guarantee that no lane value ever puts
## a horse through the wall. This shipped broken once: the wire's lanes are
## unvalidated and the placement funnel clamped nothing, so a runner could
## be placed inside the spina's masonry.


## Strictly inside the keep-out, by a hair under the boundary: a deflected
## point rests exactly ON the edge, and Rect2.has_point counts the near edges
## as contained — useless for asserting "ended up outside".
func _in_keep_out(p: Vector3) -> bool:
	var half := TrackGeometry.spina_keep_out().size * 0.5
	return absf(p.x) < half.x - 0.001 and absf(p.z) < half.y - 0.001


func test_keep_out_covers_the_swept_spina() -> void:
	# build_hippodrome.py: the wall is straight*0.82 long and ±3.2 m deep,
	# with metae plinths 7.0 × 8.4 m at ±spina_half. The rect must contain
	# every stone of it, plus a horse's margin.
	var rect := TrackGeometry.spina_keep_out()
	var half := rect.size * 0.5
	var spina_half := TrackGeometry.straight_length() * 0.82 * 0.5
	assert_true(half.x >= spina_half + 3.5,
		"keep-out %.1f m must reach past the metae at %.1f m" % [half.x, spina_half + 3.5])
	assert_true(half.y >= 4.2,
		"keep-out %.1f m deep must cover the metae plinths' 4.2 m" % half.y)
	assert_true(absf(rect.get_center().x) < 0.01 and absf(rect.get_center().y) < 0.01,
		"the spina stands centred on the infield")


func test_legal_lanes_never_touch_the_keep_out() -> void:
	# The whole racing envelope — every lane the server may legally stream
	# (ghosts validate 0.5..16; the rails sit at -0.6 and 10.6) — sampled
	# around the entire loop: not one point may land in the keep-out, and the
	# clamp must never fire on legal racing.
	var loop := TrackGeometry.loop_length()
	var inside := 0
	var deflected := 0
	var s := 0.0
	while s < loop:
		var lane := 0.5
		while lane <= 10.6:
			var p: Vector3 = TrackGeometry.lane_point(s, lane)
			if _in_keep_out(p):
				inside += 1
			if TrackGeometry.deflect_from_spina(p) != p:
				deflected += 1
			lane += 0.5
		s += 2.5
	assert_eq(inside, 0, "legal lanes must never enter the spina keep-out")
	assert_eq(deflected, 0, "legal lanes must never BE deflected")


func test_a_runner_steered_at_the_spina_is_deflected() -> void:
	# Drive straight at the barrier on the home straight: lanes deep inside
	# the infield cross the spina's ground, and every placed transform must
	# stay out of the keep-out.
	var distance := 1200.0
	var s := TrackGeometry.straight_length() * 0.5
	var pos := fposmod(s - TrackGeometry.start_offset(distance), TrackGeometry.loop_length())
	var wild := 0
	for i in 41:
		# Lane 1.0 down to -19.0: from the rail across the infield, through
		# the spina, and out the other side.
		var lane := 1.0 - float(i) * 0.5
		var origin: Vector3 = TrackGeometry.horse_transform(pos, lane, distance).origin
		if _in_keep_out(origin):
			wild += 1
	assert_eq(wild, 0, "no placement may land inside the spina, whatever the wire says")


func test_deflection_stops_at_the_barrier() -> void:
	# A lane aimed at the spina's centre must come out ON the keep-out edge —
	# sliding along the masonry — not teleported across the infield.
	var rect := TrackGeometry.spina_keep_out()
	var half := rect.size * 0.5
	var s := TrackGeometry.straight_length() * 0.5
	var aimed: Vector3 = TrackGeometry.lane_point(s, -15.0)
	assert_true(_in_keep_out(aimed), "the test must actually aim into the keep-out")
	var placed := TrackGeometry.deflect_from_spina(aimed)
	assert_false(_in_keep_out(placed), "deflected out")
	assert_true(is_equal_approx(absf(placed.z), half.y) or is_equal_approx(absf(placed.x), half.x),
		"deflection stops AT the barrier (%.2f, %.2f) vs half-extent (%.2f, %.2f)"
			% [placed.x, placed.z, half.x, half.y])
	# It came out on the side it approached from: the home straight's side.
	assert_true(signf(placed.z) == signf(aimed.z), "deflection keeps the approach side")
