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
		{
			# The training needle mid-session — the platosplaza edition's
			# panel was once re-pinned blind; here every session gets a still.
			"name": "training", "scene": "res://scenes/rider.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"setup": "inject_training", "run_s": 1.2,
			"devices": ["desktop", "phone"],
			"frame": {"luma_min": 45.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
		{
			# ...and the settled result the wire hands back, rendered verbatim.
			"name": "training_done", "scene": "res://scenes/rider.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"setup": "inject_training_done", "run_s": 1.2,
			"devices": ["desktop", "phone"],
			"frame": {"luma_min": 45.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
		{
			# The stable yard: the raise-train-race hub and the largest HUD
			# surface in the game. Its board hung entirely OFF a phone's
			# canvas until this shot existed.
			"name": "stable_yard", "scene": "res://scenes/rider.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"setup": "inject_stable_yard", "run_s": 1.2,
			"devices": ["desktop", "phone"],
			"frame": {"luma_min": 45.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
		{
			"name": "stable_bloodstock", "scene": "res://scenes/rider.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"setup": "inject_stable_bloodstock", "run_s": 1.2,
			"devices": ["desktop", "phone"],
			"frame": {"luma_min": 45.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
		{
			"name": "stable_exchange", "scene": "res://scenes/rider.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"setup": "inject_stable_exchange", "run_s": 1.2,
			"devices": ["desktop", "phone"],
			"frame": {"luma_min": 45.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
		{
			"name": "stable_honours", "scene": "res://scenes/rider.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"setup": "inject_stable_honours", "run_s": 1.2,
			"devices": ["desktop", "phone"],
			"frame": {"luma_min": 45.0, "luma_max": 190.0, "sat_min": 0.05},
			"hud": {"margin": 2.0},
		},
		{
			"name": "stable_circuit", "scene": "res://scenes/rider.tscn",
			"profiles": PROFILE_BY_DEVICE,
			"setup": "inject_stable_circuit", "run_s": 1.2,
			"devices": ["desktop", "phone"],
			"frame": {"luma_min": 45.0, "luma_max": 190.0, "sat_min": 0.05},
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


## The signed-in stable, shaped like horses:update really is: yard rows read
## grade/condition/bond/record, bloodstock needs sexes for the sire/dam picks.
const MY_HORSES: Array = [
	{"id": "h1", "name": "Boreas", "grade": "B", "sex": "colt",
		"condition": 82, "bond": 61, "record": {"wins": 3, "starts": 9}},
	{"id": "h3", "name": "Aithon", "grade": "A", "sex": "stallion",
		"condition": 74, "bond": 77, "record": {"wins": 6, "starts": 14}},
	{"id": "h9", "name": "Melite", "grade": "C", "sex": "filly",
		"condition": 66, "bond": 40, "record": {"wins": 0, "starts": 2}},
]

const TRAINING_TICK: Dictionary = {
	"sessionId": "s1", "t": 6.0, "effort": 62.0, "zoneLo": 40.0,
	"zoneHi": 70.0, "score": 14.0, "surge": false, "secondsLeft": 9.0,
}

const TRAINING_DONE: Dictionary = {
	"sessionId": "s1", "horse": {"name": "Boreas"},
	"result": {"score": 78, "stat": "stamina", "gain": 1.4, "conditionDelta": -6.0},
}

const EXCHANGE: Dictionary = {
	"purse": 740,
	"listings": [
		{"id": "l1", "horseName": "Kalliste", "grade": "B", "stableName": "Nikias Yard", "price": 260, "mine": false},
		{"id": "l2", "horseName": "Pyrois", "grade": "C", "stableName": "Kadmos Stables", "price": 180, "mine": true},
	],
}

const HONOURS: Dictionary = {
	"honours": [
		{"id": "first_win", "name": "First Laurels", "current": 3, "target": 1, "earned": true, "claimable": false},
		{"id": "campaigner", "name": "Campaigner", "current": 9, "target": 10, "earned": false, "claimable": false},
		{"id": "bloodline", "name": "Bloodline Keeper", "current": 1, "target": 1, "earned": false, "claimable": true},
	],
}

const CIRCUIT: Dictionary = {
	"season": {"id": "2026-S3"},
	"myStable": {"rank": 4, "points": 128, "title": "Rising Yard",
		"nextGoal": "Top three finishes earn the Crown invitation"},
	"stableStandings": [
		{"stableName": "Helios House", "points": 402, "wins": 21},
		{"stableName": "Nikias Yard", "points": 335, "wins": 17},
		{"stableName": "Argent Stables", "points": 300, "wins": 12},
		{"stableName": "Kadmos Stables", "points": 128, "wins": 6},
	],
}


func inject_rider_live(view: Node) -> void:
	_sign_in(view)
	inject_running(view)


func inject_training(view: Node) -> void:
	_sign_in(view)
	view.call("_on_spectate_event", "training:tick", TRAINING_TICK)


func inject_training_done(view: Node) -> void:
	inject_training(view)
	view.call("_on_spectate_event", "training:done", TRAINING_DONE)


func inject_stable_yard(view: Node) -> void:
	_sign_in(view)
	view.call("_toggle_stable")


func inject_stable_bloodstock(view: Node) -> void:
	inject_stable_yard(view)
	view.call("_open_section", "BLOODSTOCK")


## Projection sections render off the same callback the REST client fires;
## offline, the fetch is captured rather than sent, so the injected payload
## is the only content and nothing races it.
func inject_stable_exchange(view: Node) -> void:
	inject_stable_yard(view)
	view.call("_open_section", "EXCHANGE")
	view.call("_on_stable_projection", "/api/exchange", true, "", {"exchange": EXCHANGE})


func inject_stable_honours(view: Node) -> void:
	inject_stable_yard(view)
	view.call("_open_section", "HONOURS")
	view.call("_on_stable_projection", "/api/honours", true, "", {"honours": HONOURS})


func inject_stable_circuit(view: Node) -> void:
	inject_stable_yard(view)
	view.call("_open_section", "CIRCUIT")
	view.call("_on_stable_projection", "/api/circuit", true, "", {"circuit": CIRCUIT})


func _sign_in(view: Node) -> void:
	view.call("_on_spectate_event", "auth:ok", {"user": {"name": "Kadmos Stables"}})
	view.call("_on_spectate_event", "horses:update", {"horses": MY_HORSES})
	view.call("_on_spectate_event", "races:update", {"races": _open_races()})


## Two open races: one with a post time eight minutes out (the countdown
## branch), one schedule-less (the "awaiting the stewards" branch). Post
## times are computed at injection because they must sit in the future.
func _open_races() -> Array:
	var now_ms := int(Time.get_unix_time_from_system() * 1000.0)
	return [
		{"id": "r1", "name": "The Dawn Sprint", "status": "open",
			"distance": 450, "surface": "sand",
			"entries": [{"horseId": "h2"}, {"horseId": "h5"}],
			"scheduledFor": now_ms + 8 * 60 * 1000},
		{"id": "r2", "name": "The Stewards' Trial", "status": "open",
			"distance": 700, "surface": "sand",
			"entries": []},
	]


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
