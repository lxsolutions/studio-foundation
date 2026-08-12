class_name AuthStore
extends RefCounted

## Where the rider's owner code lives between visits. On the web export this
## is localStorage "arc_code", the SAME key the DOM stables use, so a rider
## signed in there is already signed in here (and back again after the DOM
## app retires). Private-mode storage throws; the config file is the quiet
## fallback everywhere, and the only store off the web.

const CONFIG_PATH := "user://rider.cfg"
const WEB_KEY := "arc_code"
## The rider's chosen faction rides beside the code (same store, same rules):
## localStorage "arc_faction" on the web so the DOM stables could read it too.
const WEB_FACTION_KEY := "arc_faction"


static func saved_code() -> String:
	var web := _web_read()
	if not web.is_empty():
		return web
	var config := ConfigFile.new()
	if config.load(CONFIG_PATH) == OK:
		return str(config.get_value("auth", "code", "")).strip_edges()
	return ""


static func save(code: String) -> void:
	var config := ConfigFile.new()
	config.load(CONFIG_PATH)
	config.set_value("auth", "code", code)
	config.save(CONFIG_PATH)
	if OS.has_feature("web"):
		JavaScriptBridge.eval(
			"try{window.localStorage.setItem(%s,%s);}catch(e){}"
			% [JSON.stringify(WEB_KEY), JSON.stringify(code)],
			true
		)


static func forget() -> void:
	var config := ConfigFile.new()
	config.load(CONFIG_PATH)
	if config.has_section_key("auth", "code"):
		config.erase_section_key("auth", "code")
	config.save(CONFIG_PATH)
	if OS.has_feature("web"):
		JavaScriptBridge.eval(
			"try{window.localStorage.removeItem(%s);}catch(e){}" % JSON.stringify(WEB_KEY),
			true
		)


static func _web_read() -> String:
	if not OS.has_feature("web"):
		return ""
	var raw: Variant = JavaScriptBridge.eval(
		"(function(){try{return window.localStorage.getItem(%s)||'';}catch(e){return '';}})()"
			% JSON.stringify(WEB_KEY),
		true
	)
	return str(raw).strip_edges()


## The rider's circus faction. Local-only for now: the racing wire has no
## faction key yet. The identity bridge (StudioClient) already carries the
## ghost payloads; the server's faction payloads pick the choice up when the
## client sends them.
static func saved_faction() -> String:
	var web := _web_read_faction()
	if not web.is_empty():
		return web
	var config := ConfigFile.new()
	if config.load(CONFIG_PATH) == OK:
		var stored := str(config.get_value("faction", "id", "")).strip_edges()
		if CircusFactions.is_valid_id(stored):
			return stored
	return ""


static func save_faction(faction_id: String) -> void:
	if not CircusFactions.is_valid_id(faction_id):
		return
	var config := ConfigFile.new()
	config.load(CONFIG_PATH)
	config.set_value("faction", "id", faction_id)
	config.save(CONFIG_PATH)
	if OS.has_feature("web"):
		JavaScriptBridge.eval(
			"try{window.localStorage.setItem(%s,%s);}catch(e){}"
			% [JSON.stringify(WEB_FACTION_KEY), JSON.stringify(faction_id)],
			true
		)


static func _web_read_faction() -> String:
	if not OS.has_feature("web"):
		return ""
	var raw: Variant = JavaScriptBridge.eval(
		"(function(){try{return window.localStorage.getItem(%s)||'';}catch(e){return '';}})()"
			% JSON.stringify(WEB_FACTION_KEY),
		true
	)
	var stored := str(raw).strip_edges()
	return stored if CircusFactions.is_valid_id(stored) else ""
