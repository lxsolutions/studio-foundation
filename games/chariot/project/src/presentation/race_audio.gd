class_name RaceAudio
extends Node

## The speaker rack: one AudioStreamPlayer per race-day sound, driven by cue
## dictionaries from AudioCues plus direct one-shots from the views. Streams
## load at runtime like the GLBs (import-order safety); the loop beds get
## their loop points set here so the WAVs stay plain files the generator can
## always overwrite. Regenerate with art_source/audio/generate_audio.py.

const SOUND_DIR := "res://assets/audio"
const LOOPS: Array[String] = ["gallop_loop", "wheel_loop", "crowd_loop"]
const ONESHOT_DB := {
	"gate_clang": -4.0,
	"crowd_swell": -3.0,
	"fanfare": -6.0,
	"whip_crack": -8.0,
	"surge_chime": -10.0,
	"ui_tick": -12.0,
	"ui_confirm": -12.0,
}

var _players: Dictionary = {}


func _ready() -> void:
	for sound_name in LOOPS:
		_players[sound_name] = _make_player(sound_name, true, 0.0)
	for sound_name: String in ONESHOT_DB:
		_players[sound_name] = _make_player(sound_name, false, float(ONESHOT_DB[sound_name]))


func apply(cues: Array[Dictionary]) -> void:
	for cue in cues:
		if cue.has("play"):
			oneshot(str(cue.get("play")))
		elif cue.has("loop"):
			var player: AudioStreamPlayer = _players.get(str(cue.get("loop")))
			if player == null:
				continue
			if bool(cue.get("on")):
				player.volume_db = float(cue.get("volume_db", 0.0))
				if not player.playing:
					player.play()
			else:
				player.stop()


func oneshot(sound_name: String) -> void:
	var player: AudioStreamPlayer = _players.get(sound_name)
	if player != null:
		player.play()


func playing(sound_name: String) -> bool:
	var player: AudioStreamPlayer = _players.get(sound_name)
	return player != null and player.playing


func loop_volume_db(sound_name: String) -> float:
	var player: AudioStreamPlayer = _players.get(sound_name)
	return player.volume_db if player != null else 0.0


func _make_player(sound_name: String, looped: bool, volume_db: float) -> AudioStreamPlayer:
	var player := AudioStreamPlayer.new()
	player.name = sound_name
	player.volume_db = volume_db
	var stream: AudioStream = load("%s/%s.wav" % [SOUND_DIR, sound_name])
	if looped and stream is AudioStreamWAV:
		var wav := stream as AudioStreamWAV
		wav.loop_mode = AudioStreamWAV.LOOP_FORWARD
		wav.loop_begin = 0
		wav.loop_end = wav.data.size() / 2
	player.stream = stream
	add_child(player)
	return player
