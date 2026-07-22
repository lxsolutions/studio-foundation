extends Node2D
## The Deep — ported onto studio-foundation (from platosplaza/games/the-deep).
## Stacked 2D strata of per-cell material + durability. Mine (E / click) to
## break cells into loot; fight the Stratum Warden with commitment combat;
## return to town to buy upgrades and let the world-sim settle the haul.
## Numbers honor the original: durability dirt20/stone60/copper85/crystal140,
## mining power 30 (45 with Reinforced Pick), warden commit attack.

const CELL := 32
const COLS := 32
const ROWS := 32
const SERVER_URL_FALLBACK := "ws://127.0.0.1:8081"
const FACTION := "00000000-0000-0000-0000-000000000001"
const SECTOR := "00000000-0000-0000-0000-000000000002"
const DEEP_SECTOR := "00000000-0000-0000-0000-000000000003"

# Material ids + durability (hits to break) + loot yield + color.
const MAT := {
	0: {"name": "air", "dur": 0, "loot": "", "color": Color(0, 0, 0, 0)},
	1: {"name": "dirt", "dur": 20, "loot": "stone", "color": Color(0.42, 0.3, 0.18)},
	2: {"name": "stone", "dur": 60, "loot": "stone", "color": Color(0.4, 0.4, 0.45)},
	3: {"name": "copper", "dur": 85, "loot": "copper_ore", "color": Color(0.75, 0.45, 0.2)},
	4: {"name": "crystal", "dur": 140, "loot": "crystal_ore", "color": Color(0.4, 0.65, 0.95)},
}

const WARDEN_HP := 70
const WARDEN_DAMAGE := 14
const PLAYER_ATTACK_DAMAGE := 28
const PLAYER_ATTACK_REACH := 2.15 * CELL

var _grid := [] # [row][col] -> {mat, dur}
var _cell_nodes := []
var _player: Node2D
var _warden: Node2D
var _mining_power := 30
var _player_hp := 100
var _max_hp := 100
var _inv := {"stone": 0, "copper_ore": 0, "crystal_ore": 0}
var _has_pick := false
var _has_ward := false
var _in_town := false

var _transport: StudioWsTransport
var _seq := 0
var _idem := 0
var _hud: Label
var _log: RichTextLabel
var _prompt: Label
var _attack_cd := 0.0
var _warden_windup := 0.0
var _warden_cd := 0.0


func _ready() -> void:
	_build_strata()
	_build_player_and_warden()
	_build_hud()
	_connect_world()


func _process(delta: float) -> void:
	if _transport:
		_transport.poll()
	_attack_cd = maxf(0.0, _attack_cd - delta)
	_move_player(delta)
	_warden_ai(delta)
	_update_prompt()


func _next_seq() -> int:
	_seq += 1
	return _seq


func _key() -> String:
	_idem += 1
	var hex := "000000000000" + ("%x" % _idem)
	hex = hex.substr(hex.length() - 12, 12)
	return "00000000-0000-0000-0000-" + hex


func _submit(event: Dictionary) -> void:
	if _transport:
		_transport.send_envelope(StudioProtocol.world_event_submit(_next_seq(), event))


func _connect_world() -> void:
	var url: String = AshaWorldConfig.ws_url()
	_transport = StudioWsTransport.new()
	_transport.envelope_received.connect(_on_envelope)
	_transport.transport_error.connect(func(m): _log_line("[world offline] " + str(m)))
	_transport.connect_to(url)
	_log_line("connecting to world %s ..." % url)


func _on_envelope(envelope: Dictionary) -> void:
	match str(envelope.get("type", "")):
		"hello_ack":
			_log_line("world session established")
			_transport.send_envelope(StudioProtocol.hello(_next_seq(), "asha_world-the-deep", "0.1.0"))
		"world_event_result":
			_log_line(("settled: " if bool(envelope.get("applied", false)) else "rejected: ") + str(envelope.get("summary", "")))


