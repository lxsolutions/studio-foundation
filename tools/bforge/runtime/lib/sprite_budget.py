"""Pure resource preflight for :mod:`render.sprite`.

This module deliberately imports neither ``bpy`` nor numpy.  The render op calls
it before looking up scene objects, allocating image arrays, creating Blender
datablocks, or starting Cycles, so an unsafe request fails cheaply.

The budget has two complementary caps:

* peak float-buffer storage accounts for three sheet-sized buffers (the numpy
  sheet, straight-alpha save copy, and Blender image), two full-resolution
  render buffers, and sixteen output-frame equivalents for the linear post
  chain;
* pixel-work accounts for every Cycles sample at supersampled resolution,
  sixteen output-resolution post passes per view, and the final sheet.

The work ceiling is intentionally the exact cost of the documented largest
standard directional profile: 16 views at 512 px, 2x supersampling, and 96
samples.  Callers can trade any of those dimensions against the others.
"""

from __future__ import annotations

import math

MIN_FRAME_PX = 32
MAX_FRAME_PX = 2048
MAX_RENDER_PX = 4096
MIN_SUPERSAMPLE = 1
MAX_SUPERSAMPLE = 4
MIN_VIEWS = 1
MAX_VIEWS = 64
MIN_SAMPLES = 8
MAX_SAMPLES = 256
MAX_SHEET_AXIS_PX = 8192

RGBA_FLOAT_BYTES = 4 * 4
SHEET_BUFFER_EQUIVALENTS = 3
RENDER_BUFFER_EQUIVALENTS = 2
POST_BUFFER_EQUIVALENTS = 16
POST_WORK_EQUIVALENTS = 16
MAX_WORKING_SET_BYTES = 512 * 1024 * 1024

# 16 * (1024^2 * 96 + 512^2 * 16) + 2048^2
MAX_PIXEL_WORK = 1_681_915_904


class SpriteBudgetError(ValueError):
    """The effective sprite request exceeds a preflight resource cap."""


def plan_sprite_request(size: int, supersample: int, views: int, samples: int) -> dict:
    """Clamp controls, calculate the complete resource plan, and enforce it.

    The returned dictionary is JSON-serialisable and is embedded in operation
    results/sidecars so a caller can see the effective cost it asked for.
    """

    frame_px = max(MIN_FRAME_PX, min(MAX_FRAME_PX, int(size)))
    effective_supersample = max(
        MIN_SUPERSAMPLE,
        min(MAX_SUPERSAMPLE, int(supersample), MAX_RENDER_PX // frame_px),
    )
    effective_views = max(MIN_VIEWS, min(MAX_VIEWS, int(views)))
    effective_samples = max(MIN_SAMPLES, min(MAX_SAMPLES, int(samples)))

    render_px = frame_px * effective_supersample
    cols = math.isqrt(effective_views)
    if cols * cols < effective_views:
        cols += 1
    rows = (effective_views + cols - 1) // cols
    sheet_width_px = cols * frame_px
    sheet_height_px = rows * frame_px

    frame_pixels = frame_px * frame_px
    render_frame_pixels = render_px * render_px
    sheet_pixels = sheet_width_px * sheet_height_px
    rendered_pixels = effective_views * render_frame_pixels
    sample_pixel_work = rendered_pixels * effective_samples
    post_pixel_work = effective_views * frame_pixels * POST_WORK_EQUIVALENTS
    pixel_work = sample_pixel_work + post_pixel_work + sheet_pixels

    working_pixel_slots = (
        sheet_pixels * SHEET_BUFFER_EQUIVALENTS
        + render_frame_pixels * RENDER_BUFFER_EQUIVALENTS
        + frame_pixels * POST_BUFFER_EQUIVALENTS
    )
    working_set_bytes = working_pixel_slots * RGBA_FLOAT_BYTES

    budget = {
        "sheet_px": [sheet_width_px, sheet_height_px],
        "sheet_pixels": sheet_pixels,
        "rendered_pixels": rendered_pixels,
        "sample_pixel_work": sample_pixel_work,
        "post_pixel_work": post_pixel_work,
        "pixel_work": pixel_work,
        "max_pixel_work": MAX_PIXEL_WORK,
        "working_set_bytes": working_set_bytes,
        "max_working_set_bytes": MAX_WORKING_SET_BYTES,
        "max_sheet_axis_px": MAX_SHEET_AXIS_PX,
    }

    reasons = []
    if sheet_width_px > MAX_SHEET_AXIS_PX or sheet_height_px > MAX_SHEET_AXIS_PX:
        reasons.append(
            f"sheet {sheet_width_px}x{sheet_height_px} exceeds "
            f"{MAX_SHEET_AXIS_PX}px per axis"
        )
    if working_set_bytes > MAX_WORKING_SET_BYTES:
        reasons.append(
            f"estimated float buffers {working_set_bytes / (1024 * 1024):.1f} MiB exceed "
            f"{MAX_WORKING_SET_BYTES // (1024 * 1024)} MiB"
        )
    if pixel_work > MAX_PIXEL_WORK:
        reasons.append(
            f"aggregate work {pixel_work:,} exceeds {MAX_PIXEL_WORK:,} pixel-work units"
        )
    if reasons:
        raise SpriteBudgetError(
            "render.sprite resource budget rejected the effective request before Blender "
            f"allocation/render ({'; '.join(reasons)}; frame={frame_px}px, "
            f"render={render_px}px, views={effective_views}, supersample="
            f"{effective_supersample}x, samples={effective_samples}). Reduce size, views, "
            "supersample, or samples."
        )

    return {
        "frame_px": frame_px,
        "render_px": render_px,
        "supersample": effective_supersample,
        "views": effective_views,
        "samples": effective_samples,
        "cols": cols,
        "rows": rows,
        "budget": budget,
    }
