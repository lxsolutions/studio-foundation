class_name AshaDeepLoopState
extends RefCounted
## Renderer- and transport-independent rules for The Deep vertical-slice loop.

const REFINE_RATIO: int = 10
const VEHICLE_COST: int = 10

enum Phase {
	EXTRACTION,
	BATTLE_READY,
	BATTLE_ACTIVE,
	COMPLETE,
}

var phase: Phase = Phase.EXTRACTION
var raw_ore: int = 0
var refined_alloy: int = 0
var has_vehicle: bool = false
var territory_captured: bool = false


func can_mine() -> bool:
	return phase == Phase.EXTRACTION


func mine(units: int) -> bool:
	if not can_mine() or units <= 0:
		return false
	raw_ore += units
	return true


func can_refine() -> bool:
	return phase == Phase.EXTRACTION and raw_ore >= REFINE_RATIO


func refine() -> int:
	if not can_refine():
		return 0
	var produced: int = raw_ore / REFINE_RATIO
	raw_ore -= produced * REFINE_RATIO
	refined_alloy += produced
	return produced


func can_build_vehicle() -> bool:
	return phase == Phase.EXTRACTION and not has_vehicle and refined_alloy >= VEHICLE_COST


func build_vehicle() -> bool:
	if not can_build_vehicle():
		return false
	refined_alloy -= VEHICLE_COST
	has_vehicle = true
	phase = Phase.BATTLE_READY
	return true


func can_begin_battle() -> bool:
	return phase == Phase.BATTLE_READY


func begin_battle() -> bool:
	if not can_begin_battle():
		return false
	phase = Phase.BATTLE_ACTIVE
	return true


func can_capture_outpost() -> bool:
	return phase == Phase.BATTLE_ACTIVE


func capture_outpost() -> bool:
	if not can_capture_outpost():
		return false
	territory_captured = true
	phase = Phase.COMPLETE
	return true


func phase_label() -> String:
	match phase:
		Phase.EXTRACTION:
			return "extraction"
		Phase.BATTLE_READY:
			return "battle ready"
		Phase.BATTLE_ACTIVE:
			return "battle active"
		Phase.COMPLETE:
			return "loop complete"
	return "unknown"
