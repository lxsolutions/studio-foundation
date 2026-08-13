extends StudioTestCase
## The sign-in gate itself: built exactly the way _ready builds it (the HUD
## canvas, then the panel), tapped through the buttons' own pressed signals.
## The RACING_SPECTATE_OFFLINE stub captures the gate's REST calls in
## handoff_captured instead of touching the network, so the whole one-tap
## trip is driven without a socket: "Take the reins" spends a plaza session
## at /api/sso when one waits (RACING_SSO_TOKEN is the headless stand-in for
## localStorage arb_token), mints a plaza guest identity at /api/session when
## none does, and degrades to the local card mint when the Plaza or the
## racing API cannot be reached. Server answers are replayed by hand through
## _on_gate_request_completed with _gate_flow set, the same seam the
## HTTPRequest signal drives in production.


func _make_gate() -> RiderView:
	var view := (load("res://scenes/rider.tscn") as PackedScene).instantiate() as RiderView
	# No tree, no _ready: the full view's ready needs a live window, which a
	# headless suite inside _initialize does not have. The gate does not.
	view._build_hud()
	view._build_code_panel()
	view.audio = RaceAudio.new()
	view.client = RecordingRiderClient.new()
	view.stable_client = StableClient.new()
	view._studio = StudioClient.new()
	return view


func _replay(view: RiderView, flow: String, result: int, status: int, body_text: String) -> void:
	view._gate_flow = flow
	view._on_gate_request_completed(result, status, PackedStringArray(), body_text.to_utf8_buffer())


func test_one_tap_mints_stores_shows_and_registers_the_card() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	var view := _make_gate()
	assert_true(view != null, "the rider scene is a RiderView")

	assert_eq(view._minted_card, "", "no card before the tap")
	view._mint_button.pressed.emit()

	var card := view._minted_card
	assert_true(SsoExchange.is_code_shape(card), "the minted card has the server's shape")
	assert_eq(card.length(), SsoExchange.CODE_LENGTH, "six glyphs, like the server's minter")
	assert_eq(AuthStore.saved_code(), card, "the card is stored silently for the next boot")
	assert_true(view._gate_status.text.contains(card),
		"the gate says the one thing a new stable must hear: " + view._gate_status.text)
	assert_true(view._mint_button.disabled, "the mint button rides out the trip disabled")
	assert_true(view._reins_button.disabled, "the reins button rides out the trip disabled")

	assert_eq(view.handoff_captured.size(), 1, "exactly one request leaves the gate")
	if view.handoff_captured.size() == 1:
		var request: Dictionary = view.handoff_captured[0]
		assert_eq(str(request.get("path")), "/api/login",
			"the register call is the login call")
		assert_eq(str(request.get("body")), JSON.stringify({ "code": card }),
			"carrying the minted card verbatim")

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)


func test_take_the_reins_with_a_plaza_token_goes_straight_to_sso() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	var old_token := OS.get_environment("RACING_SSO_TOKEN")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	OS.set_environment("RACING_SSO_TOKEN", "tok-env")
	var view := _make_gate()

	view._reins_button.pressed.emit()

	assert_eq(view._gate_status.text, "Signing you in from the Plaza…", "the busy line names the trip")
	assert_eq(view._studio.token, "tok-env", "the bridge rides the same plaza session")
	assert_eq(view.handoff_captured.size(), 1, "one request, no guest mint")
	if view.handoff_captured.size() == 1:
		var request: Dictionary = view.handoff_captured[0]
		assert_eq(str(request.get("path")), "/api/sso", "the session spends at the exchange")
		assert_eq(str(request.get("body")), JSON.stringify({ "t": "tok-env" }),
			"carrying the plaza token verbatim")
		assert_eq(str(request.get("base", "")), "", "the exchange rides the racing server's own mount")

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)
	OS.set_environment("RACING_SSO_TOKEN", old_token)


func test_take_the_reins_without_a_token_mints_a_plaza_guest_first() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	var old_token := OS.get_environment("RACING_SSO_TOKEN")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	OS.set_environment("RACING_SSO_TOKEN", "")
	var view := _make_gate()

	view._reins_button.pressed.emit()

	assert_eq(view._gate_status.text, "Meeting the Plaza…", "the busy line names the guest mint")
	assert_eq(view.handoff_captured.size(), 1, "one request: the guest mint")
	if view.handoff_captured.size() == 1:
		var request: Dictionary = view.handoff_captured[0]
		assert_eq(int(request.get("method")), HTTPClient.METHOD_POST)
		assert_eq(str(request.get("base")), "https://ashaarena.com",
			"the guest mint lives on the plaza, not the racing server")
		assert_eq(str(request.get("path")), "/api/session")
		var handle := str((JSON.parse_string(str(request.get("body"))) as Dictionary).get("handle", ""))
		assert_true(handle.begins_with("Rider-"), "the studio page's own handle shape: " + handle)

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)
	OS.set_environment("RACING_SSO_TOKEN", old_token)


