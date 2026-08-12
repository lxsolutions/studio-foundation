class_name GhostRun
extends RefCounted

## A recorded time-trial run — "beat my lap". One horse's tick stream (t in
## milliseconds on the race clock, pos in meters, lane, speed) plus the
## official time, captured from the same spectate feed the broadcast renders.
## Pure data and math: no nodes, no rendering, so the whole module is
## headless-testable. The on-disk shape follows StudioReplay's convention (a
## schema-versioned JSON run file under user://) specialized for ticks.
##
## Bounds mirror server/src/ghosts.rs — change both or change neither. The
## server applies them to every submitted run; the client applies them before
## a run may be saved or armed, so a ghost that cannot have been a race is
## never stored or shown.

const SCHEMA := 1
const MIN_TICKS := 8
## 20k ticks at 200ms bounds a stored run to ~66 minutes of race clock.
const MAX_TICKS := 20000
const MIN_TOTAL_MS := 30000
const MAX_TOTAL_MS := 1200000
const MAX_HANDLE := 24
const MIN_LANE := 0.5
const MAX_LANE := 16.0
const MAX_POS_M := 50000.0
const MAX_SPEED_MPS := 100.0

## The spectate tick clock's unit is the server's business: seconds today, but
## the client never assumes. finish() measures the stream against the official
## timeMs (always milliseconds) and normalizes every tick to milliseconds;
## tick_scale_ms records the conversion so a live tick_t can be mapped onto
## the stored stream during a replay.
var tick_scale_ms := 1.0

var handle := ""
var faction := ""
var distance_m := 0.0
var total_ms := 0
var ticks: Array[Dictionary] = []
var _cursor := 0
var _last_query_ms := -1.0


## Start recording: rider handle (the stable name), declared faction, and the
## race's distance. The handle is clipped to the plate, never rejected here —
## validation_error() is the gate for saving.
func begin(p_handle: String, p_faction: String, p_distance_m: float) -> void:
	handle = p_handle.strip_edges().left(MAX_HANDLE)
	faction = p_faction
	distance_m = p_distance_m
	total_ms = 0
	ticks.clear()
	_cursor = 0
	_last_query_ms = -1.0
	tick_scale_ms = 1.0


## Fold one race:tick into the stream. horse_id picks the recorded horse out
## of the tick's horses array; a tick without that horse, or one whose clock
## ran backwards, adds nothing. t is the tick's raw race-clock value.
func sample(t: float, tick_horses: Array, horse_id: String) -> bool:
	if horse_id.is_empty():
		return false
	for horse in tick_horses:
		if typeof(horse) != TYPE_DICTIONARY:
			continue
		if str((horse as Dictionary).get("horseId", "")) != horse_id:
			continue
		if not ticks.is_empty() and t < float((ticks[-1] as Dictionary).get("t", 0.0)):
			return false
		ticks.append({
			"t": t,
			"pos": float((horse as Dictionary).get("pos", 0.0)),
			"lane": float((horse as Dictionary).get("lane", 1.0)),
			"speed": float((horse as Dictionary).get("speed", 0.0)),
		})
		return true
	return false


## Close the run with the official time (always milliseconds) and normalize
## every tick to the same millisecond clock. The scale is inferred, not
## assumed: a stream whose last sample sits ~1000x below the official time
## was carried in seconds. Anything closer to 1:1 was already milliseconds.
func finish(p_total_ms: int) -> void:
	total_ms = p_total_ms
	tick_scale_ms = 1.0
	if not ticks.is_empty():
		var last_t := float((ticks[-1] as Dictionary).get("t", 0.0))
		if last_t > 0.0 and float(total_ms) / last_t > 100.0:
			tick_scale_ms = 1000.0
	if tick_scale_ms != 1.0:
		for tick in ticks:
			(tick as Dictionary)["t"] = float((tick as Dictionary).get("t", 0.0)) * tick_scale_ms


## "" when the run may be saved, armed, or submitted; the reason otherwise.
## The same bounds the server enforces, in the same order.
func validation_error() -> String:
	if handle.is_empty() or handle.length() > MAX_HANDLE:
		return "a ghost handle is 1..=%d characters" % MAX_HANDLE
	if not CircusFactions.is_valid_id(faction):
		return "no such faction: %s" % faction
	if total_ms < MIN_TOTAL_MS or total_ms > MAX_TOTAL_MS:
		return "totalMs must sit within %d..=%d" % [MIN_TOTAL_MS, MAX_TOTAL_MS]
	if ticks.size() < MIN_TICKS or ticks.size() > MAX_TICKS:
		return "a ghost run holds %d..=%d ticks" % [MIN_TICKS, MAX_TICKS]
	if distance_m <= 0.0 or distance_m > MAX_POS_M:
		return "a ghost run needs a plausible distance"
	var last_t := -INF
	for tick in ticks:
		var t := float(tick.get("t", 0.0))
		var pos: float = tick.get("pos", 0.0)
		var lane: float = tick.get("lane", 0.0)
		var speed: float = tick.get("speed", 0.0)
		if is_nan(t) or is_nan(pos) or is_nan(lane) or is_nan(speed) \
			or is_inf(t) or is_inf(pos) or is_inf(lane) or is_inf(speed):
			return "tick values must be finite"
		if t < last_t:
			return "tick times must not run backwards"
		last_t = t
		if t < 0.0 or t > float(MAX_TOTAL_MS):
			return "tick times stay within 0..=%dms" % MAX_TOTAL_MS
		if pos < 0.0 or pos > MAX_POS_M:
			return "tick positions stay within 0..=%dm" % int(MAX_POS_M)
		if lane < MIN_LANE or lane > MAX_LANE:
			return "tick lanes stay within %s..=%s" % [str(MIN_LANE), str(MAX_LANE)]
		if speed < 0.0 or speed > MAX_SPEED_MPS:
			return "tick speeds stay within 0..=%dm/s" % int(MAX_SPEED_MPS)
	return ""


