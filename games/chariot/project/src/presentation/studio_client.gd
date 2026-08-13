class_name StudioClient
extends Node

## The studio-protocol websocket client: the bridge between GhostStore's
## transport seam and the in-repo Rust game server (server/, over
## StudioWsTransport + StudioProtocol from studio_core — the addon stays
## untouched). ghost_submit / ghost_fetch ride application_request envelopes;
## the server answers application_result in send order, so in-flight requests
## settle one FIFO queue (the protocol carries no correlation ids).
##
## Two entry points for the same pipe: request/submit_now/fetch_now take a
## reply Callable and never suspend (the test suite drives them through
## pump()); submit/fetch/transport_mapping are the coroutine wrappers the
## GhostStore seam awaits. The bridge is opportunistic, never a hard
## dependency: no server URL (RACING_SPECTATE_OFFLINE=1, the test suite's
## posture), a connect failure, or a dropped socket parks it for the session,
## and every request then answers an immediate offline-shaped refusal —
## GhostStore falls back to local-only, exactly as without a bridge.
## RACING_STUDIO_URL overrides the server address (set but empty parks the
## bridge). Otherwise the bridge follows the page that served the game:
## /studio on the same origin at a domain root (racing.ashaarena.com, where
## /webgpu and /webgl are the export's own mounts, not game prefixes), and
## /racing/studio when the game is served under a /racing path
## (ashaarena.com/racing/…). Off the web DEFAULT_BASE_URL stands.

const DEFAULT_BASE_URL := "wss://racing.ashaarena.com/studio"
const CLIENT_NAME := "chariot"
const REQUEST_TIMEOUT_S := 10.0
const HANDSHAKE_TIMEOUT_S := 5.0

var base_url := ""
## The plaza bearer token, attached to ghost_submit when we hold one. Source:
## the ?t= handoff token captured at the sign-in gate (it overrides whatever
## discover_plaza_token found), else the same-origin arb_token. The owner
## code is NOT a token: the club has no verify endpoint for it, so code-signed
## riders submit under the server-claimed member path, as before the bridge.
var token := ""

var _transport: StudioTransport = null
var _configured := false
var _connecting := false
var _connect_remaining_s := 0.0
var _handshook := false
var _gave_up := false
## Requests made before the handshake completes, in arrival order.
var _backlog: Array[Dictionary] = []
var _in_flight: Array[_InFlight] = []


## One sent request awaiting its application_result: the reply Callable fires
## exactly once — from pump() when the answer or its timeout arrives, or from
## _on_drop when the socket dies.
class _InFlight:
	extends RefCounted
	var on_reply: Callable
	var remaining_s: float = 0.0

	func _init(cb: Callable, timeout_s: float) -> void:
		on_reply = cb
		remaining_s = timeout_s


## The coroutine half of a request: settle may fire synchronously (a parked
## bridge answers before the caller reaches its await), so the reply is
## stored, not just signalled.
class _Settle:
	extends RefCounted
	signal settled(reply: Dictionary)
	var resolved := false
	var reply: Dictionary = {}

	func settle(p_reply: Dictionary) -> void:
		if resolved:
			return
		resolved = true
		reply = p_reply
		settled.emit(p_reply)


func _ready() -> void:
	_configure()


func _process(delta: float) -> void:
	pump(delta)


## Resolve the server URL once. An explicitly set base_url (tests, embedders)
## always wins; RACING_STUDIO_URL overrides the default verbatim — set but
## empty parks the bridge — and the offline flag parks it too. On the web the
## default is derived from the page's own origin and path so the same export
## answers at racing.ashaarena.com and at ashaarena.com/racing; anywhere else
## the DEFAULT_BASE_URL mount stands.
func _configure() -> void:
	if _configured:
		return
	_configured = true
	if not base_url.is_empty():
		return
	if OS.has_environment("RACING_STUDIO_URL"):
		base_url = OS.get_environment("RACING_STUDIO_URL")
		return
	if OS.get_environment("RACING_SPECTATE_OFFLINE") == "1":
		return
	if OS.has_feature("web"):
		var derived := derive_ws_url(_page_url())
		if not derived.is_empty():
			base_url = derived
			return
	base_url = DEFAULT_BASE_URL


