#!/usr/bin/env python3
"""Audit measured screen-space HUD rectangles from any game runtime."""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path


def _rect(raw: dict) -> dict:
    rect = {key: float(raw[key]) for key in ("x", "y", "width", "height")}
    rect["id"] = str(raw.get("id", "unnamed"))
    rect["edge"] = str(raw.get("edge", ""))
    rect["right"] = rect["x"] + rect["width"]
    rect["bottom"] = rect["y"] + rect["height"]
    return rect


def audit_hud(payload: dict, max_bottom_share: float = 0.34, min_control: float = 44) -> dict:
    viewport = payload["viewport"]
    width = float(viewport["width"])
    height = float(viewport["height"])
    regions = [_rect(raw) for raw in payload.get("regions", [])]
    controls = [_rect(raw) for raw in payload.get("controls", [])]
    findings: list[dict] = []

    for rect in [*regions, *controls]:
        if rect["x"] < 0 or rect["y"] < 0 or rect["right"] > width or rect["bottom"] > height:
            findings.append({"kind": "out_of_bounds", "id": rect["id"]})

    for left, right in combinations(regions, 2):
        overlap_x = min(left["right"], right["right"]) - max(left["x"], right["x"])
        overlap_y = min(left["bottom"], right["bottom"]) - max(left["y"], right["y"])
        if overlap_x > 0 and overlap_y > 0:
            findings.append(
                {
                    "kind": "panel_overlap",
                    "ids": [left["id"], right["id"]],
                    "pixels": round(overlap_x * overlap_y, 2),
                }
            )

    bottom = [rect for rect in regions if rect["edge"] == "bottom"]
    bottom_top = min((rect["y"] for rect in bottom), default=height)
    bottom_share = max(0.0, min(1.0, (height - bottom_top) / height))
    if bottom_share > max_bottom_share:
        findings.append(
            {
                "kind": "bottom_band_too_tall",
                "actual": round(bottom_share, 4),
                "maximum": max_bottom_share,
            }
        )

    for control in controls:
        if control["width"] < min_control or control["height"] < min_control:
            findings.append(
                {
                    "kind": "control_too_small",
                    "id": control["id"],
                    "size": [control["width"], control["height"]],
                    "minimum": min_control,
                }
            )

    return {
        "ok": not findings,
        "viewport": {"width": width, "height": height},
        "metrics": {
            "bottom_band_share": round(bottom_share, 4),
            "battlefield_height": round(bottom_top, 2),
            "region_count": len(regions),
            "control_count": len(controls),
        },
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="HUD measurement JSON path, or - for stdin")
    parser.add_argument("--max-bottom-share", type=float, default=0.34)
    parser.add_argument("--min-control", type=float, default=44)
    args = parser.parse_args()
    if args.input == "-":
        payload = json.load(sys.stdin)
    else:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = audit_hud(payload, args.max_bottom_share, args.min_control)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
