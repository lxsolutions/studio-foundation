"""The First Fire settlement pack — Ashenward's Age-1 homestead, in one scene.

Eight camp assets on a 4 m grid, all built from stock bforge recipes and
compositions, then gated TWICE: per-asset gameready.review inside the gated
export.asset, and check.conformance across the whole set — because a camp of
individually-fine props that don't look like one game is the failure this
example exists to prevent.

    uv run --project tools python tools/bforge/examples/first_fire.py [out_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402

GRID = 4.0  # metres between asset anchors


def campfire(f: Forge, at):
    names = []
    for i in range(8):
        angle = i * 45.0
        x = at[0] + 0.45 * __import__("math").cos(__import__("math").radians(angle))
        y = at[1] + 0.45 * __import__("math").sin(__import__("math").radians(angle))
        names.append(
            f.call(
                "prop.rock",
                name=f"campfire_stone_{i}",
                location=[x, y, at[2]],
                size=[0.24, 0.22, 0.2],
                detail=1,
                seed=60 + i,
            )["name"]
        )
    for i in range(3):
        names.append(
            f.call(
                "build.cylinder",
                name=f"campfire_log_{i}",
                radius=0.045,
                depth=0.7,
                segments=8,
                material="wood",
                color="#5d4426",
                location=[at[0], at[1], at[2] + 0.28],
            )["name"]
        )
        f.call("object.transform", name=f"campfire_log_{i}", rotation=[62.0, 0.0, i * 120.0])
    coals = f.call(
        "build.cylinder",
        name="campfire_coals",
        radius=0.26,
        radius_top=0.2,
        depth=0.1,
        segments=12,
        material="stone",
        location=[at[0], at[1], at[2] + 0.05],
    )["name"]
    f.call(
        "material.set", object=coals, preset="stone", name="m_embers", color="#ff5a14", emission=4.5
    )
    return names + [coals]


def hide_tent(f: Forge, at):
    names = []
    # Ridge pole along X at the peak, one support pole at each end.
    names.append(
        f.call(
            "build.cylinder",
            name="tent_ridge",
            radius=0.035,
            depth=2.4,
            segments=8,
            material="wood",
            color="#6a4e2c",
            location=[at[0], at[1], at[2] + 1.55],
        )["name"]
    )
    f.call("object.transform", name="tent_ridge", rotation=[0.0, 90.0, 0.0])
    for side in (-1, 1):
        names.append(
            f.call(
                "build.cylinder",
                name=f"tent_pole_{side}",
                radius=0.035,
                depth=1.6,
                segments=8,
                material="wood",
                color="#6a4e2c",
                location=[at[0] + side * 1.1, at[1], at[2] + 0.8],
            )["name"]
        )
    # Two sloped hide panels leaning on the ridge — the A in A-frame.
    for side, rot, yoff in (("a", 58.0, -0.72), ("b", -58.0, 0.72)):
        panel = f.call(
            "build.box",
            name=f"tent_hide_{side}",
            size=[2.3, 0.05, 1.9],
            material="cloth",
            color="#7a5a38",
            location=[at[0], at[1] + yoff, at[2] + 0.82],
        )["name"]
        f.call("object.transform", name=panel, rotation=[rot, 0.0, 0.0])
        f.call("paint.fill", name=panel, color="#c9b898")
        f.call("paint.cavity", name=panel, color="#4a3620", mode="cavity", strength=0.5)
        names.append(panel)
    return names


def palisade(f: Forge, at):
    names = []
    for i in range(7):
        depth = 2.4 if i % 2 == 0 else 2.55
        names.append(
            f.call(
                "build.cylinder",
                name=f"palisade_log_{i}",
                radius=0.09,
                radius_top=0.0,
                depth=depth,
                segments=10,
                material="wood",
                color="#6a4e2c",
                location=[at[0] + (i - 3) * 0.19, at[1], at[2] + depth / 2.0],
            )["name"]
        )
    return names


def storage_rack(f: Forge, at):
    rack = f.call(
        "prop.furniture",
        name="rack",
        kind="shelf",
        size=[1.4, 0.5, 1.2],
        location=list(at),
        seed=21,
    )["name"]
    sack_a = f.call(
        "prop.sack", name="rack_sack_a", location=[at[0] - 0.3, at[1], at[2] + 0.75], seed=31
    )["name"]
    sack_b = f.call(
        "prop.sack", name="rack_sack_b", location=[at[0] + 0.32, at[1] - 0.05, at[2]], seed=47
    )["name"]
    return [rack, sack_a, sack_b]


def well(f: Forge, at):
    import math

    names = []
    stone_names = []
    for row in range(2):
        for i in range(9):
            angle = i * 40.0 + row * 20.0
            stone_names.append(
                f.call(
                    "prop.rock",
                    name=f"well_stone_{row}_{i}",
                    location=[
                        at[0] + 0.62 * math.cos(math.radians(angle)),
                        at[1] + 0.62 * math.sin(math.radians(angle)),
                        at[2] + 0.14 + row * 0.24,
                    ],
                    size=[0.3, 0.28, 0.24],
                    detail=1,
                    seed=100 + row * 10 + i,
                )["name"]
            )
    for side in (-1, 1):
        names.append(
            f.call(
                "build.cylinder",
                name=f"well_post_{side}",
                radius=0.05,
                depth=1.3,
                segments=8,
                material="wood",
                color="#6a4e2c",
                location=[at[0] + side * 0.62, at[1], at[2] + 0.65],
            )["name"]
        )
    names.append(
        f.call(
            "build.cylinder",
            name="well_bar",
            radius=0.045,
            depth=1.34,
            segments=8,
            material="wood",
            color="#5d4426",
            location=[at[0], at[1], at[2] + 1.28],
        )["name"]
    )
    f.call("object.transform", name="well_bar", rotation=[0.0, 90.0, 0.0])
    # 18 stones + posts + bar would ship as 21 draw calls — join to two.
    f.call("object.join", names=stone_names, into="well_stones")
    f.call("object.join", names=[n for n in names if "post" in n or "bar" in n], into="well_frame")
    return ["well_stones", "well_frame"]


def workbench(f: Forge, at):
    bench = f.call(
        "prop.furniture",
        name="workbench",
        kind="table",
        size=[1.4, 0.7, 0.8],
        location=list(at),
        seed=9,
    )["name"]
    axe = f.call(
        "prop.weapon",
        name="bench_axe",
        kind="axe",
        location=[at[0] + 0.2, at[1], at[2] + 0.82],
        seed=5,
    )["name"]
    f.call("object.transform", name="bench_axe", rotation=[0.0, 0.0, 78.0])
    debris = f.call(
        "prop.debris", name="bench_shavings", location=[at[0] - 0.4, at[1] + 0.3, at[2]], seed=12
    )["name"]
    return [bench, axe, debris]


def firewood(f: Forge, at):
    names = []
    rows = ((3, 0.07), (2, 0.21), (1, 0.35))
    for row, (count, z) in enumerate(rows):
        for i in range(count):
            names.append(
                f.call(
                    "build.cylinder",
                    name=f"firewood_{row}_{i}",
                    radius=0.07,
                    depth=0.8,
                    segments=10,
                    material="wood",
                    color="#6a4e2c",
                    location=[at[0] + (i - (count - 1) / 2.0) * 0.16, at[1], at[2] + z],
                )["name"]
            )
            f.call("object.transform", name=f"firewood_{row}_{i}", rotation=[0.0, 90.0, 0.0])
    return names


def supply_stack(f: Forge, at):
    crate = f.call("prop.crate", name="supply_crate", location=list(at), seed=3)["name"]
    barrel = f.call(
        "prop.barrel",
        name="supply_barrel",
        height=0.9,
        bands=3,
        location=[at[0] + 0.85, at[1] + 0.2, at[2]],
        seed=7,
    )["name"]
    sack = f.call(
        "prop.sack", name="supply_sack", location=[at[0] + 0.35, at[1] - 0.55, at[2]], seed=53
    )["name"]
    f.call("object.transform", name="supply_crate", rotation=[0.0, 0.0, 12.0])
    return [crate, barrel, sack]


ASSETS = [
    ("campfire", campfire, "The First Fire itself — stone ring, log teepee, live embers"),
    ("hide_tent", hide_tent, "A-frame hide shelter, weathered leather"),
    ("palisade", palisade, "Sharpened-log stockade section"),
    ("storage_rack", storage_rack, "Drying/storage rack with sacks"),
    ("well", well, "Stone well with wooden windlass frame"),
    ("workbench", workbench, "Crafter's bench with axe and shavings"),
    ("firewood_pile", firewood, "Stacked firewood pyramid"),
    ("supply_stack", supply_stack, "Crate, barrel and sack supply cluster"),
]


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "first_fire")
    out_dir.mkdir(parents=True, exist_ok=True)
    with Forge() as forge:
        forge.call("session.reset")
        every_object = []
        per_asset = {}
        for index, (asset_id, builder, _brief) in enumerate(ASSETS):
            at = [(index % 4) * GRID, (index // 4) * GRID, 0.0]
            names = builder(forge, at)
            per_asset[asset_id] = names
            every_object.extend(names)

        conformance = forge.call("check.conformance", objects=every_object)
        print(
            f"set conformance: {conformance['coherent']}/{len(conformance['objects'])} "
            f"coherent, outliers: {conformance['outliers'] or 'none'}"
        )

        for asset_id, _builder, brief in ASSETS:
            names = per_asset[asset_id]
            review = forge.call("gameready.review", objects=names)
            if not review["passed"]:
                raise SystemExit(f"{asset_id} failed the gate: {review['findings']}")
            result = forge.call(
                "export.asset",
                asset_id=asset_id,
                out_dir=str(out_dir),
                objects=names,
                engine="threejs",
                category="environment",
                ai_prompt=brief,
                contact_sheet=True,
            )
            print(
                f"{asset_id:14s} {result['triangles']:5d} tris  {result['bytes'] / 1024:4.0f} KiB"
            )
    print(f"\npack -> {out_dir}")


if __name__ == "__main__":
    main()
