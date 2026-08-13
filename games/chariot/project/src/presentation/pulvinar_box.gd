class_name PulvinarBox
extends Node3D

## The Emperor's Box — the pulvinar, the royal seat cut into the front of the
## cavea at the home straight's midpoint, above the spina line. One emperor in
## purple and gold watches the race seated; at the decisive beat he rises and
## extends the arm, thumb down — the arena's verdict.
##
## Scene-level, not generator-level, on purpose: the cavea is ONE continuous
## oval sweep in art_source/build_hippodrome.py (bforge path_shape="oval" has
## no gap), so a masonry notch means splitting that sweep, rebuilding the whole
## venue through Blender, and re-validating the mesh the suite pins. A booth
## built here from primitives carries the same read at a fraction of the risk,
## and every placement number is derived from track_spec.json through
## TrackGeometry — the same sharing rule crowd_director.gd follows — so a spec
## move moves the box too. No new art files: marble, gold and purple come off
## the palette the venue and the exhibition already use, and the emperor is
## the crowd's own seated/standing figures with a royal tint.
##
## The crowd figures are swept statics — no rig, no arm bone — so the verdict
## is a pose swap: seated figure out, standing figure in, with the
## thumb-down arm composited from primitives and swept out procedurally.

const SEATED_MODEL := "res://assets/models/crowd_seated.glb"
const STANDING_MODEL := "res://assets/models/crowd_standing.glb"
const HEAD_MODEL := "res://assets/models/crowd_head.glb"

## The box spans 12 m of the home straight, centred on its midpoint.
const HALF_WIDTH_M := 6.0
## The crowd notch is a little wider than the masonry, so no spectator's
## shoulder clips the drapes.
const SEAT_NOTCH_HALF_WIDTH_M := 6.9
## The platform projects off the podium face toward the sand and its rear
## embeds 2 m into the cavea's solid profile — planted, never floating.
const FRONT_PROJECTION_M := 4.5
const REAR_EMBED_M := 2.0
## The floor rides above the podium wall: high enough that the emperor clears
## the parapet and the front rows, low enough to stay under the first tiers.
const FLOOR_ABOVE_PODIUM_M := 1.4
## The emperor is a head and a half taller than the crowd around him — a
## Roman emperor was never life-size in his own venue.
const EMPEROR_SCALE := 1.55

## The verdict beat: the arm sweeps out, holds the thumb-down while the laurel
## board goes up, then settles back to the throne. Once per race.
const VERDICT_RISE_S := 0.55
const VERDICT_HOLD_S := 4.0
const VERDICT_SETTLE_S := 0.6
## Arm angles about the shoulder's local X: tucked along the body at rest,
## thrust forward over the parapet for the verdict.
const ARM_TUCKED_DEG := -72.0
const ARM_EXTENDED_DEG := -8.0

# The palette the venue already speaks: travertine from the generator, gold
# and purple from the exhibition's fallback liveries, a crowd skin tone.
const MARBLE := Color("d6c4a0")
const GOLD := Color("e8ba32")
const PURPLE := Color("843c8b")
const SKIN := Color("e0b48c")

## Test-visible count of verdicts delivered since boot — the once-per-race pin.
var times_delivered := 0

var _built := false
var _armed := true
var _posing := false
var _pose_frozen := false
var _pose_t := 0.0
var _seated: Node3D
var _standing: Node3D
var _arm: Node3D


## Mid-straight on the home side: s=0 opens the home straight (z=-radius), so
## its midpoint is the straight's halfway arc length.
static func box_s() -> float:
	return TrackGeometry.straight_length() * 0.5


## The podium wall's lateral offset from the lane-1 centerline — the same
## arithmetic crowd_director.gd seats the house from.
static func podium_offset() -> float:
	var spec: Dictionary = TrackGeometry.spec()
	var stands: Dictionary = spec.get("stands", {})
	return (float(spec.rail_outer_offset_lanes) - 1.0) * float(spec.lane_width_m) \
		+ float(stands.get("podium_extra_m", 15.0))


static func floor_top() -> float:
	var spec: Dictionary = TrackGeometry.spec()
	var stands: Dictionary = spec.get("stands", {})
	return float(stands.get("podium_height_m", 3.4)) + FLOOR_ABOVE_PODIUM_M


static func front_offset() -> float:
	return podium_offset() - FRONT_PROJECTION_M


static func back_offset() -> float:
	return podium_offset() + REAR_EMBED_M


static func center_offset() -> float:
	return (front_offset() + back_offset()) * 0.5


## The box's world anchor: platform floor centre, facing the sand.
static func anchor_transform() -> Transform3D:
	var s := box_s()
	var outward: Vector3 = TrackGeometry.normal_at(s)
	var base: Vector3 = TrackGeometry.point_at(s)
	var pos := base + outward * center_offset() + Vector3.UP * floor_top()
	return Transform3D(Basis.looking_at(-outward, Vector3.UP), pos)


