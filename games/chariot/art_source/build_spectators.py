"""Build The Chariot Club's crowd figures.

    python games/chariot/art_source/build_spectators.py [--render] [--install]

The stands were filled with `CapsuleMesh(radius=0.36, height=1.15)` — a pill
only 1.6x taller than it is wide — plus a 96-triangle sphere for a head. Ten
thousand of those read as scattered confetti, not as an audience.

What makes a crowd read as people at distance is silhouette, not detail:
shoulders wider than the waist, a distinct neck and head, and a human aspect
ratio. None of that is expensive. These figures come in at roughly HALF the
triangles of the capsules they replace while actually looking like a person.

Three poses, because a crowd of identical figures reads as wallpaper: seated,
standing, and arms-up cheering. Three MultiMeshes is still only three draw
calls for the whole house.
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
MODELS = GAME / "project" / "assets" / "models"
SOURCE = GAME / "assets-source" / "crowd"

SIDES = 6  # torso cross-section; 6 is the fewest that still reads as rounded


def ring(sides=SIDES):
    out = []
    for index in range(sides):
        theta = 2.0 * math.pi * index / sides + math.pi / sides
        out.extend([math.cos(theta), math.sin(theta)])
    return out


def flat3(points):
    return [v for p in points for v in p]


def flat2(pairs):
    return [v for p in pairs for v in p]


# Torso stations run hips -> waist -> chest -> shoulders. The waist pinch and
# the shoulder flare ARE the human silhouette; a capsule has neither.
SEATED_PATH = [
    (0.0, 0.10, 0.02),  # hips, pushed slightly forward on the seat
    (0.0, 0.06, 0.24),  # waist
    (0.0, 0.02, 0.48),  # chest
    (0.0, 0.00, 0.68),  # shoulders
    (0.0, 0.00, 0.76),  # neck
]
SEATED_SCALE = [
    (0.19, 0.15),
    (0.15, 0.12),
    (0.20, 0.14),
    (0.25, 0.15),
    (0.09, 0.08),
]

STANDING_PATH = [
    (0.0, 0.02, 0.02),
    (0.0, 0.00, 0.34),
    (0.0, 0.00, 0.66),
    (0.0, 0.00, 0.92),
    (0.0, 0.00, 1.02),
]
STANDING_SCALE = [
    (0.17, 0.14),
    (0.15, 0.12),
    (0.21, 0.14),
    (0.26, 0.15),
    (0.09, 0.08),
]


def build_body(forge, name, path, scales, tunic):
    forge.call(
        "build.sweep",
        name=name,
        profile=ring(),
        profile_scales=flat2(scales),
        path=flat3(path),
        path_shape="custom",
        closed_path=False,
        closed_profile=True,
        material="cloth",
        color=tunic,
        uv="box",
        uv_scale=1.0,
        origin=None,
        smooth=False,
        _timeout=600,
    )
    return name


def add_arms(forge, name, shoulder_z, raised, tunic):
    """Arm stubs. Only the cheering pose gets them: at crowd distance a lowered
    arm is inside the torso silhouette and costs triangles for nothing."""
    made = []
    for side, sign in (("l", 1.0), ("r", -1.0)):
        arm = f"{name}_arm_{side}"
        if raised:
            path = [
                (sign * 0.22, 0.0, shoulder_z),
                (sign * 0.30, 0.02, shoulder_z + 0.20),
                (sign * 0.30, 0.04, shoulder_z + 0.40),
            ]
            scales = [(0.075, 0.075), (0.060, 0.060), (0.050, 0.050)]
        else:
            path = [
                (sign * 0.22, 0.0, shoulder_z),
                (sign * 0.24, 0.04, shoulder_z - 0.22),
            ]
            scales = [(0.075, 0.075), (0.055, 0.055)]
        forge.call(
            "build.sweep",
            name=arm,
            profile=ring(4),
            profile_scales=flat2(scales),
            path=flat3(path),
            path_shape="custom",
            closed_path=False,
            closed_profile=True,
            material="cloth",
            color=tunic,
            uv="box",
            origin=None,
            smooth=False,
            _timeout=600,
        )
        made.append(arm)
    return made


VARIANTS = [
    ("crowd_seated", SEATED_PATH, SEATED_SCALE, False, 0.76),
    ("crowd_standing", STANDING_PATH, STANDING_SCALE, False, 1.02),
    ("crowd_cheering", STANDING_PATH, STANDING_SCALE, True, 1.02),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--tile", type=int, default=320)
    parser.add_argument("--samples", type=int, default=22)
    args = parser.parse_args()

    forge = Forge(workdir=str(REPO), out_dir=str(REPO / "assets-generated" / "bforge"))
    rows = []
    try:
        forge.start()

        for name, path, scales, raised, shoulder_z in VARIANTS:
            forge.call("session.reset")
            parts = [build_body(forge, name, path, scales, "#b8b2a4")]
            if raised:
                parts += add_arms(forge, name, shoulder_z - 0.12, True, "#b8b2a4")
            if len(parts) > 1:
                forge.call("object.join", names=parts, into=name)
            forge.call("material.consolidate", tolerance=0.02)
            forge.call(
                "gameready.pivot", objects=[name], origin="bottom", to_origin=True
            )
            info = forge.call("object.inspect", name=name)
            check = forge.call("check.asset", triangle_budget=120, material_budget=2)
            blend = forge.call("export.blend", out=f"crowd/{name}.blend")
            glb = forge.call(
                "export.gltf",
                out=f"crowd/{name}.glb",
                engine="godot",
                strict=False,
                rename={name: "Figure"},
                _timeout=600,
            )
            rows.append(
                {
                    "asset": name,
                    "triangles": info["triangles"],
                    "ok": check["ok"],
                    "kb": glb["bytes"] // 1024,
                    "blend": blend["path"],
                    "glb": glb["path"],
                }
            )
            print(
                f"{'OK ' if check['ok'] else 'CHK'} {name:16} "
                f"{info['triangles']:>4} tris  {glb['bytes'] // 1024:>3} KB"
            )
            for failure in check["failures"][:2]:
                print(f"     [{failure['level']}] {failure['msg'][:88]}")

        # The head is its own MultiMesh so it can carry a skin tone independent
        # of the tunic colour. 20 triangles, against the 96 it replaces.
        forge.call("session.reset")
        forge.call(
            "build.sphere",
            name="crowd_head",
            radius=0.105,
            kind="uv",
            segments=6,
            rings=4,
            material="cloth",
            color="#d8b48c",
            uv="smart",
            origin="center",
            smooth=True,
        )
        forge.call(
            "object.transform", name="crowd_head", scale=[0.92, 1.0, 1.12], apply=True
        )
        forge.call(
            "gameready.pivot", objects=["crowd_head"], origin="center", to_origin=True
        )
        info = forge.call("object.inspect", name="crowd_head")
        blend = forge.call("export.blend", out="crowd/crowd_head.blend")
        glb = forge.call(
            "export.gltf",
            out="crowd/crowd_head.glb",
            engine="godot",
            strict=False,
            rename={"crowd_head": "Figure"},
            _timeout=600,
        )
        rows.append(
            {
                "asset": "crowd_head",
                "triangles": info["triangles"],
                "ok": True,
                "kb": glb["bytes"] // 1024,
                "blend": blend["path"],
                "glb": glb["path"],
            }
        )
        print(
            f"OK  {'crowd_head':16} {info['triangles']:>4} tris  "
            f"{glb['bytes'] // 1024:>3} KB"
        )

        body_total = max(r["triangles"] for r in rows if r["asset"] != "crowd_head")
        print(
            f"\nper spectator: {body_total} (body) + "
            f"{rows[-1]['triangles']} (head) = "
            f"{body_total + rows[-1]['triangles']} tris   "
            f"[was 48 + 96 = 144 with capsules]"
        )

        if args.render:
            # A crowd is judged as a crowd, never one figure at a time.
            forge.call("session.reset")
            placed = []
            for row_index in range(4):
                for seat in range(9):
                    variant = VARIANTS[(row_index * 3 + seat) % 3][0]
                    label = f"c_{row_index}_{seat}"
                    forge.call(
                        "session.import",
                        path=f"assets-generated/bforge/crowd/{variant}.glb",
                        prefix=label,
                        _timeout=600,
                    )
                    obj = forge.call("object.list", prefix=label)["objects"][0]
                    at = [(seat - 4) * 0.62, -row_index * 0.95, row_index * 0.52]
                    forge.call(
                        "object.transform",
                        name=obj,
                        location=at,
                        rotation=[0, 0, 8.0 * ((seat % 3) - 1)],
                        apply=True,
                    )
                    placed.append(obj)
                    # The head is a separate MultiMesh in game; the silhouette
                    # cannot be judged without it.
                    forge.call(
                        "session.import",
                        path="assets-generated/bforge/crowd/crowd_head.glb",
                        prefix=f"h_{label}",
                        _timeout=600,
                    )
                    head = forge.call("object.list", prefix=f"h_{label}")["objects"][0]
                    shoulder = 0.76 if variant == "crowd_seated" else 1.02
                    forge.call(
                        "object.transform",
                        name=head,
                        location=[at[0], at[1], at[2] + shoulder + 0.11],
                        apply=True,
                    )
                    placed.append(head)
            shot = forge.call(
                "render.camera",
                out="crowd/crowd_block.png",
                position=[0.6, 7.4, 3.1],
                target=[0.0, -1.4, 1.0],
                lens=52.0,
                resolution=900,
                aspect=1.6,
                samples=args.samples,
                _timeout=1800,
            )
            print(f"crowd block: {shot['rel']}")

        if args.install:
            SOURCE.mkdir(parents=True, exist_ok=True)
            for row in rows:
                asset = row["asset"]
                shutil.copyfile(row["blend"], SOURCE / f"{asset}.blend")
                shutil.copyfile(row["glb"], MODELS / f"{asset}.glb")
                (SOURCE / f"{asset}.meta.json").write_text(
                    json.dumps(
                        {
                            "asset_id": asset,
                            "category": "character",
                            "license": "proprietary",
                            "source": {"origin": "generated"},
                            "creator": "studio-foundation (tools/bforge)",
                            "provenance": {
                                "method": "ai_generated",
                                "commercial_use_allowed": True,
                                "modified": False,
                                "ai": {
                                    "system": "bforge (headless Blender, allowlisted ops)",
                                    "tool": "bforge",
                                    "workflow": "games/chariot/art_source/build_spectators.py",
                                    "description": "Crowd figure for MultiMesh stands: human silhouette at crowd LOD",
                                    "deterministic": True,
                                    "human_review": "pending",
                                },
                            },
                            "games": "chariot",
                            "lod_policy": "none",
                            "collision_policy": "none",
                            "texture_policy": "compressed",
                            "animation_set": "none",
                            "budgets": {
                                "triangles": 120,
                                "materials": 2,
                                "texture_max_px": 256,
                            },
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            print(
                f"installed -> {MODELS.relative_to(REPO)} and {SOURCE.relative_to(REPO)}"
            )
        return 0
    except ForgeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        forge.stop()


if __name__ == "__main__":
    sys.exit(main())
