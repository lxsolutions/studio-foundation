class_name StudioLog
extends RefCounted
## Structured logging: leveled, tagged, ring-buffered for the dev console.
## Output format is one readable line; `data` is JSON for machine parsing.

signal message_logged(entry: Dictionary)

enum Level { DEBUG, INFO, WARN, ERROR }

const RING_MAX: int = 500
const LEVEL_NAMES: Array[String] = ["DEBUG", "INFO", "WARN", "ERROR"]

var min_level: int = Level.INFO
var ring: Array[Dictionary] = []


func debug(tag: String, msg: String, data: Dictionary = {}) -> void:
	_emit(Level.DEBUG, tag, msg, data)


func info(tag: String, msg: String, data: Dictionary = {}) -> void:
	_emit(Level.INFO, tag, msg, data)


func warn(tag: String, msg: String, data: Dictionary = {}) -> void:
	_emit(Level.WARN, tag, msg, data)


func error(tag: String, msg: String, data: Dictionary = {}) -> void:
	_emit(Level.ERROR, tag, msg, data)


func _emit(level: int, tag: String, msg: String, data: Dictionary) -> void:
	if level < min_level:
		return
	var entry: Dictionary = {
		"level": LEVEL_NAMES[level],
		"tag": tag,
		"msg": msg,
		"data": data,
		"frame": Engine.get_process_frames(),
	}
	ring.append(entry)
	if ring.size() > RING_MAX:
		ring.pop_front()
	var suffix: String = "" if data.is_empty() else " " + JSON.stringify(data)
	var line: String = "[%s] %s: %s%s" % [LEVEL_NAMES[level], tag, msg, suffix]
	if level >= Level.ERROR:
		push_error(line)
	elif level == Level.WARN:
		push_warning(line)
	else:
		print(line)
	message_logged.emit(entry)
