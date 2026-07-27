"""Build The Chariot Club's racing biga and its charioteer, via bforge.

    python games/chariot/art_source/build_biga.py [--render] [--install]

The shipping chariot was stacked axis-aligned boxes — including the driver,
who was seven cuboids and a slab for a crest. It is the thing on screen for
every second of every race, at the closest range of anything in the game.

Contract with the game (src/presentation/broadcast_view.gd):
  * top-level objects named `Car`, `WheelL`, `WheelR`, `Charioteer`
  * each wheel's ORIGIN at its own hub — the runtime spins local X from
    authoritative speed, so an off-centre origin makes the wheel orbit
  * materials named `CarFront`, `Tunic`, `Crest` — the livery tints look them
    up by name and recolour per stable
  * forward is -Z in Godot, which is +Y in Blender before the glTF axis change

A single horse draws between two side shafts. A central pole is a two-horse
rig and would pierce the animal.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "bforge"))

from bforge import Forge, ForgeError  # noqa: E402

GAME = REPO / "games" / "chariot"
MODEL_PATH = GAME / "project" / "assets" / "models" / "racing_chariot.glb"

# Oiled ash and bronze, not painted plastic. The livery colours arrive at
# runtime; everything structural stays timber and metal.
ASH = "#8a6a44"
ASH_DARK = "#6b5133"
BRONZE = "#a8762e"
IRON = "#6f7378"
LEATHER = "#5e4029"
LIVERY = "#c9c2b0"   # placeholder: the game recolours these per stable
SKIN = "#b07d55"

WHEEL_R = 0.55
WHEEL_X = 0.84
HUB_Z = 0.55
AXLE_Y = -1.25


def spin(forge, name, degrees):
    """Rotate and BAKE. The build ops place but never orient, and an unbaked
    node rotation does not survive the join into another object's space."""
    forge.call("object.transform", name=name, rotation=degrees, apply=True)


def build_wheel(forge, name, x_sign):
    """A spoked wheel whose origin is its hub.

    Built AT THE ORIGIN and moved afterwards, because everything here is
    joined into the hub and a join keeps the ACTIVE object's origin — put the
    wheel at its final place first and it spins around the chariot instead of
    around its own axle.
    """
    hub = f"{name}_hub"
    # The nave: a turned bronze barrel, wider at the middle like a real one.
    forge.call(
        "build.lathe",
        name=hub,
        profile=[0.045, -0.11, 0.10, -0.09, 0.115, 0.0, 0.10, 0.09, 0.045, 0.11],
        segments=14, material="metal", color=BRONZE, origin="center", smooth=True,
    )
    spin(forge, hub, [0.0, 90.0, 0.0])
    parts = [hub]
    # Felloe (the wooden rim) under an iron tyre — two rings, not one, which is
    # the read that says "wheel built by a wheelwright" rather than "torus".
    forge.call(
        "build.torus",
        name=f"{name}_felloe", major=WHEEL_R - 0.075, minor=0.055,
        major_segments=32, minor_segments=8,
        material="wood", color=ASH, origin="center",
    )
    spin(forge, f"{name}_felloe", [0.0, 90.0, 0.0])
    parts.append(f"{name}_felloe")
    forge.call(
        "build.torus",
        name=f"{name}_tyre", major=WHEEL_R - 0.022, minor=0.028,
        major_segments=32, minor_segments=6,
        material="metal", color=IRON, origin="center",
    )
    spin(forge, f"{name}_tyre", [0.0, 90.0, 0.0])
    parts.append(f"{name}_tyre")
    for k in range(10):
        spoke = f"{name}_spoke_{k}"
        # Turned spokes: thick at the nave, thin at the felloe.
        forge.call(
            "build.cylinder",
            name=spoke, radius=0.030, radius_top=0.018,
            depth=WHEEL_R - 0.10, segments=6,
            material="wood", color=ASH, origin="bottom",
        )
        spin(forge, spoke, [0.0, 90.0, 36.0 * k])
        parts.append(spoke)
    forge.call("object.join", names=parts, into=hub)
    forge.call(
        "object.transform",
        name=hub,
        location=[x_sign * WHEEL_X, AXLE_Y, HUB_Z],
        apply=False,
    )
    return hub


