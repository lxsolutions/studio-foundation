"""The quality bar, demonstrated end to end.

    python tools/bforge/examples/hero_shot.py [--samples 128]

Builds a Roman amphitheatre with `env.amphitheatre`, surfaces it with the
layered PBR stack (curvature-driven edge wear, occlusion-driven cavity grime,
two noise octaves plus low-frequency blotching), dresses the sand, and shoots
it with `render.cinematic` — physical sun and sky, global illumination,
atmospheric haze and a filmic tonemap.

Everything here runs on CPU. Cycles is a full path tracer, so the quality
ceiling is set by the assets and the lighting, not by a GPU.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "bforge"))

from bforge import Forge  # noqa: E402

STONE = "#c9b48c"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=110)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--quality", default="medium")
    parser.add_argument("--haze", type=float, default=0.0016)
    args = parser.parse_args()

    with Forge(workdir=str(REPO), out_dir=str(REPO / "assets-generated" / "bforge")) as forge:
        forge.call("session.reset")

        venue = forge.call(
            "env.amphitheatre",
            name="arena",
            shape="circle",
            arena_radius=38.0,
            tiers=3,
            tier_depth=9.0,
            tier_rise=5.4,
            rows_per_tier=7,
            arcade_height=9.5,
            colonnade=True,
            gateways=2,
            stone=STONE,
            stone_shade="#8c7a58",
            sand="#d9c49a",
            banner_color="#7a201a",
            quality=args.quality,
            _timeout=3600,
        )
        print(
            f"venue    : {venue['triangles']} tris, {venue['total_height_m']} m tall, "
            f"{venue['arcade_bays']} arches"
        )

        # Scatter rubble and a few props on the sand so the floor is not bare.
        forge.call(
            "prop.debris",
            name="rubble",
            count=14,
            radius=16.0,
            piece_size=0.45,
            kind="stone",
            location=[6.0, -4.0, 0.0],
            seed=5,
        )
        forge.call(
            "prop.rock",
            name="boulder",
            size=[2.6, 2.2, 1.7],
            detail=3,
            angular=True,
            location=[-11.0, 7.0, 0.0],
            seed=9,
        )

        # The surface layer — this is the step that separates clean low-poly
        # from AAA. Bake it so the venue ships with real maps, not a node graph.
        for name, base, dirt, wear in (
            ("arena", STONE, "#3a2f22", 0.45),
            ("boulder", "#7d7263", "#241c14", 0.6),
            ("rubble", "#8a7f6e", "#2b2118", 0.55),
        ):
            forge.call("uv.unwrap", object=name, style="smart_packed", margin=0.015, _timeout=1800)
            forge.call(
                "material.pbr",
                object=name,
                base_color=base,
                roughness=0.86,
                detail_scale=22.0,
                grain=0.6,
                edge_wear=wear,
                cavity_dirt=0.7,
                dirt_color=dirt,
                bump=0.45,
                seed=3,
            )
        print("surfaced : layered PBR on venue, boulder and rubble")

        critique = forge.call("check.critique", _timeout=1800)
        print(f"critique : {critique['errors']} errors, {critique['warnings']} warnings")

        # Cameras must sit INSIDE the bowl. The stands are a solid mass from
        # the podium (44 m) out to the back wall (71 m); anything placed in that
        # band is inside a wall and renders black. render.cinematic now warns
        # about this, which is how the first pass got caught.
        shots = [
            ("hero", [-24.0, -26.0, 4.5], [12.0, 22.0, 15.0], 30.0, 2.39),
            ("gate", [0.0, -27.0, 2.6], [0.0, 40.0, 13.0], 28.0, 2.39),
            ("tiers", [-10.0, -12.0, 5.0], [22.0, 26.0, 24.0], 45.0, 1.78),
        ]
        for label, position, target, lens, aspect in shots:
            shot = forge.call(
                "render.cinematic",
                out=f"hero/{label}.png",
                position=position,
                target=target,
                lens=lens,
                resolution=args.width,
                aspect=aspect,
                samples=args.samples,
                sun_energy=4.2,
                sun_angle=[38.0, 128.0],
                sky_strength=1.0,
                haze=args.haze,
                bounces=6,
                look="agx",
                _timeout=5400,
            )
            analysis = shot["analysis"]
            if "luma_linear" not in analysis:
                # A frame the instruments cannot read is a frame that is empty
                # or black; say so loudly rather than dying on a KeyError.
                print(f"{label:9}: UNREADABLE — {analysis.get('error', analysis)}")
                for note in shot.get("_notes", []):
                    print(f"           ! {note}")
                continue
            print(
                f"{label:9}: {shot['rel']}  luma {analysis['luma_linear']['mean']:.3f} "
                f"lin  contrast {analysis['luma']['contrast']:.2f}  "
                f"blown {analysis['blown_highlights']:.1%}  "
                f"sat {analysis['mean_saturation']:.2f}"
            )
            for finding in analysis["findings"] + shot.get("_notes", []):
                print(f"           ! {finding}")

        report = REPO / "assets-generated" / "bforge" / "hero_shot.json"
        report.write_text(
            json.dumps({"venue": venue, "critique": critique}, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
