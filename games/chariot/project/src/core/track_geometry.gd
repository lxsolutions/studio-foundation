class_name TrackGeometry
extends RefCounted

## The hippodrome oval as pure math, sharing assets/track_spec.json with the
## Blender generator so the mesh and this parametrization can never drift.
##
## The generator builds in Blender's XY ground plane; the glTF export maps that
## to Godot as x -> x and y -> -z. Every function here returns Godot-space
## Vector3 values consistent with the exported meshes.
##
## s is arc length in meters along the lane-1 centerline: s=0 starts the home
## straight, the finish line sits at finish_s_m, and race positions map through
## start_offset(distance) so every distance ends exactly at the finish post.

static var _spec: Dictionary = {}

## The spina's footprint in Godot space, matching what the generator sweeps
## (art_source/build_hippodrome.py): a wall straight*0.82 long and ±3.2 m deep
## down the infield's centre, with metae plinths 7.0 × 8.4 m parked on both
## ends (so they reach 3.5 m past the wall and 4.2 m deep). Nothing on the
## sand may ever occupy that ground: every runner is transform-driven — there
## is no physics body to bounce off the barrier — so this keep-out is the only
## thing between a wild lane value and a chariot passing through stone.
const SPINA_LENGTH_FRACTION := 0.82
const SPINA_WALL_HALF_DEPTH_M := 3.2
const SPINA_META_HALF_LENGTH_M := 3.5
const SPINA_META_HALF_DEPTH_M := 4.2
## A horse's half-width: the runner's body, not just its centreline point,
## must stay off the masonry.
const SPINA_KEEP_OUT_MARGIN_M := 1.4


static func spec() -> Dictionary:
	if _spec.is_empty():
		var file := FileAccess.open("res://assets/track_spec.json", FileAccess.READ)
		assert(file != null, "track_spec.json missing")
		var parsed: Variant = JSON.parse_string(file.get_as_text())
		assert(typeof(parsed) == TYPE_DICTIONARY, "track_spec.json malformed")
		_spec = parsed
	return _spec


static func straight_length() -> float:
	return float(spec()["straight_m"])


static func turn_radius() -> float:
	return float(spec()["turn_radius_m"])


static func lane_width() -> float:
	return float(spec()["lane_width_m"])


static func finish_s() -> float:
	return float(spec()["finish_s_m"])


static func loop_length() -> float:
	return 2.0 * straight_length() + 2.0 * PI * turn_radius()


## Lane-1 centerline point at arc length s, in Godot space (y up, track in XZ).
static func point_at(s: float) -> Vector3:
	var straight := straight_length()
	var radius := turn_radius()
	var half := straight / 2.0
	s = fposmod(s, loop_length())
	if s < straight:
		return Vector3(-half + s, 0.0, -radius)
	s -= straight
	var arc := PI * radius
	if s < arc:
		var theta := s / radius
		return Vector3(half + radius * sin(theta), 0.0, -radius * cos(theta))
	s -= arc
	if s < straight:
		return Vector3(half - s, 0.0, radius)
	s -= straight
	var theta2 := s / radius
	return Vector3(-half - radius * sin(theta2), 0.0, radius * cos(theta2))


## Outward normal (away from the infield) at arc length s.
static func normal_at(s: float) -> Vector3:
	var straight := straight_length()
	var radius := turn_radius()
	s = fposmod(s, loop_length())
	if s < straight:
		return Vector3(0.0, 0.0, -1.0)
	s -= straight
	var arc := PI * radius
	if s < arc:
		var theta := s / radius
		return Vector3(sin(theta), 0.0, -cos(theta))
	s -= arc
	if s < straight:
		return Vector3(0.0, 0.0, 1.0)
	s -= straight
	var theta2 := s / radius
	return Vector3(-sin(theta2), 0.0, cos(theta2))


## Unit direction of travel at arc length s.
static func heading_at(s: float) -> Vector3:
	var straight := straight_length()
	var radius := turn_radius()
	s = fposmod(s, loop_length())
	if s < straight:
		return Vector3(1.0, 0.0, 0.0)
	s -= straight
	var arc := PI * radius
	if s < arc:
		var theta := s / radius
		return Vector3(cos(theta), 0.0, sin(theta))
	s -= arc
	if s < straight:
		return Vector3(-1.0, 0.0, 0.0)
	s -= straight
	var theta2 := s / radius
	return Vector3(-cos(theta2), 0.0, -sin(theta2))


## The ground the spina and its metae stand on, as an XZ rect centred on the
## origin, margin included. Legal lanes (0.5..16) never come within 35 m of
## it; this exists for the day a wire value does not.
static func spina_keep_out() -> Rect2:
	var half_len := straight_length() * SPINA_LENGTH_FRACTION * 0.5 \
		+ SPINA_META_HALF_LENGTH_M + SPINA_KEEP_OUT_MARGIN_M
	var half_depth := SPINA_META_HALF_DEPTH_M + SPINA_KEEP_OUT_MARGIN_M
	return Rect2(Vector2(-half_len, -half_depth), Vector2(half_len * 2.0, half_depth * 2.0))


## Push a ground point out of the spina keep-out along the axis of least
## penetration — a deflection, not a stop, so a corrupt lane slides along the
## barrier instead of passing through it or teleporting across the infield.
static func deflect_from_spina(p: Vector3) -> Vector3:
	var rect := spina_keep_out()
	if not rect.has_point(Vector2(p.x, p.z)):
		return p
	var half := rect.size * 0.5
	var push_x := half.x - absf(p.x)
	var push_z := half.y - absf(p.z)
	if push_z <= push_x:
		p.z = (1.0 if p.z >= 0.0 else -1.0) * half.y
	else:
		p.x = (1.0 if p.x >= 0.0 else -1.0) * half.x
	return p


static func lane_point(s: float, lane: float) -> Vector3:
	return point_at(s) + normal_at(s) * (lane - 1.0) * lane_width()


## Arc length of the starting gate for a race of the given distance: races end
## exactly at the finish line, so the gate sits distance meters before it.
static func start_offset(distance: float) -> float:
	return fposmod(finish_s() - distance, loop_length())


## Whether arc length s sits on one of the two turns. The oval always bends
## toward the infield, so presentation (the charioteer's lean) needs only the
## fact of the turn, never its direction.
static func in_turn(s: float) -> bool:
	var straight := straight_length()
	var arc := PI * turn_radius()
	s = fposmod(s, loop_length())
	return (s >= straight and s < straight + arc) or s >= 2.0 * straight + arc


## Full transform for a horse: pos meters into a race of the given distance,
## lane as the live float the sim streams. Forward is -Z, matching the model.
## Race positions clamp at the gate; ambience (the post parade) may pass
## clamp_start=false to walk the ground behind it. The origin is deflected
## out of the spina keep-out last: lanes come off the wire unvalidated, and a
## runner must never be placed inside the central barrier.
static func horse_transform(pos_m: float, lane: float, distance: float, clamp_start: bool = true) -> Transform3D:
	var s := start_offset(distance) + (maxf(pos_m, 0.0) if clamp_start else pos_m)
	var origin := deflect_from_spina(lane_point(s, lane))
	var forward := heading_at(s)
	return Transform3D.IDENTITY.looking_at(forward, Vector3.UP).translated(origin)
