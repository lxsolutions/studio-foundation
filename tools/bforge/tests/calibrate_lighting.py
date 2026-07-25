"""Calibrate the render light rig against a known grey card.

    python tools/bforge/tests/calibrate_lighting.py

A neutral 18% grey sphere must come back reading ~0.18 linear. If it reads
brighter, every material in every review render is being judged through an
over-exposed rig — which is exactly how a correct dark stone albedo got
mistaken for a broken material, three times, before check.image existed.

Run at several subject scales: the rig scales light power with radius squared,
so a calibration that only holds for one size is not a calibration.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402

TARGET = 0.18
SIZES = [0.25, 1.0, 4.0, 20.0]


def main() -> int:
    rows = []
    with Forge(workdir=".", out_dir="assets-generated/bforge") as forge:
        for size in SIZES:
            forge.call("session.reset")
            # 18% grey in LINEAR, the standard photographic mid-tone.
            forge.call(
                "build.sphere",
                name="card",
                kind="ico",
                subdivisions=3,
                radius=size,
                material="",
                uv="none",
                origin="center",
            )
            forge.call(
                "material.set",
                object="card",
                preset="stone",
                color=[0.18, 0.18, 0.18],
                roughness=0.9,
                metallic=0.0,
            )
            result = forge.call(
                "render.view",
                out=f"calib/grey_{size}.png",
                resolution=256,
                samples=16,
                _timeout=900,
            )
            analysis = result["analysis"]
            # LINEAR, not the displayed sRGB value. Albedo and light power are
            # physical quantities; comparing them against a display-encoded
            # number misreads exposure by about 2x.
            mean = analysis["luma_linear"]["mean"]
            rows.append((size, mean, analysis["subject_coverage"], analysis["blown_highlights"]))
            print(
                f"radius {size:>5} m  ->  linear luma {mean:.3f}  "
                f"(target {TARGET:.2f}, off by {mean / TARGET:.2f}x)  "
                f"coverage {analysis['subject_coverage']:.2f}  "
                f"blown {analysis['blown_highlights']:.1%}"
            )

    ratios = [mean / TARGET for _s, mean, _c, _b in rows if mean > 0]
    if not ratios:
        print("\nno usable samples")
        return 1
    average = sum(ratios) / len(ratios)
    spread = max(ratios) / min(ratios)
    print(f"\nmean over-exposure {average:.2f}x   scale-consistency {spread:.2f}x")
    if average > 1.25 or average < 0.8:
        print(f"ACTION: divide the key-light constant in render.py by {average:.2f}")
        return 1
    if spread > 1.6:
        print("ACTION: exposure drifts with subject size — the radius**2 law is off")
        return 1
    print("light rig is calibrated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