# --- strata generation (deterministic, seeded ore) -------------------------

func _build_strata() -> void:
	_grid.clear()
	_cell_nodes.clear()
	for r in ROWS:
		var row := []
		var node_row := []
		for c in COLS:
			row.append({"mat": 0, "dur": 0})
			node_row.append(null)
		_grid.append(row)
		_cell_nodes.append(node_row)

	# Border + interior fill: dirt upper, stone lower, with seeded ore.
	for r in ROWS:
		for c in COLS:
			var mat := 0
			if r >= 6 and r < ROWS - 2:
				mat = 1 if r < 18 else 2
			if c < 2 or c >= COLS - 2:
				mat = 0
			_grid[r][c]["mat"] = mat
			_grid[r][c]["dur"] = MAT[mat]["dur"]

	# Seeded ore (deterministic placement; better deeper).
	for pos in [Vector2i(8, 10), Vector2i(20, 12), Vector2i(14, 20)]:
		_seed(pos, 3)
	for pos in [Vector2i(10, 26), Vector2i(22, 28)]:
		_seed(pos, 4)

	# Render cells.
	for r in ROWS:
		for c in COLS:
			_make_cell_node(r, c)


func _seed(pos: Vector2i, mat: int) -> void:
	_grid[pos.y][pos.x]["mat"] = mat
	_grid[pos.y][pos.x]["dur"] = MAT[mat]["dur"]


func _make_cell_node(r: int, c: int) -> void:
	var mat: int = _grid[r][c]["mat"]
	if mat == 0:
		return
	var rect := ColorRect.new()
	rect.color = MAT[mat]["color"]
	rect.position = Vector2(c * CELL, r * CELL)
	rect.size = Vector2(CELL, CELL)
	add_child(rect)
	_cell_nodes[r][c] = rect


# --- player + warden --------------------------------------------------------

func _build_player_and_warden() -> void:
	_player = Node2D.new()
	var body := ColorRect.new()
	body.color = Color(0.3, 0.55, 0.9)
	body.size = Vector2(CELL - 6, CELL - 6)
	body.position = Vector2(3, 3)
	_player.add_child(body)
	_player.position = Vector2(4 * CELL, 3 * CELL)
	add_child(_player)

	_warden = Node2D.new()
	var wbody := ColorRect.new()
	wbody.color = Color(0.8, 0.25, 0.25)
	wbody.size = Vector2(CELL, CELL)
	_warden.add_child(wbody)
	_warden.position = Vector2(20 * CELL, 16 * CELL)
	_warden.set_meta("hp", WARDEN_HP)
	add_child(_warden)

	var cam := Camera2D.new()
	cam.position = _player.position
	cam.zoom = Vector2(0.8, 0.8)
	_player.add_child(cam)


func _move_player(delta: float) -> void:
	var dir: Vector2 = StudioInputMap.move_vector()
	if dir != Vector2.ZERO:
		_player.position += dir.normalized() * 4.8 * CELL * delta
		_player.position.x = clampf(_player.position.x, CELL * 2, CELL * (COLS - 2))
		_player.position.y = clampf(_player.position.y, CELL * 2, CELL * (ROWS - 2))


func _cell_at_world(pos: Vector2) -> Vector2i:
	return Vector2i(int(pos.x / CELL), int(pos.y / CELL))


func _facing_cell() -> Vector2i:
	# Mine toward the mouse if it's near, else the cell in the last move direction,
	# else the nearest non-air cell within reach. Robust: center-to-center distance.
	var mouse_cell := _cell_at_world(get_global_mouse_position())
	if _in_bounds(mouse_cell) and _grid[mouse_cell.y][mouse_cell.x]["mat"] != 0:
		if _cell_center(mouse_cell).distance_to(_player.position) <= 1.9 * CELL:
			return mouse_cell
	return _nearest_solid_cell(1.9 * CELL)