## The studio socket's address for a page at `page_url` (origin + path, e.g.
## "https://ashaarena.com/racing/webgpu/index.html"): same origin, /studio at
## a domain root, /racing/studio under a /racing path. Pure string work so
## the whole derivation table is testable offline; anything unparseable
## answers "" and the caller falls back to the default mount.
static func derive_ws_url(page_url: String) -> String:
	var rest := page_url.strip_edges()
	var scheme := ""
	if rest.begins_with("https://"):
		scheme = "wss://"
	elif rest.begins_with("http://"):
		scheme = "ws://"
	else:
		return ""
	rest = rest.substr(rest.find("://") + 3)
	var slash := rest.find("/")
	var host := rest if slash < 0 else rest.substr(0, slash)
	if host.is_empty():
		return ""
	var path := "" if slash < 0 else rest.substr(slash)
	# pathname carries neither, but a hand-typed URL might.
	var cut := path.find("?")
	if cut >= 0:
		path = path.substr(0, cut)
	cut = path.find("#")
	if cut >= 0:
		path = path.substr(0, cut)
	var prefix := ""
	if path == "/racing" or path.begins_with("/racing/"):
		prefix = "/racing"
	return scheme + host + prefix + "/studio"


## origin + pathname from the browser, "" off the web; derivation lives in
## derive_ws_url so the policy never touches JavaScriptBridge directly.
static func _page_url() -> String:
	if not OS.has_feature("web"):
		return ""
	return str(JavaScriptBridge.eval(
		"window.location.origin+window.location.pathname", true))


## The same-origin plaza session, when the plaza itself served this build:
## localStorage "arb_token", the key the plaza writes and the Minerals bridge
## reads. Empty off the web or cross-origin.
static func discover_plaza_token() -> String:
	if not OS.has_feature("web"):
		return ""
	var raw: Variant = JavaScriptBridge.eval(
		"(function(){try{return window.localStorage.getItem('arb_token')||'';}catch(e){return '';}})()",
		true
	)
	return str(raw).strip_edges()


## Test seam: run the bridge over a StudioLoopbackTransport pair instead of a
## real socket. Call before the first request.
func inject_transport(transport: StudioTransport) -> void:
	_transport = transport
	_wire_transport()


# ── The reply-Callable entry points (never suspend; the test suite's pipe) ───

## Send one application payload; on_reply fires exactly once with the reply
## dictionary. Queues behind the handshake when the socket is still opening.
func request(payload: Dictionary, on_reply: Callable) -> void:
	_configure()
	if _gave_up or base_url.is_empty():
		on_reply.call({"ok": false, "error": "the studio bridge is offline"})
		return
	if not _handshook:
		_backlog.append({"payload": payload, "on_reply": on_reply})
		if not _connecting:
			_begin_connect()
		return
	_send(payload, on_reply)


## Store a run on the server. The plaza token goes along when we hold one;
## the server then keys the ghost by the verified stable identity.
func submit_now(payload: Dictionary, on_reply: Callable) -> void:
	var body := payload.duplicate()
	if not token.is_empty():
		body["token"] = token
	request(body, on_reply)


## Fetch a run by id. No identity needed: a ghost is public to its holder.
func fetch_now(payload: Dictionary, on_reply: Callable) -> void:
	request(payload, on_reply)


# ── The coroutine wrappers (the GhostStore seam awaits these) ────────────────

func submit(payload: Dictionary) -> Dictionary:
	var settle := _Settle.new()
	submit_now(payload, settle.settle)
	if settle.resolved:
		return settle.reply
	return await settle.settled


func fetch(payload: Dictionary) -> Dictionary:
	var settle := _Settle.new()
	fetch_now(payload, settle.settle)
	if settle.resolved:
		return settle.reply
	return await settle.settled


