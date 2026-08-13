class_name WebHandoff
extends RefCounted

## The arrival side of the Plaza handoff. platosplaza.com opens the stables
## with ?t=TOKEN; we lift the token out of the page URL and scrub it from the
## address bar and history immediately, exactly like the DOM stables do.
## RACING_SSO_TOKEN serves the same token to headless checks, where there is
## no page. Served same-origin with the plaza (ashaarena.com/racing/), the
## build also reads the plaza's own localStorage session straight out of the
## browser — plaza_token below — so a visitor who already carries an Arena
## identity never meets a code at all. Parsing lives in SsoExchange so the
## policy is testable offline; this file only touches the browser.


## The page origin on the web, empty elsewhere; recovery_url turns it into
## the stables-office address.
static func page_origin() -> String:
	if not OS.has_feature("web"):
		return ""
	return str(JavaScriptBridge.eval("window.location.origin||''", true))


## True when a handoff token is waiting (env or page URL) WITHOUT consuming
## it: no scrubbing here, the rider's gate does that when it takes the token.
static func token_waiting() -> bool:
	if not OS.get_environment("RACING_SSO_TOKEN").is_empty():
		return true
	if not OS.has_feature("web"):
		return false
	var query := str(JavaScriptBridge.eval("window.location.search||''", true))
	return not SsoExchange.extract_token(query).is_empty()


static func take_token() -> String:
	var env_token := OS.get_environment("RACING_SSO_TOKEN")
	if not env_token.is_empty():
		return env_token.strip_edges()
	if not OS.has_feature("web"):
		return ""
	var query := str(JavaScriptBridge.eval("window.location.search||''", true))
	var token := SsoExchange.extract_token(query)
	if token.is_empty():
		return ""
	var scrubbed := SsoExchange.scrubbed_query(query)
	var suffix := "" if scrubbed.is_empty() else "?" + scrubbed
	JavaScriptBridge.eval(
		"window.history.replaceState(null,'',window.location.pathname+%s+window.location.hash);"
			% JSON.stringify(suffix),
		true
	)
	return token


## The plaza's own session: localStorage "arb_token", the key the plaza
## writes and every Asha surface reads (the Minerals bridge reads the same
## key). Same-origin at ashaarena.com/racing/ this build shares that store,
## so a visitor carrying an Arena identity is already known here. Unlike
## take_token this is a READ, never a consume: the session is the visitor's
## everywhere, not a one-shot handoff. RACING_SSO_TOKEN is the env/test path
## off the web, the same override take_token honours.
static func plaza_token() -> String:
	var env_token := OS.get_environment("RACING_SSO_TOKEN")
	if not env_token.is_empty():
		return env_token.strip_edges()
	if not OS.has_feature("web"):
		return ""
	var raw: Variant = JavaScriptBridge.eval(
		"(function(){try{return window.localStorage.getItem('arb_token')||'';}catch(e){return '';}})()",
		true
	)
	return str(raw).strip_edges()


## Write a freshly minted plaza guest session back under the plaza's own key,
## so the identity travels to every other Asha surface the visitor meets.
## Off the web there is no shared store; the gate still spends the token once
## at /api/sso for this session's entry.
static func store_plaza_session(token: String) -> void:
	var trimmed := token.strip_edges()
	if trimmed.is_empty() or not OS.has_feature("web"):
		return
	JavaScriptBridge.eval(
		"try{window.localStorage.setItem('arb_token',%s);}catch(e){}" % JSON.stringify(trimmed),
		true
	)


## The challenge-ghost half of the handoff: ?ghost=<id> opens the game with
## that ghost armed on the sand. Taken once and scrubbed from the address bar
## exactly like the token; RACING_GHOST_ID serves headless checks. Deep links
## survive the token scrub (each take removes only its own key), so a link can
## carry both a sign-in and a challenge.
static func take_ghost_id() -> String:
	var env_id := OS.get_environment("RACING_GHOST_ID")
	if not env_id.is_empty():
		return env_id.strip_edges()
	if not OS.has_feature("web"):
		return ""
	var query := str(JavaScriptBridge.eval("window.location.search||''", true))
	var ghost_id := SsoExchange.extract_ghost_id(query)
	if ghost_id.is_empty():
		return ""
	var scrubbed := SsoExchange.scrubbed_ghost_query(query)
	var suffix := "" if scrubbed.is_empty() else "?" + scrubbed
	JavaScriptBridge.eval(
		"window.history.replaceState(null,'',window.location.pathname+%s+window.location.hash);"
			% JSON.stringify(suffix),
		true
	)
	return ghost_id
