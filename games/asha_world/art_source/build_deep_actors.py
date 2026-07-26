"""Generate The Deep's two actor blockouts with bforge.

    python games/asha_world/art_source/build_deep_actors.py [--render] [--install]

The dressing pack gave the mine its Blender identity; the two figures standing
in it are still bare capsules. These are their bodies: the delver, a stocky
miner under a brimmed helmet with a pack on its back, and the Stratum Warden,
a horned obsidian monolith that is deliberately NOT humanoid, so the pair can
never be confused at the tactical camera's distance.

Both are silhouette work. The consuming game draws actors with its own
material overrides (unshaded-adjacent flat colors, the same doctrine as its
loot) and adds its own head lamp and ember eye, so these masters carry no
lamp and no eye, and their materials are library truth rather than what the
player sees. Faces: -Y forward in Blender, which the glTF export turns into
-Z forward — the orientation the game's `_face()` already assumes.

Writes .blend masters plus .meta.json sidecars into `assets-source/deep/`, so
the assets go through the existing ADR 0006 pipeline (`just asset-cook`).
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

ACTORS = [
    (
        "deep_delver",
        2600,
        "character",
        "The player's miner — stocky figure, brimmed helmet, back pack",
        [
            (
                "char.humanoid",
                {
                    "name": "deep_delver",
                    "height": 1.45,
                    "build": "stylized",
                    "bulk": 1.2,
                    "detail": 7,
                    "skin": "#8a7358",
                    "seed": 71,
                },
            ),
            # Brimmed mining helmet: a lathe of brim + dome, sat on the crown.
            # The consuming game mounts its own lamp on the facing side; the
            # helmet's job is only to make "miner" readable in silhouette.
            (
                "build.lathe",
                {
                    "name": "helmet",
                    # Flat [radius, height, ...] pairs, bottom to top: brim, then dome.
                    "profile": [
                        0.20, 0.00,
                        0.21, 0.02,
                        0.15, 0.03,
                        0.14, 0.10,
                        0.10, 0.16,
                        0.001, 0.19,
                    ],
                    "segments": 10,
                    "material": "bronze",
                    "color": "#7a5c34",
                    "smooth": True,
                    "location": [0.0, 0.0, 1.30],
                },
            ),
            # The pack rides between the shoulders, +Y = behind a -Y-facing figure.
            (
                "build.box",
                {
                    "name": "backpack",
                    "size": [0.30, 0.16, 0.40],
                    "bevel": 0.03,
                    "material": "cloth",
                    "color": "#4f3d2a",
                    "location": [0.0, 0.17, 0.92],
                },
            ),
            (
                "object.join",
                {"names": ["deep_delver", "helmet", "backpack"], "into": "deep_delver"},
            ),
        ],
    ),
    (
        "deep_warden",
        1600,
        "character",
        "The Stratum Warden — horned obsidian monolith, deliberately inhuman",
        [
            # The body is one lathed mass: broad at the shoulder, narrowing to
            # a crown, faceted rather than smooth so it reads as cut stone.
            (
                "build.lathe",
                {
                    "name": "deep_warden",
                    # Flat [radius, height, ...] pairs: broad shoulder mass
                    # narrowing to a crown.
                    "profile": [
                        0.30, 0.00,
                        0.38, 0.18,
                        0.42, 0.55,
                        0.46, 0.92,
                        0.40, 1.14,
                        0.28, 1.32,
                        0.14, 1.48,
                        0.001, 1.56,
                    ],
                    "segments": 9,
                    "material": "rock",
                    "color": "#2a2438",
                    "smooth": False,
                },
            ),
            # A matched pair of swept-back horns. No eye: the consuming game
            # adds its own ember eye, which is also its attack telegraph.
            # object.transform rotates a piece about its own center, so the
            # base swings as the tip does -- the first render showed every
            # attachment floating free of the body. The pieces are therefore
            # buried DEEP in the mass: long horns rooted well inside the crown
            # radius, so wherever the pivot swings the base, it stays in rock.
            (
                "build.cylinder",
                {
                    "name": "horn_l",
                    "radius": 0.08,
                    "radius_top": 0.0,
                    "depth": 0.62,
                    "segments": 6,
                    "material": "rock",
                    "color": "#191521",
                    "location": [0.10, 0.0, 1.18],
                    "smooth": False,
                },
            ),
            ("object.transform", {"name": "horn_l", "rotation": [12, 30, 0], "apply": True}),
            (
                "build.cylinder",
                {
                    "name": "horn_r",
                    "radius": 0.08,
                    "radius_top": 0.0,
                    "depth": 0.62,
                    "segments": 6,
                    "material": "rock",
                    "color": "#191521",
                    "location": [-0.10, 0.0, 1.18],
                    "smooth": False,
                },
            ),
            ("object.transform", {"name": "horn_r", "rotation": [12, -30, 0], "apply": True}),
            # Shoulder ridges, half-sunk into the flank at the widest band.
            (
                "build.wedge",
                {
                    "name": "ridge_l",
                    "size": [0.30, 0.24, 0.20],
                    "material": "rock",
                    "color": "#191521",
                    "location": [0.30, 0.0, 0.88],
                },
            ),
            (
                "build.wedge",
                {
                    "name": "ridge_r",
                    "size": [0.30, 0.24, 0.20],
                    "material": "rock",
                    "color": "#191521",
                    "location": [-0.30, 0.0, 0.88],
                },
            ),
            (
                "object.join",
                {
                    "names": ["deep_warden", "horn_l", "horn_r", "ridge_l", "ridge_r"],
                    "into": "deep_warden",
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
                "workflow": "games/asha_world/art_source/build_deep_actors.py",
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
        for asset_id, budget, category, description, steps in ACTORS:
            try:
                forge.call("session.reset")
                for op, params in steps:
                    forge.call(op, _timeout=600, **params)

                forge.call("material.consolidate", tolerance=0.02)
                forge.call("gameready.collision", name=asset_id, mode="convex")
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
                status = "OK " if check["ok"] and info["triangles"] <= budget else "CHECK"
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

    report = REPO / "assets-generated" / "bforge" / "deep_actors.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    total = sum(r.get("triangles", 0) for r in rows)
    print(f"\n{len(rows) - len(failures)}/{len(rows)} actors, {total} triangles total")
    if args.install:
        print(f"installed masters + sidecars -> {SOURCE.relative_to(REPO)}")
    print(f"report -> {report.relative_to(REPO)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
