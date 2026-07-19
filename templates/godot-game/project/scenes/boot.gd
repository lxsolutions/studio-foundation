extends Node
## Application boot: waits for the Studio autoload boot sequence, then routes
## to the main menu. Keep this scene logic-free — boot behavior belongs to
## studio_core so every game boots identically.


func _ready() -> void:
	var studio: Node = get_node("/root/Studio")
	if not bool(studio.get("booted")):
		await studio.boot_completed
	var headless: bool = bool((studio.get("platform") as Dictionary).get("headless", false))
	studio.router.go_to("res://scenes/main_menu.tscn", 0.0 if headless else 0.15)
