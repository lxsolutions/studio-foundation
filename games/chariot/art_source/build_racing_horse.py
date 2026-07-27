"""Build The Chariot Club's racing horse — anatomy, tack, rig and gallop.

    python games/chariot/art_source/build_racing_horse.py [--render] [--install]

The shipping horse was 332 triangles of stacked boxes: a Minecraft pony. This
builds a real one.

The body, neck and head are a single swept form whose cross-section is scaled
per station along the spine, which is how you get the shapes that actually make
a horse read: a deep girth behind the elbow, a narrowed loin, a rounded croup,
a crested neck that is deep and narrow where the barrel is wide and shallow.
Legs are swept the same way, so the forearm swells and the cannon bone stays
thin, with the knee, hock and fetlock as bulges rather than boxes.

Contract with the game (broadcast_view.gd):
  * one mesh node named `Horse`
  * materials named `Coat`, `Sock`, `Cloth`, `Plume` — the tint code looks them
    up by name and recolours per stable
  * an AnimationPlayer with a clip named `Gallop`, speed-scaled by the sim
  * forward is -Z in Godot, so the model is built facing +Y in Blender

The master keeps snake_case names for `just asset-validate`; the exporter's
rename map applies the engine-facing names to the GLB only.
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
MODEL_PATH = GAME / "project" / "assets" / "models" / "racing_horse.glb"
SOURCE = GAME / "assets-source" / "horse"

# Withers height of a Roman chariot horse: they were small, roughly 14-15 hands.
WITHERS = 1.52
# An ellipse cross-section. Everything downstream scales this, so it stays unit.
RING = 14


def ellipse(sides=RING, width=1.0, height=1.0):
    """Cross-section as a flat [lateral, vertical, ...] list."""
    out = []
    for index in range(sides):
        theta = 2.0 * math.pi * index / sides
        out.extend([math.cos(theta) * width, math.sin(theta) * height])
    return out


# How much narrower the top of the section is than the bottom.
BARREL_TAPER = 0.26


def barrel(sides=RING, taper=BARREL_TAPER):
    """A horse's cross-section, which is an EGG and not an ellipse.

    The belly is broad and round; the back narrows towards the ridge of the
    spine. Swept with a plain ellipse the whole animal comes out slab-sided —
    the same width at the backbone as at the deepest part of the barrel — which
    is most of why it read as a goat rather than a horse.

    The same egg is right the whole way along the sweep: a neck is narrow at the
    crest and wide where it meets the shoulder, and a head is narrow across the
    forehead and broad through the jaw.
    """
    out = []
    for index in range(sides):
        theta = 2.0 * math.pi * index / sides
        vertical = math.sin(theta)
        out.extend([math.cos(theta) * (1.0 - taper * vertical), vertical])
    return out


def flat3(points):
    return [value for point in points for value in point]


def flat2(pairs):
    return [value for pair in pairs for value in pair]


# --- the spine -------------------------------------------------------------
# (y forward, z up). One continuous run from tail-base to muzzle: a horse has no
# seam between barrel, neck and head and modelling one is what makes the join
# look glued together.
# Proportions are anchored to withers height H, the way a horse is actually
# measured. Body length = H. Head = 0.40H. Neck = 0.40H. Ground to elbow =
# 0.53H. Get the head length wrong and you do not get a stylised horse, you get
# a llama — which is exactly what the first attempt produced at 0.36 m.
SPINE = [
    (0.0, -0.86, 1.14),  # dock (tail base)
    # THE WITHERS ARE THE HIGH POINT OF A HORSE. Level with the croup — which
    # is how this was — the topline reads as a pony or a goat however good the
    # rest is. The back dips slightly between them, and rises again to the
    # quarters.
    (0.0, -0.66, 1.21),  # croup
    (0.0, -0.42, 1.22),  # rump: widest point behind
    (0.0, -0.14, 1.15),  # loin
    (0.0, 0.14, 1.15),  # barrel
    (0.0, 0.34, 1.18),  # girth: deepest part of the horse
    (0.0, 0.52, 1.27),  # withers: highest point of the back
    (0.0, 0.68, 1.34),  # base of neck
    (0.0, 0.84, 1.54),  # mid crest
    (0.0, 0.96, 1.68),  # upper crest
    (0.0, 1.04, 1.76),  # poll
    (0.0, 1.18, 1.72),  # forehead
    (0.0, 1.36, 1.58),  # nasal bone
    (0.0, 1.50, 1.44),  # muzzle  (poll->muzzle = 0.56 m)
]

# (lateral, vertical) multipliers at each spine station. This list IS the horse:
# wide-and-shallow through the barrel, narrow-and-deep up the crest of the neck.
SPINE_SCALE = [
    (0.10, 0.12),  # dock: thin
    (0.28, 0.27),  # croup: broad and round
    (0.32, 0.31),  # rump: the quarters are the engine, and look it
    (0.235, 0.30),  # loin: tucks up and in — a racehorse is cut away here
    (0.29, 0.37),  # barrel
    (0.31, 0.40),  # girth: deepest, and deeper than the flank by a clear margin
    (0.25, 0.35),  # withers
    # DEEP BUT NARROW. A neck as wide as it is deep is a llama's; a horse's is
    # a blade, tall from crest to gullet and thin across.
    (0.145, 0.30),  # neck base
    (0.110, 0.25),  # crest: narrow and deep
    (0.090, 0.21),
    (0.078, 0.16),  # poll
    (0.095, 0.13),  # forehead
    (0.075, 0.105),  # nasal
    (0.070, 0.085),  # muzzle
]

# --- legs ------------------------------------------------------------------
# Each leg is a swept taper. Joints are bulges in the scale ramp, not boxes.
FORE_LEG = [
    (0.0, 0.02, 1.02),  # shoulder
    (0.0, 0.06, 0.80),  # upper arm
    (0.0, 0.00, 0.62),  # elbow
    (0.0, 0.01, 0.44),  # forearm
    (0.0, 0.00, 0.30),  # knee
    (0.0, 0.00, 0.16),  # cannon
    (0.0, 0.01, 0.07),  # fetlock
    (0.0, 0.04, 0.015),  # pastern
    (0.0, 0.05, 0.0),  # hoof
]
# A foreleg is a heavy muscled forearm running down to a fine cannon — the
# taper is most of what says "horse". At barely 1.5x from forearm to cannon it
# was a spindle with a knee drawn on it; a real one is nearer 2.5x.
FORE_SCALE = [
    (0.135, 0.150),  # shoulder
    (0.120, 0.135),  # upper arm
    (0.100, 0.116),  # elbow
    (0.078, 0.095),  # forearm: the muscle
    (0.058, 0.066),  # knee
    (0.036, 0.044),  # cannon: the fine bone
    (0.042, 0.048),  # fetlock
    (0.046, 0.046),  # pastern
    (0.056, 0.052),  # hoof
]

HIND_LEG = [
    (0.0, -0.06, 1.06),  # hip
    (0.0, -0.02, 0.84),  # thigh
    (0.0, 0.02, 0.64),  # stifle
    (0.0, -0.08, 0.46),  # gaskin, swinging back
    (0.0, -0.11, 0.34),  # hock
    (0.0, -0.04, 0.18),  # cannon
    (0.0, -0.01, 0.07),  # fetlock
    (0.0, 0.02, 0.015),  # pastern
    (0.0, 0.03, 0.0),  # hoof
]
HIND_SCALE = [
    (0.150, 0.170),
    (0.135, 0.155),
    (0.105, 0.125),
    (0.070, 0.090),
    (0.058, 0.070),
    (0.036, 0.040),
    (0.042, 0.044),
    (0.048, 0.044),
    (0.056, 0.050),
]

# WHERE ALONG THE HORSE EACH PAIR OF LEGS STANDS.
#
# FORE_LEG and HIND_LEG describe the SHAPE of a leg — the S of a foreleg, the
# stifle-and-hock zigzag of a hind leg — around their own origin. They were
# never translated to where the legs actually attach, so all four columns
# descended at y~0 and every hoof landed in a bunch under the belly, with
# nothing under the chest and nothing under the quarters. That is what made the
# gallop read as a kangaroo hop: the animation was fine, the horse had its legs
# in the wrong place. Rewriting the gait could never have fixed it.
FORE_Y = 0.38
HIND_Y = -0.30
FORE_X = 0.155
HIND_X = 0.175


def offset(points, dx, dy=0.0):
    return [(x + dx, y + dy, z) for x, y, z in points]


def build_horse(forge, quality):
    ring = {"low": 8, "medium": 12, "high": 16}[quality]
    forge.call("session.reset")
    parts = []

    # --- body, neck and head as one continuous sweep --------------------
    forge.call(
        "build.sweep",
        name="horse",
        profile=barrel(ring),
        profile_scales=flat2(SPINE_SCALE),
        path=flat3(SPINE),
        path_shape="custom",
        closed_path=False,
        closed_profile=True,
        material="cloth",
        color="#8a5a34",
        uv="smart_packed",
        origin=None,
        smooth=True,
        _timeout=600,
    )
    parts.append("horse")

    # --- legs -----------------------------------------------------------
    for side, sign in (("l", 1.0), ("r", -1.0)):
        forge.call(
            "build.sweep",
            name=f"foreleg_{side}",
            profile=ellipse(max(6, ring - 4)),
            profile_scales=flat2(FORE_SCALE),
            path=flat3(offset(FORE_LEG, sign * FORE_X, FORE_Y)),
            path_shape="custom",
            closed_path=False,
            closed_profile=True,
            material="cloth",
            color="#8a5a34",
            uv="smart",
            origin=None,
            smooth=True,
            _timeout=600,
        )
        forge.call(
            "build.sweep",
            name=f"hindleg_{side}",
            profile=ellipse(max(6, ring - 4)),
            profile_scales=flat2(HIND_SCALE),
            path=flat3(offset(HIND_LEG, sign * HIND_X, HIND_Y)),
            path_shape="custom",
            closed_path=False,
            closed_profile=True,
            material="cloth",
            color="#8a5a34",
            uv="smart",
            origin=None,
            smooth=True,
            _timeout=600,
        )
        parts += [f"foreleg_{side}", f"hindleg_{side}"]

        # Hooves get their own dark material via the Sock slot later; here they
        # are just a flared cylinder so the leg does not end in a point.
        forge.call(
            "build.cylinder",
            name=f"hoof_{side}_f",
            radius=0.062,
            radius_top=0.056,
            depth=0.075,
            segments=8,
            location=[sign * FORE_X, 0.05 + FORE_Y, 0.037],
            material="rubber",
            color="#2b2118",
            uv="cylinder",
            origin="center",
            smooth=False,
        )
        forge.call(
            "build.cylinder",
            name=f"hoof_{side}_h",
            radius=0.062,
            radius_top=0.056,
            depth=0.075,
            segments=8,
            location=[sign * HIND_X, 0.03 + HIND_Y, 0.037],
            material="rubber",
            color="#2b2118",
            uv="cylinder",
            origin="center",
            smooth=False,
        )
        parts += [f"hoof_{side}_f", f"hoof_{side}_h"]

        # Ears: small cones, angled outward and forward.
        forge.call(
            "build.cylinder",
            name=f"ear_{side}",
            radius=0.032,
            radius_top=0.0,
            depth=0.13,
            segments=6,
            location=[sign * 0.052, 1.08, 1.80],
            material="cloth",
            color="#8a5a34",
            uv="cylinder",
            origin="center",
            smooth=True,
        )
        forge.call(
            "object.transform",
            name=f"ear_{side}",
            rotation=[-16.0, 0.0, sign * -14.0],
            apply=True,
        )
        parts.append(f"ear_{side}")

    # --- jaw: a horse's head is not a cone ------------------------------
    forge.call(
        "build.sphere",
        name="jaw",
        radius=0.085,
        kind="ico",
        subdivisions=2,
        location=[0.0, 1.13, 1.60],
        material="cloth",
        color="#8a5a34",
        uv="smart",
        origin="center",
        smooth=True,
    )
    forge.call("object.transform", name="jaw", scale=[0.95, 1.35, 1.05], apply=True)
    parts.append("jaw")

    # --- mane: a crest strip, swept along the neck -----------------------
    # A MANE SITS ON THE CREST, NOT INSIDE THE NECK.
    #
    # This path used to follow the spine's own centreline, which is where the
    # sweep for the NECK is generated from — so the whole mane was buried a
    # quarter of a metre inside the animal and had never once been visible. It
    # is the neck's TOP SURFACE that is wanted: the spine station plus that
    # station's vertical half-scale.
    # A mane runs from the WITHERS to the poll, not just the top third — and it
    # sits a little proud of the crest so the hair stands off the neck.
    mane_path = [
        (0.0, 0.54, 1.65),  # withers:    1.27 + 0.35, where the mane starts
        (0.0, 0.70, 1.68),  # neck base:  1.34 + 0.30
        (0.0, 0.84, 1.83),  # mid crest:  1.54 + 0.25
        (0.0, 0.96, 1.92),  # upper:      1.68 + 0.21
        (0.0, 1.06, 1.94),  # poll:       1.76 + 0.16
    ]
    forge.call(
        "build.sweep",
        name="mane",
        profile=[-0.018, -0.10, 0.018, -0.10, 0.030, 0.055, -0.030, 0.055],
        # Fuller along the crest so it reads at race distance instead of
        # vanishing into the neck it sits on.
        profile_scales=[1.05, 0.95, 1.30, 1.25, 1.35, 1.25, 1.15, 1.00, 0.80, 0.55],
        path=flat3(mane_path),
        path_shape="custom",
        closed_path=False,
        closed_profile=True,
        material="cloth",
        color="#2a1b12",
        uv="box",
        uv_scale=0.5,
        origin=None,
        smooth=False,
        _timeout=600,
    )
    # Forelock between the ears.
    forge.call(
        "build.cylinder",
        name="forelock",
        radius=0.055,
        radius_top=0.02,
        depth=0.20,
        segments=6,
        location=[0.0, 1.13, 1.74],
        material="cloth",
        color="#2a1b12",
        uv="cylinder",
        origin="center",
        smooth=False,
    )
    forge.call("object.transform", name="forelock", rotation=[62.0, 0, 0], apply=True)
    parts += ["mane", "forelock"]

    # --- tail: arched, thick at the dock ---------------------------------
    tail_path = [
        (0.0, -0.78, 1.06),
        (0.0, -0.90, 1.02),
        (0.0, -0.99, 0.88),
        (0.0, -1.03, 0.68),
        (0.0, -1.02, 0.50),
    ]
    forge.call(
        "build.sweep",
        name="tail",
        profile=ellipse(8),
        # A TAIL IS A MASS OF HAIR, NOT A CONE. Tapering steadily to 0.022 gave
        # a rat's tail — a smooth horn coming off the quarters. A real one is
        # thin only at the dock, swells immediately below it where the hair
        # falls, and carries most of that volume nearly to the end.
        profile_scales=[
            0.075,
            0.085,   # dock: the bone, and the only thin part
            0.105,
            0.130,   # the hair takes over and it thickens at once
            0.105,
            0.140,
            0.085,
            0.125,
            0.055,
            0.085,   # still full at the tip, not a point
        ],
        path=flat3(tail_path),
        path_shape="custom",
        closed_path=False,
        closed_profile=True,
        material="cloth",
        color="#2a1b12",
        uv="cylinder",
        origin=None,
        smooth=True,
        _timeout=600,
    )
    parts.append("tail")

    # --- Roman harness ---------------------------------------------------
    # Breastcollar: the strap a chariot horse actually pulls against.
    forge.call(
        "build.sweep",
        name="breastcollar",
        profile=[-0.030, -0.075, 0.030, -0.075, 0.030, 0.075, -0.030, 0.075],
        path=flat3(
            [
                (-0.20, 0.60, 1.00),
                (-0.10, 0.72, 0.96),
                (0.0, 0.75, 0.95),
                (0.10, 0.72, 0.96),
                (0.20, 0.60, 1.00),
            ]
        ),
        path_shape="custom",
        closed_path=False,
        closed_profile=True,
        material="cloth",
        color="#7d1f1f",
        uv="box",
        uv_scale=0.6,
        origin=None,
        smooth=False,
        _timeout=600,
    )
    # Girth strap around the barrel.
    forge.call(
        "build.sweep",
        name="girth",
        profile=[-0.028, -0.055, 0.028, -0.055, 0.028, 0.055, -0.028, 0.055],
        path=flat3(
            [
                (0.0, 0.30, 0.74),
                (0.24, 0.30, 0.92),
                (0.30, 0.30, 1.12),
                (0.16, 0.30, 1.28),
                (0.0, 0.30, 1.32),
                (-0.16, 0.30, 1.28),
                (-0.30, 0.30, 1.12),
                (-0.24, 0.30, 0.92),
                (0.0, 0.30, 0.74),
            ]
        ),
        path_shape="custom",
        closed_path=True,
        closed_profile=True,
        material="cloth",
        color="#7d1f1f",
        uv="box",
        uv_scale=0.6,
        origin=None,
        smooth=False,
        _timeout=600,
    )
    # Bridle: browband + noseband + cheek pieces.
    forge.call(
        "build.sweep",
        name="noseband",
        profile=[-0.016, -0.030, 0.016, -0.030, 0.016, 0.030, -0.016, 0.030],
        path=flat3(
            [
                (0.0, 1.235, 1.685),
                (0.062, 1.245, 1.625),
                (0.0, 1.255, 1.565),
                (-0.062, 1.245, 1.625),
                (0.0, 1.235, 1.685),
            ]
        ),
        path_shape="custom",
        closed_path=True,
        closed_profile=True,
        material="cloth",
        color="#3a2415",
        uv="box",
        uv_scale=0.4,
        origin=None,
        smooth=False,
        _timeout=600,
    )
    forge.call(
        "build.sweep",
        name="browband",
        profile=[-0.016, -0.028, 0.016, -0.028, 0.016, 0.028, -0.016, 0.028],
        path=flat3(
            [
                (0.0, 1.10, 1.78),
                (0.070, 1.13, 1.70),
                (0.052, 1.20, 1.58),
                (0.0, 1.22, 1.545),
                (-0.052, 1.20, 1.58),
                (-0.070, 1.13, 1.70),
                (0.0, 1.10, 1.78),
            ]
        ),
        path_shape="custom",
        closed_path=True,
        closed_profile=True,
        material="cloth",
        color="#3a2415",
        uv="box",
        uv_scale=0.4,
        origin=None,
        smooth=False,
        _timeout=600,
    )
    parts += ["breastcollar", "girth", "noseband", "browband"]

    # --- plume: the stable's colours, worn on the head -------------------
    forge.call(
        "build.sweep",
        name="plume",
        profile=ellipse(6),
        profile_scales=[0.020, 0.020, 0.055, 0.070, 0.048, 0.062, 0.020, 0.026],
        path=flat3(
            [(0.0, 1.10, 1.80), (0.0, 1.09, 1.90), (0.0, 1.06, 2.00), (0.0, 1.01, 2.07)]
        ),
        path_shape="custom",
        closed_path=False,
        closed_profile=True,
        material="cloth",
        color="#c8b23c",
        uv="cylinder",
        origin=None,
        smooth=False,
        _timeout=600,
    )
    forge.call(
        "build.cylinder",
        name="plume_boss",
        radius=0.042,
        depth=0.05,
        segments=8,
        location=[0.0, 1.105, 1.785],
        material="gold",
        uv="cylinder",
        origin="center",
        smooth=True,
    )
    parts += ["plume", "plume_boss"]

    return parts, ring


# --- skeleton --------------------------------------------------------------
# A real quadruped chain. Named snake_case so the studio validator accepts it.
def horse_bones():
    bones = [
        {
            "name": "root",
            "head": [0, -0.30, 1.10],
            "tail": [0, 0.10, 1.10],
            "parent": "",
        },
        {
            "name": "spine",
            "head": [0, 0.10, 1.10],
            "tail": [0, 0.40, 1.15],
            "parent": "root",
        },
        {
            "name": "chest",
            "head": [0, 0.40, 1.15],
            "tail": [0, 0.62, 1.14],
            "parent": "spine",
        },
        {
            "name": "neck",
            "head": [0, 0.62, 1.14],
            "tail": [0, 0.92, 1.52],
            "parent": "chest",
        },
        {
            "name": "head",
            "head": [0, 0.92, 1.52],
            "tail": [0, 1.30, 1.58],
            "parent": "neck",
        },
        {
            "name": "croup",
            "head": [0, -0.30, 1.10],
            "tail": [0, -0.66, 1.12],
            "parent": "root",
        },
        {
            "name": "tail_a",
            "head": [0, -0.78, 1.06],
            "tail": [0, -0.95, 0.96],
            "parent": "croup",
        },
        {
            "name": "tail_b",
            "head": [0, -0.95, 0.96],
            "tail": [0, -1.03, 0.60],
            "parent": "tail_a",
        },
    ]
    for side, sign in (("l", 1.0), ("r", -1.0)):
        x_f, x_h = sign * FORE_X, sign * HIND_X
        bones += [
            {
                "name": f"shoulder_{side}",
                "head": [0, 0.40, 1.12],
                "tail": [x_f, 0.04 + FORE_Y, 0.98],
                "parent": "chest",
            },
            {
                "name": f"forearm_{side}",
                "head": [x_f, 0.04 + FORE_Y, 0.98],
                "tail": [x_f, 0.00 + FORE_Y, 0.44],
                "parent": f"shoulder_{side}",
            },
            {
                "name": f"fore_cannon_{side}",
                "head": [x_f, 0.00 + FORE_Y, 0.44],
                "tail": [x_f, 0.01 + FORE_Y, 0.10],
                "parent": f"forearm_{side}",
            },
            {
                "name": f"fore_hoof_{side}",
                "head": [x_f, 0.01 + FORE_Y, 0.10],
                "tail": [x_f, 0.06 + FORE_Y, 0.0],
                "parent": f"fore_cannon_{side}",
            },
            {
                "name": f"thigh_{side}",
                "head": [0, -0.30, 1.10],
                "tail": [x_h, -0.03 + HIND_Y, 0.66],
                "parent": "croup",
            },
            {
                "name": f"gaskin_{side}",
                "head": [x_h, -0.03 + HIND_Y, 0.66],
                "tail": [x_h, -0.11 + HIND_Y, 0.34],
                "parent": f"thigh_{side}",
            },
            {
                "name": f"hind_cannon_{side}",
                "head": [x_h, -0.11 + HIND_Y, 0.34],
                "tail": [x_h, -0.01 + HIND_Y, 0.10],
                "parent": f"gaskin_{side}",
            },
            {
                "name": f"hind_hoof_{side}",
                "head": [x_h, -0.01 + HIND_Y, 0.10],
                "tail": [x_h, 0.04 + HIND_Y, 0.0],
                "parent": f"hind_cannon_{side}",
            },
        ]
    return bones


# A transverse gallop is FOUR separate beats, and the whole difference between
# a gallop and a bound is that the four legs are out of PHASE with each other.
# The hand-authored poses this replaces moved left and right together — thigh_l
# and thigh_r both swinging forward, then both back — which is a bound, the
# gait a rabbit or a kangaroo uses. It read exactly like that in game.
#
# Footfall order, left lead: off-hind, near-hind, off-fore, near-fore, then all
# four leave the ground. These are fractions of one stride.
LEG_PHASE = {
    "hind_r": 0.00,
    "hind_l": 0.13,
    "fore_r": 0.47,
    "fore_l": 0.60,
}

# A GALLOP IS NOT SYMMETRIC. It has a LEAD.
#
# The footfall order above — off-hind, near-hind, off-fore, near-fore — is a
# LEFT lead: the near fore lands last and reaches furthest, and it is the limb
# the horse balances the whole stride around. Giving both sides the same
# amplitude produces a gait that is technically four-beat and still reads
# mechanical, because a real horse is visibly lopsided and every photograph of
# one shows it.
#
# Left is also the correct lead to bake for this track. The oval turns one way,
# horses lead with the INSIDE leg, and a single clip can only carry one lead —
# so it should be the one the corners actually ask for.
LEAD_SIDE = "l"
LEAD_REACH = 1.18     # the leading limb swings this much further
OFF_REACH = 0.86      # and its partner correspondingly less
# Each joint down a limb lags the one above it and swings less: that delay is
# what makes a leg look jointed rather than like a swinging stick.
# A LEG JOINT ONLY BENDS ONE WAY.
#
# The hip and shoulder swing fore and aft, so a sine is right for them. A hock
# or a knee does not: it flexes from straight and returns to straight, and it
# cannot go past straight in the other direction. Driving them with a sine like
# the hip meant that for half of every stride they bent FORWARD through
# straight — a hyperextension no horse can make — which is the cross-legged,
# broken-stick look the gallop had.
#
# Flexion is therefore a raised cosine pinned at zero: fully folded at mid-swing
# when the leg is passing under the body, dead straight at mid-stance when it is
# carrying weight, and never once positive.
JOINT_LAG = 0.05
# A galloping horse reaches: the lead foreleg swings well ahead of the chest and
# the hind legs drive out behind the quarters. Small amplitudes read as a horse
# running on the spot, which is what these were.
HIND_SWING = 50.0                 # hip, fore and aft
HIND_FLEX = (66.0, 36.0)          # gaskin (hock), cannon — flexion only
FORE_SWING = 50.0                 # shoulder, fore and aft
FORE_FLEX = (72.0, 30.0)          # forearm (knee), cannon — flexion only

# HOW FAR THE ANIMATION ITSELF SAYS ONE STRIDE COVERS.
#
# This is not a taste value, it falls out of the geometry: a planted hoof has to
# stay still, so the ground the body covers during stance must equal the sweep
# of the leg over the same time. Sweep is 2 * (hip height) * sin(swing), and
# stance is STANCE of the cycle:
#
#     stride = 2 * 1.10 * sin(50 deg) / 0.30 = 5.62 m
#
# The client divides by this to pick the playback rate, so the hooves hold the
# ground at ANY speed instead of only at the one the clip happened to suit.
# Change the swing or the stance and this changes with it — recompute, do not
# guess, and keep the number in step with games/chariot/project (track_spec's
# neighbours) via the constant in broadcast_view.gd.
HIP_HEIGHT_M = 1.10


# A GALLOPING HORSE IS AIRBORNE MOST OF THE TIME.
#
# Each hoof is on the ground for about a quarter of a stride, not half of it.
# The difference is not cosmetic, it is the whole reason the gait reads as
# floating: at 16.5 m/s on a 0.533s cycle the body travels 4.4m during a
# half-cycle stance, while the leg can only sweep 1.42m back relative to the
# body (2 x 1.06m x sin 42). The other 3m is the planted hoof skating forward
# across the sand. Cutting stance to 0.30 cuts that error by more than half,
# and it is what a horse actually does.
STANCE = 0.30

# Where each limb pivots, in metres off the ground. thigh_* turns about its head
# at 1.10 and shoulder_* about its head at 1.12, so a hind leg and a fore leg
# sweep slightly different arcs for the same angle.
HIND_PIVOT_M = 1.10
FORE_PIVOT_M = 1.12


def limb_sweep(pivot_m, swing_deg):
    """How far this limb's foot travels backward relative to the body."""
    return 2.0 * pivot_m * math.sin(math.radians(swing_deg))


