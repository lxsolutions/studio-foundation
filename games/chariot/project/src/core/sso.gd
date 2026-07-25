class_name SsoExchange
extends RefCounted

## The no-typing gate paths. Plato's Plaza opens the stables with ?t=TOKEN in
## the URL (the same handoff the DOM stables accept); POST /api/sso exchanges
## that token for the stable's owner code, creating the stable on first
## arrival. A remembered code re-enters through POST /api/login. Everything
## here is pure string work so the whole gate policy is testable offline; the
## tokens themselves are single-purpose and never stored, only the code is.


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
	var kept: PackedStringArray = []
	for pair in _pairs(query):
		if str(pair.get("key")) != "t":
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
