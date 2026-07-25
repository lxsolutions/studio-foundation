class_name AuthStore
extends RefCounted

## Where the rider's owner code lives between visits. On the web export this
## is localStorage "arc_code", the SAME key the DOM stables use, so a rider
## signed in there is already signed in here (and back again after the DOM
## app retires). Private-mode storage throws; the config file is the quiet
## fallback everywhere, and the only store off the web.

const CONFIG_PATH := "user://rider.cfg"
const WEB_KEY := "arc_code"


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
