extends SceneTree
## Finite, headless CPU/main-loop benchmark. The Python wrapper also enables
## Godot's built-in --benchmark JSON so engine and scene metrics travel together.

const RESULT_PREFIX := "BENCHMARK_RESULT "

var _scene_path := "res://scenes/game.tscn"
var _warmup_frames := 120
var _sample_frames := 600
var _instance: Node = null
var _frame := 0
var _started_usec := 0


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	_scene_path = _opt(args, "--scene", _scene_path)
	_warmup_frames = maxi(0, int(_opt(args, "--warmup", str(_warmup_frames))))
	_sample_frames = maxi(1, int(_opt(args, "--frames", str(_sample_frames))))
	var packed := load(_scene_path) as PackedScene
	if packed == null:
		printerr("[benchmark] cannot load scene: " + _scene_path)
		quit(2)
		return
	_instance = packed.instantiate()
	root.add_child(_instance)


func _process(_delta: float) -> bool:
	_frame += 1
	if _frame == _warmup_frames + 1:
		_started_usec = Time.get_ticks_usec()
	if _frame < _warmup_frames + _sample_frames:
		return false
	var duration_usec := maxi(1, Time.get_ticks_usec() - _started_usec)
	var duration_ms := float(duration_usec) / 1000.0
	var result := {
		"mode": "headless_cpu",
		"scene": _scene_path,
		"warmup_frames": _warmup_frames,
		"sample_frames": _sample_frames,
		"duration_ms": duration_ms,
		"average_frame_ms": duration_ms / float(_sample_frames),
		"fps": float(_sample_frames) * 1000000.0 / float(duration_usec),
	}
	print(RESULT_PREFIX + JSON.stringify(result))
	quit(0)
	return true


func _opt(args: PackedStringArray, name: String, fallback: String) -> String:
	var index := args.find(name)
	return args[index + 1] if index >= 0 and index + 1 < args.size() else fallback
