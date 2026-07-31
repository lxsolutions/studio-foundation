# HUD layout QA

tools/screenshots/hud_layout.py turns runtime-measured screen rectangles into
an engine-neutral layout gate. It catches the failure class where every widget
is individually valid but the combined HUD covers the game, overlaps another
panel, leaves the viewport, or shrinks an interactive control below a usable
size.

Capture the real rectangles from the running game, label persistent bottom
panels with "edge": "bottom", and pass the JSON on stdin:

    $json | python tools/screenshots/hud_layout.py -

The default contract allows the persistent bottom command band to consume at
most 34% of viewport height and requires interactive controls to be at least
44 by 44 pixels. Override those thresholds only for a documented platform
profile, not to grandfather an accidental overlay.

The report includes the remaining battlefield height and fails with exit code
1 when it finds any violation. Use this alongside a rendered screenshot: the
geometry gate proves space ownership, while the image proves visual hierarchy,
contrast, and whether the game still reads behind the HUD.