def build_car(forge):
    """The car: a floor, a curved front breastwork, side rails, axle, shafts
    and reins. Swept rather than stacked, so the front actually curves the way
    a biga's does."""
    parts = []
    forge.call(
        "build.box",
        name="car_floor",
        size=[0.95, 0.80, 0.10],
        location=[0.0, -1.05, 0.50],
        bevel=0.02,
        material="wood",
        color=ASH_DARK,
        origin="center",
    )
    parts.append("car_floor")
    # The breastwork the driver leans into: a curved shell, open at the back.
    # The rail the driver leans into. A swept ARC put it beside the car, not
    # around it — the arc path begins at its location rather than centring on
    # it — so this is a ring, which cannot be placed ambiguously, plus
    # stanchions down to the floor. Open-backed reads from the stanchion gap.
    forge.call(
        "build.torus",
        name="car_front", major=0.46, minor=0.045,
        major_segments=18, minor_segments=6,
        location=[0.0, -1.02, 1.28],
        material="cloth", color=LIVERY, origin="center",
    )
    forge.call("object.transform", name="car_front", scale=[1.0, 0.86, 1.0], apply=True)
    parts.append("car_front")
    for i, (sx, sy) in enumerate([(-0.44, -1.42), (0.44, -1.42), (-0.30, -0.62), (0.30, -0.62)]):
        post = f"car_post_{i}"
        forge.call(
            "build.cylinder",
            name=post, radius=0.026, depth=0.78, segments=6,
            location=[sx, sy, 0.90],
            material="wood", color=ASH, origin="center",
        )
        parts.append(post)
    forge.call(
        "build.cylinder",
        name="axle", radius=0.05, depth=1.72, segments=8,
        location=[0.0, AXLE_Y, HUB_Z],
        material="wood", color=ASH_DARK, origin="center",
    )
    spin(forge, "axle", [0.0, 90.0, 0.0])
    parts.append("axle")
    for sign, side in ((-1.0, "l"), (1.0, "r")):
        shaft = f"shaft_{side}"
        forge.call(
            "build.cylinder",
            name=shaft, radius=0.035, depth=3.15, segments=6,
            location=[sign * 0.44, 0.86, 0.86],
            material="wood", color=ASH, origin="center",
        )
        spin(forge, shaft, [98.5, 0.0, 0.0])
        parts.append(shaft)
        rein = f"rein_{side}"
        forge.call(
            "build.cylinder",
            name=rein, radius=0.017, depth=3.95, segments=4,
            location=[sign * 0.20, 1.52, 1.58],
            # Rubber, not cloth: `cloth` has to stay unambiguously the LIVERY
            # surface, because that is the one the game recolours per stable
            # and it finds it by material name.
            material="rubber", color=LEATHER, origin="center",
        )
        spin(forge, rein, [98.0, 0.0, 0.0])
        parts.append(rein)
    forge.call("object.join", names=parts, into="car_floor")
    return "car_floor"


