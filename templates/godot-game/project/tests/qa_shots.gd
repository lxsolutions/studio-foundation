extends RefCounted
## Visual QA shots for this game, run by studio_core's qa_capture gate:
##   just GAME=<this-game> qa-godot
##
## Every generated game starts with one honest shot: the main menu, on a
## desktop and a phone, with a not-black/not-white exposure alarm. Grow this
## the way the shipped games do — one shot per screen a player actually
## meets, driven through the same seams the wire uses (never hand-posed
## nodes), with bounds calibrated from build/qa/report.json rather than
## guessed. Tag load-bearing HUD Controls into the qa_hud group (and touch
## targets into qa_tap) and the gate holds them on screen and at a hittable
## size on every device preset.

func shots() -> Array:
	return [
		{
			"name": "main_menu", "scene": "res://scenes/main_menu.tscn",
			"run_s": 1.0,
			"devices": ["desktop", "phone"],
			"frame": {"luma_min": 8.0, "luma_max": 240.0},
			"hud": {"margin": 2.0},
		},
	]
