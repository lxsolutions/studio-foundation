class_name AudioCues
extends RefCounted

## Which sounds accompany which race moments, as pure data: feed the phase
## transition, get cue dictionaries back ({play: name} one-shots and
## {loop: name, on: bool, volume_db: float} bed changes). The players stay
## dumb; every decision lives here where it is testable without an audio
## driver. Arriving mid-race is deliberately quiet about the moment you
## missed: the gate only clangs out of gate or parade, the crowd only roars
## over a finish you watched run.

const CROWD_PARADE_DB := -16.0
const CROWD_HUSH_DB := -20.0
const CROWD_RACE_DB := -12.0
const CROWD_AFTER_DB := -14.0
const GALLOP_DB := -10.0
const WHEEL_DB := -14.0


static func for_transition(now_phase: String, was_phase: String) -> Array[Dictionary]:
	if now_phase == was_phase:
		return []
	match now_phase:
		"parading":
			return [_crowd(CROWD_PARADE_DB), _gallop_off(), _wheels_off()]
		"gate":
			return [_crowd(CROWD_HUSH_DB), _gallop_off(), _wheels_off()]
		"running":
			var running: Array[Dictionary] = [
				_crowd(CROWD_RACE_DB),
				{ "loop": "gallop_loop", "on": true, "volume_db": GALLOP_DB },
				{ "loop": "wheel_loop", "on": true, "volume_db": WHEEL_DB },
			]
			if was_phase == "gate" or was_phase == "parading":
				running.push_front({ "play": "gate_clang" })
			return running
		"finished":
			var finished: Array[Dictionary] = [_gallop_off(), _wheels_off(), _crowd(CROWD_AFTER_DB)]
			if was_phase == "running":
				finished.append({ "play": "crowd_swell" })
				finished.append({ "play": "fanfare" })
			return finished
		_:
			return [_gallop_off(), _wheels_off(), { "loop": "crowd_loop", "on": false }]


static func _crowd(volume_db: float) -> Dictionary:
	return { "loop": "crowd_loop", "on": true, "volume_db": volume_db }


static func _gallop_off() -> Dictionary:
	return { "loop": "gallop_loop", "on": false }


static func _wheels_off() -> Dictionary:
	return { "loop": "wheel_loop", "on": false }