def _stride_m():
    """Ground one stride covers — the mean of what the four limbs sweep.

    Every limb then takes `its own sweep / this` as its stance fraction, which
    is what makes each planted foot hold still. Averaging over the four is what
    keeps those fractions centred on STANCE rather than drifting off it.
    """
    from_limbs = []
    for reach in (LEAD_REACH, OFF_REACH):
        from_limbs.append(limb_sweep(HIND_PIVOT_M, HIND_SWING * reach))
        from_limbs.append(limb_sweep(FORE_PIVOT_M, FORE_SWING * reach))
    return sum(from_limbs) / len(from_limbs) / STANCE


def _flex(turn, phase, amplitude, stance, lag=0.0):
    """One joint's flexion, in degrees, always <= 0.

    Dead straight through the whole stance, carrying the horse. All the folding
    happens airborne: the leg leaves the ground straight, folds tightly as it
    passes under the body, and is straight again by the time it reaches out to
    land.

    A cosine that merely peaks at mid-swing is not the same thing — it leaves
    the leg still half folded at the moment it should be reaching, so the horse
    paws at the ground instead of striding, and never covers any distance.
    """
    turned = (turn - phase - lag) % 1.0
    if turned < stance:
        return 0.0
    swing = (turned - stance) / (1.0 - stance)
    return -amplitude * math.sin(math.pi * swing)


