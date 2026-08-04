"""Build a four-character cast through the full bforge quality loop.

Every character: proportioned humanoid -> face + hands -> era-appropriate
outfit -> vertex-colour wear -> rig + idle/walk clips -> quality gate ->
gated export (.blend + .glb + .meta.json + contact sheet).

Usage (from the repo root):

    uv run --project tools python tools/bforge/examples/characters.py [out_dir]

The point of the example is the LOOP, not the cast: generate, measure
(check.materials, gameready.review), then export only what passes. Characters
are where the 'brown blob' failure hurts most, and every guard against it is
exercised here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402

CAST = [
    {
        "id": "settler",
        "brief": "First Fire settler — hide wrap, work-worn hands, no metal anywhere",
        "height": 1.68, "build": "stylized", "skin": "#a8795a",
        "outfit": [("pteruges", "cloth"), ("bracers", "leather")],
        "wear_on": [],
        "seed": 11,
    },
    {
        "id": "scout",
        "brief": "Hunter-scout — lean, leather bracers, cloth wrap, moves first",
        "height": 1.74, "build": "lithe", "skin": "#8a6248",
        "outfit": [("pteruges", "cloth"), ("bracers", "leather")],
        "wear_on": [],
        "seed": 23,
    },
    {
        "id": "warden",
        "brief": "Fortification-era bronze guard — cuirass, crested helmet, aspis on the forearm",
        "height": 1.82, "build": "heroic", "skin": "#b08a68",
        "outfit": [("cuirass", "bronze"), ("pteruges", "leather"), ("greaves", "bronze"),
                   ("bracers", "leather"), ("helmet", "bronze"), ("shield", "bronze")],
        "wear_on": ["cuirass", "helmet", "shield"],
        "seed": 3,
    },
    {
        "id": "raider",
        "brief": "Frontier raider — heavy, dark leather and scavenged iron, shield right",
        "height": 1.86, "build": "realistic", "skin": "#96684e",
        "outfit": [("cuirass", "iron"), ("pteruges", "leather"), ("bracers", "leather"),
                   ("helmet", "iron"), ("shield", "iron")],
        "wear_on": ["cuirass", "helmet", "shield"],
        "seed": 41,
    },
]


def build_character(forge: Forge, spec: dict, out_dir: Path) -> dict:
    forge.call("session.reset")
    name = spec["id"]
    height = spec["height"]

    forge.call("char.humanoid", name=name, height=height, build=spec["build"],
               skin=spec["skin"], seed=spec["seed"])
    forge.call("char.face", name=name, height=height, build=spec["build"])
    forge.call("char.hands", name=name, height=height, build=spec["build"])

    pieces = []
    for piece, material in spec["outfit"]:
        result = forge.call(
            "char.outfit", name=name, piece=piece, height=height,
            build=spec["build"], material=material,
            side="r" if spec["id"] == "raider" and piece == "shield" else "l",
        )
        pieces.append((result["object"], material))

    # Wear: grime in the cavities, dust at the hem — on METAL, where it reads.
    for obj, material in pieces:
        if obj.rsplit("_", 1)[-1] in spec["wear_on"]:
            forge.call("paint.fill", name=obj, color="#ffffff")
            forge.call("paint.cavity", name=obj, color="#3a2c1c",
                       mode="cavity", strength=0.55)
            forge.call("paint.height", name=obj, low="#5a4a34", high="#ffffff",
                       curve="smooth")

    rig = forge.call("char.rig", name=name, height=height, build=spec["build"])
    for clip in ("idle", "walk"):
        forge.call("char.animate", rig=rig["armature"], clip=clip, length=24)

    objects = [name, rig["armature"]] + [obj for obj, _m in pieces]
    review = forge.call("gameready.review", objects=objects)
    if not review["passed"]:
        raise SystemExit(f"{name} failed the quality gate: {review['findings']}")

    result = forge.call(
        "export.asset", asset_id=name, out_dir=str(out_dir), objects=objects,
        engine="threejs", category="character", ai_prompt=spec["brief"],
    )
    separation = forge.call("check.materials", objects=objects)["max_delta_e"]
    return {
        "id": name, "triangles": result["triangles"], "bytes": result["bytes"],
        "max_delta_e": separation, "pieces": len(pieces),
    }


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "characters")
    out_dir.mkdir(parents=True, exist_ok=True)
    with Forge() as forge:
        for spec in CAST:
            report = build_character(forge, spec, out_dir)
            print(
                f"{report['id']:8s}  {report['triangles']:5d} tris  "
                f"{report['pieces']} pieces  ΔE {report['max_delta_e']:5.1f}  "
                f"{report['bytes'] / 1024:.0f} KiB"
            )
    print(f"\npack -> {out_dir}")


if __name__ == "__main__":
    main()
