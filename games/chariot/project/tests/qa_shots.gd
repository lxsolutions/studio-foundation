extends RefCounted
## The Chariot Club's visual QA shots, run by studio_core's qa_capture gate:
##   just GAME=games/chariot qa-godot
##
## Every shot is driven through the same seams the wire uses
## (_on_spectate_event with server-shaped payloads), never by posing nodes, so
## a still is always of a state the race office could really produce. The
## transport stays parked (RACING_SPECTATE_OFFLINE) — a capture that depends
## on a live server photographs whatever that server happens to be doing,
## which on a shared dev box once meant another game's server on this port.
##
## Frame bounds are calibrated from measured captures on the ANGLE/compat
## path, not guessed; recalibrate from build/qa/report.json if the grade
## deliberately changes.

## One eight-horse field, used by every race shot. h1 belongs to the signed-in
## stable in the rider shots, so the rider HUD has a drive to show.
const ENTRIES: Array = [
	{"horseId": "h1", "horseName": "Boreas", "number": 1, "gate": 1, "tint": 0, "silk": "crimson"},
	{"horseId": "h2", "horseName": "Zephyros", "number": 2, "gate": 2, "tint": 1, "silk": "azure"},
	{"horseId": "h3", "horseName": "Aithon", "number": 3, "gate": 3, "tint": 2, "silk": "gold"},
	{"horseId": "h4", "horseName": "Phlegon", "number": 4, "gate": 4, "tint": 3, "silk": "ivory"},
	{"horseId": "h5", "horseName": "Notos", "number": 5, "gate": 5, "tint": 4, "silk": "viridian"},
	{"horseId": "h6", "horseName": "Euros", "number": 6, "gate": 6, "tint": 5, "silk": "violet"},
	{"horseId": "h7", "horseName": "Pyrois", "number": 7, "gate": 7, "tint": 6, "silk": "umber"},
	{"horseId": "h8", "horseName": "Lampos", "number": 8, "gate": 8, "tint": 7, "silk": "rose"},
]

const RACE: Dictionary = {
	"name": "The Sunset Handicap", "distance": 700.0, "entries": ENTRIES,
	# The running caption renders distance/surface/weather; a fixture without
	# these photographs "700m · ·" and reads as a caption bug that isn't.
	"surface": "sand", "weather": "clear",
}

const RESULTS: Array = [
	{"pos": 1, "horseName": "Aithon", "stableName": "Kadmos Stables", "timeMs": 83450, "earned": 120},
	{"pos": 2, "horseName": "Boreas", "stableName": "Kadmos Stables", "timeMs": 84100, "earned": 60},
	{"pos": 3, "horseName": "Zephyros", "stableName": "Nikias Yard", "timeMs": 84800, "earned": 30},
	{"pos": 4, "horseName": "Notos", "stableName": "Nikias Yard", "timeMs": 86200, "earned": 0},
]

## Each device photographs the tier it would really ship: honest crowd
## density, and a mobile-tier build is ~15x fewer instances than desktop —
## which is also what keeps a full sweep tractable on the software rasterizer.
const PROFILE_BY_DEVICE: Dictionary = {
	"desktop": "desktop_high", "tablet": "mobile_high", "phone": "mobile_high",
}


func env() -> Dictionary:
	return {"RACING_SPECTATE_OFFLINE": "1"}


func shots() -> Array:
	return [
		{
			# What a visitor meets first: the empty house running exhibition
			# laps. The saturation floor is the gray-wash alarm; the luma
			# bounds catch a lost lighting rig or a buried camera.
			"name": "establishing", "scene": "res://scenes/spectator.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"pre_setup": "disable_boot_route", "run_s": 2.0,
			"devices": ["desktop", "tablet", "phone"],
			"frame": {"luma_min": 50.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
		{
			# The field loaded at the carceres, clock counting down.
			"name": "gate", "scene": "res://scenes/spectator.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"pre_setup": "disable_boot_route", "setup": "inject_gate", "run_s": 2.0,
			"devices": ["desktop"],
			"frame": {"luma_min": 50.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
		{
			# Mid-race: chase camera on the field, running order filling the
			# strip. The strip staying on screen at phone size is the check
			# that caught the running order off the bottom in BOTH views once.
			"name": "running", "scene": "res://scenes/spectator.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"pre_setup": "disable_boot_route", "setup": "inject_running", "run_s": 2.0,
			"devices": ["desktop", "phone"],
			"frame": {"luma_min": 50.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
		{
			# The laurel board over the settled race.
			"name": "verdict", "scene": "res://scenes/spectator.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"pre_setup": "disable_boot_route", "setup": "inject_finished", "run_s": 2.5,
			"devices": ["desktop", "phone"],
			"frame": {"luma_min": 45.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
		{
			# The sign-in gate: the first thing a new owner ever sees. Tap
			# floors on the code box, the join button and both link buttons —
			# at phone scale these are the controls a thumb must actually hit.
			"name": "signin", "scene": "res://scenes/rider.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"run_s": 1.2,
			"devices": ["desktop", "tablet", "phone"],
			"frame": {"luma_min": 45.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
		{
			# The surface an owner drives from: signed in, own horse running,
			# whip/guide/block bar up. This screen is looked at for the whole
			# race and was never once photographed before this shot existed.
			"name": "rider_live", "scene": "res://scenes/rider.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"setup": "inject_rider_live", "run_s": 2.0,
			"devices": ["desktop", "phone"],
			"frame": {"luma_min": 50.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
	]


## The stands would route a machine with a remembered code straight to the
## rider's gate, which is not what the spectator shots photograph.
func disable_boot_route(view: Node) -> void:
	view.set("boot_route_enabled", false)


func inject_gate(view: Node) -> void:
	view.call("_on_spectate_event", "spectate:hello",
		{"phase": "gate", "startsInMs": 12000, "race": RACE})


func inject_running(view: Node) -> void:
	view.call("_on_spectate_event", "spectate:hello", {"phase": "running", "race": RACE})
	view.call("_on_spectate_event", "race:tick", _tick())


func inject_finished(view: Node) -> void:
	inject_running(view)
	var settled := RACE.duplicate()
	settled["results"] = RESULTS
	view.call("_on_spectate_event", "race:phase", {"status": "finished", "race": settled})


func inject_rider_live(view: Node) -> void:
	view.call("_on_spectate_event", "auth:ok", {"user": {"name": "Kadmos Stables"}})
	view.call("_on_spectate_event", "horses:update", {"horses": [
		{"id": "h1", "name": "Boreas"}, {"id": "h3", "name": "Aithon"},
	]})
	view.call("_on_spectate_event", "races:update", {"races": []})
	inject_running(view)


## Mid-race field: leader at 240 m of 700, tail 60 m back, lanes fanned.
func _tick() -> Dictionary:
	var horses: Array = []
	for index in ENTRIES.size():
		var entry: Dictionary = ENTRIES[index]
		horses.append({
			"horseId": entry["horseId"],
			"rank": index + 1,
			"pos": 240.0 - 9.0 * index,
			"speed": 16.5 - 0.3 * index,
			"finished": false,
			"lane": float(1 + (index % 8)),
		})
	return {"t": 42.5, "horses": horses}