def _swing(turn, phase, amplitude, stance, lag=0.0):
    """Hip or shoulder angle: forward is positive.

    Two different motions, not one sine. While the hoof is PLANTED the horse
    rotates over it at a constant rate, so the angle runs from full forward to
    full back in a straight line — that steady sweep is what keeps a planted
    foot still against the ground. Once it is airborne the leg swings back to
    the front on an eased curve. Both halves meet at the same angle, so the
    join never snaps.
    """
    turned = (turn - phase - lag) % 1.0
    if turned < stance:
        return amplitude * (1.0 - 2.0 * (turned / stance))
    airborne = (turned - stance) / (1.0 - stance)
    return -amplitude * math.cos(math.pi * airborne)


def _sine_swing(turn, phase, amplitude, lag=0.0):
    """One joint's angle at this point in the stride."""
    return amplitude * math.sin(2.0 * math.pi * (turn - phase - lag))


# Fixed at import, once every constant it depends on exists. The build prints
# it and broadcast_view.gd holds the same number as GALLOP_STRIDE_M.
STRIDE_M = _stride_m()


def gallop_keys(length):
    """A four-beat transverse gallop, generated from per-leg phase offsets.

    Driving every joint from one phase per leg makes it impossible for the two
    hinds (or the two fores) to move together by accident, which is the failure
    the hand-written version had.
    """
    frames = {}
    for frame in range(1, length + 1):
        turn = float(frame - 1) / float(length)
        pose = {}
        # EACH LIMB IS ON THE GROUND FOR ITS OWN LENGTH OF TIME.
        #
        # Once the lead limb reaches further than its partner, one stance
        # fraction cannot serve both: the horse's body covers the same ground
        # per stride whatever the leg is doing, so a limb that sweeps 1.89m and
        # a limb that sweeps 1.50m must be down for different lengths of time or
        # one of them is dragging. A real gallop does exactly this — the four
        # contact times are not equal — and it is the last of the slip.
        #
        # The rule falls out of the requirement itself: stance = sweep / stride.
        for side, leg in (("l", "hind_l"), ("r", "hind_r")):
            phase = LEG_PHASE[leg]
            gaskin, cannon = HIND_FLEX
            reach = LEAD_REACH if side == LEAD_SIDE else OFF_REACH
            swing_deg = HIND_SWING * reach
            stance = limb_sweep(HIND_PIVOT_M, swing_deg) / STRIDE_M
            # Positive is forward, measured off the rig rather than guessed.
            pose[f"thigh_{side}"] = [_swing(turn, phase, swing_deg, stance), 0, 0]
            pose[f"gaskin_{side}"] = [_flex(turn, phase, gaskin, stance, JOINT_LAG), 0, 0]
            pose[f"hind_cannon_{side}"] = [
                _flex(turn, phase, cannon, stance, 2.0 * JOINT_LAG), 0, 0]
        for side, leg in (("l", "fore_l"), ("r", "fore_r")):
            phase = LEG_PHASE[leg]
            forearm, cannon = FORE_FLEX
            reach = LEAD_REACH if side == LEAD_SIDE else OFF_REACH
            swing_deg = FORE_SWING * reach
            stance = limb_sweep(FORE_PIVOT_M, swing_deg) / STRIDE_M
            pose[f"shoulder_{side}"] = [_swing(turn, phase, swing_deg, stance), 0, 0]
            pose[f"forearm_{side}"] = [_flex(turn, phase, forearm, stance, JOINT_LAG), 0, 0]
            pose[f"fore_cannon_{side}"] = [
                _flex(turn, phase, cannon, stance, 2.0 * JOINT_LAG), 0, 0]
        # The back rounds and extends once per stride; the neck and head work
        # against it, which is the counterweight a galloping horse actually is.
        # A galloping horse's head and neck are a COUNTERWEIGHT, swinging
        # against the back once per stride. At a few degrees it reads as a
        # stiff-necked rocking-horse; this is the motion that sells the effort.
        pose["spine"] = [6.0 * math.sin(2.0 * math.pi * turn), 0, 0]
        pose["croup"] = [-9.0 * math.sin(2.0 * math.pi * turn), 0, 0]
        # A GALLOPING HORSE REACHES WITH ITS HEAD. It does not run in the
        # collected, head-up carriage of a dressage horse — it stretches the
        # neck out and low and drives from behind. These oscillated around the
        # REST carriage, so the animal nodded politely while sprinting.
        #
        # Measured, not guessed: negative neck takes the muzzle from 2.08m down
        # to 1.65m and pushes it forward, so the extension is a negative BIAS
        # under the swing. The head takes a small positive bias back so the face
        # stays level instead of pointing at the sand.
        pose["neck"] = [-20.0 - 15.0 * math.sin(2.0 * math.pi * turn + 0.6), 0, 0]
        pose["head"] = [8.0 + 9.0 * math.sin(2.0 * math.pi * turn + 1.1), 0, 0]
        # And the tail STREAMS. Negative extends it back — rear reach goes 1.16m
        # at rest to 1.46m by -40 — so at a gallop it flies out behind instead
        # of hanging off the quarters like a rope. It is only ever the gallop
        # clip: stop the animation and the horse returns to its rest pose with
        # the tail down, which is what a standing horse does.
        pose["tail_a"] = [-42.0 - 8.0 * math.sin(2.0 * math.pi * turn), 0, 0]
        pose["tail_b"] = [-24.0 - 7.0 * math.sin(2.0 * math.pi * turn + 0.5), 0, 0]
        frames[frame] = {bone: [round(v, 2) for v in angles] for bone, angles in pose.items()}
    frames[length] = dict(frames[1])
    return {str(k): v for k, v in frames.items()}


