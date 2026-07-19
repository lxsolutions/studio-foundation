class_name StudioRng
extends RefCounted
## Deterministic random support. One run seed, many named streams — systems
## must take their own stream ("combat", "loot", "vfx") so draws in one system
## never perturb another. Replays store the run seed (see StudioReplay).

var run_seed: int = 0
var _streams: Dictionary = {}


## seed 0 = randomize (normal play). Fixed seeds come from config
## ("debug.fixed_seed") or replay files.
func set_run_seed(seed_value: int) -> void:
	if seed_value == 0:
		randomize()
		seed_value = randi() | 1
	run_seed = seed_value
	_streams.clear()


## Stable derivation: same run seed + same name => same stream, in any order.
func derive_seed(stream_name: String) -> int:
	return hash(str(run_seed) + ":" + stream_name)


func stream(stream_name: String) -> RandomNumberGenerator:
	if _streams.has(stream_name):
		return _streams[stream_name]
	var generator: RandomNumberGenerator = RandomNumberGenerator.new()
	generator.seed = derive_seed(stream_name)
	_streams[stream_name] = generator
	return generator


func state() -> Dictionary:
	var snapshot: Dictionary = {"run_seed": run_seed, "streams": {}}
	var streams_out: Dictionary = snapshot["streams"]
	for stream_name in _streams.keys():
		var generator: RandomNumberGenerator = _streams[stream_name]
		streams_out[stream_name] = generator.state
	return snapshot


func restore(snapshot: Dictionary) -> void:
	set_run_seed(int(snapshot.get("run_seed", 0)))
	var streams_in: Variant = snapshot.get("streams", {})
	if streams_in is Dictionary:
		for stream_name in (streams_in as Dictionary).keys():
			var generator: RandomNumberGenerator = stream(str(stream_name))
			generator.state = int((streams_in as Dictionary)[stream_name])