## The GhostStore.transport seam: ghost_submit rides submit, ghost_fetch
## rides fetch. The store awaits the answer; a parked bridge answers
## immediately (no suspension) and the store falls back to local.
func transport_mapping(payload: Dictionary) -> Dictionary:
	match str(payload.get("kind", "")):
		"ghost_submit":
			return await submit(payload)
		"ghost_fetch":
			return await fetch(payload)
	return {"ok": false, "error": "the studio bridge does not carry " + str(payload.get("kind", "?"))}


func close() -> void:
	_gave_up = true
	if _transport != null:
		_transport.close("client closing")


func _send(payload: Dictionary, on_reply: Callable) -> void:
	var envelope := StudioProtocol.application_request(_transport.seq(), payload)
	if _transport.send_envelope(envelope) != OK:
		on_reply.call({"ok": false, "error": "the studio bridge dropped the send"})
		return
	_in_flight.append(_InFlight.new(on_reply, REQUEST_TIMEOUT_S))


func _begin_connect() -> void:
	_connecting = true
	_connect_remaining_s = HANDSHAKE_TIMEOUT_S
	if _transport == null:
		inject_transport(StudioWsTransport.new())
	if _transport.connect_to(base_url) != OK:
		_on_drop("connect failed")


func _wire_transport() -> void:
	_transport.connected.connect(_on_connected)
	_transport.envelope_received.connect(_on_envelope)
	_transport.disconnected.connect(_on_drop)
	_transport.transport_error.connect(_on_drop)


func _on_connected() -> void:
	_transport.send_envelope(StudioProtocol.hello(_transport.seq(), CLIENT_NAME, _build_string()))


## The build string for the hello handshake, from the Studio autoload when
## the tree carries it (production), "dev" when it does not (detached tests).
func _build_string() -> String:
	var studio := get_node_or_null("/root/Studio") if is_inside_tree() else null
	if studio != null:
		var info: Variant = studio.get("build_info")
		if info != null:
			return str((info as Object).get("version"))
	return "dev"


func _on_envelope(envelope: Dictionary) -> void:
	match str(envelope.get("type", "")):
		"hello_ack":
			_connecting = false
			_handshook = true
			var backlog := _backlog
			_backlog = []
			for entry in backlog:
				_send(entry.get("payload", {}), entry.get("on_reply", Callable()))
		"application_result":
			if _in_flight.is_empty():
				return
			var next: _InFlight = _in_flight.pop_front()
			next.on_reply.call(_fold_result(envelope))


## The server puts its game-owned JSON in the result summary; unfold it. A
## summary that is not JSON degrades to the bare accepted flag.
static func _fold_result(envelope: Dictionary) -> Dictionary:
	var accepted := bool(envelope.get("accepted", false))
	var parsed: Variant = JSON.parse_string(str(envelope.get("summary", "")))
	if typeof(parsed) == TYPE_DICTIONARY:
		return parsed
	return {"ok": accepted}


## A dead socket parks the bridge for the session (a page load retries) and
## settles everything waiting — a request must never hang.
func _on_drop(reason: String) -> void:
	_handshook = false
	_connecting = false
	_gave_up = true
	var error := {"ok": false, "error": "the studio bridge dropped: " + reason}
	var backlog := _backlog
	_backlog = []
	for entry in backlog:
		var on_reply: Callable = entry.get("on_reply", Callable())
		on_reply.call(error)
	while not _in_flight.is_empty():
		var next: _InFlight = _in_flight.pop_front()
		next.on_reply.call(error)


## The pump: the transport polls, the handshake and every in-flight request
## count down their timeouts. _process drives this in the tree; tests drive
## it by hand.
func pump(delta: float) -> void:
	if _transport != null:
		_transport.poll()
	if _connecting and not _handshook:
		_connect_remaining_s -= delta
		if _connect_remaining_s <= 0.0:
			_on_drop("the studio bridge timed out saying hello")
	for next in _in_flight.duplicate():
		next.remaining_s -= delta
		if next.remaining_s <= 0.0:
			_in_flight.erase(next)
			next.on_reply.call({"ok": false, "error": "the studio bridge timed out"})
