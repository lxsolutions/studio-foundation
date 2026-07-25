class_name CrowdDirector
extends MultiMeshInstance3D

## The Asha Colosseum's crowd: every tier seated from one fixed seed so the
## house looks the same every raceday, tinted in the four circus factions
## with the wider palette sprinkled thin, breathing gently at rest and
## rising as one when the wire's crowd_swell moment lands. Seat math mirrors
## art_source/blender/generate_assets.py exactly: the podium ring at
## (rail_outer − 1) · lane_width + 15, five tiers of depth 7.0 rising 4.2
## with 2.2 risers, first course at podium height + 1.

const TIER_DEPTH := 7.0
const TIER_RISE := 4.2
const TIER_RISER := 2.2
const N_TIERS := 5
const PODIUM_H := 3.4
const ROW_FRACTIONS: Array[float] = [0.22, 0.52, 0.82]
const SPACING := 1.15
const EMPTY_SEAT_ODDS := 0.12
const SEAT_SEED := 424242
const FACTIONS: Array[Color] = [
	Color(0.157, 0.353, 0.620), Color(0.184, 0.494, 0.263),
	Color(0.788, 0.169, 0.157), Color(0.910, 0.886, 0.827),
]

const SKIN_TONES: Array[Color] = [
	Color("f2d6b3"), Color("e0b48c"), Color("c68e5f"),
	Color("a96b45"), Color("845433"), Color("6b4126"),
]

var seat_positions: Array[Vector3] = []
var seat_colors: Array[Color] = []
var _head_transforms: Array[Transform3D] = []
var _head_colors: Array[Color] = []
var _sway_t := 0.0
var _roar := 0.0


func _ready() -> void:
	build()


func podium_offset() -> float:
	var spec := TrackGeometry.spec()
	return (float(spec.rail_outer_offset_lanes) - 1.0) * float(spec.lane_width_m) + 15.0


func build() -> void:
	seat_positions.clear()
	seat_colors.clear()
	_head_transforms.clear()
	_head_colors.clear()
	var rng := RandomNumberGenerator.new()
	rng.seed = SEAT_SEED
	var loop := TrackGeometry.loop_length()
	var base_off := podium_offset() + 1.2
	var base_h := PODIUM_H + 1.0
	var transforms: Array[Transform3D] = []
	var colors: Array[Color] = []
	for tier in N_TIERS:
		var h_lo := base_h + tier * (TIER_RISE + TIER_RISER) + TIER_RISER - 1.0
		for f in ROW_FRACTIONS:
			var off := base_off + tier * TIER_DEPTH + float(f) * TIER_DEPTH
			var h := h_lo + float(f) * TIER_RISE + 0.55
			var count := int((loop + TAU * off) / SPACING)
			for i in count:
				if rng.randf() < EMPTY_SEAT_ODDS:
					continue
				var s := fmod((float(i) + rng.randf() * 0.4) / float(count) * loop, loop)
				# normal_at points OUTWARD — lanes grow along +normal — so the
				# house ADDS it to sit on the risers. The first ship subtracted
				# and floated ten thousand souls over the sand; the suite now
				# pins the SIGNED outward projection so this cannot recur.
				var seat := TrackGeometry.point_at(s) + TrackGeometry.normal_at(s) * off + Vector3(0.0, h, 0.0)
				var lean := Basis(Vector3.UP, rng.randf_range(-0.4, 0.4)).scaled(Vector3(0.58, 0.85 + rng.randf() * 0.2, 0.58))
				transforms.append(Transform3D(lean, seat))
				# Factions sit together in arcs, Circus Maximus style: whole
				# blocks of Blue, Green, Red, White with stray visitors
				# sprinkled through, so the tiers read as crowd from the sand.
				var block := int(s / 13.0)
				var tint := FACTIONS[block % FACTIONS.size()] if rng.randf() < 0.9 \
						else Color.from_hsv(rng.randf(), 0.45, 0.75)
				colors.append(tint)
				seat_positions.append(seat)
				seat_colors.append(tint)
				# A skin-tone head floats atop each torso, tracking its body's
				# height scale, so the tiers read as PEOPLE, not capsules.
				var body_ys := lean.y.length()
				var head_at := seat + Vector3(0.0, 0.98 * body_ys, 0.0)
				var head_lean := Basis().scaled(Vector3.ONE * rng.randf_range(0.88, 1.08))
				_head_transforms.append(Transform3D(head_lean, head_at))
				_head_colors.append(SKIN_TONES[rng.randi() % SKIN_TONES.size()])
	# The body: a slim torso capsule, waist up — rows hide the rest.
	var body := CapsuleMesh.new()
	body.radius = 0.36
	body.height = 1.15
	body.radial_segments = 6
	body.rings = 2
	var skin := StandardMaterial3D.new()
	skin.vertex_color_use_as_albedo = true
	skin.roughness = 1.0
	body.material = skin
	var house := MultiMesh.new()
	house.transform_format = MultiMesh.TRANSFORM_3D
	house.use_colors = true
	house.mesh = body
	house.instance_count = transforms.size()
	for i in transforms.size():
		house.set_instance_transform(i, transforms[i])
		house.set_instance_color(i, colors[i])
	multimesh = house
	_build_heads()


func _build_heads() -> void:
	var old := find_child("Heads", false, false)
	if old != null:
		old.queue_free()
	var head := SphereMesh.new()
	head.radius = 0.16
	head.height = 0.32
	head.radial_segments = 8
	head.rings = 6
	var skin := StandardMaterial3D.new()
	skin.vertex_color_use_as_albedo = true
	skin.roughness = 0.9
	head.material = skin
	var faces := MultiMesh.new()
	faces.transform_format = MultiMesh.TRANSFORM_3D
	faces.use_colors = true
	faces.mesh = head
	faces.instance_count = _head_transforms.size()
	for i in _head_transforms.size():
		faces.set_instance_transform(i, _head_transforms[i])
		faces.set_instance_color(i, _head_colors[i])
	var heads := MultiMeshInstance3D.new()
	heads.name = "Heads"
	heads.multimesh = faces
	add_child(heads)


## The wire says the crowd swells; the house rises as one and settles.
func roar() -> void:
	_roar = 1.0


func _process(delta: float) -> void:
	_sway_t += delta
	_roar = maxf(0.0, _roar - delta * 0.55)
	scale = Vector3(1.0, 1.0 + sin(_sway_t * 1.7) * 0.006 + _roar * 0.05, 1.0)