## The seating notch: the box stands where the home straight's front rows
## would be. crowd_director.gd asks this for every seat, so the break in the
## rows is the same arithmetic as the platform — never eyeballed twice.
static func blocks_seat(s: float, offset: float) -> bool:
	var spec: Dictionary = TrackGeometry.spec()
	var stands: Dictionary = spec.get("stands", {})
	var tier_depth := float(stands.get("tier_depth_m", 7.0))
	var podium := podium_offset()
	var loop: float = TrackGeometry.loop_length()
	var ds := absf(fposmod(s - box_s() + loop * 0.5, loop) - loop * 0.5)
	return ds < SEAT_NOTCH_HALF_WIDTH_M and offset >= podium - 0.1 \
		and offset <= podium + tier_depth + 0.1


func _ready() -> void:
	if not _built:
		build()


func build() -> void:
	if _built:
		return
	_built = true
	transform = anchor_transform()
	var marble := _material(MARBLE, 0.9)
	var gold := _material(GOLD, 0.5, 0.4)
	# The purple cloth carries a whisper of emission: the canopy shades its own
	# booth, and unlifted purple in shadow reads as a black slab.
	var purple := _material(PURPLE, 1.0, 0.0, 0.18)
	_build_masonry(marble, gold, purple)
	_build_emperor(purple, gold)


func _material(albedo: Color, roughness: float, metallic: float = 0.0, glow: float = 0.0) -> StandardMaterial3D:
	var mat := StandardMaterial3D.new()
	mat.albedo_color = albedo
	mat.roughness = roughness
	mat.metallic = metallic
	if glow > 0.0:
		mat.emission_enabled = true
		mat.emission = albedo
		mat.emission_energy_multiplier = glow
	return mat


func _add_box(size: Vector3, pos: Vector3, mat: Material, label: String) -> MeshInstance3D:
	var mesh := BoxMesh.new()
	mesh.size = size
	mesh.material = mat
	var node := MeshInstance3D.new()
	node.name = label
	node.mesh = mesh
	node.position = pos
	add_child(node)
	return node


func _add_cylinder(radius: float, height: float, pos: Vector3, mat: Material, label: String) -> MeshInstance3D:
	var mesh := CylinderMesh.new()
	mesh.top_radius = radius
	mesh.bottom_radius = radius
	mesh.height = height
	mesh.radial_segments = 10
	mesh.material = mat
	var node := MeshInstance3D.new()
	node.name = label
	node.mesh = mesh
	node.position = pos
	add_child(node)
	return node


## The booth itself, in local space: -Z faces the sand, the floor's top is
## y=0, and the plan runs ±HALF_WIDTH_M across and front_offset..back_offset
## in depth. A raised platform, a gold-capped parapet, purple side drapes and
## cloth of honour, four columns, and a canopied gable — the silhouette has
## to name the seat before the emperor himself is visible.
func _build_masonry(marble: Material, gold: Material, purple: Material) -> void:
	var width := HALF_WIDTH_M * 2.0
	var depth := back_offset() - front_offset()
	# Platform and parapet.
	_add_box(Vector3(width, 0.7, depth), Vector3(0.0, -0.35, 0.0), marble, "Platform")
	_add_box(Vector3(width, 0.55, 0.35), Vector3(0.0, 0.275, -depth * 0.5 + 0.175), marble, "Parapet")
	_add_box(Vector3(width, 0.12, 0.45), Vector3(0.0, 0.61, -depth * 0.5 + 0.175), gold, "ParapetCap")
	_add_box(Vector3(0.35, 0.55, depth), Vector3(-HALF_WIDTH_M + 0.175, 0.275, 0.0), marble, "SideWallL")
	_add_box(Vector3(0.35, 0.55, depth), Vector3(HALF_WIDTH_M - 0.175, 0.275, 0.0), marble, "SideWallR")
	# The cloth of honour: a purple wall behind the throne, so the emperor
	# always reads against purple instead of against the crowd.
	_add_box(Vector3(width, 4.4, 0.25), Vector3(0.0, 2.2, depth * 0.5 - 0.125), purple, "ClothOfHonour")
	# Columns and canopy.
	for sx in [-1.0, 1.0]:
		for sz in [-1.0, 1.0]:
			_add_cylinder(0.16, 4.4, Vector3(sx * (HALF_WIDTH_M - 0.4), 2.2, sz * (depth * 0.5 - 0.45)), marble, "Column")
	_add_box(Vector3(width + 1.0, 0.35, depth + 1.1), Vector3(0.0, 4.575, 0.0), purple, "Canopy")
	_add_box(Vector3(width + 1.0, 0.5, 0.18), Vector3(0.0, 4.45, -depth * 0.5 - 0.46), gold, "Fascia")
	# Drapes hanging from the canopy's front corners.
	_add_box(Vector3(1.7, 2.7, 0.14), Vector3(-HALF_WIDTH_M + 0.65, 3.05, -depth * 0.5 + 0.4), purple, "DrapeL")
	_add_box(Vector3(1.7, 2.7, 0.14), Vector3(HALF_WIDTH_M - 0.65, 3.05, -depth * 0.5 + 0.4), purple, "DrapeR")
	# The gable over the fascia: two shallow slabs meeting at a ridge, with the
	# imperial disc set between them.
	var gable_l := _add_box(Vector3(4.4, 0.26, 1.0), Vector3(-1.95, 5.15, -depth * 0.5 - 0.1), marble, "GableL")
	gable_l.rotation_degrees.z = 17.0
	var gable_r := _add_box(Vector3(4.4, 0.26, 1.0), Vector3(1.95, 5.15, -depth * 0.5 - 0.1), marble, "GableR")
	gable_r.rotation_degrees.z = -17.0
	var disc_mesh := CylinderMesh.new()
	disc_mesh.top_radius = 0.38
	disc_mesh.bottom_radius = 0.38
	disc_mesh.height = 0.08
	disc_mesh.radial_segments = 16
	disc_mesh.material = gold
	var disc := MeshInstance3D.new()
	disc.name = "ImperialDisc"
	disc.mesh = disc_mesh
	disc.position = Vector3(0.0, 5.05, -depth * 0.5 - 0.52)
	disc.rotation_degrees.x = 90.0
	add_child(disc)


