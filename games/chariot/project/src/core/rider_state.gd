class_name RiderState
extends RefCounted

## Everything the rider screen knows about the signed-in owner, folded from
## main-namespace events. Pure and server-shaped: the sim's authority is never
## second-guessed here, and inputs are "encouragements" the view sends without
## predicting their outcome.

var user: Dictionary = {}
var my_horse_ids: Dictionary = {}
var my_horses: Array = []
var races: Array = []
var auth_error: String = ""
var last_toast: Dictionary = {}
var my_race_horse_id: String = ""
var my_tick: Dictionary = {}


func signed_in() -> bool:
	return not user.is_empty()


func stable_name() -> String:
	return str(user.get("name", ""))


func apply(event_name: String, data: Variant) -> bool:
	match event_name:
		"auth:ok":
			if typeof(data) != TYPE_DICTIONARY or typeof(data.get("user")) != TYPE_DICTIONARY:
				return false
			user = data.get("user")
			auth_error = ""
			return true
		"auth:error":
			auth_error = str(data.get("message", "authentication failed")) if typeof(data) == TYPE_DICTIONARY else "authentication failed"
			user = {}
			return true
		"horses:update":
			if typeof(data) != TYPE_DICTIONARY or typeof(data.get("horses")) != TYPE_ARRAY:
				return false
			my_horse_ids.clear()
			my_horses = []
			for horse in data.get("horses"):
				if typeof(horse) == TYPE_DICTIONARY and horse.has("id"):
					my_horse_ids[str(horse["id"])] = true
					my_horses.append(horse)
			return true
		"races:update":
			if typeof(data) != TYPE_DICTIONARY or typeof(data.get("races")) != TYPE_ARRAY:
				return false
			races = data.get("races")
			return true
		"toast":
			if typeof(data) != TYPE_DICTIONARY:
				return false
			last_toast = data
			return true
	return false


## Called with the race entries whenever the race picture changes: remembers
## which entry is mine, if any.
func track_my_entry(entries_by_horse: Dictionary) -> void:
	my_race_horse_id = ""
	for horse_id: String in entries_by_horse:
		if my_horse_ids.has(horse_id):
			my_race_horse_id = horse_id
			return


func riding() -> bool:
	return not my_race_horse_id.is_empty()


## Pull my horse's row out of a race:tick horses array.
func fold_tick(tick_horses: Array) -> void:
	if my_race_horse_id.is_empty():
		my_tick = {}
		return
	for horse in tick_horses:
		if typeof(horse) == TYPE_DICTIONARY and str(horse.get("horseId", "")) == my_race_horse_id:
			my_tick = horse
			return


func my_energy() -> float:
	return float(my_tick.get("energy", 0.0))


func my_rank() -> int:
	return int(my_tick.get("rank", 0))


func my_finished() -> bool:
	return bool(my_tick.get("finished", false))


func my_remaining_m(tick_data: Dictionary) -> float:
	var remaining: Variant = tick_data.get("remainingM", {})
	if typeof(remaining) == TYPE_DICTIONARY and remaining.has(my_race_horse_id):
		return float(remaining[my_race_horse_id])
	return -1.0


func open_races() -> Array:
	var out: Array = []
	for race in races:
		if typeof(race) == TYPE_DICTIONARY and str(race.get("status", "")) == "open":
			out.append(race)
	return out


## The yard's working string: horses the club will still train, feed, and
## enter. The server keeps sold and retired horses on the owner's list — the
## sale is a record, not an erasure — so the yard filters here; without it the
## first tap on ENTER meets "This horse is no longer active."
func active_horses() -> Array:
	var out: Array = []
	for horse in my_horses:
		if typeof(horse) == TYPE_DICTIONARY and str(horse.get("status", "active")) == "active":
			out.append(horse)
	return out


## The horse the yard's actions ride on: the current pick while it is still
## active, the first active horse when the pick sold or retired out from
## under the rider, or "" when the string is empty.
func pick_active(current_id: String) -> String:
	var active := active_horses()
	for horse in active:
		if str(horse.get("id", "")) == current_id:
			return current_id
	if active.is_empty():
		return ""
	return str((active[0] as Dictionary).get("id", ""))


## The raceId this horse is entered in, or "" — only open races count, because
## locked and later phases can no longer be withdrawn from.
func entered_open_race(horse_id: String) -> String:
	for race in open_races():
		var entries: Variant = race.get("entries", [])
		if typeof(entries) != TYPE_ARRAY:
			continue
		for entry in entries:
			if typeof(entry) == TYPE_DICTIONARY and str(entry.get("horseId", "")) == horse_id:
				return str(race.get("id", ""))
	return ""
