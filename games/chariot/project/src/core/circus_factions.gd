class_name CircusFactions
extends RefCounted

## The four circus factions as pure data: every race accrues to one of them.
## Byzantine model — Veneta (Blues), Prasina (Greens), Russata (Reds), Albata
## (Whites). The identity colors are the LIVERY silks (broadcast_view's
## fallbacks and the exhibition field already lead with these), not the crowd
## director's deliberately muted vegetable dyes. Engine-independent: no nodes,
## no rendering, so the whole module is headless-testable.

const FACTIONS: Array[Dictionary] = [
	{ "id": "blue", "name": "Blues", "latin": "Veneta", "color": "285a9e" },
	{ "id": "green", "name": "Greens", "latin": "Prasina", "color": "2f7e43" },
	{ "id": "red", "name": "Reds", "latin": "Russata", "color": "c92b28" },
	{ "id": "white", "name": "Whites", "latin": "Albata", "color": "e8e2d3" },
]

## The circus points table: first four home score, the rest of the field does
## not. Mirrors server/src/factions.rs — change both or change neither.
const POINTS_BY_PLACE: Array[int] = [9, 6, 4, 2]

## Fallback silks when the wire sends no color: the four factions first, then
## the wider stable palette (what broadcast_view painted before factions had
## names). RaceState assigns these to colorless entries in gate order, so the
## tally and the tint always resolve the SAME color for the same horse.
const SILK_FALLBACKS: Array[String] = [
	"285a9e", "2f7e43", "c92b28", "e8e2d3", "e8ba32",
	"843c8b", "e77323", "212124", "35a39c", "af4d7b",
]


static func fallback_livery(index: int) -> Color:
	return Color(SILK_FALLBACKS[index % SILK_FALLBACKS.size()])


## The color an entry actually wears: its wire silk when that parses, the
## fallback palette otherwise. Entries with no valid silk are MUTATED to carry
## the assigned fallback, so every later lookup (tint, tally) sees one truth.
## from_string — not html_is_valid — is the parser, because the wire sends
## named colors ("crimson") as well as hex, and named colors are silk.
static func effective_silk(entry: Dictionary, index: int) -> Color:
	var parsed := _parse_silk(str(entry.get("silk", "")))
	if parsed != INVALID_SILK:
		return parsed
	var fallback := fallback_livery(index)
	entry["silk"] = "#" + SILK_FALLBACKS[index % SILK_FALLBACKS.size()]
	return fallback


## An out-of-range color no real silk can parse to: from_string returns it
## verbatim only when the string is neither hex nor a known color name.
const INVALID_SILK := Color(-1.0, -1.0, -1.0)


static func _parse_silk(silk: String) -> Color:
	if silk.is_empty():
		return INVALID_SILK
	return Color.from_string(silk, INVALID_SILK)


static func ids() -> Array[String]:
	var out: Array[String] = []
	for faction in FACTIONS:
		out.append(str(faction.get("id", "")))
	return out


static func is_valid_id(faction_id: String) -> bool:
	return faction_id in ids()


static func name_for(faction_id: String) -> String:
	for faction in FACTIONS:
		if str(faction.get("id")) == faction_id:
			return str(faction.get("name", ""))
	return ""


static func color_for(faction_id: String) -> Color:
	for faction in FACTIONS:
		if str(faction.get("id")) == faction_id:
			return Color(str(faction.get("color", "ffffff")))
	return Color.TRANSPARENT


static func color_hex_for(faction_id: String) -> String:
	for faction in FACTIONS:
		if str(faction.get("id")) == faction_id:
			return str(faction.get("color", ""))
	return ""


## A rider's faction membership is one dictionary, { "faction": id }. Anything
## that does not name a real faction is not a membership.
static func membership(faction_id: String) -> Dictionary:
	if not is_valid_id(faction_id):
		return {}
	return { "faction": faction_id }


static func is_valid_membership(candidate: Variant) -> bool:
	if typeof(candidate) != TYPE_DICTIONARY:
		return false
	return is_valid_id(str((candidate as Dictionary).get("faction", "")))