## The emperor, twice: seated on his throne for the running of the race, and
## standing with the verdict arm for the beat that ends it. Only one is ever
## visible. The arm is composited from primitives because the crowd figures
## carry no rig to rotate — a swept static has no elbow.
func _build_emperor(purple: Material, gold: Material) -> void:
	# The throne: gold pedestal, seat and tall back, against the cloth.
	_add_box(Vector3(1.0, 0.5, 0.9), Vector3(0.0, 0.25, 0.9), gold, "ThronePedestal")
	_add_box(Vector3(1.0, 1.7, 0.18), Vector3(0.0, 1.35, 1.28), gold, "ThroneBack")

	_seated = _spawn_figure(SEATED_MODEL, PURPLE, Vector3(0.0, 0.5, 0.9))
	_seated.name = "EmperorSeated"
	_standing = _spawn_figure(STANDING_MODEL, PURPLE, Vector3(0.0, 0.0, -0.6))
	_standing.name = "EmperorStanding"
	_standing.visible = false
	_arm = _build_verdict_arm(_standing, purple)


## One royal figure: a crowd body in purple, a skin head, and the gold laurel
## no one else in the house may wear.
func _spawn_figure(path: String, tint: Color, pos: Vector3) -> Node3D:
	var figure := Node3D.new()
	figure.position = pos
	figure.scale = Vector3.ONE * EMPEROR_SCALE
	add_child(figure)
	var body := _instance_figure_mesh(path)
	if body != null:
		figure.add_child(body)
		# The emperor glows faintly — the canopy shades the booth, and the one
		# man the whole house is watching must never read as a shadow.
		_tint(body, tint, 0.3)
	var head := _instance_figure_mesh(HEAD_MODEL)
	if head != null:
		var shoulder := 0.76 if path == SEATED_MODEL else 1.02
		head.position = Vector3(0.0, shoulder + 0.11, 0.0)
		figure.add_child(head)
		_tint(head, SKIN, 0.25)
		# The laurel: a thin gold torus canted on the crown.
		var wreath_mesh := TorusMesh.new()
		wreath_mesh.inner_radius = 0.095
		wreath_mesh.outer_radius = 0.125
		wreath_mesh.rings = 12
		wreath_mesh.ring_segments = 6
		var wreath := MeshInstance3D.new()
		wreath.name = "Laurel"
		wreath.mesh = wreath_mesh
		wreath.material_override = _material(GOLD, 0.45, 0.5)
		wreath.position = Vector3(0.0, shoulder + 0.19, 0.0)
		wreath.rotation_degrees.x = 78.0
		figure.add_child(wreath)
	return figure


func _instance_figure_mesh(path: String) -> MeshInstance3D:
	if not ResourceLoader.exists(path):
		push_warning("pulvinar figure missing: %s — run build_spectators.py" % path)
		return null
	var scene: PackedScene = load(path)
	if scene == null:
		return null
	var node: Node = scene.instantiate()
	var found := node.find_child("Figure", true, false) as MeshInstance3D
	if found != null:
		# Detach from the throwaway scene root so no stray transform rides along.
		node.remove_child(found)
		found.position = Vector3.ZERO
	node.free()
	return found


