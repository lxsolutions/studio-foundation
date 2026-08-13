class_name SsoExchange
extends RefCounted

## The no-typing gate paths. Plato's Plaza opens the stables with ?t=TOKEN in
## the URL (the same handoff the DOM stables accept); POST /api/sso exchanges
## that token for the stable's owner code, creating the stable on first
## arrival. A remembered code re-enters through POST /api/login. A stranger
## with neither taps once and the gate mints a code in the server's own
## format (mint_code below), registering it through the same login call.
## Everything here is pure string work so the whole gate policy is testable
## offline; the tokens themselves are single-purpose and never stored, only
## the code is.


## Pull t out of a raw query string ("?t=X&y=1" or "t=X&y=1"). Empty when
## absent. First t wins, mirroring URLSearchParams in the DOM stables.
static func extract_token(query: String) -> String:
	for pair in _pairs(query):
		if str(pair.get("key")) == "t":
			return str(pair.get("value")).strip_edges()
	return ""


## The same query with every t removed, other params kept verbatim and in
## order, no leading "?". Feeds history.replaceState so tokens never linger
## in the address bar or history.
static func scrubbed_query(query: String) -> String:
	return _scrubbed(query, "t")


## Pull the challenge-ghost id out of a raw query string ("?ghost=g-7").
## Empty when absent. First ghost wins, same as the token.
static func extract_ghost_id(query: String) -> String:
	for pair in _pairs(query):
		if str(pair.get("key")) == "ghost":
			return str(pair.get("value")).strip_edges()
	return ""


## The same query with every ghost removed — the deep link is one-shot, so it
## leaves the address bar exactly like the token does.
static func scrubbed_ghost_query(query: String) -> String:
	return _scrubbed(query, "ghost")


## The shareable challenge link for a ghost: this page's origin carrying
## ?ghost=<id> and nothing else. Off the web (no origin to read) it points at
## the racing origin, the same fallback recovery_url takes.
static func ghost_challenge_url(page_origin: String, ghost_id: String) -> String:
	var origin := page_origin.strip_edges().trim_suffix("/")
	if not origin.begins_with("http://") and not origin.begins_with("https://"):
		origin = "https://racing.ashaarena.com"
	return origin + "/?ghost=" + ghost_id.uri_encode()


static func _scrubbed(query: String, banned_key: String) -> String:
	var kept: PackedStringArray = []
	for pair in _pairs(query):
		if str(pair.get("key")) != banned_key:
			kept.append(str(pair.get("raw")))
	return "&".join(kept)


## The exchange request in StableActions' builder shape.
static func exchange_request(token: String) -> Dictionary:
	return {
		"method": HTTPClient.METHOD_POST,
		"path": "/api/sso",
		"body": JSON.stringify({ "t": token }),
	}


## The remembered-code re-entry that pairs with the handoff.
static func login_request(code: String) -> Dictionary:
	return {
		"method": HTTPClient.METHOD_POST,
		"path": "/api/login",
		"body": JSON.stringify({ "code": code }),
	}


# ── New stables: the one-tap mint ─────────────────────────────────────────────

## The stable-code shape the racing server's own minter uses (server/models.js
## randomCode in archer-racing-club: 32 unambiguous glyphs — no I/O/0/1 —
## six long; the socket auth clamps at twelve). The club exposes NO public
## register endpoint: /api/sso mints only from a Plaza arena token, /api/login
## validates. So a stranger's first tap mints client-side in the server's
## format, then REGISTERS THROUGH THE LOGIN CALL — a deploy that creates on
## login makes the code real with that one request, and the card is the
## rider's from the first tap either way.
const CODE_ALPHABET := "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
const CODE_LENGTH := 6
## The server's own clamp (socket auth and REST login both slice to 12).
const CODE_MAX_LENGTH := 12


## A fresh stable code in the server's format. The RNG is injectable so the
## suite can pin determinism; production passes nothing and gets a random one.
static func mint_code(rng: RandomNumberGenerator = null) -> String:
	if rng == null:
		rng = RandomNumberGenerator.new()
		rng.randomize()
	var code := ""
	for i in CODE_LENGTH:
		code += CODE_ALPHABET[rng.randi() % CODE_ALPHABET.length()]
	return code


## Whether a typed or minted code has the server's shape: 1–12 glyphs from
## the mint alphabet, case-insensitive (auth upcases before it looks).
static func is_code_shape(code: String) -> bool:
	var trimmed := code.strip_edges()
	if trimmed.is_empty() or trimmed.length() > CODE_MAX_LENGTH:
		return false
	for i in trimmed.length():
		if CODE_ALPHABET.find(trimmed[i].to_upper()) < 0:
			return false
	return true


## The minted code's registration IS the login call: on a create-on-login
## deploy this answers ok and the stable exists from that moment; on a
## validate-only deploy it answers like any unknown code and the socket's
## verdict stands. Either way the gate enters with the card.
static func register_request(code: String) -> Dictionary:
	return login_request(code)


## Fold the exchange response into { ok, code, created, error }.
static func fold_exchange(status: int, body_text: String) -> Dictionary:
	var parsed: Variant = JSON.parse_string(body_text)
	var body: Dictionary = parsed if typeof(parsed) == TYPE_DICTIONARY else {}
	var code := str(body.get("code", "")).strip_edges()
	if status >= 200 and status < 300 and bool(body.get("ok", false)) and not code.is_empty():
		return { "ok": true, "code": code, "created": bool(body.get("created", false)), "error": "" }
	var message := str(body.get("error", ""))
	if message.is_empty():
		message = "The Plaza handoff did not stick (HTTP %d)." % status
	return { "ok": false, "code": "", "created": false, "error": message }


## Whether a failed remembered-code login should forget the code: only when
## the club answered and rejected it, never on a 429 lockout (the code may be
## fine) and never on network trouble (status 0). Mirrors the DOM stables.
static func should_forget(status: int) -> bool:
	return status >= 400 and status != 429


## Where "Lost your code?" goes: the legacy DOM stables carry the whole
## email-reset flow, so recovery is a link-out (deploy doc D2-A). The owner
## retired /play on 2026-07-19 (it now redirects into this club); the legacy
## app lives on as the stables OFFICE at /office. Same origin when served
## beside it (the /ride mount); the racing origin otherwise.
static func recovery_url(page_origin: String) -> String:
	var origin := page_origin.strip_edges().trim_suffix("/")
	if origin.begins_with("http://") or origin.begins_with("https://"):
		return origin + "/office/"
	return "https://racing.ashaarena.com/office/"


## http(s) base for gate REST calls, derived from the socket base url.
static func http_base(socket_base_url: String) -> String:
	if socket_base_url.begins_with("wss://"):
		return "https://" + socket_base_url.trim_prefix("wss://")
	if socket_base_url.begins_with("ws://"):
		return "http://" + socket_base_url.trim_prefix("ws://")
	return socket_base_url


static func _pairs(query: String) -> Array[Dictionary]:
	var pairs: Array[Dictionary] = []
	for raw_pair in query.trim_prefix("?").split("&", false):
		var split_at := raw_pair.find("=")
		var raw_key := raw_pair if split_at < 0 else raw_pair.substr(0, split_at)
		var raw_value := "" if split_at < 0 else raw_pair.substr(split_at + 1)
		pairs.append({
			"key": raw_key.uri_decode(),
			"value": raw_value.uri_decode(),
			"raw": raw_pair,
		})
	return pairs
