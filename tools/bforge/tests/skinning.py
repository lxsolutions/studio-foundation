"""Skinning regression test: a character must rig the same wherever it stands.

These three failures all shipped silently, because a character authored at the
origin looks fine and nobody rigs a blockout anywhere else until they are
assembling a scene — at which point the figure tears itself apart and it reads
as a modelling mistake rather than a tooling one.

    python tools/bforge/tests/skinning.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402

HEIGHT = 1.72
# One arm swung forward — the pose that exposes every one of these bugs.
POSE = {"upper_arm_l": [64.0, 0.0, 0.0], "upper_arm_r": [64.0, 0.0, 0.0]}


def posed_size(forge, location, pose=POSE):
    """Build, rig, pose and bake a figure at `location`; return size, bake, area."""
    forge.call("session.reset")
    forge.call(
        "char.humanoid",
        name="f",
        height=HEIGHT,
        build="heroic",
        bulk=1.25,
        detail=8,
        location=location,
    )
    rig = forge.call("char.rig", name="f", height=HEIGHT, build="heroic")
    if pose:
        forge.call("char.pose", rig=rig.get("armature"), preset="custom", bones=pose)
    baked = forge.call("char.bake_pose", mesh="f", rig=rig.get("armature"))
    info = forge.call("object.inspect", name="f")
    return info["bounds"]["size"], baked, info["uv"]["world_area_m2"]


def main():
    failures = []
    with Forge() as forge:
        at_origin, baked_origin, _area = posed_size(forge, [0.0, 0.0, 0.0])
        offset, _baked_offset, posed_area = posed_size(forge, [0.0, -0.92, 0.55])
        _rest, _baked_rest, rest_area = posed_size(forge, [0.0, -0.92, 0.55], pose=None)

        # 1. char.bake_pose must actually write the pose into the vertices.
        # Exported without its armature, an unbaked figure ships in the rest
        # pose — standing to attention, arms at its sides.
        if float(baked_origin.get("moved", 0.0)) < 0.05:
            failures.append(
                f"char.bake_pose reported no movement: {baked_origin!r} — the pose did not bake"
            )

        # 2. THE SAME CHARACTER MUST RIG THE SAME WHEREVER IT STANDS.
        # The skinner used to compare world-space vertices against
        # armature-local bone positions, so every bone was displaced by exactly
        # the character's offset from the origin. A figure built on a vehicle
        # floor got its pelvis weighted to its shins.
        drift = max(abs(a - b) for a, b in zip(at_origin, offset, strict=True))
        if drift > 0.01:
            failures.append(
                f"rigging depends on where the character stands: at origin {at_origin} "
                f"vs offset {offset} (drift {drift:.3f}m) — skinning is solving in mixed spaces"
            )

        # 3. An arm must not bring the torso with it.
        # Arms rest at the sides, which runs the arm bones ~3cm from the flank
        # while the spine is ~19cm away, so by distance alone the arm owns the
        # waist and swings a bat-wing of torso forward with it. Depth is the
        # tell: a figure reaching forward is about one arm deep, not two.
        limit = 0.62 * HEIGHT
        if offset[1] > limit:
            failures.append(
                f"posed figure is {offset[1]:.3f}m deep, over the {limit:.3f}m an arm can "
                "reach — the torso is being dragged along with the arm"
            )

        # 4. Posing must not manufacture surface area.
        # Rotating a limb moves geometry; it does not create it. When a bone
        # captures vertices from a neighbouring shell — the arm bone taking the
        # torso's flank — the skin stretches a web between the two, and that web
        # is new area. It leaves the bounding box alone, so nothing above sees
        # it; the figure just quietly grows a bat-wing.
        growth = posed_area / rest_area if rest_area else 0.0
        if growth > 1.10:
            failures.append(
                f"posing grew the surface by {growth:.2f}x ({rest_area:.3f} -> "
                f"{posed_area:.3f} m2) — bones are dragging geometry across mesh shells"
            )

    for line in failures:
        print("FAIL:", line)
    if failures:
        return 1
    print(f"skinning OK — origin {at_origin}, offset {offset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
