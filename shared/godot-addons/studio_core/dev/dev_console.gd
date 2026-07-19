class_name StudioDevConsole
extends CanvasLayer
## Developer console (F12). ONLY exists in debug builds — the Studio autoload
## refuses to instantiate it otherwise, and OS.is_debug_build() is re-checked
## here as defense in depth. Games register commands via register_command().

var _commands: Dictionary = {}
var _panel: PanelContainer
var _output: RichTextLabel
var _input: LineEdit


func _ready() -> void:
	if not OS.is_debug_build():
		queue_free()
		return
	layer = 90
	visible = false
	_build_ui()
	register_command("help", _cmd_help, "list commands")
	register_command("log", _cmd_log, "show recent log entries")
	register_command("flags", _cmd_flags, "flags [name on|off] — inspect/override feature flags")
	register_command("profile", _cmd_profile, "profile [name] — show or switch render profile")
	register_command("quit", func(_args: PackedStringArray) -> String:
		get_tree().quit()
		return "bye", "quit the game")


func register_command(command_name: String, handler: Callable, help_text: String = "") -> void:
	_commands[command_name] = {"handler": handler, "help": help_text}


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("dev_console"):
		visible = not visible
		if visible:
			_input.grab_focus()
		get_viewport().set_input_as_handled()


func _build_ui() -> void:
	_panel = PanelContainer.new()
	_panel.set_anchors_preset(Control.PRESET_TOP_WIDE)
	_panel.custom_minimum_size = Vector2(0, 260)
	var vbox: VBoxContainer = VBoxContainer.new()
	_panel.add_child(vbox)
	_output = RichTextLabel.new()
	_output.scroll_following = true
	_output.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_output.append_text("[b]studio console[/b] — type 'help'\n")
	vbox.add_child(_output)
	_input = LineEdit.new()
	_input.placeholder_text = "command…"
	_input.text_submitted.connect(_on_submit)
	vbox.add_child(_input)
	add_child(_panel)


func _on_submit(text: String) -> void:
	_input.clear()
	var trimmed: String = text.strip_edges()
	if trimmed.is_empty():
		return
	_output.append_text("> %s\n" % trimmed)
	var parts: PackedStringArray = trimmed.split(" ", false)
	var command_name: String = parts[0]
	var args: PackedStringArray = parts.slice(1)
	if not _commands.has(command_name):
		_output.append_text("unknown command '%s'\n" % command_name)
		return
	var entry: Dictionary = _commands[command_name]
	var handler: Callable = entry["handler"]
	var result: Variant = handler.call(args)
	if result is String and not String(result).is_empty():
		_output.append_text(String(result) + "\n")


func _studio() -> Node:
	return get_node_or_null("/root/Studio")


func _cmd_help(_args: PackedStringArray) -> String:
	var lines: PackedStringArray = []
	for command_name in _commands.keys():
		var entry: Dictionary = _commands[command_name]
		lines.append("  %s — %s" % [command_name, entry["help"]])
	return "\n".join(lines)


func _cmd_log(_args: PackedStringArray) -> String:
	var studio: Node = _studio()
	if studio == null:
		return "Studio autoload not found"
	var entries: Array[Dictionary] = studio.log.ring
	var lines: PackedStringArray = []
	for entry in entries.slice(maxi(entries.size() - 15, 0)):
		lines.append("[%s] %s: %s" % [entry["level"], entry["tag"], entry["msg"]])
	return "\n".join(lines)


func _cmd_flags(args: PackedStringArray) -> String:
	var studio: Node = _studio()
	if studio == null:
		return "Studio autoload not found"
	if args.size() == 2:
		studio.flags.set_override(args[0], args[1] == "on")
		return "%s override -> %s" % [args[0], args[1]]
	return "usage: flags <name> on|off"


func _cmd_profile(args: PackedStringArray) -> String:
	var studio: Node = _studio()
	if studio == null:
		return "Studio autoload not found"
	if args.is_empty():
		return "current: %s" % studio.profiles.current_name
	var ok: bool = studio.profiles.apply(args[0], get_viewport(), studio.platform)
	return "switched to %s" % args[0] if ok else "unknown profile %s" % args[0]
