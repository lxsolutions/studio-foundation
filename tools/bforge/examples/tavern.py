"""Worked example: compose a complete game scene, then ship it.

Builds a stone tavern interior — room shell, furniture, barrels, crates, a lit
brazier and an armed character — then validates it, gives it collision, and
exports a single GLB. Roughly what an agent does when asked for "a tavern".

    python tools/bforge/examples/tavern.py [--out docs/bforge/tavern.png]

The point is not any single prop. It is that composition holds together: shared
palette, one grid, consistent texel density, everything origin-correct so it
sits on the floor instead of through it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402

GRID = 4.0
UV_SCALE = 2.0  # one texel density for every surface in the scene


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="assets-generated/bforge/tavern/tavern.png")
    parser.add_argument("--tile", type=int, default=440)
    parser.add_argument("--samples", type=int, default=36)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    forge = Forge(workdir=".", out_dir="assets-generated/bforge")
    try:
        forge.start()
        forge.call("session.reset")

        # --- shell -----------------------------------------------------
        forge.call(
            "kit.room",
            name="tavern",
            size=[2, 2],
            grid=GRID,
            height=3.2,
            doors=1,
            windows=2,
            pillars=True,
            material="stone",
            uv_scale=UV_SCALE,
            seed=11,
        )

        # --- furniture -------------------------------------------------
        forge.call(
            "prop.furniture",
            name="long_table",
            kind="table",
            size=[2.4, 1.0, 0.78],
            location=[4.0, 3.2, 0.0],
            seed=2,
        )
        for index, x in enumerate((2.9, 5.1)):
            forge.call(
                "prop.furniture",
                name=f"bench_{index}",
                kind="bench",
                size=[2.2, 0.42, 0.45],
                location=[x, 3.2, 0.0],
                round_legs=True,
                seed=3 + index,
            )
        forge.call(
            "prop.furniture",
            name="shelf",
            kind="shelf",
            size=[1.6, 0.4, 2.0],
            location=[1.2, 7.4, 0.0],
            seed=6,
        )

        # --- clutter ---------------------------------------------------
        for index, (x, y) in enumerate([(1.0, 1.1), (1.9, 1.0), (1.3, 1.9)]):
            forge.call(
                "prop.barrel",
                name=f"barrel_{index}",
                height=0.95,
                radius=0.30,
                location=[x, y, 0.0],
                seed=20 + index,
            )
        for index, (x, y, z) in enumerate([(6.9, 1.1, 0.0), (6.6, 1.9, 0.0), (6.9, 1.1, 0.9)]):
            forge.call(
                "prop.crate",
                name=f"crate_{index}",
                size=[0.85, 0.85, 0.85],
                location=[x, y, z],
                seed=30 + index,
            )
        forge.call("prop.sack", name="sack_a", location=[5.9, 1.4, 0.0], seed=41)
        forge.call(
            "prop.chest",
            name="chest_a",
            location=[6.4, 6.6, 0.0],
            separate_lid=False,
            seed=42,
        )
        forge.call(
            "prop.debris",
            name="floor_debris",
            count=7,
            radius=1.4,
            piece_size=0.10,
            location=[4.0, 5.6, 0.0],
            seed=43,
        )

        # --- light source ----------------------------------------------
        forge.call(
            "prop.torch",
            name="brazier",
            style="brazier",
            height=1.05,
            location=[4.0, 6.9, 0.0],
            emission=8.0,
            seed=50,
        )

        # --- an inhabitant ---------------------------------------------
        forge.call("char.humanoid", name="keeper", height=1.78, build="realistic", seed=61)
        forge.call(
            "object.transform",
            name="keeper",
            location=[4.0, 4.6, 0.0],
            rotation=[0, 0, 180],
            apply=True,
        )
        rig = forge.call("char.rig", name="keeper", build="realistic")
        forge.call("char.pose", rig=rig["armature"], preset="a_pose")
        forge.call("prop.weapon", name="cleaver", kind="dagger", length=0.42, seed=62)
        forge.call(
            "char.attach", prop="cleaver", rig=rig["armature"], bone="hand_r", offset=[0, 0, -0.05]
        )

        # --- review ------------------------------------------------------
        info = forge.call("session.info")
        budget = forge.call("gameready.budget", profile="browser_webgpu", asset_class="environment")
        critique = forge.call("check.critique")

        print(
            f"scene    : {info['object_count']} objects, "
            f"{info['total_triangles']} triangles, "
            f"{len(info['materials'])} materials"
        )
        print(
            f"budget   : {'within' if budget['within_budget'] else 'OVER'} "
            f"browser_webgpu/environment ({budget['triangle_budget']} per object)"
        )
        print(f"critique : {critique['errors']} errors, {critique['warnings']} warnings")
        for finding in critique["findings"][:6]:
            print(f"           [{finding['severity']}] {finding['object']}: {finding['issue']}")

        sheet = forge.call(
            "render.contact_sheet",
            out=args.out,
            tile=args.tile,
            samples=args.samples,
            panels=["hero", "low", "top", "wireframe"],
            columns=4,
            _timeout=1800,
        )
        print(f"render   : {sheet['rel']}")

        if args.export:
            forge.call("gameready.collision", name="tavern", mode="simplified", ratio=0.3)
            exported = forge.call(
                "export.asset",
                asset_id="tavern_scene",
                out_dir="tavern",
                engine="godot",
                category="environment",
                ai_prompt="a stone tavern interior with furniture, clutter, a brazier and a keeper",
                contact_sheet=False,
                strict=False,
                _timeout=1800,
            )
            print(f"export   : {json.dumps(exported['outputs'], indent=13)}")
        return 0
    finally:
        forge.stop()


if __name__ == "__main__":
    sys.exit(main())
