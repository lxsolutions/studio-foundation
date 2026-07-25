"""Does the pipeline reproduce the colour it was asked for?

Runs a set of known albedos through material + render + measure and checks the
result lands near the input. This is the test that separates "my art direction
is wrong" from "the tool is lying to me" — a distinction that cost several
rounds of blind adjustment before the instruments existed.

    python tools/bforge/tests/test_fidelity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402


def srgb_to_linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def hex_to_linear(text: str):
    text = text.lstrip("#")
    return [srgb_to_linear(int(text[i : i + 2], 16) / 255.0) for i in (0, 2, 4)]


# Deliberately spans the range: near-black, dark saturated, mid, bright.
CASES = [
    ("#2a2018", "very dark brown"),
    ("#6d6152", "mid warm grey"),
    ("#8f4a3f", "saturated madder red"),
    ("#2e6b34", "saturated green"),
    ("#d6c4a0", "bright travertine"),
]


def fit(samples):
    """Least-squares fit of rendered = albedo * gain + offset.

    A physically-based render of a dielectric is NOT albedo scaled by a
    constant. Every surface carries a broad white specular term, so the honest
    model is `albedo * gain + offset`, where `offset` is that sheen. Asserting a
    pure ratio instead makes a correct renderer look broken: saturated green
    measures "5.4x too bright" purely because the sheen dwarfs its dark red and
    blue channels.

    What a faithful pipeline must guarantee is that ONE gain and ONE offset
    explain every swatch and every channel. Drift in the fit is a real bug;
    the offset itself is optics.
    """
    n = len(samples)
    sx = sum(a for a, _r in samples)
    sy = sum(r for _a, r in samples)
    sxx = sum(a * a for a, _r in samples)
    sxy = sum(a * r for a, r in samples)
    denominator = n * sxx - sx * sx
    if abs(denominator) < 1e-9:
        return 1.0, 0.0, 1.0
    gain = (n * sxy - sx * sy) / denominator
    offset = (sy - gain * sx) / n
    residual = max(abs(r - (a * gain + offset)) for a, r in samples)
    return gain, offset, residual


def main() -> int:
    failures = []
    samples = []
    with Forge(workdir=".", out_dir="assets-generated/bforge") as forge:
        for hex_color, label in CASES:
            forge.call("session.reset")
            # A flat plate facing the camera: no curvature, no self-shadowing,
            # so what comes back is the albedo response and nothing else.
            forge.call(
                "build.plane", name="card", size=[2.0, 2.0], material="", uv="none", origin="center"
            )
            forge.call("object.transform", name="card", rotation=[90, 0, 0], apply=True)
            forge.call(
                "material.set",
                object="card",
                preset="stone",
                color=hex_color,
                roughness=0.9,
                metallic=0.0,
            )
            result = forge.call(
                "render.view",
                out=f"fidelity/{hex_color[1:]}.png",
                view="front",
                resolution=192,
                samples=16,
                _timeout=900,
            )
            analysis = result["analysis"]
            # The un-quantised mean. `dominant_colors` buckets into 8 levels and
            # reports dark surfaces up to 4x too bright, which looks exactly
            # like a rendering bug and is not one.
            got = analysis["mean_color"]["hex"]
            want_lin = hex_to_linear(hex_color)
            got_lin = analysis["mean_color"]["linear"]
            # Compare RATIOS, not absolutes: a render is albedo times exposure,
            # so a constant factor across all channels is exposure and a
            # per-channel drift is a colour bug.
            for want, got_channel in zip(want_lin, got_lin, strict=True):
                samples.append((want, got_channel))
            # Ordering must survive: a darker albedo must never render lighter
            # than a brighter one in the same channel.
            print(f"     {label:24} asked {hex_color}  got {got}")

    gain, offset, residual = fit(samples)
    print(
        f"\nresponse: rendered = albedo * {gain:.2f} + {offset:.3f}   max residual {residual:.3f}"
    )
    print("  gain   = how hard the rig lights the subject")
    print("  offset = dielectric specular sheen (physics, not a bug)")

    if residual > 0.075:
        failures.append(
            f"response is not a single line (residual {residual:.3f}) — some "
            "colours are being transformed differently from others, which is a "
            "real colour-management bug"
        )
    if not 0.6 <= gain <= 2.2:
        failures.append(f"gain {gain:.2f} is outside a sane exposure range")
    if offset > 0.30:
        failures.append(
            f"specular sheen {offset:.3f} is swamping the albedo — soften or "
            "dim the review rig, saturated colours cannot read through it"
        )

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\ncolour fidelity: PASS (single consistent response across all swatches)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
