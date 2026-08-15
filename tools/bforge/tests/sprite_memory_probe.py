"""Isolated Blender peak-RSS probe for the accepted sprite-sheet boundary."""

from __future__ import annotations

import json
import resource
import sys
from pathlib import Path

import bpy

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
sys.path.insert(0, str(RUNTIME))

from lib import post, sprite_budget  # noqa: E402

MARKER = "BFORGE_MEMORY "


def peak_rss_kib() -> int:
    """Linux reports ru_maxrss in KiB; the invoking regression is Linux-only."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


output = Path(sys.argv[sys.argv.index("--") + 1])
output.parent.mkdir(parents=True, exist_ok=True)
plan = sprite_budget.plan_sprite_request(
    size=512,
    supersample=2,
    views=16,
    samples=96,
)
baseline_kib = peak_rss_kib()
numpy = post.require_numpy()
frame_px = plan["frame_px"]
sheet_width, sheet_height = plan["budget"]["sheet_px"]
sheet = numpy.zeros((sheet_height, sheet_width, 4), dtype=numpy.float32)

# Sixteen separated opaque subjects exercise alpha unpremultiplication, eight
# dilation passes, distant hidden-RGB fallback, and the full Blender PNG path.
for index in range(plan["views"]):
    row, column = divmod(index, plan["cols"])
    top = row * frame_px + 96
    left = column * frame_px + 128
    sheet[top : top + 320, left : left + 256, 0] = 0.72
    sheet[top : top + 320, left : left + 256, 1] = 0.18
    sheet[top : top + 320, left : left + 256, 2] = 0.08
    sheet[top : top + 320, left : left + 256, 3] = 1.0

allocated_kib = peak_rss_kib()
post.save(sheet, output, premultiplied=True)
peak_kib = peak_rss_kib()
budget = plan["budget"]
print(
    MARKER
    + json.dumps(
        {
            "blender_version": list(bpy.app.version),
            "sheet_px": budget["sheet_px"],
            "baseline_kib": baseline_kib,
            "allocated_kib": allocated_kib,
            "peak_kib": peak_kib,
            "delta_bytes": (peak_kib - baseline_kib) * 1024,
            "save_buffer_bytes": budget["save_buffer_bytes"],
            "working_set_bytes": budget["working_set_bytes"],
            "max_working_set_bytes": budget["max_working_set_bytes"],
            "output_bytes": output.stat().st_size,
        },
        sort_keys=True,
    ),
    flush=True,
)
