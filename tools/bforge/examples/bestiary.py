"""The surface-wave bestiary, rebuilt through the enforced bforge loop.

Eight enemy archetypes for Ashenward/Spike, replacing the old 'zero-pixel
mannequin' generation: five humanoid fighters/casters, one hooded stalker,
one quadruped runner, one hexapod. Every model: proportioned body ->
outfit -> wear paint where it reads -> rig -> idle/walk clips -> quality
gate -> gated export with a review sheet. Every mob carries the underworld
signature: emissive green eyes that read at swarm distance.

    uv run --project tools python tools/bforge/examples/bestiary.py [out_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402

# The underworld signature. One glance at the swarm and you know what bank
# of the Styx it came from.
UNDERWORLD_GLOW = "#39ff88"

ROSTER = [
    {
        "id": "fallen_peltast", "family": "humanoid",
        "brief": "Fallen peltast — a pale dead soldier with a scavenged iron shield, swarm fodder",
        "height": 1.74, "build": "lithe", "skin": "#c9c2b0",
        "outfit": [("shield", "iron"), ("bracers", "leather")],
        "wear": ["shield"], "seed": 61,
    },
    {
        "id": "tomb_breaker", "family": "humanoid",
        "brief": "Tomb Breaker — massive dark-iron breaker that cracks gates and bones",
        "height": 1.92, "build": "heroic", "skin": "#8a7a66",
        "outfit": [("cuirass", "iron"), ("greaves", "iron"), ("helmet", "iron")],
        "wear": ["cuirass", "helmet"], "seed": 67,
    },
    {
        "id": "bone_oracle", "family": "humanoid",
        "brief": "Bone Oracle — robed caster reading the dead's debts, pale as candle wax",
        "height": 1.78, "build": "lithe", "skin": "#cfc6b2",
        "outfit": [("robe", "cloth"), ("hood", "cloth")],
        "wear": [], "seed": 71,
    },
    {
        "id": "dread_strategos", "family": "humanoid",
        "brief": "Dread Strategos — bronze-cased dead general, crested, still giving orders",
        "height": 1.9, "build": "heroic", "skin": "#9a8a72",
        "outfit": [("cuirass", "bronze"), ("pteruges", "leather"), ("greaves", "bronze"),
                   ("helmet", "bronze"), ("shield", "bronze")],
        "wear": ["cuirass", "helmet", "shield"], "seed": 73,
    },
    {
        "id": "stygian_warlock", "family": "humanoid",
        "brief": "Stygian Warlock — river-green robed horror from the far bank",
        "height": 1.84, "build": "realistic", "skin": "#7d8471",
        "outfit": [("robe", "cloth"), ("hood", "cloth")],
        "robe_color": "#2e3b33", "hood_color": "#242f28",
        "wear": [], "seed": 79,
    },
    {
        "id": "ash_stalker", "family": "humanoid",
        "brief": "Bone Stalker — gaunt ash-pale stalker in a burial shroud, fast and hungry",
        "height": 1.92, "build": "lithe", "skin": "#a39c88",
        "outfit": [("hood", "cloth"), ("bracers", "leather")],
        "hood_color": "#191b1b",
        "wear": [], "seed": 43,
    },
    {
        "id": "dire_hound", "family": "quadruped",
        "brief": "Molossian Dire Hound — soot-dark underworld runner, all ribs and teeth",
        "plan": "canine", "length": 1.75, "shoulder": 1.0, "bulk": 0.96,
        "skin": "#24231f", "seed": 89,
    },
    {
        "id": "carrion_scarab", "family": "insect",
        "brief": "Carrion Scarab — dog-sized burial-beetle that eats what the war leaves",
        "length": 1.0, "shoulder": 0.42, "bulk": 1.35, "skin": "#3a3026", "seed": 83,
    },
]


def build_humanoid(forge: Forge, spec: dict, out_dir: Path) -> dict:
    name = spec["id"]
    forge.call("char.humanoid", name=name, height=spec["height"], build=spec["build"],
               skin=spec["skin"], seed=spec["seed"])
    forge.call("char.face", name=name, height=spec["height"], build=spec["build"],
               eyes="glow", eye_color=UNDERWORLD_GLOW)
    forge.call("char.hands", name=name, height=spec["height"], build=spec["build"])
    pieces = []
    for piece, material in spec["outfit"]:
        kwargs = {}
        if f"{piece}_color" in spec:
            kwargs["color"] = spec[f"{piece}_color"]
        result = forge.call("char.outfit", name=name, piece=piece,
                            height=spec["height"], build=spec["build"],
                            material=material, **kwargs)
        pieces.append(result["object"])
    for obj in pieces:
        leaf = obj.rsplit("_", 1)[-1]
        if leaf in spec["wear"]:
            forge.call("paint.fill", name=obj, color="#ffffff")
            forge.call("paint.cavity", name=obj, color="#2c2118", mode="cavity",
                       strength=0.55)
            forge.call("paint.height", name=obj, low="#4a3a28", high="#ffffff",
                       curve="smooth")
    # Surface richness on the metal: baked AO + roughness (the flat-color
    # ceiling breaker). 512 is plenty for RTS-distance armor.
    for obj in pieces:
        if obj.rsplit("_", 1)[-1] in spec["wear"]:
            forge.call("material.bake_pbr", object=obj,
                       maps=["base_color", "roughness", "ao"], size=512, samples=16)
    # Surface relief that actually exports (bake passes only capture geometry
    # normals): cloth gets weave, bare skin gets pores.
    for obj in pieces:
        leaf = obj.rsplit("_", 1)[-1]
        if leaf in ("robe", "hood"):
            forge.call("material.detail_normal", object=obj, pattern="weave",
                       scale=64.0, strength=0.45, size=512, seed=spec["seed"] + 7)
    forge.call("material.detail_normal", object=name, pattern="pores",
               scale=42.0, strength=0.3, size=512, seed=spec["seed"] + 13)
    rig = forge.call("char.rig", name=name, height=spec["height"], build=spec["build"])
    for clip in ("idle", "walk", "attack", "death"):
        forge.call("char.animate", rig=rig["armature"], clip=clip, length=24)
    objects = [name, rig["armature"]] + pieces
    review = forge.call("gameready.review", objects=objects)
    if not review["passed"]:
        raise SystemExit(f"{name} failed the gate: {review['findings']}")
    result = forge.call("export.asset", asset_id=name, out_dir=str(out_dir),
                        objects=objects, engine="threejs", category="character",
                        ai_prompt=spec["brief"])
    return {"id": name, "triangles": result["triangles"], "bytes": result["bytes"]}


def build_quadruped(forge: Forge, spec: dict, out_dir: Path) -> dict:
    name = spec["id"]
    plan = spec.get("plan", "canine")
    forge.call("char.creature", name=name, plan=plan, length=spec["length"],
               shoulder=spec["shoulder"], bulk=spec["bulk"], skin=spec["skin"],
               eyes="glow", eye_color=UNDERWORLD_GLOW, seed=spec["seed"])
    forge.call("material.detail_normal", object=name, pattern="pores",
               scale=30.0, strength=0.5, size=512, seed=spec["seed"] + 13)
    rig = forge.call("char.creature_rig", name=name, plan=plan,
                     length=spec["length"], shoulder=spec["shoulder"])
    for clip in ("idle", "walk", "trot"):
        forge.call("char.animate", rig=rig["armature"], clip=clip, length=24)
    objects = [name, rig["armature"]]
    review = forge.call("gameready.review", objects=objects)
    if not review["passed"]:
        raise SystemExit(f"{name} failed the gate: {review['findings']}")
    result = forge.call("export.asset", asset_id=name, out_dir=str(out_dir),
                        objects=objects, engine="threejs", category="character",
                        ai_prompt=spec["brief"])
    return {"id": name, "triangles": result["triangles"], "bytes": result["bytes"]}


def build_insect(forge: Forge, spec: dict, out_dir: Path) -> dict:
    name = spec["id"]
    forge.call("char.creature", name=name, plan="insect", length=spec["length"],
               shoulder=spec["shoulder"], bulk=spec["bulk"], skin=spec["skin"],
               eyes="glow", eye_color=UNDERWORLD_GLOW, seed=spec["seed"])
    forge.call("material.detail_normal", object=name, pattern="scales",
               scale=24.0, strength=0.55, size=512, seed=spec["seed"] + 13)
    rig = forge.call("char.creature_rig", name=name, plan="insect",
                     length=spec["length"], shoulder=spec["shoulder"])
    for clip in ("idle", "walk"):
        forge.call("char.animate", rig=rig["armature"], clip=clip, length=24)
    objects = [name, rig["armature"]]
    review = forge.call("gameready.review", objects=objects)
    if not review["passed"]:
        raise SystemExit(f"{name} failed the gate: {review['findings']}")
    result = forge.call("export.asset", asset_id=name, out_dir=str(out_dir),
                        objects=objects, engine="threejs", category="character",
                        ai_prompt=spec["brief"])
    return {"id": name, "triangles": result["triangles"], "bytes": result["bytes"]}


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "bestiary")
    out_dir.mkdir(parents=True, exist_ok=True)
    with Forge() as forge:
        for spec in ROSTER:
            forge.call("session.reset")
            if spec["family"] == "insect":
                report = build_insect(forge, spec, out_dir)
            elif spec["family"] == "quadruped":
                report = build_quadruped(forge, spec, out_dir)
            else:
                report = build_humanoid(forge, spec, out_dir)
            print(f"{report['id']:18s} {report['triangles']:5d} tris  "
                  f"{report['bytes'] / 1024:4.0f} KiB")
    print(f"\nroster -> {out_dir}")


if __name__ == "__main__":
    main()
