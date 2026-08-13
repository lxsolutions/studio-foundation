extends StudioTestCase
## The one-tap "Raise a new stable" path: a stranger mints a stable card in
## the racing server's own code format (server/models.js randomCode: 32
## unambiguous glyphs, six long), registers it through the login call, and
## keeps it in AuthStore for the next boot. The flow decision itself lives in
## rider_view (_on_gate_request_completed, flow "mint": always enter with the
## card, never forget it) — the transport is stubbed there by
## RACING_SPECTATE_OFFLINE's handoff_captured seam; what is pinned here is
## everything the wire sees. The plaza half of the gate is pinned here too:
## the guest mint's request and answer shape (POST /api/session, the arena
## studio page's own call) and the /api/sso exchange the session spends at.


func test_minted_codes_have_the_servers_shape() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	for n in 50:
		var code := SsoExchange.mint_code(rng)
		assert_eq(code.length(), SsoExchange.CODE_LENGTH, "six glyphs, like randomCode")
		assert_true(SsoExchange.is_code_shape(code), "minted code passes its own shape check: " + code)


func test_mint_is_deterministic_under_a_seed_and_varies_across_draws() -> void:
	var first := RandomNumberGenerator.new()
	first.seed = 4242
	var second := RandomNumberGenerator.new()
	second.seed = 4242
	assert_eq(SsoExchange.mint_code(first), SsoExchange.mint_code(second),
		"same seed, same card — the suite can pin the mint")
	var seen := {}
	var dupes := 0
	for n in 200:
		var code := SsoExchange.mint_code(first)
		if seen.has(code):
			dupes += 1
		seen[code] = true
	assert_eq(dupes, 0, "200 draws from a 32^6 space never repeat")


func test_code_shape_table() -> void:
	assert_true(SsoExchange.is_code_shape("AS4G57"), "a freshly minted card")
	assert_true(SsoExchange.is_code_shape("as4g57"), "lowercase is the same code, auth upcases")
	assert_true(SsoExchange.is_code_shape("ABCDEFGHJKLM"), "twelve glyphs is the server's clamp")
	assert_false(SsoExchange.is_code_shape(""), "empty is not a code")
	assert_false(SsoExchange.is_code_shape("ABCDEFGHJKLMN"), "thirteen is over the clamp")
	assert_false(SsoExchange.is_code_shape("AS4G5!"), "punctuation is not in the alphabet")
	assert_false(SsoExchange.is_code_shape("AS4G 7"), "neither is whitespace inside")
	assert_false(SsoExchange.is_code_shape("I0O1"), "the ambiguous glyphs are not minted or accepted")


func test_register_is_the_login_call_carrying_the_card_verbatim() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 99
	var code := SsoExchange.mint_code(rng)
	var request := SsoExchange.register_request(code)
	assert_eq(int(request.get("method")), HTTPClient.METHOD_POST)
	assert_eq(str(request.get("path")), "/api/login",
		"registration rides the login call — a create-on-login deploy makes the card real with it")
	assert_eq(str(request.get("body")), JSON.stringify({ "code": code }),
		"the minted card crosses the wire exactly as minted")


func test_a_created_stables_answer_folds_ok() -> void:
	# What a create-on-login deploy answers the register call: the same shape
	# as any good login. The gate's mint flow enters on it.
	var body := JSON.stringify({
		"ok": true,
		"created": true,
		"user": { "name": "Arena Rider" },
		"horses": [],
		"openRaces": [],
	})
	var folded := StableActions.fold_response(200, body)
	assert_true(bool(folded.get("ok")), "a created stable folds as a good login")
	# …and the validate-only refusal the old deploys answer: a clean not-ok,
	# never a crash — the gate enters anyway and the socket's verdict speaks.
	var refused := StableActions.fold_response(401, JSON.stringify({ "error": "Invalid stable code." }))
	assert_false(bool(refused.get("ok")))
	assert_eq(str(refused.get("error")), "Invalid stable code.")


func test_a_minted_card_routes_the_next_boot_to_the_rider() -> void:
	# AuthStore.save is what the mint does silently; a remembered code is
	# exactly what boot_destination reads as "straight to the rider's gate".
	assert_eq(FrontGate.boot_destination(false, true), FrontGate.DEST_RIDER,
		"stored card, next boot: straight to the gate")
	assert_eq(FrontGate.boot_destination(true, false), FrontGate.DEST_RIDER,
		"a handoff token still wins on its own")
	assert_eq(FrontGate.boot_destination(false, false), FrontGate.DEST_STANDS,
		"a stranger with neither still lands in the stands, one door away")


