class_name StudioUiScale
extends RefCounted
## Content-scale arithmetic for phone-sized windows.
##
## Under `canvas_items` stretch with `expand` aspect, a 1280x720 design canvas
## on a 390x844 portrait window renders at scale 390/1280 = 0.30 — the whole
## HUD at 30%, with ~10 px tap targets. Measured, twice: the QA gate flagged
## "Take the reins" at 10.36 physical pixels, and the platosplaza edition of
## the same game shipped that way until its capture tool caught it.
##
## The fix is Window.content_scale_factor. The right factor balances two
## pulls: UI should render near its authored pixel size (readable, tappable),
## but scaling up shrinks the visible design area, and the widest HUD block
## still has to fit. content_scale_for() maximises UI scale subject to a
## game-declared minimum visible area, and never scales desktop DOWN.
##
## Games apply it from their root view:
##   window.content_scale_factor = StudioUiScale.content_scale_for(
##       window.size, design, MIN_VISIBLE)
## and re-apply on Window.size_changed.


## The content_scale_factor that renders UI as close to authored size as the
## window allows while keeping at least `min_visible` design units on screen.
##
##   window       physical window size in pixels
##   design       the authored canvas (project's viewport width/height)
##   min_visible  the smallest design-unit area the HUD must fit in — the
##                width of the widest must-fit block, and the height of the
##                tallest
static func content_scale_for(window: Vector2i, design: Vector2, min_visible: Vector2) -> float:
	if window.x <= 0 or window.y <= 0 or design.x <= 0.0 or design.y <= 0.0:
		return 1.0
	if min_visible.x <= 0.0 or min_visible.y <= 0.0:
		return 1.0
	# expand-aspect scale: the tighter axis sets it, the other axis grows.
	var base := minf(float(window.x) / design.x, float(window.y) / design.y)
	if base <= 0.0:
		return 1.0
	# The largest total scale that still shows min_visible design units.
	var fit_cap := minf(float(window.x) / min_visible.x, float(window.y) / min_visible.y)
	# Authored size (total scale 1.0) is the target; past it UI just gets big.
	var target := minf(1.0, fit_cap)
	# Never below 1.0: desktop layouts stay exactly as authored.
	return maxf(1.0, target / base)
