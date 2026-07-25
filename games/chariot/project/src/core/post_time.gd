class_name PostTime
extends RefCounted

## The idle screen's answer to "what do I do now". Derby cabinets never leave
## the player guessing: name the race they are entered in, count down to post,
## and point at the stable while they wait. Server epoch millis meet the local
## clock here, so a skewed machine clamps to "any moment" instead of lying.


static func clock(ms_left: int) -> String:
	var total_s := maxi(0, ms_left) / 1000
	return "%d:%02d" % [total_s / 60, total_s % 60]


## One line for the idle caption. Empty when the rider is not signed in or
## holds no horses; the caller keeps the plain colosseum caption then.
static func status_line(open_races: Array, my_horse_ids: Array, now_ms: int) -> String:
	if my_horse_ids.is_empty():
		return ""
	var mine: Dictionary = {}
	var mine_at := 0
	for race in open_races:
		if typeof(race) != TYPE_DICTIONARY:
			continue
		var entries: Variant = race.get("entries", [])
		if typeof(entries) != TYPE_ARRAY:
			continue
		for entry in entries:
			if typeof(entry) != TYPE_DICTIONARY:
				continue
			if str(entry.get("horseId", "")) in my_horse_ids:
				var at := int(race.get("scheduledFor", 0))
				if mine.is_empty() or (at > 0 and (mine_at == 0 or at < mine_at)):
					mine = race
					mine_at = at
	if mine.is_empty():
		return "Enter a race from your stable, then train while you wait."
	var name := str(mine.get("name", "the next race"))
	if mine_at <= 0:
		return "You're in the %s. The stewards will call the field." % name
	var left := mine_at - now_ms
	if left <= 0:
		return "You're in the %s. Post time any moment, reins ready." % name
	return "You're in the %s. Post time %s. Train while you wait." % [name, clock(left)]
