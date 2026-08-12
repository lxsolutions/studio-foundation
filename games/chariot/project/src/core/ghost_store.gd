class_name GhostStore
extends RefCounted

## Where challenge ghosts live between races: one schema-1 JSON run per file
## under user://ghosts/, following StudioReplay's user:// convention.
##
## The sharing path is the in-repo game server's ghost_submit / ghost_fetch
## application payloads, carried by the studio bridge (StudioClient) when a
## server is reachable. The transport is a seam: inject a Callable(payload:
## Dictionary) -> Dictionary that answers those kinds and saves submit, loads
## fetch (a server copy is mirrored locally so the run still loads offline).
## The callable MAY be a coroutine — the bridge's round trip is one — so both
## call sites await it; a synchronous callable resolves without suspending and
## save/load_ghost stay synchronous themselves. Unset means local-only.

const GHOST_DIR := "user://ghosts"
const LOCAL_PREFIX := "ghost_"

var transport := Callable()


## Save a validated run, returning its ghost id ("" when the run is no ghost
## at all). Server-first when a transport is wired, local otherwise. Awaits
## the transport's answer: with the live bridge this is a coroutine.
func save(run: GhostRun) -> String:
	if run == null or not run.is_valid():
		return ""
	if transport.is_valid():
		var reply: Dictionary = await transport.call({
			"kind": "ghost_submit",
			"member": run.handle,
			"faction": run.faction,
			"handle": run.handle,
			"totalMs": run.total_ms,
			"distanceM": run.distance_m,
			"ticks": run.ticks,
		})
		if bool(reply.get("ok", false)):
			var server_id := str(reply.get("id", ""))
			if not server_id.is_empty():
				_save_local(server_id, run)
				return server_id
	var local_id := _next_local_id()
	return local_id if _save_local(local_id, run) else ""


## Load a run by id: the local mirror first, the server when wired. null when
## no ghost answers to the id (or the stored run fails its bounds). Awaits the
## transport's answer on a local miss, exactly like save.
func load_ghost(id: String) -> GhostRun:
	var run := _load_local(id)
	if run != null:
		return run
	if transport.is_valid():
		var reply: Dictionary = await transport.call({"kind": "ghost_fetch", "id": id})
		if bool(reply.get("ok", false)):
			var fetched := GhostRun.from_dict(reply.get("ghost", {}))
			if fetched != null and fetched.is_valid():
				_save_local(id, fetched)
				return fetched
	return null


## Every locally held ghost, newest first: {id, handle, faction, totalMs}.
func list_local() -> Array[Dictionary]:
	var dir := DirAccess.open(GHOST_DIR)
	if dir == null:
		return []
	var found: Array[Dictionary] = []
	dir.list_dir_begin()
	var entry := dir.get_next()
	while not entry.is_empty():
		if not dir.current_is_dir() and entry.ends_with(".json"):
			var id := entry.trim_suffix(".json")
			var run := _load_local(id)
			if run != null:
				found.append({
					"id": id,
					"handle": run.handle,
					"faction": run.faction,
					"totalMs": run.total_ms,
				})
		entry = dir.get_next()
	dir.list_dir_end()
	found.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		return str(a.get("id", "")) > str(b.get("id", "")))
	return found


func _save_local(id: String, run: GhostRun) -> bool:
	if not _id_safe(id):
		return false
	DirAccess.make_dir_recursive_absolute(GHOST_DIR)
	var file := FileAccess.open(_path_for(id), FileAccess.WRITE)
	if file == null:
		return false
	file.store_string(JSON.stringify(run.to_dict()))
	return true


func _load_local(id: String) -> GhostRun:
	if not _id_safe(id):
		return null
	var path := _path_for(id)
	if not FileAccess.file_exists(path):
		return null
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return null
	return GhostRun.from_dict(JSON.parse_string(file.get_as_text()))


## Local ids mint from the clock; a same-millisecond second save walks a
## suffix rather than overwriting the ghost that beat it to the name.
func _next_local_id() -> String:
	var base := "%s%d" % [LOCAL_PREFIX, int(Time.get_unix_time_from_system() * 1000.0)]
	if not FileAccess.file_exists(_path_for(base)):
		return base
	var suffix := 2
	while FileAccess.file_exists(_path_for("%s_%d" % [base, suffix])):
		suffix += 1
	return "%s_%d" % [base, suffix]


func _path_for(id: String) -> String:
	return "%s/%s.json" % [GHOST_DIR, id]


## An id names exactly one file inside GHOST_DIR — never a path.
static func _id_safe(id: String) -> bool:
	return not id.is_empty() and id.find("/") < 0 and id.find("\\") < 0 and id.find("..") < 0
