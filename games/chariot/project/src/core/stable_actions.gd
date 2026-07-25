class_name StableActions
extends RefCounted

## The stable's REST verbs as pure request builders and response folds. The
## socket remains the truth channel (the server pushes horses:update and
## races:update after every mutation); these calls only carry intent and
## surface errors, so nothing here caches or predicts state.

const MEALS: Array[String] = ["oats", "apple", "herbs"]
const FOCUSES: Array[String] = ["sprints", "endurance", "gates", "paddock"]


static func enter(horse_id: String, race_id: String, code: String) -> Dictionary:
	return _post("/api/horse/%s/enter" % horse_id, { "code": code, "raceId": race_id })


static func withdraw(horse_id: String, race_id: String, code: String) -> Dictionary:
	return _post("/api/horse/%s/withdraw" % horse_id, { "code": code, "raceId": race_id })


static func train(horse_id: String, focus: String, code: String) -> Dictionary:
	return _post("/api/horse/%s/train" % horse_id, { "code": code, "focus": focus })


static func care(horse_id: String, meal: String, code: String) -> Dictionary:
	return _post("/api/horse/%s/care" % horse_id, { "code": code, "meal": meal })


# ── Bloodstock: breeding, selling, retiring ──────────────────────────────────

static func breed_preview(sire_id: String, dam_id: String, code: String) -> Dictionary:
	var request := _post("/api/breed/preview", { "code": code, "sireId": sire_id, "damId": dam_id })
	request["wants_data"] = true
	return request


static func breed(sire_id: String, dam_id: String, code: String) -> Dictionary:
	return _post("/api/breed", { "code": code, "sireId": sire_id, "damId": dam_id })


static func sell(horse_id: String, code: String) -> Dictionary:
	return _post("/api/horse/%s/sell" % horse_id, { "code": code })


static func retire(horse_id: String, code: String) -> Dictionary:
	return _post("/api/horse/%s/retire" % horse_id, { "code": code })


# ── The Bloodstock Exchange ──────────────────────────────────────────────────

static func exchange_fetch(code: String) -> Dictionary:
	return _authed_get("/api/exchange", code)


static func exchange_list(horse_id: String, price: int, code: String) -> Dictionary:
	return _post("/api/exchange/list", { "code": code, "horseId": horse_id, "price": price })


static func exchange_delist(listing_id: String, code: String) -> Dictionary:
	return { "method": HTTPClient.METHOD_DELETE, "path": "/api/exchange/list/%s" % listing_id, "body": JSON.stringify({ "code": code }) }


static func exchange_buy(listing_id: String, code: String) -> Dictionary:
	return _post("/api/exchange/buy/%s" % listing_id, { "code": code })


# ── Honours and standings projections ────────────────────────────────────────

static func honours_fetch(code: String) -> Dictionary:
	return _authed_get("/api/honours", code)


static func honours_claim(honour_id: String, code: String) -> Dictionary:
	return _post("/api/honours/%s/claim" % honour_id, { "code": code })


static func circuit_fetch(code: String) -> Dictionary:
	return _authed_get("/api/circuit", code)


static func studbook_fetch(code: String) -> Dictionary:
	return _authed_get("/api/studbook", code)


static func _post(path: String, body: Dictionary) -> Dictionary:
	return { "method": HTTPClient.METHOD_POST, "path": path, "body": JSON.stringify(body) }


static func _authed_get(path: String, code: String) -> Dictionary:
	return { "method": HTTPClient.METHOD_GET, "path": "%s?code=%s" % [path, code.uri_encode()], "body": "" }


## Fold a REST response into { ok, error }. The server's error shape is
## { error: "human readable" } with 4xx/5xx; 429 carries the lockout message.
static func fold_response(status: int, body_text: String) -> Dictionary:
	var parsed: Variant = JSON.parse_string(body_text)
	var body: Dictionary = parsed if typeof(parsed) == TYPE_DICTIONARY else {}
	if status >= 200 and status < 300 and bool(body.get("ok", false)):
		return { "ok": true, "error": "" }
	var message := str(body.get("error", ""))
	if message.is_empty():
		message = "The race office is not answering (HTTP %d)." % status
	return { "ok": false, "error": message }


## Fold a projection response, keeping the parsed payload for rendering.
static func fold_json(status: int, body_text: String) -> Dictionary:
	var parsed: Variant = JSON.parse_string(body_text)
	var body: Dictionary = parsed if typeof(parsed) == TYPE_DICTIONARY else {}
	var folded := fold_response(status, body_text)
	folded["data"] = body
	return folded
