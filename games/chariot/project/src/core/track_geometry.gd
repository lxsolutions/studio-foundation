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
## clamp_start=false to walk the ground behind it.
static func horse_transform(pos_m: float, lane: float, distance: float, clamp_start: bool = true) -> Transform3D:
	var s := start_offset(distance) + (maxf(pos_m, 0.0) if clamp_start else pos_m)
	var origin := lane_point(s, lane)
	var forward := heading_at(s)
	return Transform3D.IDENTITY.looking_at(forward, Vector3.UP).translated(origin)
