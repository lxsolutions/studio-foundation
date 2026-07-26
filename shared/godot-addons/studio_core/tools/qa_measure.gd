class_name StudioQaMeasure
extends RefCounted
## Pure measurement half of the visual QA gate (see qa_capture.gd).
##
## Everything here takes an Image or plain Rect2s and returns findings, with no
## renderer, viewport or scene access — so the arithmetic that decides whether
## a build FAILS is unit-testable headlessly, and the capture runner stays a
## thin shell around it.
##
## Why measure at all: a capture nobody measures is a screenshot nobody looks
## at. The numbers below exist because each caught a real shipped bug that eye
## review missed for weeks:
##   luma bounds     a "plausible-looking" filmic grade shipped at mean luma
##                   254 — a white screen with UI on it.
##   saturation min  the same grade measured 0.035 saturation: gray wash.
##   probes          ore rendered ALL WHITE (emission clipping) at a spot the
##                   palette said should be orange.
##   hud checks      a rider HUD re-anchored blind put the running order off
##                   the bottom of the screen in BOTH views, and phone tap
##                   targets rendered at ~15 px.

## Below this, a touch control is not reliably hittable. Apple's HIG says
## 44 pt; Android says 48 dp; we take the smaller as the floor.
const DEFAULT_MIN_TAP_PX := 44.0


## Mean Rec.709 luma of the frame, 0..255. `stride` subsamples the walk —
## every 3rd pixel on both axes reads ~1/9th of the frame, which moves the
## mean by well under one luma step on any real capture but keeps a
## 1280x720 measurement in tens of milliseconds.
static func luma_mean(image: Image, stride: int = 3) -> float:
	var totals := _walk(image, stride)
	return 0.0 if totals["samples"] == 0 else float(totals["luma"]) / float(totals["samples"])


## Mean HSV saturation of the frame, 0..1.
static func saturation_mean(image: Image, stride: int = 3) -> float:
	var totals := _walk(image, stride)
	return 0.0 if totals["samples"] == 0 else float(totals["saturation"]) / float(totals["samples"])


static func _walk(image: Image, stride: int) -> Dictionary:
	var totals := {"samples": 0, "luma": 0.0, "saturation": 0.0}
	if image == null or image.get_width() == 0 or image.get_height() == 0:
		return totals
	var step := maxi(1, stride)
	for y in range(0, image.get_height(), step):
		for x in range(0, image.get_width(), step):
			var color := image.get_pixel(x, y)
			totals["luma"] += luma_of(color) * 255.0
			totals["saturation"] += color.s
			totals["samples"] = int(totals["samples"]) + 1
	return totals


static func luma_of(color: Color) -> float:
	return 0.2126 * color.r + 0.7152 * color.g + 0.0722 * color.b


## Average color in a (2*radius+1)^2 box around fractional frame coordinates
## (0..1 on both axes). Box-averaged rather than a single pixel so a probe is
## not defeated by one antialiased edge or one bright crowd sprite.
static func probe_color(image: Image, at: Vector2, radius: int = 2) -> Color:
	if image == null or image.get_width() == 0 or image.get_height() == 0:
		return Color.BLACK
	var cx := clampi(int(at.x * image.get_width()), 0, image.get_width() - 1)
	var cy := clampi(int(at.y * image.get_height()), 0, image.get_height() - 1)
	var sum := Vector3.ZERO
	var count := 0
	for y in range(maxi(0, cy - radius), mini(image.get_height(), cy + radius + 1)):
		for x in range(maxi(0, cx - radius), mini(image.get_width(), cx + radius + 1)):
			var color := image.get_pixel(x, y)
			sum += Vector3(color.r, color.g, color.b)
			count += 1
	if count == 0:
		return Color.BLACK
	return Color(sum.x / count, sum.y / count, sum.z / count)


## Largest per-channel difference between two colors, in 0..255 steps.
static func channel_delta_255(a: Color, b: Color) -> float:
	return 255.0 * maxf(absf(a.r - b.r), maxf(absf(a.g - b.g), absf(a.b - b.b)))


## Frame-level checks. `spec` keys (all optional — absent means unchecked):
##   luma_min / luma_max    mean-luma bounds, 0..255
##   sat_min / sat_max      mean-saturation bounds, 0..1
##   probes: [ { at: [x, y] fractions, expect: [r, g, b] 0..255,
##               tol: per-channel steps (default 40), label: String } ]
## Returns findings shaped like the budget gate's: check/actual/bound/fix.
static func check_frame(image: Image, spec: Dictionary) -> Array[Dictionary]:
	var findings: Array[Dictionary] = []
	if spec.is_empty():
		return findings
	var luma := luma_mean(image)
	var saturation := saturation_mean(image)
	if spec.has("luma_min") and luma < float(spec["luma_min"]):
		findings.append(_finding("luma_low", luma, float(spec["luma_min"]),
			"Frame is darker than declared. Lighting rig lost, camera buried, or scene failed to build."))
	if spec.has("luma_max") and luma > float(spec["luma_max"]):
		findings.append(_finding("luma_high", luma, float(spec["luma_max"]),
			"Frame is brighter than declared. Check exposure/tonemap — a 254-luma frame is a white screen."))
	if spec.has("sat_min") and saturation < float(spec["sat_min"]):
		findings.append(_finding("saturation_low", saturation, float(spec["sat_min"]),
			"Gray wash. A grade or fog is eating the palette."))
	if spec.has("sat_max") and saturation > float(spec["sat_max"]):
		findings.append(_finding("saturation_high", saturation, float(spec["sat_max"]),
			"Oversaturated versus declared intent."))
	for probe in spec.get("probes", []) as Array:
		var probe_dict: Dictionary = probe
		var at_raw: Array = probe_dict.get("at", [0.5, 0.5])
		var at := Vector2(float(at_raw[0]), float(at_raw[1]))
		var expect_raw: Array = probe_dict.get("expect", [0, 0, 0])
		var expect := Color(
			float(expect_raw[0]) / 255.0, float(expect_raw[1]) / 255.0, float(expect_raw[2]) / 255.0)
		var tol := float(probe_dict.get("tol", 40.0))
		var actual := probe_color(image, at)
		var delta := channel_delta_255(actual, expect)
		if delta > tol:
			var finding := _finding("probe", delta, tol,
				"Color at (%.2f, %.2f) is [%d, %d, %d], expected [%d, %d, %d]." % [
					at.x, at.y,
					roundi(actual.r * 255.0), roundi(actual.g * 255.0), roundi(actual.b * 255.0),
					roundi(expect.r * 255.0), roundi(expect.g * 255.0), roundi(expect.b * 255.0),
				])
			finding["label"] = str(probe_dict.get("label", "probe"))
			findings.append(finding)
	return findings


