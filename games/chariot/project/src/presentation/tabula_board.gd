class_name TabulaBoard
extends Node3D

## The colosseum's tabula: a marble-framed board on the infield by the
## finish, facing the stands, carrying the announcer's headline and the
## running order the way Derby Owners' infield screen carries the tote.
## Built at runtime from primitive meshes (the house's crowd does the same);
## the view feeds it through set_board() and never reaches inside.

const BOARD_W := 16.0
const BOARD_H := 8.6
const SCREEN_INSET := 0.7
const INFIELD_OFFSET_M := -16.0
const LEG_H := 4.6

var _headline: Label3D
var _detail: Label3D


func _ready() -> void:
	_build()


## Stands on the infield across from the finish line, its face toward the
## home-straight crowd. normal_at points OUTWARD, so the infield sits at a
## negative offset and the face looks along +normal.
static func stand_position() -> Vector3:
	var finish := TrackGeometry.finish_s()
	return TrackGeometry.point_at(finish) + TrackGeometry.normal_at(finish) * INFIELD_OFFSET_M


static func face_direction() -> Vector3:
	return TrackGeometry.normal_at(TrackGeometry.finish_s())


func _build() -> void:
	var marble := StandardMaterial3D.new()
	marble.albedo_color = Color(0.788, 0.757, 0.678)
	marble.roughness = 0.55
	var slate := StandardMaterial3D.new()
	slate.albedo_color = Color(0.075, 0.067, 0.058)
	slate.roughness = 0.35
	var gold := StandardMaterial3D.new()
	gold.albedo_color = Color(0.855, 0.647, 0.216)
	gold.metallic = 0.6
	gold.roughness = 0.35

	var frame := MeshInstance3D.new()
	frame.name = "Frame"
	var frame_mesh := BoxMesh.new()
	frame_mesh.size = Vector3(BOARD_W + 1.6, BOARD_H + 1.6, 0.8)
	frame.mesh = frame_mesh
	frame.material_override = marble
	frame.position = Vector3(0.0, LEG_H + BOARD_H / 2.0, 0.0)
	add_child(frame)

	var screen := MeshInstance3D.new()
	screen.name = "Screen"
	var screen_mesh := BoxMesh.new()
	screen_mesh.size = Vector3(BOARD_W, BOARD_H, 0.3)
	screen.mesh = screen_mesh
	screen.material_override = slate
	screen.position = Vector3(0.0, LEG_H + BOARD_H / 2.0, 0.3)
	add_child(screen)

	var laurel := MeshInstance3D.new()
	laurel.name = "Crown"
	var laurel_mesh := BoxMesh.new()
	laurel_mesh.size = Vector3(4.2, 0.5, 0.5)
	laurel.mesh = laurel_mesh
	laurel.material_override = gold
	laurel.position = Vector3(0.0, LEG_H + BOARD_H + 1.1, 0.0)
	add_child(laurel)

	for x_sign in [-1.0, 1.0]:
		var leg := MeshInstance3D.new()
		leg.name = "LegL" if x_sign < 0.0 else "LegR"
		var leg_mesh := BoxMesh.new()
		leg_mesh.size = Vector3(1.1, LEG_H, 1.1)
		leg.mesh = leg_mesh
		leg.material_override = marble
		leg.position = Vector3(x_sign * (BOARD_W / 2.0 - 1.2), LEG_H / 2.0, 0.0)
		add_child(leg)

	_headline = Label3D.new()
	_headline.name = "Headline"
	_headline.font_size = 148
	_headline.pixel_size = 0.0095
	_headline.width = int((BOARD_W - SCREEN_INSET * 2.0) / 0.0095)
	_headline.autowrap_mode = TextServer.AUTOWRAP_WORD
	_headline.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_headline.modulate = Color(0.957, 0.808, 0.463)
	_headline.outline_size = 22
	_headline.outline_modulate = Color(0.02, 0.02, 0.02)
	_headline.position = Vector3(0.0, LEG_H + BOARD_H - 2.0, 0.62)
	add_child(_headline)

	_detail = Label3D.new()
	_detail.name = "Detail"
	_detail.font_size = 96
	_detail.pixel_size = 0.0095
	_detail.width = int((BOARD_W - SCREEN_INSET * 2.0) / 0.0095)
	_detail.autowrap_mode = TextServer.AUTOWRAP_WORD
	_detail.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_detail.modulate = Color(0.949, 0.925, 0.847)
	_detail.outline_size = 16
	_detail.outline_modulate = Color(0.02, 0.02, 0.02)
	_detail.position = Vector3(0.0, LEG_H + BOARD_H / 2.0 - 1.1, 0.62)
	add_child(_detail)


func set_board(headline: String, detail: String) -> void:
	if not headline.is_empty():
		_headline.text = headline
	_detail.text = detail


func headline_text() -> String:
	return _headline.text


func detail_text() -> String:
	return _detail.text
