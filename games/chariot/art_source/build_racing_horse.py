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
    (0.0, -0.66, 1.24),  # croup
    (0.0, -0.42, 1.24),  # rump: widest point behind
    (0.0, -0.14, 1.15),  # loin
    (0.0, 0.14, 1.14),  # barrel
    (0.0, 0.34, 1.16),  # girth: deepest part of the horse
    (0.0, 0.52, 1.22),  # withers
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
    (0.27, 0.26),  # croup: broad and round
    (0.30, 0.30),  # rump
    (0.26, 0.32),  # loin: tucks in laterally, stays deep
    (0.29, 0.36),  # barrel
    (0.30, 0.37),  # girth: deepest
    (0.26, 0.34),  # withers
    (0.19, 0.28),  # neck base
    (0.15, 0.24),  # crest: narrow and deep
    (0.12, 0.20),
    (0.10, 0.15),  # poll
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
FORE_SCALE = [
    (0.105, 0.115),
    (0.090, 0.105),
    (0.072, 0.086),
    (0.055, 0.070),
    (0.052, 0.058),
    (0.036, 0.040),
    (0.042, 0.044),
    (0.048, 0.044),
    (0.056, 0.050),
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
        profile=ellipse(ring),
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
    mane_path = [
        (0.0, 0.72, 1.30),
        (0.0, 0.84, 1.52),
        (0.0, 0.96, 1.70),
        (0.0, 1.04, 1.82),
        (0.0, 1.10, 1.84),
    ]
    forge.call(
        "build.sweep",
        name="mane",
        profile=[-0.018, -0.10, 0.018, -0.10, 0.030, 0.055, -0.030, 0.055],
        profile_scales=[0.7, 0.55, 1.0, 1.0, 1.0, 0.95, 0.8, 0.6, 0.5, 0.3],
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
        profile_scales=[
            0.085,
            0.095,
            0.078,
            0.090,
            0.062,
            0.075,
            0.042,
            0.052,
            0.022,
            0.028,
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
# Each joint down a limb lags the one above it and swings less: that delay is
# what makes a leg look jointed rather than like a swinging stick.
JOINT_LAG = 0.08
HIND_SWING = (34.0, 30.0, 20.0)   # thigh, gaskin, cannon amplitudes
FORE_SWING = (32.0, 30.0, 26.0)   # shoulder, forearm, cannon


def _swing(turn, phase, amplitude, lag=0.0):
    """One joint's angle at this point in the stride."""
    return amplitude * math.sin(2.0 * math.pi * (turn - phase - lag))


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
        for side, leg in (("l", "hind_l"), ("r", "hind_r")):
            phase = LEG_PHASE[leg]
            thigh, gaskin, cannon = HIND_SWING
            pose[f"thigh_{side}"] = [_swing(turn, phase, thigh), 0, 0]
            # The gaskin folds AGAINST the thigh — a leg that folds the same
            # way it swings is a stilt.
            pose[f"gaskin_{side}"] = [-_swing(turn, phase, gaskin, JOINT_LAG), 0, 0]
            pose[f"hind_cannon_{side}"] = [_swing(turn, phase, cannon, 2.0 * JOINT_LAG), 0, 0]
        for side, leg in (("l", "fore_l"), ("r", "fore_r")):
            phase = LEG_PHASE[leg]
            shoulder, forearm, cannon = FORE_SWING
            pose[f"shoulder_{side}"] = [_swing(turn, phase, shoulder), 0, 0]
            pose[f"forearm_{side}"] = [-_swing(turn, phase, forearm, JOINT_LAG), 0, 0]
            pose[f"fore_cannon_{side}"] = [_swing(turn, phase, cannon, 2.0 * JOINT_LAG), 0, 0]
        # The back rounds and extends once per stride; the neck and head work
        # against it, which is the counterweight a galloping horse actually is.
        pose["spine"] = [4.5 * math.sin(2.0 * math.pi * turn), 0, 0]
        pose["croup"] = [-7.0 * math.sin(2.0 * math.pi * turn), 0, 0]
        pose["neck"] = [-9.0 * math.sin(2.0 * math.pi * turn + 0.6), 0, 0]
        pose["head"] = [6.0 * math.sin(2.0 * math.pi * turn + 1.1), 0, 0]
        pose["tail_a"] = [-20.0 - 8.0 * math.sin(2.0 * math.pi * turn), 0, 0]
        pose["tail_b"] = [-13.0 - 6.0 * math.sin(2.0 * math.pi * turn + 0.5), 0, 0]
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
        "--quality", default="medium", choices=["low", "medium", "high"]
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
        print(
            f"gallop   : {clip['fcurves']} curves, {clip['keyframes']} keys, "
            f"{clip['frames']} frames"
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