## HUD-level checks against plain data, no Control access.
## `controls`: [ { name: String, rect: Rect2 (canvas units, global),
##                 tap: bool } ]  — the runner collects these from the
## qa_hud / qa_tap groups and passes only nodes visible in tree.
## `spec` keys:
##   margin       tolerated canvas-unit overhang before "offscreen" (default 0)
##   min_tap_px   physical-pixel floor for tap targets (default 44)
##   px_per_unit  physical pixels per canvas unit (default 1; the runner
##                derives it from window size / visible rect so phone-scale
##                content is judged at the size a thumb actually meets)
static func check_controls(controls: Array, viewport: Rect2, spec: Dictionary = {}) -> Array[Dictionary]:
	var findings: Array[Dictionary] = []
	var margin := float(spec.get("margin", 0.0))
	var min_tap := float(spec.get("min_tap_px", DEFAULT_MIN_TAP_PX))
	var px_per_unit := float(spec.get("px_per_unit", 1.0))
	var allowed := viewport.grow(margin)
	for entry in controls:
		var control: Dictionary = entry
		var name := str(control.get("name", "?"))
		var rect: Rect2 = control.get("rect", Rect2())
		if rect.size.x <= 0.0 or rect.size.y <= 0.0:
			var empty := _finding("hud_empty", 0.0, 1.0,
				"'%s' is visible but has no size — layout collapsed." % name)
			empty["label"] = name
			findings.append(empty)
			continue
		if not allowed.encloses(rect):
			var overhang := _overhang(rect, allowed)
			var off := _finding("hud_offscreen", overhang, margin,
				"'%s' sticks %.0f units outside the viewport (rect %s vs %s)." % [
					name, overhang, rect, viewport])
			off["label"] = name
			findings.append(off)
		if bool(control.get("tap", false)):
			var physical := minf(rect.size.x, rect.size.y) * px_per_unit
			if physical < min_tap:
				var tap := _finding("tap_target_small", physical, min_tap,
					"'%s' renders at %.0f px on this device — under the %.0f px touch floor." % [
						name, physical, min_tap])
				tap["label"] = name
				findings.append(tap)
	return findings


## Pairwise collisions among sibling HUD blocks. The runner passes only
## top-level qa_hud controls (nested members legitimately sit inside their
## panels); two of THOSE overlapping is a layout bug — a title panel and a
## corner door colliding at phone width was the first catch. A small margin
## tolerates deliberate 1-2 unit kisses between stacked bars.
## `controls`: [ { name: String, rect: Rect2 } ]; spec: { overlap_margin }.
static func check_overlaps(controls: Array, spec: Dictionary = {}) -> Array[Dictionary]:
	var findings: Array[Dictionary] = []
	var allow := float(spec.get("overlap_margin", 4.0))
	for i in controls.size():
		for j in range(i + 1, controls.size()):
			var a: Dictionary = controls[i]
			var b: Dictionary = controls[j]
			var inter: Rect2 = (a["rect"] as Rect2).intersection(b["rect"] as Rect2)
			if inter.size.x > allow and inter.size.y > allow:
				var finding := _finding("hud_overlap", minf(inter.size.x, inter.size.y), allow,
					"'%s' and '%s' overlap by %.0fx%.0f units." % [
						str(a.get("name", "?")), str(b.get("name", "?")),
						inter.size.x, inter.size.y])
				finding["label"] = "%s+%s" % [str(a.get("name", "?")), str(b.get("name", "?"))]
				findings.append(finding)
	return findings


## How far `rect` pokes outside `bounds`, in canvas units (max over the four
## edges; 0 when enclosed).
static func _overhang(rect: Rect2, bounds: Rect2) -> float:
	var over := 0.0
	over = maxf(over, bounds.position.x - rect.position.x)
	over = maxf(over, bounds.position.y - rect.position.y)
	over = maxf(over, rect.end.x - bounds.end.x)
	over = maxf(over, rect.end.y - bounds.end.y)
	return maxf(over, 0.0)


static func _finding(check: String, actual: float, bound: float, fix: String) -> Dictionary:
	return {
		"check": check,
		"actual": snappedf(actual, 0.01),
		"bound": snappedf(bound, 0.01),
		"fix": fix,
	}