func _in_bounds(c: Vector2i) -> bool:
	return c.x >= 0 and c.y >= 0 and c.x < COLS and c.y < ROWS


func _cell_center(c: Vector2i) -> Vector2:
	return Vector2(c.x * CELL + CELL * 0.5, c.y * CELL + CELL * 0.5)


func _nearest_solid_cell(reach: float) -> Vector2i:
	var pc := _cell_at_world(_player.position)
	var best := Vector2i(-1, -1)
	var best_d := reach
	for dy in range(-2, 3):
		for dx in range(-2, 3):
			var c := Vector2i(pc.x + dx, pc.y + dy)
			if not _in_bounds(c):
				continue
			if _grid[c.y][c.x]["mat"] == 0:
				continue
			var d: float = _cell_center(c).distance_to(_player.position)
			if d < best_d:
				best_d = d
				best = c
	return best


func _try_mine() -> void:
	var target := _facing_cell()
	if target.x < 0:
		return
	var cell: Dictionary = _grid[target.y][target.x]
	var mat: int = cell["mat"]
	if mat == 0:
		return
	cell["dur"] -= _mining_power
	if cell["dur"] <= 0:
		_break_cell(target, mat)
	else:
		# Flash the cell to show damage.
		var node: ColorRect = _cell_nodes[target.y][target.x]
		if node:
			node.modulate = Color(1.4, 1.4, 1.4)


func _break_cell(target: Vector2i, mat: int) -> void:
	_grid[target.y][target.x]["mat"] = 0
	_grid[target.y][target.x]["dur"] = 0
	var node: ColorRect = _cell_nodes[target.y][target.x]
	if node:
		node.queue_free()
		_cell_nodes[target.y][target.x] = null
	var loot: String = MAT[mat]["loot"]
	_inv[loot] += 1
	_log_line("mined %s (%s)" % [loot, MAT[mat]["name"]])
	# The world remembers: each haul is a bounded extraction event.
	_submit({
		"ResourceExtracted": {
			"faction": FACTION, "sector": SECTOR,
			"resource": "RawOre", "units": 1, "idempotency_key": _key(),
		},
	})
	_refresh_hud()


# --- combat -----------------------------------------------------------------

func _try_attack() -> void:
	if _attack_cd > 0.0:
		return
	_attack_cd = 0.42
	if _player.position.distance_to(_warden.position) <= PLAYER_ATTACK_REACH:
		var hp: int = int(_warden.get_meta("hp")) - PLAYER_ATTACK_DAMAGE
		_warden.set_meta("hp", hp)
		_log_line("hit warden (%d hp left)" % hp)
		if hp <= 0:
			_kill_warden()


func _kill_warden() -> void:
	_log_line("warden defeated — dropped 1 crystal")
	_inv["crystal_ore"] += 1
	_warden.position = Vector2(20 * CELL, 16 * CELL)
	_warden.set_meta("hp", WARDEN_HP)
	_refresh_hud()


func _warden_ai(delta: float) -> void:
	_warden_cd = maxf(0.0, _warden_cd - delta)
	var d: float = _warden.position.distance_to(_player.position)
	if _warden_windup > 0.0:
		# Commitment attack: windup, then impact. The player can read and dodge it.
		_warden_windup -= delta
		if _warden_windup <= 0.0:
			if d <= 1.7 * CELL:
				_take_damage(WARDEN_DAMAGE)
			_warden_cd = 0.72
	elif d < 5.5 * CELL and d > 1.5 * CELL:
		var dir: Vector2 = (_player.position - _warden.position).normalized()
		_warden.position += dir * 2.15 * CELL * delta
	elif d <= 1.5 * CELL and _warden_cd <= 0.0 and not _in_town:
		_warden_windup = 0.62  # dodge window before the hit lands
		_log_line("warden winds up — dodge!")