func test_a_minted_guest_session_is_spent_at_sso() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	var old_token := OS.get_environment("RACING_SSO_TOKEN")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	OS.set_environment("RACING_SSO_TOKEN", "")
	var view := _make_gate()
	view._reins_button.pressed.emit()

	_replay(view, "guest", HTTPRequest.RESULT_SUCCESS, 200,
		JSON.stringify({ "token": "tok-guest", "handle": "Rider-0042" }))

	assert_eq(view._studio.token, "tok-guest", "the bridge takes the fresh session")
	assert_eq(view._gate_status.text, "Signing you in from the Plaza…", "straight into the exchange")
	assert_eq(view.handoff_captured.size(), 2, "the exchange follows the mint")
	if view.handoff_captured.size() == 2:
		var request: Dictionary = view.handoff_captured[1]
		assert_eq(str(request.get("path")), "/api/sso")
		assert_eq(str(request.get("body")), JSON.stringify({ "t": "tok-guest" }),
			"the minted token spends once, at the exchange")

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)
	OS.set_environment("RACING_SSO_TOKEN", old_token)


func test_an_unreachable_guest_mint_falls_back_to_a_local_stable() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	var old_token := OS.get_environment("RACING_SSO_TOKEN")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	OS.set_environment("RACING_SSO_TOKEN", "")
	var view := _make_gate()
	view._reins_button.pressed.emit()

	_replay(view, "guest", HTTPRequest.RESULT_CANT_CONNECT, 0, "")

	var card := view._minted_card
	assert_true(SsoExchange.is_code_shape(card), "a local card stands in for the plaza trip")
	assert_eq(AuthStore.saved_code(), card, "and it is stored like any minted card")
	assert_true(view._gate_status.text.contains("The Plaza is out of reach"),
		"the note says what happened: " + view._gate_status.text)
	assert_true(view._gate_status.text.contains(card), "the note carries the card too")
	assert_eq(view.handoff_captured.size(), 2, "the register call follows the fallback")
	if view.handoff_captured.size() == 2:
		assert_eq(str((view.handoff_captured[1] as Dictionary).get("path")), "/api/login")
		assert_eq(str((view.handoff_captured[1] as Dictionary).get("body")), JSON.stringify({ "code": card }))

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)
	OS.set_environment("RACING_SSO_TOKEN", old_token)


func test_an_sso_refusal_shows_the_servers_message_and_keeps_the_gate_up() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	var old_token := OS.get_environment("RACING_SSO_TOKEN")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	OS.set_environment("RACING_SSO_TOKEN", "tok-env")
	var view := _make_gate()
	var client := view.client as RecordingRiderClient
	view._reins_button.pressed.emit()

	_replay(view, "sso", HTTPRequest.RESULT_SUCCESS, 401, JSON.stringify({ "error": "Unknown arena token." }))

	assert_eq(view._code_error.text, "Unknown arena token.", "the server's own words, verbatim")
	assert_false(view._reins_button.disabled, "the gate is back up: Take the reins retries")
	assert_false(view._mint_button.disabled, "and the local door stands")
	assert_eq(client.started_code, "", "no entry on a refusal")
	assert_eq(view.handoff_captured.size(), 1, "and no silent local mint behind the rider's back")

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)
	OS.set_environment("RACING_SSO_TOKEN", old_token)


func test_an_unreachable_sso_falls_back_to_a_local_stable() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	var old_token := OS.get_environment("RACING_SSO_TOKEN")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	OS.set_environment("RACING_SSO_TOKEN", "tok-env")
	var view := _make_gate()
	view._reins_button.pressed.emit()

	_replay(view, "sso", HTTPRequest.RESULT_CANT_CONNECT, 0, "")

	var card := view._minted_card
	assert_true(SsoExchange.is_code_shape(card), "the racing API unreachable: a local card stands in")
	assert_eq(AuthStore.saved_code(), card, "stored like any minted card")
	assert_true(view._gate_status.text.contains("The Plaza is out of reach"),
		"the note says what happened: " + view._gate_status.text)
	assert_eq(view.handoff_captured.size(), 2, "the register call follows the fallback")
	if view.handoff_captured.size() == 2:
		assert_eq(str((view.handoff_captured[1] as Dictionary).get("path")), "/api/login")

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)
	OS.set_environment("RACING_SSO_TOKEN", old_token)


