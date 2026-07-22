extends StudioTestCase
## The Deep's campaign loop rules stay deterministic and headless-testable.


func test_refining_preserves_unconverted_ore() -> void:
	var state: AshaDeepLoopState = AshaDeepLoopState.new()
	assert_true(state.mine(105))
	assert_eq(state.refine(), 10)
	assert_eq(state.raw_ore, 5)
	assert_eq(state.refined_alloy, 10)


func test_vehicle_requires_enough_alloy() -> void:
	var state: AshaDeepLoopState = AshaDeepLoopState.new()
	state.mine(90)
	state.refine()
	assert_false(state.build_vehicle())
	assert_eq(state.phase, AshaDeepLoopState.Phase.EXTRACTION)

	state.mine(10)
	state.refine()
	assert_true(state.build_vehicle())
	assert_eq(state.refined_alloy, 0)
	assert_eq(state.phase, AshaDeepLoopState.Phase.BATTLE_READY)


func test_outpost_capture_requires_active_battle() -> void:
	var state: AshaDeepLoopState = _state_with_vehicle()
	assert_false(state.capture_outpost())
	assert_true(state.begin_battle())
	assert_true(state.capture_outpost())
	assert_true(state.territory_captured)
	assert_eq(state.phase, AshaDeepLoopState.Phase.COMPLETE)


func test_completed_loop_rejects_more_extraction() -> void:
	var state: AshaDeepLoopState = _state_with_vehicle()
	state.begin_battle()
	state.capture_outpost()
	assert_false(state.mine(100))
	assert_eq(state.refine(), 0)


func _state_with_vehicle() -> AshaDeepLoopState:
	var state: AshaDeepLoopState = AshaDeepLoopState.new()
	state.mine(AshaDeepLoopState.REFINE_RATIO * AshaDeepLoopState.VEHICLE_COST)
	state.refine()
	state.build_vehicle()
	return state
