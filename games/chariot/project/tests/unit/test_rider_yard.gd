extends StudioTestCase
## The yard works only the active string. The server keeps sold and retired
## horses on the owner's list as records, so the view must never let one
## become the pick — entering it is the server's "no longer active" refusal.


func _stable_with(statuses: Array) -> RiderState:
	var state := RiderState.new()
	var horses: Array = []
	for i in statuses.size():
		horses.append({ "id": "h_%d" % i, "name": "Horse %d" % i, "status": str(statuses[i]) })
	state.apply("horses:update", { "horses": horses })
	return state


func test_active_horses_drops_sold_and_retired() -> void:
	var state := _stable_with(["sold", "active", "retired", "active"])
	var active := state.active_horses()
	assert_eq(active.size(), 2, "only the active two work the yard")
	assert_eq(str((active[0] as Dictionary).get("id")), "h_1")
	assert_eq(str((active[1] as Dictionary).get("id")), "h_3")
	assert_eq(state.my_horses.size(), 4, "the raw list keeps the records")


func test_pick_active_keeps_a_still_active_pick() -> void:
	var state := _stable_with(["active", "active"])
	assert_eq(state.pick_active("h_1"), "h_1", "a live pick stands")


func test_pick_active_re_deals_a_sold_pick() -> void:
	var state := _stable_with(["sold", "active"])
	assert_eq(state.pick_active("h_0"), "h_1",
		"the sold horse can no longer be the pick — the first active is dealt")


func test_pick_active_is_empty_when_no_runner_stands() -> void:
	var state := _stable_with(["sold", "retired"])
	assert_eq(state.pick_active("h_0"), "", "no active horse, no pick")
	var empty := RiderState.new()
	assert_eq(empty.pick_active(""), "", "an empty stable picks nothing")
