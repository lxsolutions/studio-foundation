class_name StudioAudioSettings
extends RefCounted
## Audio buses and settings. Ensures the studio bus layout exists (Master ->
## Music/SFX/UI) and persists user volumes via StudioConfig.

const BUSES: Array[String] = ["Music", "SFX", "UI"]

var config: StudioConfig


func _init(cfg: StudioConfig) -> void:
	config = cfg


func ensure_buses() -> void:
	for bus_name in BUSES:
		if AudioServer.get_bus_index(bus_name) == -1:
			var index: int = AudioServer.bus_count
			AudioServer.add_bus(index)
			AudioServer.set_bus_name(index, bus_name)
			AudioServer.set_bus_send(index, "Master")


func apply() -> void:
	ensure_buses()
	set_volume("Master", get_volume("Master"))
	for bus_name in BUSES:
		set_volume(bus_name, get_volume(bus_name))


func get_volume(bus_name: String) -> float:
	return config.get_float("audio.volume." + bus_name.to_lower(), 1.0)


## linear 0..1 -> dB, persisted.
func set_volume(bus_name: String, linear: float) -> void:
	var index: int = AudioServer.get_bus_index(bus_name)
	if index == -1:
		return
	linear = clampf(linear, 0.0, 1.0)
	AudioServer.set_bus_volume_db(index, linear_to_db(maxf(linear, 0.0001)))
	AudioServer.set_bus_mute(index, linear <= 0.001)
	config.set_user("audio.volume." + bus_name.to_lower(), linear)


func save() -> void:
	config.save_user()
