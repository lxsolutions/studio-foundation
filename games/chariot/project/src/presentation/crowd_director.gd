class_name CrowdDirector
extends MultiMeshInstance3D

## The Asha Colosseum's crowd: every tier seated from one fixed seed so the
## house looks the same every raceday, tinted in the four circus factions
## with the wider palette sprinkled thin, breathing gently at rest and
## rising as one when the wire's crowd_swell moment lands. Seat math mirrors
## art_source/blender/generate_assets.py exactly: the podium ring at
## (rail_outer − 1) · lane_width + 15, five tiers of depth 7.0 rising 4.2
## with 2.2 risers, first course at podium height + 1.
##
## Three things decide whether a stand reads as an audience or as confetti,
## and the first version of this got all three wrong:
##
##   SILHOUETTE. A capsule is a pill. People are head, neck, shoulders and a
##   tapered torso. The crowd figures (games/chariot/art_source/build_spectators.py)
##   carry that shape for FEWER triangles than the capsule they replace, in
##   three poses so the tiers are not wallpaper.
##
##   FACING. Everyone in a circus watches the sand. Random yaw made ten
##   thousand people stare in ten thousand directions, which is the single
##   biggest reason it read as scattered objects rather than a crowd.
##
##   VALUE. Real crowds are mostly muted with colour accents. Full-saturation
##   faction red/green/blue/white at uniform brightness is what produced the
##   confetti look; every instance now varies in brightness and a good third
##   wear undyed cloth.

## Tier geometry comes from track_spec.json's `stands` block, which the mesh
## generator (art_source/build_hippodrome.py) sweeps the seating surface from.
## These were duplicated constants once; the generator was rebuilt to a
## different rise and the top third of the house ended up hovering behind the
## building. Read the spec, never restate it. Fallbacks match the shipped spec
## so an older file still boots.
## Tighter than a body is wide, so shoulders overlap and a tier reads as a
## packed mass rather than a dotted line. A stand with air between every
## spectator looks empty from the sand no matter how good one figure is.
const SPACING := 0.95
const EMPTY_SEAT_ODDS := 0.06
## Crowd figures are modelled at true human scale, which is correct and reads
## as too small once a tier is 90 m away. Stylising them up recovers the visual
## mass without going back to man-sized pills.
const FIGURE_SCALE := 1.22
const SEAT_SEED := 424242

const FIGURE_MODELS := {
	"seated": "res://assets/models/crowd_seated.glb",
	"standing": "res://assets/models/crowd_standing.glb",
	"cheering": "res://assets/models/crowd_cheering.glb",
}
const HEAD_MODEL := "res://assets/models/crowd_head.glb"
## Shoulder height per pose, for sitting the head on the neck.
const SHOULDER_H := {"seated": 0.76, "standing": 1.02, "cheering": 1.02}
## Most of the house is seated; a scattering stands, fewer still are on their
## feet cheering. Weights must sum to 1.0.
const POSE_MIX := {"seated": 0.70, "standing": 0.20, "cheering": 0.10}

## The four circus factions — Veneta, Prasina, Russata, Albata — in VEGETABLE
## DYE, not printer ink. Woad blue, weld green, madder red and undyed white all
## sit well under half saturation. Fire-engine primaries are what made the
## stands read as a bin of Lego.
const FACTIONS: Array[Color] = [
	Color("46587a"), Color("4a6b47"), Color("8f4a3f"), Color("ded5c4"),
]
## Undyed wool, linen, and the cheap earth dyes everyone else could afford.
## This is the bulk of a Roman crowd and it is why a shot of the Circus reads
## as a sea of dust and cream with colour flecked through it, rather than as
## four solid bands of team kit.
const PLAIN_CLOTH: Array[Color] = [
	Color("d8cbb0"), Color("c9bda2"), Color("bdae90"), Color("b0a184"),
	Color("a8926f"), Color("907a5c"), Color("7b6448"), Color("63513a"),
	Color("9a958a"), Color("837e74"), Color("b08a4e"), Color("a3705f"),
]
## How much of the house wears no faction at all. Dye was expensive; most
## people in the cheap seats owned one good tunic and it was the colour of the
## sheep it came off.
const PLAIN_SHARE := 0.80
const SKIN_TONES: Array[Color] = [
	Color("f2d6b3"), Color("e0b48c"), Color("c68e5f"),
	Color("a96b45"), Color("845433"), Color("6b4126"),
]

var seat_positions: Array[Vector3] = []
var seat_colors: Array[Color] = []
var _pose_nodes: Dictionary = {}
var _heads: MultiMeshInstance3D
var _sway_t := 0.0
var _roar := 0.0


func _ready() -> void:
	build()


func stands_spec() -> Dictionary:
	var spec: Dictionary = TrackGeometry.spec()
	var stands: Dictionary = spec.get("stands", {})
	return {
		"podium_extra_m": float(stands.get("podium_extra_m", 15.0)),
		"podium_height_m": float(stands.get("podium_height_m", 3.4)),
		"tiers": int(stands.get("tiers", 5)),
		"tier_depth_m": float(stands.get("tier_depth_m", 7.0)),
		"tier_rise_m": float(stands.get("tier_rise_m", 4.2)),
		"tier_riser_m": float(stands.get("tier_riser_m", 2.2)),
		"rows_per_tier": maxi(1, int(stands.get("rows_per_tier", 6))),
	}