## Which faction a color belongs to, by nearest RGB distance. Server silks are
## stable colors, not faction kit; the tally needs a deterministic answer for
## whatever hex the wire carried, so "closest faction color" is the rule.
static func nearest_to_color(color: Color) -> String:
	var best := ""
	var best_distance := INF
	for faction in FACTIONS:
		var faction_color := Color(str(faction.get("color", "ffffff")))
		var distance := pow(color.r - faction_color.r, 2.0) \
			+ pow(color.g - faction_color.g, 2.0) \
			+ pow(color.b - faction_color.b, 2.0)
		if distance < best_distance:
			best_distance = distance
			best = str(faction.get("id", ""))
	return best


static func nearest_to_hex(hex: String) -> String:
	var parsed := _parse_silk(hex)
	if parsed == INVALID_SILK:
		return ""
	return nearest_to_color(parsed)


## A race entry's faction: the wire's explicit "faction" key wins (the racing
## server does not send one yet; the faction-first server will), otherwise the
## entry's silk resolves to its nearest faction. "" means unaffiliated.
static func entry_faction(entry: Dictionary) -> String:
	var explicit := str(entry.get("faction", ""))
	if is_valid_id(explicit):
		return explicit
	return nearest_to_hex(str(entry.get("silk", "")))


## A finisher's faction: explicit on the result first, then the result's own
## silk, then the parade entry it joins to (by horseId, then by horseName).
static func result_faction(result: Dictionary, entries_by_horse: Dictionary) -> String:
	var explicit := str(result.get("faction", ""))
	if is_valid_id(explicit):
		return explicit
	var from_silk := nearest_to_hex(str(result.get("silk", "")))
	if not from_silk.is_empty():
		return from_silk
	var entry := _entry_for_result(result, entries_by_horse)
	if entry.is_empty():
		return ""
	return entry_faction(entry)


static func _entry_for_result(result: Dictionary, entries_by_horse: Dictionary) -> Dictionary:
	var horse_id := str(result.get("horseId", ""))
	if not horse_id.is_empty() and entries_by_horse.has(horse_id):
		var by_id: Variant = entries_by_horse[horse_id]
		if typeof(by_id) == TYPE_DICTIONARY:
			return by_id
	var horse_name := str(result.get("horseName", ""))
	if horse_name.is_empty():
		return {}
	for entry: Variant in entries_by_horse.values():
		if typeof(entry) == TYPE_DICTIONARY and str((entry as Dictionary).get("horseName", "")) == horse_name:
			return entry
	return {}


static func points_for_place(place: int) -> int:
	if place < 1 or place > POINTS_BY_PLACE.size():
		return 0
	return POINTS_BY_PLACE[place - 1]


## Fold one race's faction-tagged finishers into points per faction. Input
## rows carry "faction" and "pos"; unknown factions and unscored places add
## nothing, and all four factions always appear (zero is a real standing).
static func tally(tagged_results: Array) -> Dictionary:
	var points: Dictionary = {}
	for faction_id in ids():
		points[faction_id] = 0
	for result in tagged_results:
		if typeof(result) != TYPE_DICTIONARY:
			continue
		var faction_id := str((result as Dictionary).get("faction", ""))
		if not is_valid_id(faction_id):
			continue
		points[faction_id] = int(points[faction_id]) + points_for_place(int((result as Dictionary).get("pos", 0)))
	return points


## Faction ids ordered for display: highest tally first, faction order
## breaking ties.
static func ordered_ids(points: Dictionary) -> Array[String]:
	var ordered := ids()
	ordered.sort_custom(func(a: String, b: String) -> bool:
		return int(points.get(a, 0)) > int(points.get(b, 0)))
	return ordered


## One line for the tabula or the laurel board: "Blues 9 · Greens 6 · ...",
## highest tally first, faction order breaking ties.
static func tally_line(points: Dictionary) -> String:
	var pieces: Array[String] = []
	for faction_id in ordered_ids(points):
		pieces.append("%s %d" % [name_for(faction_id), int(points.get(faction_id, 0))])
	return "  ·  ".join(pieces)