def gallop_locations(length):
    """Body rise and fall. A gallop is a leap, so the root must actually leave."""
    q = max(1, length // 4)
    return {
        "1": {"root": [0.0, 0.0, -0.03]},
        str(q): {"root": [0.0, 0.0, 0.015]},
        str(q * 2): {"root": [0.0, 0.0, -0.02]},
        str(q * 3): {"root": [0.0, 0.0, 0.055]},
        str(length): {"root": [0.0, 0.0, -0.03]},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        # HIGH by default. The horse is the thing the camera is pointed at for
        # a whole race and it was shipping at 1,488 triangles against a 6,000
        # budget — a quarter of what it was allowed, spent on a silhouette that
        # goes faceted the moment it fills the frame.
        "--quality", default="high", choices=["low", "medium", "high"]
    )
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument(
        "--no-rig",
        action="store_true",
        help="Stop after the mesh, so renders show the undeformed anatomy",
    )
    parser.add_argument("--frames", type=int, default=16)
    parser.add_argument("--tile", type=int, default=420)
    parser.add_argument("--samples", type=int, default=32)
    args = parser.parse_args()

    forge = Forge(workdir=str(REPO), out_dir=str(REPO / "assets-generated" / "bforge"))
    try:
        forge.start()
        parts, ring = build_horse(forge, args.quality)
        print(f"built {len(parts)} parts (ring={ring})")

        merged = forge.call("object.join", names=parts, into="horse", _timeout=900)
        print(
            f"joined   : {merged['triangles']} tris, {len(merged['materials'])} materials"
        )

        # The game tints by material NAME, so the merged mesh needs exactly the
        # four slots it looks for. Paint them by region rather than modelling
        # separate objects: hooves and lower legs take Sock, the tack takes
        # Cloth, the plume takes Plume.
        forge.call("material.consolidate", tolerance=0.03)
        forge.call("object.shade", name="horse", mode="smooth", angle=42.0)
        forge.call(
            "uv.unwrap",
            object="horse",
            style="smart_packed",
            margin=0.015,
            _timeout=600,
        )

        if args.no_rig:
            forge.call(
                "render.contact_sheet",
                out="chariot/racing_horse_mesh.png",
                tile=args.tile,
                samples=args.samples,
                panels=["left", "hero", "front", "wireframe"],
                columns=4,
                _timeout=2400,
            )
            print(
                "mesh-only sheet: assets-generated/bforge/chariot/racing_horse_mesh.png"
            )
            return 0

        rig = forge.call("rig.skeleton", name="horse_rig", bones=horse_bones())
        print(f"rig      : {rig['bone_count']} bones, root '{rig['root']}'")
        skin = forge.call(
            "rig.skin",
            mesh="horse",
            rig=rig["armature"],
            falloff=2.4,
            influences=2,
            _timeout=900,
        )
        print(
            f"skin     : {skin['weighted_vertices']} vertices into "
            f"{skin['vertex_groups']} groups"
        )

        clip = forge.call(
            "rig.keyframe",
            rig=rig["armature"],
            action="gallop",
            keys=gallop_keys(args.frames),
            locations=gallop_locations(args.frames),
            length=args.frames,
            loop=True,
            _timeout=600,
        )
        stride = STRIDE_M
        print(
            f"gallop   : {clip['fcurves']} curves, {clip['keyframes']} keys, "
            f"{clip['frames']} frames, stride {stride:.2f} m"
        )

        check = forge.call("check.asset", triangle_budget=6000, material_budget=6)
        critique = forge.call("check.critique", _timeout=600)
        print(
            f"validate : {'ok' if check['ok'] else 'FAILED'} "
            f"({check['errors']} errors)  critique {critique['errors']}E/"
            f"{critique['warnings']}W"
        )
        for failure in check["failures"][:4]:
            print(
                f"           [{failure['level']}] {failure['id']}: {failure['msg'][:90]}"
            )

        blend = forge.call("export.blend", out="chariot/racing_horse.blend")

        # Master stays snake_case for the validator; the GLB gets the exact
        # names broadcast_view.gd looks up.
        materials = forge.call("material.list")["materials"]
        rename = {"horse": "Horse", "gallop": "Gallop"}
        for slot, target in (
            ("m_cloth", "Coat"),
            ("m_rubber", "Sock"),
            ("m_gold", "Plume"),
        ):
            if any(m["name"] == slot for m in materials):
                rename[slot] = target
        for entry in materials:
            if entry["name"].startswith("m_cloth_") and "Cloth" not in rename.values():
                rename[entry["name"]] = "Cloth"
                break

        glb = forge.call(
            "export.gltf",
            out="chariot/racing_horse.glb",
            engine="godot",
            strict=False,
            rename=rename,
            _timeout=900,
        )
        print(f"export   : {glb['bytes'] // 1024} KB, animations={glb['animations']}")
        print(f"renamed  : {json.dumps(glb['renamed'])}")

        if args.render:
            sheet = forge.call(
                "render.contact_sheet",
                out="chariot/racing_horse.png",
                tile=args.tile,
                samples=args.samples,
                panels=["hero", "left", "front", "wireframe"],
                columns=4,
                _timeout=2400,
            )
            print(f"sheet    : {sheet['rel']}")
            shot = forge.call(
                "render.camera",
                out="chariot/racing_horse_hero.png",
                position=[2.3, 2.0, 1.35],
                target=[0.0, 0.45, 1.05],
                lens=70.0,
                resolution=900,
                aspect=1.5,
                samples=args.samples,
                _timeout=2400,
            )
            print(f"hero     : {shot['rel']}")

        if args.install:
            SOURCE.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(blend["path"], SOURCE / "racing_horse.blend")
            (SOURCE / "racing_horse.meta.json").write_text(
                json.dumps(
                    {
                        "asset_id": "racing_horse",
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
                                "workflow": "games/chariot/art_source/build_racing_horse.py",
                                "description": "Roman chariot racing horse: swept equine anatomy, harness and plume, 24-bone quadruped rig, four-beat transverse gallop",
                                "deterministic": True,
                                "human_review": "pending",
                            },
                        },
                        "games": "chariot",
                        "lod_policy": "auto",
                        "collision_policy": "auto",
                        "texture_policy": "compressed",
                        "animation_set": "gallop",
                        "budgets": {
                            "triangles": 6000,
                            "materials": 6,
                            "texture_max_px": 1024,
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            shutil.copyfile(glb["path"], MODEL_PATH)
            print(f"installed: {MODEL_PATH.relative_to(REPO)}")
        return 0
    except ForgeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        forge.stop()


if __name__ == "__main__":
    sys.exit(main())