## One seat row per step the generator cuts, spread across the tier's depth.
## Three rows over a 7 m tier leaves 2.3 m of bare stone between them, which
## from the sand reads as a few thin stripes of people rather than a full house.
func row_fractions() -> Array[float]:
	var rows: int = int(stands_spec().rows_per_tier)
	var out: Array[float] = []
	for index in rows:
		out.append((float(index) + 0.5) / float(rows))
	return out


func podium_offset() -> float:
	var spec: Dictionary = TrackGeometry.spec()
	var stands := stands_spec()
	return (float(spec.rail_outer_offset_lanes) - 1.0) * float(spec.lane_width_m) \
		+ float(stands.podium_extra_m)


## How full the house is on the active render profile. Falls back to a full
## stadium when the Studio autoload is missing — headless asset tools and unit
## tests build this director in isolation, and a silently empty colosseum would
## be a much worse failure than an over-budget one.
func crowd_density() -> float:
	var studio: Node = get_node_or_null(^"/root/Studio")
	if studio == null:
		return 1.0
	var raw: Variant = studio.get("profiles")
	if raw == null or not (raw is StudioRenderProfiles):
		return 1.0
	var profiles: StudioRenderProfiles = raw
	return clampf(profiles.budget("crowd_density", 1.0), 0.05, 1.0)


func build() -> void:
	seat_positions.clear()
	seat_colors.clear()
	var rng := RandomNumberGenerator.new()
	rng.seed = SEAT_SEED
	var stands := stands_spec()
	var tier_depth := float(stands.tier_depth_m)
	var tier_rise := float(stands.tier_rise_m)
	var tier_riser := float(stands.tier_riser_m)
	var n_tiers := int(stands.tiers)
	var loop: float = TrackGeometry.loop_length()
	var base_off := podium_offset() + 1.2
	var base_h := float(stands.podium_height_m) + 1.0

	# The crowd is the single largest triangle contributor in the game, and until
	# now it was built identically on every render profile -- a phone drew the same
	# ~107,600 instanced figures as a desktop. Widening the spacing thins the stands
	# evenly rather than speckling them with gaps, so a sparser house still reads as
	# a house. Seeded the same way, so a given profile is still reproducible.
	var density := crowd_density()
	var spacing: float = SPACING / maxf(density, 0.01)

	var by_pose := {}
	var colors_by_pose := {}
	for pose in FIGURE_MODELS:
		by_pose[pose] = [] as Array[Transform3D]
		colors_by_pose[pose] = [] as Array[Color]
	var head_transforms: Array[Transform3D] = []
	var head_colors: Array[Color] = []

	var fractions := row_fractions()
	for tier in n_tiers:
		var h_lo := base_h + tier * (tier_rise + tier_riser) + tier_riser - 1.0
		for f in fractions:
			var off := base_off + tier * tier_depth + float(f) * tier_depth
			var h := h_lo + float(f) * tier_rise + 0.55
			var count := int((loop + TAU * off) / spacing)
			for i in count:
				if rng.randf() < EMPTY_SEAT_ODDS:
					continue
				var s := fmod((float(i) + rng.randf() * 0.4) / float(count) * loop, loop)
				# normal_at points OUTWARD — lanes grow along +normal — so the
				# house ADDS it to sit on the risers. The first ship subtracted
				# and floated ten thousand souls over the sand; the suite now
				# pins the SIGNED outward projection so this cannot recur.
				# TrackGeometry's statics return Variant across script boundaries,
				# so these need explicit types to satisfy the parser.
				var outward: Vector3 = TrackGeometry.normal_at(s)
				var base: Vector3 = TrackGeometry.point_at(s)
				var seat: Vector3 = base + outward * off + Vector3(0.0, h, 0.0)

				# Face the sand. A few heads turn to a neighbour; nobody has
				# their back to the race.
				var inward: Vector3 = -outward
				var facing := Basis.looking_at(inward, Vector3.UP)
				facing = facing.rotated(Vector3.UP, rng.randf_range(-0.22, 0.22))
				var build_scale := Vector3(
					rng.randf_range(0.92, 1.06),
					rng.randf_range(0.90, 1.10),
					rng.randf_range(0.92, 1.06)
				) * FIGURE_SCALE

				var pose := _pick_pose(rng)
				by_pose[pose].append(Transform3D(facing.scaled(build_scale), seat))
				var tint := _cloth_color(rng, s)
				colors_by_pose[pose].append(tint)
				seat_positions.append(seat)
				seat_colors.append(tint)

				# A skin-tone head rides the shoulders of its own pose, tracking
				# that body's height scale, so the tiers read as PEOPLE.
				var head_at: Vector3 = seat + Vector3(
					0.0, (float(SHOULDER_H[pose]) + 0.11) * build_scale.y, 0.0
				)
				head_transforms.append(Transform3D(
					facing.scaled(
						Vector3.ONE * rng.randf_range(0.90, 1.06) * FIGURE_SCALE
					),
					head_at,
				))
				head_colors.append(SKIN_TONES[rng.randi() % SKIN_TONES.size()])

	for pose in FIGURE_MODELS:
		_fill_pose(pose, by_pose[pose], colors_by_pose[pose])
	_fill_heads(head_transforms, head_colors)


