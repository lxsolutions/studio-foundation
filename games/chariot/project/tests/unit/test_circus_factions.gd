extends StudioTestCase
## The four circus factions: identity data, membership validation, silk
## resolution, and the race points tally (mirrored by server/src/factions.rs).


func test_four_factions_with_unique_ids_and_colors() -> void:
	var ids := CircusFactions.ids()
	assert_eq(ids, ["blue", "green", "red", "white"], "the Byzantine four, in order")
	var seen_colors: Dictionary = {}
	for faction_id in ids:
		var hex := CircusFactions.color_hex_for(faction_id)
		assert_true(Color.html_is_valid(hex), "faction color must be a hex color: " + faction_id)
		assert_false(seen_colors.has(hex), "faction colors must be distinct: " + hex)
		seen_colors[hex] = true
		assert_false(CircusFactions.name_for(faction_id).is_empty(), "faction needs a name")


func test_membership_validation() -> void:
	assert_true(CircusFactions.is_valid_membership(CircusFactions.membership("green")))
	assert_eq(str(CircusFactions.membership("red").get("faction", "")), "red")
	assert_true(CircusFactions.membership("gold").is_empty(), "unknown factions do not join")
	assert_false(CircusFactions.is_valid_membership({}))
	assert_false(CircusFactions.is_valid_membership({ "faction": "purple" }))
	assert_false(CircusFactions.is_valid_membership("blue"), "a bare string is not a membership")


func test_nearest_color_resolves_faction_silks() -> void:
	assert_eq(CircusFactions.nearest_to_hex("285a9e"), "blue", "exact faction silk")
	assert_eq(CircusFactions.nearest_to_hex("#2f7e43"), "green", "hash-prefixed silk")
	assert_eq(CircusFactions.nearest_to_hex("d03a30"), "red", "a near red stays red")
	assert_eq(CircusFactions.nearest_to_hex("f2eee2"), "white", "a near white stays white")
	assert_eq(CircusFactions.nearest_to_hex("crimson"), "red", "the wire sends named colors too")
	assert_eq(CircusFactions.nearest_to_hex("azure"), "white",
		"nearest is geometric, not nominal: azure sits closer to white than to the faction's deep blue")
	assert_eq(CircusFactions.nearest_to_hex(""), "", "no silk, no faction")
	assert_eq(CircusFactions.nearest_to_hex("not-a-color"), "", "unparseable silk, no faction")


func test_effective_silk_keeps_wire_color_and_assigns_fallbacks() -> void:
	var wired := { "silk": "crimson" }
	assert_eq(CircusFactions.effective_silk(wired, 3), Color("dc143c"), "the wire's silk wins")
	assert_eq(str(wired.get("silk")), "crimson", "a real silk is never rewritten")
	var colorless := {}
	var assigned := CircusFactions.effective_silk(colorless, 1)
	assert_eq(assigned, CircusFactions.fallback_livery(1))
	assert_eq(CircusFactions.nearest_to_hex(str(colorless.get("silk", ""))), "green",
		"the assigned fallback is written back, and it resolves to a faction")
	var unknown_name := { "silk": "viridian" }
	CircusFactions.effective_silk(unknown_name, 4)
	assert_ne(str(unknown_name.get("silk")), "viridian",
		"names outside the parser fall back, exactly as the old tint path did")


func test_points_table() -> void:
	assert_eq(CircusFactions.points_for_place(1), 9)
	assert_eq(CircusFactions.points_for_place(2), 6)
	assert_eq(CircusFactions.points_for_place(3), 4)
	assert_eq(CircusFactions.points_for_place(4), 2)
	assert_eq(CircusFactions.points_for_place(5), 0, "fifth home scores nothing")
	assert_eq(CircusFactions.points_for_place(0), 0)


func test_tally_folds_one_race() -> void:
	var points: Dictionary = CircusFactions.tally([
		{ "faction": "blue", "pos": 1 },
		{ "faction": "green", "pos": 2 },
		{ "faction": "blue", "pos": 3 },
		{ "faction": "white", "pos": 5 },
		{ "faction": "gold", "pos": 1 },
		"garbage-row",
	])
	assert_eq(int(points.get("blue", -1)), 13, "first and third home")
	assert_eq(int(points.get("green", -1)), 6)
	assert_eq(int(points.get("red", -1)), 0, "all four factions always appear")
	assert_eq(int(points.get("white", -1)), 0, "unscored places add nothing")
	assert_eq(points.size(), 4)


func test_tally_line_orders_by_points() -> void:
	var line := CircusFactions.tally_line({ "blue": 13, "green": 6, "red": 9, "white": 0 })
	assert_eq(line, "Blues 13  ·  Reds 9  ·  Greens 6  ·  Whites 0")


func _race_with_results() -> Dictionary:
	return {
		"name": "The Consualia",
		"distance": 1800.0,
		"entries": [
			{ "horseId": "h1", "horseName": "Xanthos", "silk": "285a9e" },
			{ "horseId": "h2", "horseName": "Balios", "silk": "2f7e43" },
			{ "horseId": "h3", "horseName": "Aithon", "silk": "c92b28" },
		],
		"results": [
			{ "pos": 1, "horseName": "Balios", "timeMs": 83450 },
			{ "pos": 2, "horseId": "h1", "horseName": "Xanthos", "timeMs": 83600 },
			{ "pos": 3, "horseName": "Aithon", "timeMs": 84100 },
		],
	}


func test_race_state_tags_finishers_and_tallies() -> void:
	var state := RaceState.new()
	assert_true(state.apply("spectate:hello", { "phase": "finished", "race": _race_with_results() }))
	assert_eq(state.results.size(), 3)
	assert_eq(str(state.results[0].get("faction", "")), "green", "joins to the entry by horseName")
	assert_eq(str(state.results[1].get("faction", "")), "blue", "joins by horseId first")
	assert_eq(str(state.results[2].get("faction", "")), "red")
	assert_eq(int(state.faction_points.get("green", -1)), 9)
	assert_eq(int(state.faction_points.get("blue", -1)), 6)
	assert_eq(int(state.faction_points.get("red", -1)), 4)
	assert_eq(int(state.faction_points.get("white", -1)), 0)


func test_race_state_honours_explicit_wire_faction() -> void:
	var race := _race_with_results()
	(race["results"] as Array)[0]["faction"] = "white"
	var state := RaceState.new()
	state.apply("race:phase", { "status": "finished", "race": race })
	assert_eq(str(state.results[0].get("faction", "")), "white", "explicit key beats silk")
	assert_eq(int(state.faction_points.get("white", -1)), 9)


func test_race_state_resets_tally_between_races() -> void:
	var state := RaceState.new()
	state.apply("race:phase", { "status": "finished", "race": _race_with_results() })
	state.apply("race:phase", { "status": "parading", "race": { "name": "Next", "entries": [] } })
	assert_eq(state.results, [])
	assert_eq(state.faction_points, CircusFactions.tally([]), "a new card zeroes the tally")
