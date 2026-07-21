extends Control
## Asha World vertical slice (ADR 0007, docs/architecture/vertical-slice.md).
## One authoritative world, experienced through a simple command loop:
##   MINE (extract ore) -> REFINE (ore -> alloy) -> BUILD (vehicle) -> BATTLE
##   -> TERRITORY (sector flips, deeper mine unlocks).
## Every action emits a canonical WorldEvent over the wire; the server's
## world-sim settles it into shared state. This client is a thin view — the
## server is authoritative.

const SERVER_URL := "ws://127.0.0.1:8081"
const FACTION := "00000000-0000-0000-0000-000000000001"
const SECTOR := "00000000-0000-0000-0000-000000000002"
const DEEP_SECTOR := "00000000-0000-0000-0000-000000000003"

var _transport: StudioWsTransport
var _seq := 0
var _idem := 100 # idempotency-key counter (per run)
var _log: RichTextLabel
var _status: Label
var _buttons := {}
var _state := {
	"raw_ore": 0,
	"refined_alloy": 0,
	"vehicle": false,
	"territory": false,
}


func _ready() -> void:
	_build_ui()
	_transport = StudioWsTransport.new()
	_transport.connected.connect(_on_connected)
	_transport.envelope_received.connect(_on_envelope)
	_transport.transport_error.connect(func(msg): _append("[err] " + str(msg)))
	_append("connecting to world server %s ..." % SERVER_URL)
	_transport.connect_to(SERVER_URL)


func _process(_delta: float) -> void:
	# Transports are RefCounted and poll-driven (the Studio autoload polls its
	# own; a bare scene must poll manually each frame).
	_transport.poll()


func _next_seq() -> int:
	_seq += 1
	return _seq


func _on_connected() -> void:
	_append("connected; saying hello")
	_transport.send_envelope(StudioProtocol.hello(_next_seq(), "asha_world-slice", "0.1.0"))


func _on_envelope(envelope: Dictionary) -> void:
	var t: String = str(envelope.get("type", ""))
	match t:
		"hello_ack":
			_append("world session established")
			_set_status("connected — begin by mining")
			_buttons["mine"].disabled = false
		"world_event_result":
			var applied: bool = bool(envelope.get("applied", false))
			_append(("-> settled: " if applied else "-> rejected: ") + str(envelope.get("summary", "")))
		"error":
			_append("[server error] " + str(envelope.get("message", "")))


func _submit(event: Dictionary) -> void:
	_transport.send_envelope(StudioProtocol.world_event_submit(_next_seq(), event))


func _key() -> String:
	_idem += 1
	# Idempotency key as a UUID-shaped string; uniqueness per run is enough here.
	# GDScript's % operator has no hex-padding, so build the 12-hex-digit tail manually.
	var hex := "000000000000" + ("%x" % _idem)
	hex = hex.substr(hex.length() - 12, 12)
	return "00000000-0000-0000-0000-" + hex


# --- the loop -------------------------------------------------------------

func _on_mine() -> void:
	_append("descending into The Deep; mining 100 ore ...")
	_submit({
		"ResourceExtracted": {
			"faction": FACTION, "sector": SECTOR,
			"resource": "RawOre", "units": 100, "idempotency_key": _key(),
		},
	})
	_state["raw_ore"] += 100
	_buttons["refine"].disabled = _state["raw_ore"] < 100
	_refresh()


func _on_refine() -> void:
	# 10:1 ore -> alloy (world-sim economy REFINE_RATIO).
	var refined: int = _state["raw_ore"] / 10
	_state["refined_alloy"] += refined
	_state["raw_ore"] = 0
	_append("refinery converted ore into %d alloy" % refined)
	_submit({
		"ResourceExtracted": {
			"faction": FACTION, "sector": SECTOR,
			"resource": "RefinedAlloy", "units": refined, "idempotency_key": _key(),
		},
	})
	_buttons["refine"].disabled = true
	_buttons["build"].disabled = _state["refined_alloy"] < 10
	_refresh()


func _on_build() -> void:
	_append("factory building one armored vehicle (10 alloy) ...")
	_submit({
		"FactoryCompleted": {
			"faction": FACTION, "sector": SECTOR,
			"item": "armored_vehicle", "refined_units": 10, "idempotency_key": _key(),
		},
	})
	_state["vehicle"] = true
	_state["refined_alloy"] -= 10
	_buttons["build"].disabled = true
	_buttons["battle"].disabled = false
	_refresh()


func _on_battle() -> void:
	_append("battle joined over the nearby outpost ...")
	_buttons["battle"].disabled = true
	_buttons["territory"].disabled = false


func _on_territory() -> void:
	_append("outpost captured — sector flips; deeper mine unlocked")
	_submit({
		"TerritoryChanged": {
			"sector": DEEP_SECTOR, "new_controller": FACTION, "idempotency_key": _key(),
		},
	})
	_state["territory"] = true
	_buttons["territory"].disabled = true
	_set_status("LOOP CLOSED — extraction -> economy -> production -> battle -> territory")
	_refresh()


# --- ui -------------------------------------------------------------------

func _build_ui() -> void:
	set_anchors_preset(Control.PRESET_FULL_RECT)
	var root := VBoxContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 10)
	add_child(root)

	var title := Label.new()
	title.text = "Asha World — vertical slice"
	title.add_theme_font_size_override("font_size", 26)
	root.add_child(title)

	_status = Label.new()
	_set_status("offline")
	_status.add_theme_font_size_override("font_size", 14)
	root.add_child(_status)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	root.add_child(row)
	for step in ["mine", "refine", "build", "battle", "territory"]:
		var b := Button.new()
		b.text = step.capitalize()
		b.disabled = true
		row.add_child(b)
		_buttons[step] = b
	_buttons["mine"].pressed.connect(_on_mine)
	_buttons["refine"].pressed.connect(_on_refine)
	_buttons["build"].pressed.connect(_on_build)
	_buttons["battle"].pressed.connect(_on_battle)
	_buttons["territory"].pressed.connect(_on_territory)

	_log = RichTextLabel.new()
	_log.bbcode_enabled = false
	_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_log.scroll_following = true
	root.add_child(_log)


func _set_status(text: String) -> void:
	_status.text = "status: " + text


func _append(text: String) -> void:
	_log.append_text(text + "\n")


func _refresh() -> void:
	_set_status(
		"ore=%d  alloy=%d  vehicle=%s  territory=%s" % [
			_state["raw_ore"], _state["refined_alloy"],
			str(_state["vehicle"]), str(_state["territory"]),
		]
	)
