"""Build one of everything and render a review sheet per asset.

    python tools/bforge/tests/gallery.py [--only prop.crate] [--tile 300]

Not a unit test — this is the visual regression pass a human (or an agent with
vision) looks at to judge whether the recipes actually produce good assets.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge, ForgeError  # noqa: E402

CASES = [
    ("prop.crate", {"name": "crate", "size": [0.9, 0.9, 0.9], "seed": 3}),
    ("prop.barrel", {"name": "barrel", "height": 1.0, "seed": 5}),
    ("prop.chest", {"name": "chest", "separate_lid": False, "seed": 11}),
    ("prop.sack", {"name": "sack", "seed": 2}),
    ("prop.relic", {"name": "relic", "form": "medallion", "motif": "rosette", "size": 0.42, "seed": 37}),
    ("prop.rock", {"name": "rock", "detail": 2, "seed": 9}),
    ("prop.crystal", {"name": "crystal", "count": 6, "seed": 4}),
    ("prop.tree", {"name": "tree", "canopy_style": "layered", "seed": 8}),
    ("prop.pillar", {"name": "pillar", "flutes": 18, "seed": 1}),
    ("prop.torch", {"name": "torch", "style": "brazier", "seed": 6}),
    ("prop.fence", {"name": "fence", "style": "picket", "length": 4.0, "seed": 12}),
    ("prop.furniture", {"name": "table", "kind": "table", "seed": 13}),
    ("prop.weapon", {"name": "sword", "kind": "sword", "seed": 14}),
    ("prop.banner", {"name": "banner", "seed": 15}),
    (
        "prop.ancient_ship",
        {"name": "raider_galley", "style": "raider", "length": 9.2, "beam": 2.65,
         "height": 4.35, "hull_color": "#171313", "wood_color": "#3a2921",
         "metal_color": "#5b4637", "cloth_color": "#48171a"},
    ),
    ("prop.debris", {"name": "debris", "count": 10, "seed": 16}),
    ("kit.room", {"name": "room", "size": [2, 2], "roof": False, "seed": 17}),
    (
        "env.terrain",
        {"name": "terrain", "size": [30, 30], "resolution": 40, "style": "hills", "seed": 18},
    ),
    ("env.cliff", {"name": "cliff", "length": 14, "height": 7, "seed": 19}),
    ("env.arena", {"name": "arena", "radius": 12, "seed": 20}),
    ("char.humanoid", {"name": "hero", "build": "heroic", "seed": 21}),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--tile", type=int, default=300)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--out", default="assets-generated/bforge/gallery")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.only or c[0] == args.only]
    forge = Forge(workdir=".", out_dir="assets-generated/bforge")
    rows = []
    try:
        forge.start()
        for op_name, params in cases:
            label = params.get("name") or op_name.split(".")[1]
            started = time.time()
            try:
                forge.call("session.reset")
                result = forge.call(op_name, _timeout=600, **params)
                build_ms = int((time.time() - started) * 1000)
                sheet = forge.call(
                    "render.contact_sheet",
                    out=f"gallery/{label}.png",
                    tile=args.tile,
                    samples=args.samples,
                    panels=["hero", "front", "wireframe", "checker"],
                    columns=4,
                    _timeout=900,
                )
                rows.append(
                    {
                        "op": op_name,
                        "label": label,
                        "triangles": result.get("triangles") or result.get("total_triangles"),
                        "materials": result.get("materials"),
                        "bounds": (result.get("bounds") or {}).get("size"),
                        "texel_density": result.get("texel_density_px_per_m"),
                        "build_ms": build_ms,
                        "sheet": sheet["rel"],
                        "notes": result.get("_notes", []),
                    }
                )
                print(
                    f"OK   {op_name:22} {label:10} "
                    f"tris={rows[-1]['triangles']:>7} "
                    f"size={_fmt(rows[-1]['bounds'])} {build_ms:>5}ms -> {sheet['rel']}"
                )
            except ForgeError as exc:
                rows.append({"op": op_name, "label": label, "error": str(exc)})
                print(f"FAIL {op_name:22} {label:10} {exc}")
    finally:
        forge.stop()

    report = Path(args.out).with_suffix(".json")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    failures = [r for r in rows if "error" in r]
    print(f"\n{len(rows) - len(failures)}/{len(rows)} ok; report -> {report}")
    return 1 if failures else 0


def _fmt(size):
    if not size:
        return "-"
    return "x".join(f"{v:.1f}" for v in size)


if __name__ == "__main__":
    sys.exit(main())
