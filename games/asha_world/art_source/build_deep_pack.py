"""Generate The Deep's underground asset pack with bforge.

    python games/asha_world/art_source/build_deep_pack.py [--render] [--install]

The Deep is a Motherload-style digger: the player tunnels down through rock
looking for ore. Everything the shaft is dressed with has to read instantly at
small on-screen size and cost almost nothing, because there are hundreds of them
on screen and the game ships to browsers.

Writes .blend masters plus .meta.json sidecars into `assets-source/deep/`, so
the assets go through the existing ADR 0006 pipeline (`just asset-cook`) rather
than around it. bforge authors; the pipeline still validates, exports and cooks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "bforge"))

from bforge import Forge, ForgeError  # noqa: E402

GAME = REPO / "games" / "asha_world"
SOURCE = GAME / "assets-source" / "deep"

# Every asset: (id, ops to build it, triangle budget, category, what it is for).
PACK = [
    (
        "deep_ore_vein",
        900,
        "prop",
        "Rock with an embedded seam of ore — the thing the player is digging for",
        [
            (
                "prop.rock",
                {
                    "name": "deep_ore_vein",
                    "size": [1.2, 1.1, 1.0],
                    "detail": 2,
                    "roughness": 0.34,
                    "angular": True,
                    "material": "rock",
                    "color": "#4a4038",
                    "seed": 11,
                },
            ),
            # The seam is painted onto a band of the rock's own faces rather
            # than modelled as separate nuggets: it costs zero extra triangles,
            # it can never end up buried inside the rock, and an emissive band
            # reads as "valuable" even when the prop is 20 px tall on screen.
            (
                "material.face_assign",
                {
                    "object": "deep_ore_vein",
                    "preset": "emissive",
                    "select": "top_band",
                    "band_min": 0.30,
                    "band_max": 0.62,
                    "color": "#d8a13c",
                },
            ),
        ],
    ),
    (
        "deep_crystal_cluster",
        800,
        "prop",
        "Glowing crystal cluster — a light source and a landmark in a dark shaft",
        [
            (
                "prop.crystal",
                {
                    "name": "deep_crystal_cluster",
                    "count": 7,
                    "height": 1.15,
                    "radius": 0.15,
                    "sides": 6,
                    "spread": 34.0,
                    "color": "#57c8e8",
                    "emission": 2.4,
                    "seed": 21,
                },
            ),
        ],
    ),
    (
        "deep_stalactite",
        400,
        "prop",
        "Ceiling spike — hangs from tunnel roofs to break up flat ceilings",
        [
            (
                "build.lathe",
                {
                    "name": "deep_stalactite",
                    "profile": [
                        0.0,
                        0.0,
                        0.055,
                        0.05,
                        0.14,
                        0.55,
                        0.24,
                        1.35,
                        0.30,
                        1.75,
                        0.0,
                        1.8,
                    ],
                    "segments": 7,
                    "material": "rock",
                    "color": "#5a4f45",
                    "uv": "cylinder",
                    "origin": "bottom",
                    "smooth": False,
                },
            ),
            (
                "build.deform",
                {
                    "name": "deep_stalactite",
                    "mode": "jitter",
                    "amount": 0.022,
                    "seed": 31,
                },
            ),
        ],
    ),
    (
        "deep_support_frame",
        900,
        "architecture",
        "Timber pit prop — reads as 'someone dug here before you'",
        [
            (
                "build.box",
                {
                    "name": "deep_support_frame",
                    "size": [0.22, 0.22, 2.4],
                    "location": [-1.05, 0.0, 0.0],
                    "bevel": 0.02,
                    "material": "wood",
                    "color": "#5d4128",
                    "origin": "bottom",
                },
            ),
            (
                "build.box",
                {
                    "name": "post_r",
                    "size": [0.22, 0.22, 2.4],
                    "location": [1.05, 0.0, 0.0],
                    "bevel": 0.02,
                    "material": "wood",
                    "color": "#5d4128",
                    "origin": "bottom",
                },
            ),
            (
                "build.box",
                {
                    "name": "lintel",
                    "size": [2.5, 0.24, 0.26],
                    "location": [0.0, 0.0, 2.4],
                    "bevel": 0.02,
                    "material": "wood",
                    "color": "#5d4128",
                    "origin": "bottom",
                },
            ),
            (
                "build.box",
                {
                    "name": "brace_l",
                    "size": [0.62, 0.16, 0.16],
                    "location": [-0.72, 0.0, 2.1],
                    "bevel": 0.015,
                    "material": "wood",
                    "color": "#4a3320",
                    "origin": "center",
                },
            ),
            (
                "object.transform",
                {"name": "brace_l", "rotation": [0, 40, 0], "apply": True},
            ),
            (
                "build.box",
                {
                    "name": "brace_r",
                    "size": [0.62, 0.16, 0.16],
                    "location": [0.72, 0.0, 2.1],
                    "bevel": 0.015,
                    "material": "wood",
                    "color": "#4a3320",
                    "origin": "center",
                },
            ),
            (
                "object.transform",
                {"name": "brace_r", "rotation": [0, -40, 0], "apply": True},
            ),
            (
                "object.join",
                {
                    "names": [
                        "deep_support_frame",
                        "post_r",
                        "lintel",
                        "brace_l",
                        "brace_r",
                    ],
                    "into": "deep_support_frame",
                },
            ),
        ],
    ),
    (
        "deep_mine_cart",
        1200,
        "prop",
        "Ore cart — set dressing that says 'industry' and doubles as a container",
        [
            (
                "build.box",
                {
                    "name": "deep_mine_cart",
                    "size": [1.15, 0.78, 0.52],
                    "location": [0.0, 0.0, 0.34],
                    "bevel": 0.03,
                    "material": "iron",
                    "color": "#584d42",
                    "origin": "bottom",
                },
            ),
            (
                "build.extrude",
                {
                    "name": "deep_mine_cart",
                    "direction": "up",
                    "distance": -0.34,
                    "inset": 0.07,
                },
            ),
            (
                "build.box",
                {
                    "name": "chassis",
                    "size": [1.0, 0.62, 0.14],
                    "location": [0.0, 0.0, 0.2],
                    "bevel": 0.02,
                    "material": "iron",
                    "color": "#3b342c",
                    "origin": "center",
                },
            ),
            (
                "build.cylinder",
                {
                    "name": "wheel_a",
                    "radius": 0.19,
                    "depth": 0.09,
                    "segments": 10,
                    "location": [-0.34, 0.0, 0.19],
                    "material": "iron",
                    "color": "#2c2620",
                    "smooth": True,
                },
            ),
            (
                "object.transform",
                {"name": "wheel_a", "rotation": [90, 0, 0], "apply": True},
            ),
            (
                "build.array",
                {
                    "name": "wheel_a",
                    "counts": [1, 2],
                    "spacing": [0, 0.64, 0],
                    "join": True,
                },
            ),
            (
                "build.cylinder",
                {
                    "name": "wheel_b",
                    "radius": 0.19,
                    "depth": 0.09,
                    "segments": 10,
                    "location": [0.34, 0.0, 0.19],
                    "material": "iron",
                    "color": "#2c2620",
                    "smooth": True,
                },
            ),
            (
                "object.transform",
                {"name": "wheel_b", "rotation": [90, 0, 0], "apply": True},
            ),
            (
                "build.array",
                {
                    "name": "wheel_b",
                    "counts": [1, 2],
                    "spacing": [0, 0.64, 0],
                    "join": True,
                },
            ),
            (
                "object.join",
                {
                    "names": ["deep_mine_cart", "chassis", "wheel_a", "wheel_b"],
                    "into": "deep_mine_cart",
                },
            ),
        ],
    ),
    (
        "deep_lantern",
        500,
        "prop",
        "Hanging pit lantern — a warm point of light against cold rock",
        [
            (
                "prop.torch",
                {
                    "name": "deep_lantern",
                    "style": "standing",
                    "height": 0.62,
                    "flame_color": "#ffb347",
                    "emission": 11.0,
                    "material": "bronze",
                    "seed": 41,
                },
            ),
        ],
    ),
    (
        "deep_rubble",
        700,
        "prop",
        "Broken spoil left after a dig — fills empty floor cheaply",
        [
            (
                "prop.debris",
                {
                    "name": "deep_rubble",
                    "count": 11,
                    "radius": 1.1,
                    "piece_size": 0.19,
                    "kind": "stone",
                    "material": "rock",
                    "seed": 51,
                },
            ),
        ],
    ),
    (
        "deep_drill_head",
        1400,
        "prop",
        "The digger's drill — the player's own tool, seen every frame",
        [
            (
                "build.cylinder",
                {
                    "name": "deep_drill_head",
                    "radius": 0.34,
                    "radius_top": 0.0,
                    "depth": 0.86,
                    "segments": 10,
                    "material": "iron",
                    "color": "#8a8f96",
                    "origin": "bottom",
                    "smooth": False,
                },
            ),
            (
                "build.deform",
                {"name": "deep_drill_head", "mode": "taper", "amount": 0.92},
            ),
            (
                "build.cylinder",
                {
                    "name": "collar",
                    "radius": 0.40,
                    "depth": 0.22,
                    "segments": 10,
                    "location": [0.0, 0.0, -0.11],
                    "material": "bronze",
                    "smooth": True,
                },
            ),
            (
                "build.greeble",
                {
                    "name": "collar",
                    "seed": 61,
                    "density": 0.5,
                    "depth": 0.035,
                    "cuts": 1,
                },
            ),
            (
                "build.cylinder",
                {
                    "name": "shaft",
                    "radius": 0.16,
                    "depth": 0.46,
                    "segments": 8,
                    "location": [0.0, 0.0, -0.44],
                    "material": "iron",
                    "color": "#4a443c",
                    "smooth": True,
                },
            ),
            (
                "object.join",
                {
                    "names": ["deep_drill_head", "collar", "shaft"],
                    "into": "deep_drill_head",
                },
            ),
        ],
    ),
]


def meta_for(asset_id, category, budget, description):
    return {
        "asset_id": asset_id,
        "category": category,
        "license": "proprietary",
        "source": {"origin": "generated"},
        "creator": "studio-foundation (tools/bforge)",
        "provenance": {
            "method": "ai_generated",
            "commercial_use_allowed": True,
            "modified": False,
            "ai": {
                "system": "bforge (headless Blender, allowlisted ops, deterministic)",
                "tool": "bforge",
                "workflow": "games/asha_world/art_source/build_deep_pack.py",
                "description": description,
                "deterministic": True,
                "human_review": "pending",
            },
        },
        "games": "asha_world",
        "lod_policy": "auto",
        "collision_policy": "explicit",
        "texture_policy": "compressed",
        "animation_set": "none",
        "budgets": {"triangles": budget, "materials": 3, "texture_max_px": 1024},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Write .blend masters + sidecars into assets-source/deep",
    )
    parser.add_argument("--tile", type=int, default=300)
    parser.add_argument("--samples", type=int, default=18)
    args = parser.parse_args()

    forge = Forge(workdir=str(REPO), out_dir=str(REPO / "assets-generated" / "bforge"))
    rows = []
    failures = []
    try:
        forge.start()
        for asset_id, budget, category, description, steps in PACK:
            try:
                forge.call("session.reset")
                for op, params in steps:
                    forge.call(op, _timeout=600, **params)

                forge.call("material.consolidate", tolerance=0.02)
                forge.call("gameready.collision", name=asset_id, mode="convex")
                # to_origin matters: a single-asset master must have its root at
                # (0,0,0) or `just asset-validate` rejects it.
                forge.call(
                    "gameready.pivot",
                    objects=[asset_id],
                    origin="bottom",
                    to_origin=True,
                )

                check = forge.call(
                    "check.asset",
                    triangle_budget=budget,
                    material_budget=3,
                    require_collision=True,
                )
                critique = forge.call("check.critique")
                info = forge.call("object.inspect", name=asset_id)

                blend = forge.call("export.blend", out=f"deep/{asset_id}.blend")
                glb = forge.call(
                    "export.gltf",
                    out=f"deep/{asset_id}.glb",
                    engine="godot",
                    strict=False,
                    _timeout=600,
                )

                row = {
                    "asset": asset_id,
                    "triangles": info["triangles"],
                    "budget": budget,
                    "materials": info["materials"],
                    "valid": check["ok"],
                    "errors": critique["errors"],
                    "kb": glb["bytes"] // 1024,
                    "blend": blend["path"],
                }
                rows.append(row)
                status = (
                    "OK " if check["ok"] and info["triangles"] <= budget else "CHECK"
                )
                print(
                    f"{status} {asset_id:22} {info['triangles']:>6}/{budget} tris  "
                    f"{len(info['materials'])} mats  {row['kb']:>4} KB"
                )
                if not check["ok"]:
                    for failure in check["failures"][:3]:
                        print(
                            f"      [{failure['level']}] {failure['id']}: {failure['msg'][:88]}"
                        )
                    failures.append(asset_id)

                if args.render:
                    sheet = forge.call(
                        "render.contact_sheet",
                        out=f"deep/{asset_id}.png",
                        tile=args.tile,
                        samples=args.samples,
                        panels=["hero", "front", "wireframe", "checker"],
                        columns=4,
                        _timeout=1200,
                    )
                    row["sheet"] = sheet["rel"]

                if args.install:
                    SOURCE.mkdir(parents=True, exist_ok=True)
                    import shutil

                    shutil.copyfile(blend["path"], SOURCE / f"{asset_id}.blend")
                    (SOURCE / f"{asset_id}.meta.json").write_text(
                        json.dumps(
                            meta_for(asset_id, category, budget, description), indent=2
                        )
                        + "\n",
                        encoding="utf-8",
                    )
            except ForgeError as exc:
                failures.append(asset_id)
                rows.append({"asset": asset_id, "error": str(exc)})
                print(f"FAIL {asset_id:22} {exc}")
    finally:
        forge.stop()

    report = REPO / "assets-generated" / "bforge" / "deep_pack.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    total = sum(r.get("triangles", 0) for r in rows)
    print(f"\n{len(rows) - len(failures)}/{len(rows)} assets, {total} triangles total")
    if args.install:
        print(f"installed masters + sidecars -> {SOURCE.relative_to(REPO)}")
    print(f"report -> {report.relative_to(REPO)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
