"""Build The Chariot Club's gladiator pair, via bforge.

    python games/chariot/art_source/build_gladiators.py [--render]

The midday show on the infield. These were hand-stacked boxes: the pairing
every Roman crowd knew, rendered as cuboids. The whole point of a murmillo
against a retiarius is that you can tell which is which from the SILHOUETTE
at forty metres — the tower shield and crested helmet against the trident,
the net and a bare head.

Contract with the game (src/presentation/broadcast_view.gd):
  * two top-level objects named `Murmillo` and `Retiarius`
  * materials named `Tunic` and `Crest` — the duel tints them per fighter
  * `Bronze`, `Iron` and `Net` present, so armour and kit read as themselves
  * forward is -Z in Godot, which is +Y in Blender before the glTF axis change
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "bforge"))

from bforge import Forge, ForgeError  # noqa: E402

OUT = REPO / "assets-generated" / "bforge" / "chariot"

SKIN = "#a8764e"
TUNIC = "#c9c2b0"      # placeholder: the game recolours per fighter
CREST = "#c9c2b0"
BRONZE = "#a8762e"
IRON = "#70747a"
LEATHER = "#5a3d27"
NET = "#9a8f6a"
HEIGHT = 1.80


def spin(forge, name, degrees):
    forge.call("object.transform", name=name, rotation=degrees, apply=True)


def fighter_base(forge, name, bulk):
    forge.call(
        "char.humanoid",
        name=name, height=HEIGHT, build="heroic", bulk=bulk, detail=8,
        skin=SKIN, location=[0.0, 0.0, 0.0],
    )
    # Subligaculum and belt: the loincloth every gladiator fought in.
    forge.call(
        "build.cylinder",
        name=f"{name}_kilt", radius=0.21, radius_top=0.19, depth=0.34,
        segments=10, location=[0.0, 0.0, 0.86],
        material="cloth", color=TUNIC, origin="center",
    )
    forge.call(
        "build.torus",
        name=f"{name}_belt", major=0.205, minor=0.030,
        major_segments=12, minor_segments=4, location=[0.0, 0.0, 1.02],
        material="rubber", color=LEATHER, origin="center",
    )
    return [name, f"{name}_kilt", f"{name}_belt"]


def build_murmillo(forge):
    """Tower shield, short sword, the big crested helmet."""
    # A murmillo was the heavy: he should look it beside the net-man.
    parts = fighter_base(forge, "murmillo", 1.45)
    # The scutum: a tall curved shield on the left arm. Curved, because a flat
    # slab is the difference between a shield and a door.
    # A bevelled PANEL. An uncapped cylinder is a barrel, not a shield: it
    # came out as a brown drum taller than the man carrying it and hid him
    # completely. Flat reads fine at forty metres; a barrel never will.
    forge.call(
        "build.box",
        name="murmillo_scutum", size=[0.09, 0.58, 1.02],
        location=[-0.42, 0.14, 1.10], bevel=0.05,
        material="bronze", color=BRONZE, origin="center",
    )
    parts.append("murmillo_scutum")
    forge.call(
        "build.sphere",
        name="murmillo_boss", radius=0.10, segments=8, rings=5,
        location=[-0.58, 0.16, 1.12],
        material="iron", color=IRON, origin="center",
    )
    parts.append("murmillo_boss")
    # Gladius, held forward. Blade along +Y, which is Godot's -Z.
    forge.call(
        "build.box",
        name="murmillo_gladius", size=[0.045, 0.52, 0.10],
        location=[0.30, 0.62, 1.20], bevel=0.012,
        material="iron", color=IRON, origin="center",
    )
    parts.append("murmillo_gladius")
    forge.call(
        "build.cylinder",
        name="murmillo_grip", radius=0.035, depth=0.14, segments=6,
        location=[0.30, 0.30, 1.20],
        material="rubber", color=LEATHER, origin="center",
    )
    spin(forge, "murmillo_grip", [90.0, 0.0, 0.0])
    parts.append("murmillo_grip")
    # Manica: the segmented sleeve on the sword arm.
    #
    # A SLEEVE RUNS DOWN THE ARM. These marched along Y at a fixed height, so
    # instead of banding the arm they hung in the air beside the man in a neat
    # horizontal row — the single most obviously wrong thing in the render.
    # The arm centre is measured, not guessed: the body is 0.720 wide, so the
    # hanging arm sits at x ~ 0.28.
    #
    # No spin, either. A torus already encircles its own Z, which is what a band
    # round a vertical arm needs; spun 90 degrees it encircled the FORWARD axis
    # and read as a hoop standing off the shoulder.
    for i in range(4):
        seg = f"murmillo_manica_{i}"
        forge.call(
            "build.torus",
            name=seg, major=0.088, minor=0.022, major_segments=10, minor_segments=4,
            location=[0.28, 0.0, 1.32 - i * 0.11],
            material="iron", color=IRON, origin="center",
        )
        parts.append(seg)
    # Galea: bowl, brim and the crest that names him.
    forge.call(
        "build.sphere",
        name="murmillo_galea", radius=0.145, segments=10, rings=6,
        location=[0.0, 0.0, 1.66],
        material="bronze", color=BRONZE, origin="center",
    )
    parts.append("murmillo_galea")
    forge.call(
        "build.torus",
        name="murmillo_brim", major=0.155, minor=0.030,
        major_segments=12, minor_segments=4, location=[0.0, 0.0, 1.57],
        material="bronze", color=BRONZE, origin="center",
    )
    parts.append("murmillo_brim")
    forge.call(
        "build.wedge",
        name="murmillo_crest", size=[0.055, 0.30, 0.20],
        location=[0.0, -0.02, 1.83],
        material="cloth", color=CREST, origin="center",
    )
    parts.append("murmillo_crest")
    forge.call(
        "build.cylinder",
        name="murmillo_greave", radius=0.10, radius_top=0.085, depth=0.40,
        segments=8, location=[-0.11, 0.02, 0.34],
        material="bronze", color=BRONZE, origin="center",
    )
    parts.append("murmillo_greave")
    forge.call("object.join", names=parts, into="murmillo")
    return "murmillo"


def build_retiarius(forge):
    """Trident, net, one shoulder guard, and no helmet at all."""
    # Lighter than the murmillo by design, but still a fighting man.
    parts = fighter_base(forge, "retiarius", 1.20)
    # Galerus: the shoulder guard that let him keep his face open.
    forge.call(
        "build.box",
        name="retiarius_galerus", size=[0.14, 0.30, 0.26],
        location=[-0.26, 0.0, 1.46], bevel=0.03,
        material="bronze", color=BRONZE, origin="center",
    )
    parts.append("retiarius_galerus")
    # The net-man's manica is on his LEFT arm, the one that throws. Same fix as
    # the murmillo's: down the arm, not along the ground.
    for i in range(4):
        seg = f"retiarius_manica_{i}"
        forge.call(
            "build.torus",
            name=seg, major=0.078, minor=0.020, major_segments=10, minor_segments=4,
            location=[-0.276, 0.0, 1.32 - i * 0.11],
            material="iron", color=IRON, origin="center",
        )
        parts.append(seg)
    # The trident: thick enough to survive the silhouette at forty metres.
    forge.call(
        "build.cylinder",
        name="retiarius_shaft", radius=0.048, depth=2.05, segments=8,
        location=[0.30, 0.42, 1.16],
        material="wood", color=LEATHER, origin="center",
    )
    spin(forge, "retiarius_shaft", [78.0, 0.0, 0.0])
    parts.append("retiarius_shaft")
    forge.call(
        "build.box",
        name="retiarius_head", size=[0.40, 0.14, 0.09],
        location=[0.30, 1.32, 1.42],
        material="iron", color=IRON, origin="center",
    )
    parts.append("retiarius_head")
    for k, dx in enumerate((-0.16, 0.0, 0.16)):
        prong = f"retiarius_prong_{k}"
        forge.call(
            "build.cylinder",
            name=prong, radius=0.030, radius_top=0.006, depth=0.44,
            segments=6, location=[0.30 + dx, 1.56, 1.48],
            material="iron", color=IRON, origin="center",
        )
        spin(forge, prong, [78.0, 0.0, 0.0])
        parts.append(prong)
    # The net, gathered in the off hand: a hanging sheet, not a ball.
    forge.call(
        "build.plane",
        name="retiarius_net", size=[0.46, 0.52], cuts=3,
        location=[-0.44, 0.22, 1.02],
        material="cloth", color=NET, origin="center",
    )
    spin(forge, "retiarius_net", [86.0, 0.0, 14.0])
    parts.append("retiarius_net")
    forge.call("object.join", names=parts, into="retiarius")
    return "retiarius"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    with Forge() as forge:
        forge.call("session.reset")
        murmillo = build_murmillo(forge)
        retiarius = build_retiarius(forge)
        for name in (murmillo, retiarius):
            forge.call("build.cleanup", name=name, merge_distance=0.001)
        forge.call("gameready.optimize", objects=[murmillo, retiarius], triangulate=True)
        forge.call("material.consolidate")

        report = forge.call("check.critique")
        print("critique :", "errors", report.get("errors"), "warnings", report.get("warnings"))

        glb = OUT / "gladiators.glb"
        forge.call(
            "export.gltf",
            out=str(glb),
            objects=[murmillo, retiarius],
            rename={
                "murmillo": "Murmillo",
                "retiarius": "Retiarius",
                "m_cloth": "Tunic",
                "m_bronze": "Bronze",
                "m_iron": "Iron",
                # The net is a second cloth: same preset as the loincloth, a
                # different colour, so it lands in its own material slot.
                "m_cloth_2": "Net",
            },
        )
        print("export   :", f"{glb.stat().st_size // 1024} KB -> {glb}")
        forge.call("session.save", path=str(OUT / "gladiators.blend"))
        if args.render:
            forge.call("render.contact_sheet", out=str(OUT / "gladiators.png"))
            print("sheet    :", OUT / "gladiators.png")


if __name__ == "__main__":
    try:
        main()
    except ForgeError as err:
        print("bforge error:", err, file=sys.stderr)
        raise SystemExit(1)
