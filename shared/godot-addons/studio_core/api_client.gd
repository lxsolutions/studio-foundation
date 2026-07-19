class_name StudioApiClient
extends RefCounted
## JSON API client over HTTPRequest for the control API. Await-friendly:
##   var res: Dictionary = await Studio.api.get_json("/v1/status")
## Result: { ok: bool, status: int, body: Variant, error: String }

var base_url: String
var _host: Node


func _init(host: Node, api_base_url: String) -> void:
	_host = host
	base_url = api_base_url.rstrip("/")


func get_json(path: String) -> Dictionary:
	return await _request(HTTPClient.METHOD_GET, path, "")


func post_json(path: String, body: Variant = null) -> Dictionary:
	var payload: String = "" if body == null else JSON.stringify(body)
	return await _request(HTTPClient.METHOD_POST, path, payload)


func _request(method: int, path: String, payload: String) -> Dictionary:
	if _host == null or not _host.is_inside_tree():
		return {"ok": false, "status": 0, "body": null, "error": "api client host not in tree"}
	var request: HTTPRequest = HTTPRequest.new()
	request.timeout = 10.0
	_host.add_child(request)
	var headers: PackedStringArray = ["Content-Type: application/json"]
	var err: Error = request.request(base_url + path, headers, method as HTTPClient.Method, payload)
	if err != OK:
		request.queue_free()
		return {"ok": false, "status": 0, "body": null, "error": "request error %d" % err}
	var result: Array = await request.request_completed
	request.queue_free()
	var request_result: int = result[0]
	var status: int = result[1]
	var body_bytes: PackedByteArray = result[3]
	if request_result != HTTPRequest.RESULT_SUCCESS:
		return {"ok": false, "status": status, "body": null, "error": "transport failure %d" % request_result}
	var body_text: String = body_bytes.get_string_from_utf8()
	var parsed: Variant = JSON.parse_string(body_text) if not body_text.is_empty() else null
	if parsed == null and not body_text.is_empty():
		parsed = body_text # plain-text endpoints like /healthz
	return {"ok": status >= 200 and status < 300, "status": status, "body": parsed, "error": ""}