func is_valid() -> bool:
	return validation_error().is_empty()


func total_s() -> float:
	return float(total_ms) / 1000.0


func to_dict() -> Dictionary:
	return {
		"schema": SCHEMA,
		"handle": handle,
		"faction": faction,
		"distanceM": distance_m,
		"totalMs": total_ms,
		"tickScaleMs": tick_scale_ms,
		"ticks": ticks,
	}


## Parse a stored run. Returns null on anything that is not a schema-1 ghost
## run; validity (the bounds above) is a separate question callers ask with
## validation_error().
static func from_dict(data: Variant) -> GhostRun:
	if typeof(data) != TYPE_DICTIONARY:
		return null
	var dict: Dictionary = data
	if int(dict.get("schema", 0)) != SCHEMA:
		return null
	var raw_ticks: Variant = dict.get("ticks")
	if typeof(raw_ticks) != TYPE_ARRAY:
		return null
	var run := GhostRun.new()
	run.handle = str(dict.get("handle", ""))
	run.faction = str(dict.get("faction", ""))
	run.distance_m = float(dict.get("distanceM", 0.0))
	run.total_ms = int(dict.get("totalMs", 0))
	run.tick_scale_ms = float(dict.get("tickScaleMs", 1.0))
	for raw_tick in raw_ticks:
		if typeof(raw_tick) != TYPE_DICTIONARY:
			return null
		var tick: Dictionary = raw_tick
		run.ticks.append({
			"t": float(tick.get("t", 0.0)),
			"pos": float(tick.get("pos", 0.0)),
			"lane": float(tick.get("lane", 1.0)),
			"speed": float(tick.get("speed", 0.0)),
		})
	return run


## Where the ghost is at t_ms on the (normalized) race clock: an interpolated
## {pos, lane, speed}. Before the break the ghost waits at the gate; past the
## wire it stands at its final mark, speed bled to zero.
func position_at(t_ms: float) -> Dictionary:
	if ticks.is_empty():
		return {"pos": 0.0, "lane": 1.0, "speed": 0.0}
	if t_ms < _last_query_ms:
		_cursor = 0
	_last_query_ms = t_ms
	var first: Dictionary = ticks[0]
	if t_ms <= float(first.get("t", 0.0)):
		return {"pos": float(first.get("pos", 0.0)), "lane": float(first.get("lane", 1.0)), "speed": 0.0}
	while _cursor < ticks.size() - 2 and float((ticks[_cursor + 1] as Dictionary).get("t", 0.0)) < t_ms:
		_cursor += 1
	var a: Dictionary = ticks[_cursor]
	var b: Dictionary = ticks[mini(_cursor + 1, ticks.size() - 1)]
	var a_t := float(a.get("t", 0.0))
	var b_t := float(b.get("t", 0.0))
	if t_ms >= b_t:
		# At or past the final sample the run is over: hold the mark, bleed
		# the speed, let the ghost stand at the wire it already crossed.
		var at_end := _cursor >= ticks.size() - 2
		return {
			"pos": float(b.get("pos", 0.0)),
			"lane": float(b.get("lane", 1.0)),
			"speed": 0.0 if at_end else float(b.get("speed", 0.0)),
		}
	var span := b_t - a_t
	var blend := 0.0 if span <= 0.0 else (t_ms - a_t) / span
	return {
		"pos": lerpf(float(a.get("pos", 0.0)), float(b.get("pos", 0.0)), blend),
		"lane": lerpf(float(a.get("lane", 1.0)), float(b.get("lane", 1.0)), blend),
		"speed": float(b.get("speed", 0.0)),
	}


## The settle: a challenger's official time against the ghost's. Lower takes
## it; a dead heat is a tie. marginMs is always the positive gap.
static func verdict(challenger_ms: int, ghost_ms: int) -> Dictionary:
	var margin := challenger_ms - ghost_ms
	return {
		"outcome": "tie" if margin == 0 else ("loss" if margin > 0 else "win"),
		"marginMs": absi(margin),
	}
