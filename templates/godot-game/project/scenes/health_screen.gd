extends Control
## Health/status screen — DEVELOPMENT BUILDS ONLY. Shows build/platform/profile
## info and exercises live connectivity: control API ping and dedicated-server
## WebSocket handshake. This screen is the human twin of the headless
## connectivity check (tests/connectivity_check.gd).

var _studio: Node
var _output: RichTextLabel
var _ws: StudioTransport = null


func _ready() -> void:
	_studio = get_node("/root/Studio")
	if not OS.is_debug_build():
		_studio.router.go_to("res://scenes/main_menu.tscn")
		return
	var box: VBoxContainer = VBoxContainer.new()
	box.set_anchors_preset(Control.PRESET_FULL_RECT)
	box.offset_left = 24
	box.offset_top = 24
	box.offset_right = -24
	box.offset_bottom = -24
	add_child(box)

	_output = RichTextLabel.new()
	_output.bbcode_enabled = true
	_output.size_flags_vertical = Control.SIZE_EXPAND_FILL
	box.add_child(_output)

	var row: HBoxContainer = HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	box.add_child(row)
	_button(row, "Ping API", _ping_api)
	_button(row, "WebSocket handshake", _ws_handshake)
	_button(row, "Back", func() -> void: _studio.router.go_to("res://scenes/main_menu.tscn"))

	_print_static_info()


func _button(parent: Container, text: String, on_pressed: Callable) -> void:
	var button: Button = Button.new()
	button.text = text
	button.pressed.connect(on_pressed)
	parent.add_child(button)


func _line(text: String) -> void:
	_output.append_text(text + "\n")


func _print_static_info() -> void:
	_line("[b]build[/b]  %s" % _studio.build_info.describe())
	_line("[b]platform[/b]  %s" % JSON.stringify(_studio.get("platform")))
	_line("[b]render profile[/b]  %s" % _studio.profiles.current_name)
	_line("[b]api[/b]  %s" % _studio.api.base_url)
	_line("[b]ws[/b]  %s" % _studio.config.get_str("net.ws_url", "ws://127.0.0.1:8081"))
	_line("")


func _ping_api() -> void:
	_line("> GET /healthz …")
	var health: Dictionary = await _studio.api.get_json("/healthz")
	_line("  healthz: ok=%s status=%d body=%s" % [health["ok"], health["status"], str(health["body"])])
	var status: Dictionary = await _studio.api.get_json("/v1/status")
	_line("  status: %s" % JSON.stringify(status.get("body")))


func _ws_handshake() -> void:
	var url: String = _studio.config.get_str("net.ws_url", "ws://127.0.0.1:8081")
	_line("> connecting %s …" % url)
	var transport: StudioWsTransport = StudioWsTransport.new()
	_ws = transport
	_studio.net = transport # Studio polls it each frame
	transport.connected.connect(func() -> void:
		_line("  connected; sending hello")
		transport.send_envelope(StudioProtocol.hello(transport.seq(), "health-screen", _studio.build_info.version)))
	transport.envelope_received.connect(func(envelope: Dictionary) -> void:
		_line("  received: %s" % JSON.stringify(envelope))
		if str(envelope.get("type", "")) == "hello_ack":
			transport.close("handshake demo done"))
	transport.disconnected.connect(func(reason: String) -> void:
		_line("  disconnected: %s" % reason)
		_studio.net = null)
	transport.transport_error.connect(func(message: String) -> void:
		_line("  [color=red]error: %s[/color]" % message))
	transport.connect_to(url)
