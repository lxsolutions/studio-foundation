class_name Announcer
extends RefCounted

## The colosseum's voice as pure data: feed it phase transitions and the
## running order, get the tabula's headline lines back. Follows the audio
## doctrine's honesty about arrivals — a spectator who walks in mid-race is
## never told about a break they did not see.


static func for_transition(now_phase: String, was_phase: String, race_name: String) -> String:
	if now_phase == was_phase:
		return ""
	match now_phase:
		"parading":
			return "The teams parade for %s" % race_name if not race_name.is_empty() else "The grand parade"
		"gate":
			return "They load the carceres"
		"running":
			if was_phase == "gate" or was_phase == "parading":
				return "THE BREAK — they're away!"
			return "Racing is under way"
		"finished":
			return "The laurels are decided"
		"idle":
			return "The colosseum waits for the next race"
		_:
			return ""


## The running story: silent while the same team shows the way, a call the
## moment the lead changes hands. previous_leader empty means the first call.
static func leader_line(leader_name: String, previous_leader: String) -> String:
	if leader_name.is_empty() or leader_name == previous_leader:
		return ""
	if previous_leader.is_empty():
		return "%s shows the way" % leader_name
	return "%s takes the lead!" % leader_name


static func stretch_line(leader_name: String) -> String:
	if leader_name.is_empty():
		return "Into the final stretch!"
	return "%s into the final stretch!" % leader_name


## Victory from the settled results, verbatim server names.
static func victory_line(results: Array) -> String:
	for result in results:
		if typeof(result) != TYPE_DICTIONARY:
			continue
		if int(result.get("pos", 0)) == 1:
			var stable := str(result.get("stableName", ""))
			var name := str(result.get("horseName", "?"))
			if stable.is_empty():
				return "Victory — %s!" % name
			return "Victory — %s, for %s!" % [name, stable]
	return ""