func test_an_sso_success_enters_with_the_arena_stable() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	var old_token := OS.get_environment("RACING_SSO_TOKEN")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	OS.set_environment("RACING_SSO_TOKEN", "tok-env")
	var view := _make_gate()
	var client := view.client as RecordingRiderClient
	view._reins_button.pressed.emit()

	_replay(view, "sso", HTTPRequest.RESULT_SUCCESS, 200,
		JSON.stringify({ "ok": true, "code": "ABC234", "created": true }))

	assert_eq(AuthStore.saved_code(), "ABC234", "the arena-linked stable persists for the next boot")
	assert_eq(client.started_code, "ABC234", "the exchanged code is the one that goes out")
	assert_eq(view._gate_status.text, "Taking the reins…")

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)
	OS.set_environment("RACING_SSO_TOKEN", old_token)


func test_a_plaza_faction_assigns_the_silk_and_the_code_deals_one_otherwise() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	var old_token := OS.get_environment("RACING_SSO_TOKEN")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	OS.set_environment("RACING_SSO_TOKEN", "tok-env")
	var view := _make_gate()
	view._reins_button.pressed.emit()

	_replay(view, "sso", HTTPRequest.RESULT_SUCCESS, 200,
		JSON.stringify({ "ok": true, "code": "ABC234", "created": true }))
	var ids := CircusFactions.ids()
	var hashed := ids[abs("ABC234".hash()) % ids.size()]
	assert_eq(view._faction_id, hashed, "the stable code deals a silk at once")
	_replay(view, "me", HTTPRequest.RESULT_SUCCESS, 200,
		JSON.stringify({ "faction": { "id": 3, "name": "The Open Inquirers" } }))
	assert_eq(view._faction_id, ids[3 % ids.size()], "the plaza faction's color wins")
	assert_eq(AuthStore.saved_faction(), ids[3 % ids.size()], "and it persists for the next boot")

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)
	OS.set_environment("RACING_SSO_TOKEN", old_token)


func test_the_card_line_survives_a_gate_restore() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	var view := _make_gate()
	var client := view.client as RecordingRiderClient

	view._mint_new_stable()
	var card := view._minted_card
	# A server answer — any answer — repaints the gate; the card line is the
	# one thing the repaint must not eat (the busy/restore cycle is where a
	# status line usually goes to die).
	view._restore_gate("The club turned us away. Check the code and try again.")
	assert_true(view._gate_status.text.contains(card),
		"the card line survives an error repaint")
	assert_eq(view._code_error.text, "The club turned us away. Check the code and try again.",
		"and the server's verdict still shows beneath it")

	# The register call answering — whatever it answers — enters with the card:
	# the socket is the truth channel.
	_replay(view, "mint", HTTPRequest.RESULT_SUCCESS, 401, JSON.stringify({ "error": "Invalid stable code." }))
	assert_eq(client.started_code, card, "whatever the office answered, the card rides in")
	assert_eq(view._gate_status.text, "Taking the reins…")

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)


func test_a_remembered_code_boots_straight_into_the_login() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	var old_token := OS.get_environment("RACING_SSO_TOKEN")
	var old_code := OS.get_environment("RACING_CODE")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	OS.set_environment("RACING_SSO_TOKEN", "")
	OS.set_environment("RACING_CODE", "")
	var view := _make_gate()
	AuthStore.save("KMNPQR")

	view._boot_sign_in()

	assert_eq(view._gate_status.text, "Returning to your stable…", "no gate, no typing: straight in")
	assert_eq(view.handoff_captured.size(), 1, "the remembered code validates over REST")
	if view.handoff_captured.size() == 1:
		assert_eq(str((view.handoff_captured[0] as Dictionary).get("path")), "/api/login")
		assert_eq(str((view.handoff_captured[0] as Dictionary).get("body")), JSON.stringify({ "code": "KMNPQR" }))

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)
	OS.set_environment("RACING_SSO_TOKEN", old_token)
	OS.set_environment("RACING_CODE", old_code)


## A rider client that records the submitted code instead of opening a
## socket: the gate's entry path drives it, the suite stays off the wire.
class RecordingRiderClient:
	extends RiderClient
	var started_code := ""

	func start_with_code(owner_code: String) -> void:
		started_code = owner_code.strip_edges().to_upper()
