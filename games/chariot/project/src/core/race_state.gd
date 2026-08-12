class_name RaceState
extends RefCounted

## Deterministic model of everything the broadcast renders. The server is the
## only authority: this class just folds /spectate events into a picture and
## never invents state the protocol did not send.

const PHASE_IDLE := "idle"
const PHASE_PARADING := "parading"
const PHASE_GATE := "gate"
const PHASE_RUNNING := "running"
const PHASE_FINISHED := "finished"

var phase: String = PHASE_IDLE
var race: Dictionary = {}
var entries_by_horse: Dictionary = {}
var tick_horses: Array = []
var tick_t: float = 0.0
var starts_in_ms: int = -1
var results: Array = []
## Points per faction for the settled race, all four always present.
var faction_points: Dictionary = CircusFactions.tally([])


func apply(event_name: String, data: Variant) -> bool:
	match event_name:
		"spectate:hello":
			if typeof(data) != TYPE_DICTIONARY:
				return false
			var hello: Dictionary = data
			phase = str(hello.get("phase", PHASE_IDLE))
			starts_in_ms = int(hello.get("startsInMs", -1)) if hello.has("startsInMs") else -1
			_set_race(hello.get("race"))
			return true
		"race:phase":
			if typeof(data) != TYPE_DICTIONARY:
				return false
			var phased: Dictionary = data
			phase = str(phased.get("status", phase))
			starts_in_ms = int(phased.get("startsInMs", -1)) if phased.has("startsInMs") else -1
			_set_race(phased.get("race"))
			return true
		"race:tick":
			if typeof(data) != TYPE_DICTIONARY:
				return false
			var tick: Dictionary = data
			var horses: Variant = tick.get("horses")
			if typeof(horses) != TYPE_ARRAY:
				return false
			tick_horses = horses
			tick_t = float(tick.get("t", tick_t))
			return true
	return false


func _set_race(new_race: Variant) -> void:
	entries_by_horse.clear()
	results = []
	faction_points = CircusFactions.tally([])
	if typeof(new_race) != TYPE_DICTIONARY:
		race = {}
		tick_horses = []
		return
	race = new_race
	if typeof(race.get("results")) == TYPE_ARRAY:
		results = race.get("results")
	var entries: Variant = race.get("entries")
	if typeof(entries) == TYPE_ARRAY:
		var index := 0
		for raw_entry in entries:
			if typeof(raw_entry) != TYPE_DICTIONARY:
				continue
			var entry: Dictionary = raw_entry
			if not entry.has("horseId"):
				continue
			# Every horse wears a color: the wire's silk, or the fallback
			# palette in gate order. The tally then always has a faction to
			# resolve, and it is the one the broadcast paints.
			CircusFactions.effective_silk(entry, index)
			entries_by_horse[str(entry["horseId"])] = entry
			index += 1
	_tag_finishers()


## Every finisher carries their faction ("faction" key added to the result
## row) and the race's points tally folds from that. Resolution lives in
## CircusFactions: explicit wire key, then silk, then the parade entry.
func _tag_finishers() -> void:
	for result in results:
		if typeof(result) != TYPE_DICTIONARY:
			continue
		(result as Dictionary)["faction"] = CircusFactions.result_faction(result, entries_by_horse)
	faction_points = CircusFactions.tally(results)


func race_name() -> String:
	return str(race.get("name", ""))


func race_distance() -> float:
	return float(race.get("distance", 0.0))


func entry_for(horse_id: String) -> Dictionary:
	return entries_by_horse.get(horse_id, {})


func leader_id() -> String:
	for horse in tick_horses:
		if typeof(horse) == TYPE_DICTIONARY and int(horse.get("rank", 0)) == 1:
			return str(horse.get("horseId", ""))
	if not tick_horses.is_empty() and typeof(tick_horses[0]) == TYPE_DICTIONARY:
		return str(tick_horses[0].get("horseId", ""))
	return ""


## Race clock formatting, truncated to tenths like the tote board:
## 83450 ms reads 1:23.4, and a sprint under the minute reads 43.2.
static func format_time_ms(time_ms: int) -> String:
	var tenths := time_ms / 100
	var minutes := tenths / 600
	var rest := tenths % 600
	if minutes == 0:
		return "%d.%d" % [rest / 10, rest % 10]
	return "%d:%02d.%d" % [minutes, rest / 10, rest % 10]


func ranked_names(limit: int) -> Array[String]:
	var out: Array[String] = []
	for horse in tick_horses:
		if out.size() >= limit:
			break
		if typeof(horse) != TYPE_DICTIONARY:
			continue
		var horse_id := str(horse.get("horseId", ""))
		var entry := entry_for(horse_id)
		var display := str(entry.get("horseName", horse_id))
		out.append("%d  %s" % [int(horse.get("rank", out.size() + 1)), display])
	return out
