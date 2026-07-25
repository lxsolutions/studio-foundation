class_name TrainingState
extends RefCounted

## The live training session as the server tells it: a drifting gold zone, an
## effort needle, surge windows, and a settled result. Ticks arrive only for
## the owner's own session, so any tick is ours; DRIVE and EASE are the only
## words we may say back, and the score is never computed client-side.

var session_id: String = ""
var t: float = 0.0
var effort: float = 0.0
var zone_lo: float = 0.0
var zone_hi: float = 0.0
var score: float = 0.0
var surge: bool = false
var seconds_left: float = 0.0
var result: Dictionary = {}
var horse_name: String = ""
var programme_line: String = ""


func active() -> bool:
	return not session_id.is_empty() and result.is_empty()


func finished() -> bool:
	return not result.is_empty()


func in_zone() -> bool:
	return effort >= zone_lo and effort <= zone_hi


func apply(event_name: String, data: Variant) -> bool:
	match event_name:
		"training:tick":
			if typeof(data) != TYPE_DICTIONARY or not data.has("sessionId"):
				return false
			var tick: Dictionary = data
			if not result.is_empty() and str(tick["sessionId"]) != session_id:
				result = {}
			session_id = str(tick["sessionId"])
			t = float(tick.get("t", t))
			effort = float(tick.get("effort", effort))
			zone_lo = float(tick.get("zoneLo", zone_lo))
			zone_hi = float(tick.get("zoneHi", zone_hi))
			score = float(tick.get("score", score))
			surge = bool(tick.get("surge", false))
			seconds_left = float(tick.get("secondsLeft", seconds_left))
			return true
		"training:done":
			if typeof(data) != TYPE_DICTIONARY or typeof(data.get("result")) != TYPE_DICTIONARY:
				return false
			var done: Dictionary = data
			if not session_id.is_empty() and str(done.get("sessionId", "")) != session_id:
				return false
			session_id = str(done.get("sessionId", session_id))
			result = done.get("result")
			var horse: Variant = done.get("horse")
			if typeof(horse) == TYPE_DICTIONARY:
				horse_name = str(horse.get("name", ""))
			programme_line = _programme_summary(done.get("programmeResult"))
			return true
	return false


func clear() -> void:
	session_id = ""
	result = {}
	surge = false
	score = 0.0
	programme_line = ""


func result_line() -> String:
	if result.is_empty():
		return ""
	var pieces: Array[String] = ["Score %d" % int(result.get("score", 0))]
	var stat := str(result.get("stat", ""))
	if not stat.is_empty():
		pieces.append("%s +%.1f" % [stat, float(result.get("gain", 0.0))])
	var condition := float(result.get("conditionDelta", 0.0))
	if not is_zero_approx(condition):
		pieces.append("condition %+.0f" % condition)
	return "  ·  ".join(pieces)


static func _programme_summary(programme_result: Variant) -> String:
	if typeof(programme_result) != TYPE_DICTIONARY:
		return ""
	var pr: Dictionary = programme_result
	var pieces: Array[String] = []
	if pr.has("matched"):
		pieces.append("programme step matched" if bool(pr.get("matched")) else "off the programme")
	if pr.has("progress"):
		pieces.append(str(pr.get("progress")))
	if pr.has("nextFocus") and str(pr.get("nextFocus", "")) != "":
		pieces.append("next: %s" % str(pr.get("nextFocus")))
	return "  ·  ".join(pieces)