# ── The plaza identity: guest mint and SSO exchange ───────────────────────────

func test_guest_handles_wear_the_rider_shape() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 11
	for n in 50:
		var handle := SsoExchange.guest_handle(rng)
		assert_true(handle.begins_with("Rider-"), "the gate's own theme: " + handle)
		var suffix := handle.trim_prefix("Rider-")
		assert_eq(suffix.length(), 4, "a four-digit draw: " + handle)
		assert_true(suffix.is_valid_int(), "digits only: " + handle)


func test_guest_handle_is_deterministic_under_a_seed() -> void:
	var first := RandomNumberGenerator.new()
	first.seed = 5
	var second := RandomNumberGenerator.new()
	second.seed = 5
	assert_eq(SsoExchange.guest_handle(first), SsoExchange.guest_handle(second),
		"same seed, same guest — the suite can pin the mint")


func test_plaza_base_table() -> void:
	assert_eq(SsoExchange.plaza_base(""), "https://ashaarena.com",
		"off the web the plaza origin stands")
	assert_eq(SsoExchange.plaza_base("https://ashaarena.com/"), "https://ashaarena.com",
		"same-origin when the plaza served this build, trailing slash trimmed")
	assert_eq(SsoExchange.plaza_base("  http://localhost:9000 "), "http://localhost:9000",
		"a serving origin is kept, whitespace trimmed")
	assert_eq(SsoExchange.plaza_base("racing.ashaarena.com"), "https://ashaarena.com",
		"no scheme is no origin")


func test_the_guest_mint_posts_the_handle_to_the_plaza_session_desk() -> void:
	var request := SsoExchange.guest_session_request("Rider-0042", "")
	assert_eq(int(request.get("method")), HTTPClient.METHOD_POST)
	assert_eq(str(request.get("base")), "https://ashaarena.com")
	assert_eq(str(request.get("path")), "/api/session")
	assert_eq(str(request.get("body")), JSON.stringify({ "handle": "Rider-0042" }),
		"the same call and handle shape the arena's studio page uses")


func test_the_guest_mints_answer_folds() -> void:
	var ok := SsoExchange.fold_guest_session(200,
		JSON.stringify({ "token": "tok-1", "handle": "Rider-0042", "key": "k" }))
	assert_true(bool(ok.get("ok")), "a token answers ok")
	assert_eq(str(ok.get("token")), "tok-1")
	assert_eq(str(ok.get("handle")), "Rider-0042")
	var tokenless := SsoExchange.fold_guest_session(200, JSON.stringify({ "handle": "Rider-0042" }))
	assert_false(bool(tokenless.get("ok")), "a 200 without a token is not a session")
	var throttled := SsoExchange.fold_guest_session(429, JSON.stringify({ "error": "Too many guests." }))
	assert_false(bool(throttled.get("ok")))
	assert_eq(str(throttled.get("error")), "Too many guests.", "the plaza's own words travel")
	var silent := SsoExchange.fold_guest_session(0, "{}")
	assert_false(bool(silent.get("ok")))
	assert_eq(str(silent.get("error")), "The Plaza did not answer (HTTP 0).")


func test_the_exchange_posts_the_token_to_sso() -> void:
	var request := SsoExchange.exchange_request("tok-9")
	assert_eq(int(request.get("method")), HTTPClient.METHOD_POST)
	assert_eq(str(request.get("path")), "/api/sso")
	assert_eq(str(request.get("body")), JSON.stringify({ "t": "tok-9" }))


func test_an_sso_refusal_keeps_the_servers_words() -> void:
	var ok := SsoExchange.fold_exchange(200, JSON.stringify({ "ok": true, "code": "ABC234", "created": true }))
	assert_true(bool(ok.get("ok")))
	assert_eq(str(ok.get("code")), "ABC234")
	assert_true(bool(ok.get("created")), "a first arrival says so")
	var refused := SsoExchange.fold_exchange(401, JSON.stringify({ "error": "Unknown arena token." }))
	assert_false(bool(refused.get("ok")))
	assert_eq(str(refused.get("error")), "Unknown arena token.",
		"the gate shows the server's message, not a paraphrase")
