class_name WebHandoff
extends RefCounted

## The arrival side of the Plaza handoff. platosplaza.com opens the stables
## with ?t=TOKEN; we lift the token out of the page URL and scrub it from the
## address bar and history immediately, exactly like the DOM stables do.
## RACING_SSO_TOKEN serves the same token to headless checks, where there is
## no page. Parsing lives in SsoExchange so the policy is testable offline;
## this file only touches the browser.


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
