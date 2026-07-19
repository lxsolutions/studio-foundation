extends StudioTestCase
## Scene smoke: every committed scene must load and instantiate without errors.
## (Instantiation without add_child does not run _ready — that's exercised by
## the browser smoke + connectivity checks with the full autoload stack.)

const SCENES_DIR: String = "res://scenes"


func test_all_scenes_instantiate() -> void:
	var dir: DirAccess = DirAccess.open(SCENES_DIR)
	assert_true(dir != null, "scenes dir exists")
	if dir == null:
		return
	var count: int = 0
	for file_name in dir.get_files():
		# Export builds list .tscn as .tscn.remap; handle both when run from a pack.
		var scene_name: String = file_name.trim_suffix(".remap")
		if not scene_name.ends_with(".tscn"):
			continue
		var path: String = SCENES_DIR + "/" + scene_name
		var packed: Variant = load(path)
		assert_true(packed is PackedScene, "load failed: " + path)
		if packed is PackedScene:
			var instance: Node = (packed as PackedScene).instantiate()
			assert_true(instance != null, "instantiate failed: " + path)
			if instance != null:
				instance.free()
		count += 1
	assert_true(count >= 6, "expected >=6 scenes, saw %d" % count)


func test_project_config_sane() -> void:
	assert_eq(
		str(ProjectSettings.get_setting("application/run/main_scene")),
		"res://scenes/boot.tscn"
	)
	assert_true(
		str(ProjectSettings.get_setting("rendering/renderer/rendering_method.web"))
		== "gl_compatibility",
		"web fallback must be gl_compatibility (ADR 0002)"
	)