func _tint(mesh_instance: MeshInstance3D, color: Color, glow: float = 0.0) -> void:
	var mat := _material(color, 1.0, 0.0, glow)
	for surface in mesh_instance.mesh.get_surface_count():
		mesh_instance.set_surface_override_material(surface, mat)


## The verdict arm on the standing figure's right shoulder: one tapered sleeve
## in purple, a fist, and the thumb hanging BELOW the fist — pollice verso,
## readable as down even where the hand itself is a dozen pixels.
func _build_verdict_arm(figure: Node3D, purple: Material) -> Node3D:
	var pivot := Node3D.new()
	pivot.name = "VerdictArm"
	pivot.position = Vector3(0.24, 0.94, -0.02)
	pivot.rotation_degrees.x = ARM_TUCKED_DEG
	figure.add_child(pivot)
	var sleeve_mesh := CylinderMesh.new()
	sleeve_mesh.top_radius = 0.045
	sleeve_mesh.bottom_radius = 0.065
	sleeve_mesh.height = 0.52
	sleeve_mesh.radial_segments = 6
	sleeve_mesh.material = purple
	var sleeve := MeshInstance3D.new()
	sleeve.name = "Sleeve"
	sleeve.mesh = sleeve_mesh
	sleeve.rotation_degrees.x = -90.0
	sleeve.position = Vector3(0.0, 0.0, -0.26)
	pivot.add_child(sleeve)
	var fist_mesh := BoxMesh.new()
	fist_mesh.size = Vector3(0.09, 0.09, 0.12)
	fist_mesh.material = _material(SKIN, 1.0)
	var fist := MeshInstance3D.new()
	fist.name = "Fist"
	fist.mesh = fist_mesh
	fist.position = Vector3(0.0, 0.0, -0.56)
	pivot.add_child(fist)
	var thumb_mesh := BoxMesh.new()
	thumb_mesh.size = Vector3(0.06, 0.17, 0.06)
	thumb_mesh.material = _material(SKIN, 1.0)
	var thumb := MeshInstance3D.new()
	thumb.name = "Thumb"
	thumb.mesh = thumb_mesh
	thumb.position = Vector3(0.0, -0.12, -0.57)
	pivot.add_child(thumb)
	return pivot


## The race's phase, forwarded by the broadcast on every transition. The
## verdict fires on the finish — there is no wreck signal on the wire — once
## per race; a new parade re-arms it.
func note_phase(phase: String) -> void:
	match phase:
		RaceState.PHASE_FINISHED:
			if _armed:
				deliver_verdict()
		RaceState.PHASE_PARADING, RaceState.PHASE_GATE:
			_armed = true
			if _posing:
				_show_seated()


## The emperor rises and the thumb goes down. Public so the capture harness
## can drive the pose without a race.
func deliver_verdict() -> void:
	_armed = false
	_posing = true
	_pose_t = 0.0
	times_delivered += 1
	if _seated != null:
		_seated.visible = false
	if _standing != null:
		_standing.visible = true


## The capture harness's door: the full pose, held — no sweep, no settle, so
## a slow headless frame rate cannot miss the gesture.
func strike_verdict_pose() -> void:
	deliver_verdict()
	_pose_frozen = true
	if _arm != null:
		_arm.rotation_degrees.x = ARM_EXTENDED_DEG


func is_posing() -> bool:
	return _posing


## Whether the emperor currently stands in the verdict pose (test-visible).
func emperor_risen() -> bool:
	return _standing != null and _standing.visible


func _show_seated() -> void:
	_posing = false
	_pose_frozen = false
	if _standing != null:
		_standing.visible = false
	if _seated != null:
		_seated.visible = true
	if _arm != null:
		_arm.rotation_degrees.x = ARM_TUCKED_DEG


func _process(delta: float) -> void:
	if not _posing or _arm == null or _pose_frozen:
		return
	_pose_t += delta
	if _pose_t < VERDICT_RISE_S:
		var t := smoothstep(0.0, 1.0, _pose_t / VERDICT_RISE_S)
		_arm.rotation_degrees.x = lerpf(ARM_TUCKED_DEG, ARM_EXTENDED_DEG, t)
	elif _pose_t < VERDICT_RISE_S + VERDICT_HOLD_S:
		_arm.rotation_degrees.x = ARM_EXTENDED_DEG
	elif _pose_t < VERDICT_RISE_S + VERDICT_HOLD_S + VERDICT_SETTLE_S:
		var t := smoothstep(0.0, 1.0, (_pose_t - VERDICT_RISE_S - VERDICT_HOLD_S) / VERDICT_SETTLE_S)
		_arm.rotation_degrees.x = lerpf(ARM_EXTENDED_DEG, ARM_TUCKED_DEG, t)
	else:
		_show_seated()