def build_driver(forge):
    """The charioteer: a proportioned figure, not seven cuboids.

    Stood in the car, leaning into the reins. `char.humanoid` gives the figure
    the head ratios a human actually has, which is the whole reason the box
    version never read as a person however it was coloured.
    """
    forge.call(
        "char.humanoid",
        name="driver",
        height=1.72,
        build="lithe",
        bulk=0.95,
        detail=8,
        skin=SKIN,
        location=[0.0, -0.92, 0.55],
    )
    # Tunic over the body, belted — the livery surface the game recolours.
    forge.call(
        "build.cylinder",
        name="driver_tunic",
        radius=0.20,
        radius_top=0.17,
        depth=0.62,
        segments=8,
        location=[0.0, -0.92, 1.22],
        material="cloth",
        color=LIVERY,
        origin="center",
    )
    forge.call(
        "build.torus",
        name="driver_belt", major=0.19, minor=0.028,
        major_segments=10, minor_segments=4,
        location=[0.0, -0.92, 1.00],
        material="cloth", color=LEATHER, origin="center",
    )
    # Helmet and crest: the crest is the second livery surface.
    forge.call(
        "build.sphere",
        name="driver_galea",
        radius=0.135,
        segments=10,
        rings=6,
        location=[0.0, -0.92, 1.62],
        material="metal",
        color=BRONZE,
        origin="center",
    )
    forge.call(
        "build.wedge",
        name="driver_crest",
        size=[0.05, 0.34, 0.16],
        location=[0.0, -0.94, 1.78],
        material="cloth",
        color=LIVERY,
        origin="center",
    )
    # The FASCIAE: the leather bands a Roman charioteer wound round his chest,
    # the single most recognisable thing about the man. Without them he is
    # just somebody standing in a cart.
    for i in range(5):
        band = f"driver_fascia_{i}"
        forge.call(
            "build.torus",
            name=band, major=0.205, minor=0.022,
            major_segments=12, minor_segments=4,
            location=[0.0, -0.92, 1.06 + i * 0.085],
            material="rubber", color=LEATHER, origin="center",
        )
        forge.call("object.transform", name=band, scale=[1.0, 0.72, 1.0], apply=True)
    # The knife at his belt: he carried one to cut himself free of the reins.
    forge.call(
        "build.box",
        name="driver_knife", size=[0.035, 0.055, 0.18],
        location=[0.16, -0.86, 0.96],
        material="metal", color=IRON, origin="center",
    )
    forge.call(
        "object.join",
        names=(["driver", "driver_tunic", "driver_belt", "driver_galea",
                "driver_crest", "driver_knife"]
               + [f"driver_fascia_{i}" for i in range(5)]),
        into="driver",
    )
    return "driver"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    out_dir = REPO / "assets-generated" / "bforge" / "chariot"
    out_dir.mkdir(parents=True, exist_ok=True)

    with Forge() as forge:
        forge.call("session.reset")
        car = build_car(forge)
        left = build_wheel(forge, "wheel_l", -1.0)
        right = build_wheel(forge, "wheel_r", 1.0)
        driver = build_driver(forge)

        # Take the critique's own advice: the humanoid blockout leaves
        # non-manifold seams where its limbs meet the torso, and every op that
        # makes a rounded cap leaves n-gons an engine will triangulate however
        # it likes. Both are cheap to fix here and expensive to chase later.
        forge.call("build.cleanup", name=driver, merge_distance=0.001)
        forge.call(
            "gameready.optimize",
            objects=[car, left, right, driver],
            triangulate=True,
        )
        # NO baked PBR here, deliberately. material.bake_pbr collapses an
        # object to ONE material, and this game tints `CarFront`, `Tunic` and
        # `Crest` BY NAME to put each stable in its own livery — the single
        # most important thing the chariot does. A gorgeous surface that makes
        # every stable race in the same colours is a worse asset. The quality
        # here comes from the geometry: a turned nave, a felloe under an iron
        # tyre, tapered spokes, an open breastwork and a proportioned driver.
        info = forge.call("object.list")
        names = info["objects"] if isinstance(info, dict) else info
        print("built    :", ", ".join(sorted(str(o if isinstance(o, str) else o.get("name")) for o in names)))

        report = forge.call("check.critique")
        print("critique :", report.get("summary", report))

        glb = out_dir / "racing_chariot.glb"
        forge.call(
            "export.gltf",
            out=str(glb),
            objects=[car, left, right, driver],
            rename={
                # One livery surface, shared by the car's breastwork, the
                # driver's tunic and his crest — the game tints CarFront,
                # Tunic and Crest on BOTH meshes, so a single well-named
                # material puts the whole rig in the stable's colours.
                "m_cloth": "Tunic",
                "car_floor": "Car",
                "wheel_l_hub": "WheelL",
                "wheel_r_hub": "WheelR",
                "driver": "Charioteer",
            },
        )
        print("export   :", f"{glb.stat().st_size // 1024} KB -> {glb}")
        forge.call("session.save", path=str(out_dir / "racing_chariot.blend"))

        if args.render:
            sheet = out_dir / "biga.png"
            forge.call("render.contact_sheet", out=str(sheet))
            print("sheet    :", sheet)

    if args.install:
        shutil.copy2(glb, MODEL_PATH)
        print("installed:", MODEL_PATH)


if __name__ == "__main__":
    try:
        main()
    except ForgeError as err:
        print("bforge error:", err, file=sys.stderr)
        raise SystemExit(1)
