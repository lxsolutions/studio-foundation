@tool
extends EditorPlugin
## Editor-side hook. The runtime entry point is the `Studio` autoload
## (studio.gd), declared by each game project — not injected here, so projects
## stay explicit about what runs at boot.


func _enter_tree() -> void:
	pass


func _exit_tree() -> void:
	pass