func _take_damage(amount: int) -> void:
	_player_hp -= amount
	_log_line("warden hits you (-%d hp)" % amount)
	if _player_hp <= 0:
		_die()
	_refresh_hud()


func _die() -> void:
	_inv["stone"] = maxi(0, _inv["stone"] - 2)
	_player_hp = _max_hp
	_player.position = Vector2(4 * CELL, 3 * CELL)
	_log_line("you fell — woke at the lift (-2 stone)")
	_refresh_hud()


# --- town / upgrades --------------------------------------------------------

func _buy_pick() -> void:
	if _has_pick:
		return
	if _inv["copper_ore"] < 3:
		_log_line("need 3 copper ore for Reinforced Pick")
		return
	_inv["copper_ore"] -= 3
	_has_pick = true
	_mining_power = 45
	_log_line("bought Reinforced Pick (mining power 45)")
	_submit({
		"FactoryCompleted": {
			"faction": FACTION, "sector": SECTOR,
			"item": "reinforced_pick", "refined_units": 3, "idempotency_key": _key(),
		},
	})
	_refresh_hud()


func _buy_ward() -> void:
	if _has_ward or not _has_pick:
		_log_line("need Reinforced Pick first" if not _has_pick else "already warded")
		return
	if _inv["stone"] < 4 or _inv["crystal_ore"] < 2:
		_log_line("need 4 stone + 2 crystal for Rift Ward")
		return
	_inv["stone"] -= 4
	_inv["crystal_ore"] -= 2
	_has_ward = true
	_max_hp += 25
	_player_hp = _max_hp
	_log_line("bought Rift Ward (+25 max hp)")
	_submit({
		"FactoryCompleted": {
			"faction": FACTION, "sector": SECTOR,
			"item": "rift_ward", "refined_units": 6, "idempotency_key": _key(),
		},
	})
	_refresh_hud()


# --- input + hud ------------------------------------------------------------

func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("pause"):
		get_node("/root/Studio").router.go_to("res://scenes/main_menu.tscn")
	elif event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		_try_mine()
	elif event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_RIGHT:
		_try_attack()
	elif event is InputEventKey and event.pressed:
		match event.keycode:
			KEY_E: _try_mine()
			KEY_1: _buy_pick()
			KEY_2: _buy_ward()


func _update_prompt() -> void:
	var target := _facing_cell()
	var show := false
	if _in_bounds(target):
		show = _grid[target.y][target.x]["mat"] != 0
	_prompt.visible = show


func _build_hud() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	_hud = Label.new()
	_hud.add_theme_font_size_override("font_size", 16)
	_hud.position = Vector2(12, 12)
	layer.add_child(_hud)
	_prompt = Label.new()
	_prompt.text = "LMB: mine  RMB: attack"
	_prompt.add_theme_font_size_override("font_size", 16)
	_prompt.position = Vector2(12, 40)
	_prompt.visible = false
	layer.add_child(_prompt)
	var help := Label.new()
	help.text = "WASD move | LMB mine | RMB attack | 1 pick(3cu) 2 ward(4st+2cr) | Esc menu"
	help.position = Vector2(12, 680)
	layer.add_child(help)
	_log = RichTextLabel.new()
	_log.size = Vector2(560, 160)
	_log.position = Vector2(12, 500)
	_log.scroll_following = true
	layer.add_child(_log)
	var stick := StudioTouchStick.new()
	stick.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	stick.position = Vector2(24, -216)
	layer.add_child(stick)
	_refresh_hud()


func _refresh_hud() -> void:
	_hud.text = "HP %d/%d   stone %d  copper %d  crystal %d   pick:%s ward:%s" % [
		_player_hp, _max_hp, _inv["stone"], _inv["copper_ore"], _inv["crystal_ore"],
		"y" if _has_pick else "n", "y" if _has_ward else "n",
	]


func _log_line(text: String) -> void:
	_log.append_text(text + "\n")