## Factions sit together in arcs, Circus Maximus style — but a partisan block
## is a LEAN, not a uniform. Four out of five people in it are still in undyed
## cloth; the colour shows as flecks through a field of dust. Painting a whole
## 13 m arc one saturated hue is what produced solid stripes of red and green.
func _cloth_color(rng: RandomNumberGenerator, s: float) -> Color:
	var tint: Color
	if rng.randf() < PLAIN_SHARE:
		tint = PLAIN_CLOTH[rng.randi() % PLAIN_CLOTH.size()]
	else:
		var block := int(s / 26.0)
		tint = FACTIONS[block % FACTIONS.size()]
		# Even a partisan's tunic is faded cloth, not a paint chip. Pulling it
		# partway toward a neutral keeps the block readable at distance while
		# stopping it from screaming.
		var neutral := PLAIN_CLOTH[rng.randi() % PLAIN_CLOTH.size()]
		tint = tint.lerp(neutral, rng.randf_range(0.15, 0.45))
	# Sun, shade, dye lots and wear: no two tunics are the same value, and the
	# tiers sit in their own shadow, so the whole house skews down.
	var value := rng.randf_range(0.52, 0.94)
	return Color(tint.r * value, tint.g * value, tint.b * value)


func _pick_pose(rng: RandomNumberGenerator) -> String:
	var roll := rng.randf()
	var running := 0.0
	for pose in POSE_MIX:
		running += float(POSE_MIX[pose])
		if roll <= running:
			return pose
	return "seated"


func _fill_pose(pose: String, transforms: Array, colors: Array) -> void:
	var node: MultiMeshInstance3D = self if pose == "seated" else _pose_nodes.get(pose)
	if node == null:
		node = MultiMeshInstance3D.new()
		node.name = "Crowd_%s" % pose
		add_child(node)
		_pose_nodes[pose] = node
	var house := MultiMesh.new()
	house.transform_format = MultiMesh.TRANSFORM_3D
	house.use_colors = true
	house.mesh = _figure_mesh(String(FIGURE_MODELS[pose]), pose)
	house.instance_count = transforms.size()
	for i in transforms.size():
		house.set_instance_transform(i, transforms[i])
		house.set_instance_color(i, colors[i])
	node.multimesh = house


func _fill_heads(transforms: Array, colors: Array) -> void:
	if _heads == null:
		_heads = MultiMeshInstance3D.new()
		_heads.name = "Heads"
		add_child(_heads)
	var faces := MultiMesh.new()
	faces.transform_format = MultiMesh.TRANSFORM_3D
	faces.use_colors = true
	faces.mesh = _figure_mesh(HEAD_MODEL, "head")
	faces.instance_count = transforms.size()
	for i in transforms.size():
		faces.set_instance_transform(i, transforms[i])
		faces.set_instance_color(i, colors[i])
	_heads.multimesh = faces


## Pull the mesh out of a crowd .glb and give it a vertex-colour material so
## MultiMesh instance colours drive the tunic. Falls back to a primitive if the
## asset is missing, because an unbuilt asset must never empty the stands.
func _figure_mesh(path: String, pose: String) -> Mesh:
	var mesh: Mesh = null
	if ResourceLoader.exists(path):
		var scene: PackedScene = load(path)
		if scene != null:
			var node: Node = scene.instantiate()
			var found := node.find_child("Figure", true, false) as MeshInstance3D
			if found != null:
				mesh = found.mesh
			node.free()
	if mesh == null:
		push_warning("crowd figure missing: %s — run build_spectators.py" % path)
		if pose == "head":
			var sphere := SphereMesh.new()
			sphere.radius = 0.105
			sphere.height = 0.23
			sphere.radial_segments = 6
			sphere.rings = 4
			mesh = sphere
		else:
			var capsule := CapsuleMesh.new()
			capsule.radius = 0.22
			capsule.height = 0.95
			capsule.radial_segments = 6
			capsule.rings = 2
			mesh = capsule
	var cloth := StandardMaterial3D.new()
	cloth.vertex_color_use_as_albedo = true
	cloth.roughness = 1.0
	for surface in mesh.get_surface_count():
		mesh.surface_set_material(surface, cloth)
	return mesh


## The wire says the crowd swells; the house rises as one and settles.
func roar() -> void:
	_roar = 1.0


func _process(delta: float) -> void:
	_sway_t += delta
	_roar = maxf(0.0, _roar - delta * 0.55)
	scale = Vector3(1.0, 1.0 + sin(_sway_t * 1.7) * 0.006 + _roar * 0.05, 1.0)
