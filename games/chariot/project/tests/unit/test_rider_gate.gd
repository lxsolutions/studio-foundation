extends StudioTestCase
## The sign-in gate itself: built exactly the way _ready builds it (the HUD
## canvas, then the panel), tapped through the button's own pressed signal.
## The RACING_SPECTATE_OFFLINE stub captures the gate's REST call in
## handoff_captured instead of touching the network, so the whole mint trip
## is driven without a socket. What must be true after ONE tap on "Raise a
## new stable": a card in the server's code shape exists, it is stored
## (AuthStore), it rides on the gate where the rider can write it down, and
## the register call — the login call carrying the card — is the one request
## the flow makes.


func test_one_tap_mints_stores_shows_and_registers_the_card() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	var packed: PackedScene = load("res://scenes/rider.tscn")
	assert_true(packed != null, "the rider scene loads")
	if packed == null:
		OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)
		return
	# No tree, no _ready: the full view's ready needs a live window, which a
	# headless suite inside _initialize does not have. The gate does not.
	var view := packed.instantiate() as RiderView
	assert_true(view != null, "the rider scene is a RiderView")
	view._build_hud()
	view._build_code_panel()
	view.audio = RaceAudio.new()

	assert_eq(view._minted_card, "", "no card before the tap")
	view._mint_button.pressed.emit()

	var card := view._minted_card
	assert_true(SsoExchange.is_code_shape(card), "the minted card has the server's shape")
	assert_eq(card.length(), SsoExchange.CODE_LENGTH, "six glyphs, like the server's minter")
	assert_eq(AuthStore.saved_code(), card, "the card is stored silently for the next boot")
	assert_eq(view._code_edit.text, card, "the card sits in the code field")
	assert_true(view._gate_status.text.contains(card),
		"the gate says the one thing a new stable must hear: " + view._gate_status.text)
	assert_true(view._mint_button.disabled, "the mint button rides out the trip disabled")

	assert_eq(view.handoff_captured.size(), 1, "exactly one request leaves the gate")
	if view.handoff_captured.size() == 1:
		var request: Dictionary = view.handoff_captured[0]
		assert_eq(str(request.get("path")), "/api/login",
			"the register call is the login call")
		assert_eq(str(request.get("body")), JSON.stringify({ "code": card }),
			"carrying the minted card verbatim")

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)


func test_the_card_line_survives_a_gate_restore() -> void:
	var old_offline := OS.get_environment("RACING_SPECTATE_OFFLINE")
	OS.set_environment("RACING_SPECTATE_OFFLINE", "1")
	var view := (load("res://scenes/rider.tscn") as PackedScene).instantiate() as RiderView
	view._build_hud()
	view._build_code_panel()
	view.audio = RaceAudio.new()
	# _submit_code's network halves, recorded instead of wired.
	var client := RecordingRiderClient.new()
	view.client = client
	view.stable_client = StableClient.new()

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

	# Typing over the card retires it: the gate speaks for the code that is
	# actually going out.
	view._code_edit.text = "ZZZZ99"
	view._submit_code()
	assert_eq(view._minted_card, "", "a hand-typed code retires the card line")
	assert_eq(view._gate_status.text, "Taking the reins…")
	assert_eq(client.started_code, "ZZZZ99", "the typed code is the one that goes out")

	view.free()
	OS.set_environment("RACING_SPECTATE_OFFLINE", old_offline)


## A rider client that records the submitted code instead of opening a
## socket: the gate's submit path drives it, the suite stays off the wire.
class RecordingRiderClient:
	extends RiderClient
	var started_code := ""

	func start_with_code(owner_code: String) -> void:
		started_code = owner_code.strip_edges().to_upper()
