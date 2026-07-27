"""Generate The Chariot Club's hippodrome from track_spec.json, via bforge.

    python games/chariot/art_source/build_hippodrome.py [--render] [--install]

The shipping `colosseum_track.glb` was a flat oval slab: correct racing surface,
no building around it. This builds the actual circus — banked racing surface,
inner and outer rails, tiered cavea seating, the spina with its obelisk, metae
turning posts and lap-counting dolphins, plus corner towers and torches.

Every dimension is read from `project/assets/track_spec.json`, the same file
`src/core/track_geometry.gd` uses to place horses, so the mesh and the race
maths cannot drift. Blender's XY ground plane maps to Godot as x -> x,
y -> -z, which is the convention track_geometry.gd already documents.
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
SPEC_PATH = GAME / "project" / "assets" / "track_spec.json"
MODEL_PATH = GAME / "project" / "assets" / "models" / "colosseum_track.glb"

# Travertine, not concrete. A Roman venue is warm limestone in hard sunlight:
# bright cream where the sun hits, ochre in the middle, deep warm grey in the
# shade. A single flat light grey is why the first pass looked like a car park.
STONE_SUN = "#d6c4a0"
STONE_MID = "#c2ab84"
STONE_SHADE = "#9c8763"
# Bright raked sand, near-white in full sun — the value anchor of the whole
# frame and the thing the crowd and architecture read against.
HARENA = "#d9bd8e"
# Faction banners in deep madder, the only strong colour in the building.
BANNER_RED = "#7a201a"
ARCADE_H = 9.5


def flat(pairs):
    return [value for pair in pairs for value in pair]


def stadium_point(s, straight, radius):
    """Point at arc length `s` around a stadium oval, in Blender XY.

    This is `track_geometry.gd::point_at` transcribed exactly (Godot z = -y), so
    anything placed with it lands on the same curve the race maths uses. An
    ellipse is NOT the same shape and bunches everything toward the ends.
    """
    perimeter = 2.0 * straight + 2.0 * math.pi * radius
    s = s % perimeter
    half = straight * 0.5
    if s < straight:
        return (-half + s, -radius)
    s -= straight
    arc = math.pi * radius
    if s < arc:
        theta = s / radius
        return (half + math.sin(theta) * radius, -math.cos(theta) * radius)
    s -= arc
    if s < straight:
        return (half - s, radius)
    s -= straight
    theta = s / radius
    return (-half - math.sin(theta) * radius, math.cos(theta) * radius)


def stadium_normal(s, straight, radius):
    """Outward unit normal at arc length `s`, matching `stadium_point`.

    A stadium is NOT a circle, so `atan2(y, x)` of the point is not the way
    out. Along a straight the normal is constant while atan2 keeps turning, and
    on the turns the centre sits at +/- half the straight rather than at the
    origin, so atan2 is wrong there too. Anything that has to FACE outward —
    the stair wedges that divide the cavea — needs this, or it ends up stood
    broadside across the seating it is supposed to cut through.
    """
    perimeter = 2.0 * straight + 2.0 * math.pi * radius
    s = s % perimeter
    if s < straight:
        return (0.0, -1.0)
    s -= straight
    arc = math.pi * radius
    if s < arc:
        theta = s / radius
        return (math.sin(theta), -math.cos(theta))
    s -= arc
    if s < straight:
        return (0.0, 1.0)
    s -= straight
    theta = s / radius
    return (-math.sin(theta), math.cos(theta))


def cavea_profile(stands, podium_offset):
    """Stepped grandstand cross-section, derived from the SHARED stands spec.

    Real cavea seating is what sells the scale of a circus, and scale is the
    whole point — the Circus Maximus stands were ~30 m tall against a 600 m
    track. Get this wrong and the building reads as a kerb around a car park.

    Every dimension here comes from `track_spec.json`, because
    `crowd_director.gd` seats spectators using the same numbers. When this
    function invented its own row depth and rise instead, the top third of the
    crowd ended up hovering in the air behind the building.

    Each row costs two profile points (riser, tread), so triangle cost scales
    with path resolution rather than with seat count.
    """
    tiers = int(stands["tiers"])
    depth = float(stands["tier_depth_m"])
    rise = float(stands["tier_rise_m"])
    riser = float(stands["tier_riser_m"])
    rows = max(1, int(stands["rows_per_tier"]))

    # Solid podium wall from the sand up to the first seating course.
    points = [(podium_offset, 0.0), (podium_offset, float(stands["podium_height_m"]))]
    lateral, vertical = podium_offset, float(stands["podium_height_m"])
    for _tier in range(tiers):
        vertical += riser  # praecinctio wall between tiers
        points.append((lateral, vertical))
        for _row in range(rows):
            lateral += depth / rows
            points.append((lateral, vertical))  # tread
            vertical += rise / rows
            points.append((lateral, vertical))  # riser
    top = vertical
    points.append((lateral, top + float(stands["arcade_height_m"])))
    points.append(
        (
            lateral + float(stands["back_thickness_m"]),
            top + float(stands["arcade_height_m"]),
        )
    )
    points.append((lateral + float(stands["back_thickness_m"]), 0.0))
    return points, lateral, top


def build(forge, spec, quality):
    straight = float(spec["straight_m"])
    radius = float(spec["turn_radius_m"])
    lane_width = float(spec["lane_width_m"])
    inner_lane = float(spec["rail_inner_offset_lanes"])
    outer_lane = float(spec["rail_outer_offset_lanes"])

    # Lane offsets are measured from the lane-1 centreline, outward.
    inner = (inner_lane - 1.0) * lane_width
    outer = (outer_lane - 1.0) * lane_width
    segments = {"low": 12, "medium": 20, "high": 32}[quality]
    stands = spec["stands"]
    # The crowd director derives seat positions from exactly this offset.
    podium_offset = (outer_lane - 1.0) * lane_width + float(stands["podium_extra_m"])

    forge.call("session.reset")
    parts = []

    # --- racing surface -------------------------------------------------
    forge.call(
        "build.sweep",
        name="track_surface",
        profile=flat([(inner, -0.45), (outer, -0.45), (outer, 0.0), (inner, 0.0)]),
        path_shape="oval",
        straight=straight,
        radius=radius,
        segments=segments,
        # Roman circuses raced on red sand — "harena". It also gives the venue
        # the value contrast a monochrome stone bowl badly needs.
        material="sand",
        color="#a87a54",
        uv="box",
        uv_scale=8.0,
        origin="world",
        _timeout=600,
    )
    parts.append("track_surface")

    # --- infield ---------------------------------------------------------
    # The ground the spina stands on. Without it the middle of the venue is a
    # HOLE: the consuming game renders a procedural sky, so every camera that
    # looked across the oval saw straight through the infield to the sky's
    # brown ground hemisphere, and the centre of the circus read as a pit of
    # mud. Sits just under the racing surface, so the ribbon and the rails
    # always win the depth fight along their shared edge; it is wider than the
    # inner rail on purpose and everything past that edge is covered by the
    # track, the podium and the cavea.
    forge.call(
        "build.plane",
        name="infield",
        size=[straight + 2.0 * (radius + inner), 2.0 * (radius + inner)],
        location=[0.0, 0.0, -0.44],
        material="sand",
        # Unraked ground, a shade duller and cooler than the racing harena, so
        # the ribbon still reads as the surface that matters.
        color="#9c7d5e",
        uv="box",
        uv_scale=12.0,
        origin="world",
        cuts=6,
    )
    parts.append("infield")

    # --- rails ----------------------------------------------------------
    forge.call(
        "build.sweep",
        name="rail_inner",
        profile=flat(
            [(inner - 0.9, 0.0), (inner, 0.0), (inner, 1.15), (inner - 0.9, 1.15)]
        ),
        path_shape="oval",
        straight=straight,
        radius=radius,
        segments=segments,
        material="stone",
        color="stone_warm",
        uv="box",
        uv_scale=4.0,
        origin="world",
        _timeout=600,
    )
    forge.call(
        "build.sweep",
        name="rail_outer",
        profile=flat(
            [(outer, 0.0), (outer + 1.1, 0.0), (outer + 1.1, 1.55), (outer, 1.55)]
        ),
        path_shape="oval",
        straight=straight,
        radius=radius,
        segments=segments,
        material="stone",
        color="#b8b4a8",
        uv="box",
        uv_scale=4.0,
        origin="world",
        _timeout=600,
    )
    parts += ["rail_inner", "rail_outer"]

    # --- cavea (tiered seating) -----------------------------------------
    cavea_points, stand_back, stand_top = cavea_profile(stands, podium_offset)
    forge.call(
        "build.sweep",
        name="cavea",
        profile=flat(cavea_points),
        path_shape="oval",
        straight=straight,
        radius=radius,
        segments=segments,
        material="stone",
        color="#b8b4a8",
        uv="box",
        uv_scale=4.0,
        origin="world",
        _timeout=900,
    )
    parts.append("cavea")
    print(
        f"cavea    : podium at {podium_offset:.1f} m, back at {stand_back:.1f} m, "
        f"top course {stand_top:.1f} m"
    )

    # --- the Roman elevation --------------------------------------------
    # What makes a venue read as the Colosseum rather than as a stadium bowl
    # is arches, and a vertical rhythm cutting the seating into wedges. A
    # smooth stone ramp reads as a retaining wall no matter how big it is.
    bays = {"low": 28, "medium": 44, "high": 68}[quality]

    # Upper arcade ring, standing on the back of the cavea. This is the storey
    # you actually see from the sand, framing the top of the bowl.
    forge.call(
        "arch.arcade",
        name="upper_arcade",
        path_shape="oval",
        straight=straight,
        radius=radius + stand_back,
        resolution=segments * 2,
        bays=bays,
        height=ARCADE_H,
        thickness=2.4,
        opening=0.60,
        springing=0.44,
        voussoirs=7,
        plinth=0.7,
        cornice=0.9,
        engaged_columns=True,
        material="stone",
        color=STONE_SUN,
        uv_scale=3.0,
        z=stand_top,
        _timeout=1800,
    )
    parts.append("upper_arcade")

    # Crowning colonnade with statues — the Colosseum's attic storey.
    forge.call(
        "arch.colonnade",
        name="attic_colonnade",
        path_shape="oval",
        straight=straight,
        radius=radius + stand_back - 0.6,
        resolution=segments * 2,
        columns=bays,
        height=5.2,
        column_radius=0.46,
        segments=8,
        entablature=1.1,
        statues=True,
        material="stone",
        color=STONE_MID,
        uv_scale=3.0,
        z=stand_top + ARCADE_H,
        _timeout=1800,
    )
    parts.append("attic_colonnade")

    # Vomitoria: the stair wedges that divide the seating into cunei. This
    # vertical rhythm is half of what the eye reads as "Roman amphitheatre".
    wedges = {"low": 10, "medium": 18, "high": 26}[quality]
    # Spacing must be computed on the SAME radius the path is sampled at, or
    # stadium_point wraps and the wedges bunch instead of dividing the bowl
    # evenly.
    wedge_perimeter = 2.0 * straight + 2.0 * math.pi * radius
    # A vomitorium is a stair cut INTO the rake, not a slab standing on it.
    # Built as a full-height box it becomes a 36 m blank wall that blots out
    # half the bowl from any trackside camera — which is exactly how it looked
    # in the first textured build. Sweeping the cavea profile, raised one step,
    # along a short arc gives a divider that hugs the seating instead.
    step_profile = [(lat, vert + 0.8) for lat, vert in cavea_points[:-3]]
    for index in range(wedges):
        centre = wedge_perimeter * index / wedges
        span = 2.2  # metres of arc the stair occupies
        path = []
        for offset in (-span * 0.5, 0.0, span * 0.5):
            px, py = stadium_point(centre + offset, straight, radius)
            path += [px, py, 0.0]
        forge.call(
            "build.sweep",
            name=f"vomitorium_{index}",
            profile=flat(step_profile),
            path=path,
            path_shape="custom",
            closed_path=False,
            closed_profile=False,
            material="stone",
            color=STONE_SHADE,
            uv="box",
            uv_scale=3.0,
            origin="world",
            _timeout=600,
        )
        parts.append(f"vomitorium_{index}")

    # Velarium masts: the awning rig along the rim. Even bare, the ring of
    # masts against the sky is an instantly Roman silhouette.
    mast_radius = radius + stand_back + 1.4
    mast_perimeter = 2.0 * straight + 2.0 * math.pi * mast_radius
    masts = {"low": 16, "medium": 30, "high": 48}[quality]
    for index in range(masts):
        x, y = stadium_point(mast_perimeter * index / masts, straight, mast_radius)
        forge.call(
            "build.cylinder",
            name=f"mast_{index}",
            radius=0.28,
            radius_top=0.16,
            depth=11.0,
            segments=6,
            location=[x, y, stand_top + ARCADE_H + 5.2],
            material="wood",
            color="#6b5335",
            uv="cylinder",
            origin="bottom",
            smooth=False,
        )
        parts.append(f"mast_{index}")

    # --- spina: the central barrier -------------------------------------
    spina_length = straight * 0.82
    spina_half = spina_length * 0.5
    forge.call(
        "build.sweep",
        name="spina_wall",
        profile=flat(
            [(-3.2, 0.0), (3.2, 0.0), (3.2, 2.3), (2.6, 2.9), (-2.6, 2.9), (-3.2, 2.3)]
        ),
        path_shape="line",
        length=spina_length,
        segments=6,
        material="stone",
        color="stone_warm",
        uv="box",
        uv_scale=4.0,
        origin="world",
        _timeout=600,
    )
    parts.append("spina_wall")

    # Metae: three conical turning posts on a plinth at each end of the spina.
    for side, sign in (("west", -1.0), ("east", 1.0)):
        base_x = sign * spina_half
        forge.call(
            "build.box",
            name=f"meta_{side}_base",
            size=[7.0, 8.4, 1.1],
            location=[base_x, 0.0, 0.0],
            bevel=0.12,
            material="stone",
            color="stone_warm",
            uv="box",
            uv_scale=3.0,
            origin="bottom",
        )
        parts.append(f"meta_{side}_base")
        for index, offset in enumerate((-2.6, 0.0, 2.6)):
            forge.call(
                "build.cylinder",
                name=f"meta_{side}_{index}",
                radius=1.15,
                radius_top=0.12,
                depth=7.4,
                segments=10,
                location=[base_x, offset, 1.1],
                material="bronze",
                uv="cylinder",
                origin="bottom",
                smooth=True,
            )
            parts.append(f"meta_{side}_{index}")

    # Obelisk at the spina's centre — the landmark a rider steers by.
    forge.call(
        "build.box",
        name="obelisk_base",
        size=[5.2, 5.2, 1.6],
        location=[0.0, 0.0, 2.9],
        bevel=0.1,
        material="stone",
        color="stone_grey",
        uv="box",
        uv_scale=3.0,
        origin="bottom",
    )
    forge.call(
        "build.lathe",
        name="obelisk",
        profile=[
            0.0,
            0.0,
            1.55,
            0.0,
            1.55,
            0.5,
            1.25,
            0.6,
            0.62,
            20.0,
            0.9,
            20.6,
            0.0,
            22.4,
        ],
        segments=4,
        location=[0.0, 0.0, 4.5],
        material="stone",
        color="sand",
        uv="cylinder",
        origin="bottom",
        smooth=False,
    )
    parts += ["obelisk_base", "obelisk"]

    # Lap-counting dolphins: seven bronze markers, the Roman lap counter.
    for index in range(7):
        x = -spina_half * 0.55 + index * (spina_half * 1.1 / 6.0)
        forge.call(
            "build.sphere",
            name=f"dolphin_{index}",
            radius=0.85,
            kind="ico",
            subdivisions=2,
            location=[x, 0.0, 3.6],
            material="bronze",
            uv="smart",
            origin="center",
            smooth=True,
        )
        forge.call(
            "object.transform",
            name=f"dolphin_{index}",
            scale=[1.9, 0.55, 0.9],
            apply=True,
        )
        parts.append(f"dolphin_{index}")

    # --- faction banners ------------------------------------------------
    # The four circus factions: Reds, Whites, Greens, Blues. Colour is doing
    # real work here — it breaks up a monochrome stone bowl and gives a rider
    # fixed landmarks to navigate by at speed.
    faction_colors = ["#8c2020", "#d8d2c4", "#2e6b34", "#22447e"]
    banner_count = {"low": 12, "medium": 24, "high": 40}[quality]
    # On the arcade parapet at the BACK of the stands, not floating over the
    # seating where they read as coloured slabs hanging in mid-air.
    banner_radius = radius + stand_back - 1.0
    banner_perimeter = 2.0 * straight + 2.0 * math.pi * banner_radius
    for index in range(banner_count):
        x, y = stadium_point(
            banner_perimeter * index / banner_count, straight, banner_radius
        )
        forge.call(
            "prop.banner",
            name=f"banner_{index}",
            size=[2.6, 5.4],
            wave=0.16,
            segments=5,
            pole=False,
            location=[x, y, stand_top + 8.4],
            material="cloth",
            color=faction_colors[index % 4],
            seed=index,
        )
        parts.append(f"banner_{index}")

    # --- corner towers + torches ----------------------------------------
    tower_positions = []
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            tower_positions.append(
                (sx * (straight * 0.5 + radius * 0.30), sy * (radius + outer + 22.0))
            )
    for index, (x, y) in enumerate(tower_positions):
        forge.call(
            "prop.pillar",
            name=f"tower_{index}",
            height=17.0,
            radius=2.6,
            style="tuscan",
            segments=12,
            location=[x, y, 0.0],
            material="stone",
            color="stone_grey",
        )
        parts.append(f"tower_{index}")

    torch_count = {"low": 8, "medium": 16, "high": 24}[quality]
    # Ride the torches along the outer rail so they read as track lighting.
    torch_radius = radius + outer + 1.8
    torch_perimeter = 2.0 * straight + 2.0 * math.pi * torch_radius
    for index in range(torch_count):
        x, y = stadium_point(
            torch_perimeter * index / torch_count, straight, torch_radius
        )
        forge.call(
            "prop.torch",
            name=f"torch_{index}",
            style="standing",
            height=2.4,
            location=[x, y, 1.55],
            emission=9.0,
            seed=index,
        )
        parts.append(f"torch_{index}")

    return parts


# Which parts are stone, and therefore share one tiling travertine map. Sand,
# bronze and cloth keep their own flat materials — a single texture stretched
# over everything is how you lose the material contrast the venue depends on.
STONE_PREFIXES = (
    "rail_",
    "cavea",
    "upper_arcade",
    "attic_colonnade",
    "vomitorium_",
    "spina_wall",
    "meta_",
    "obelisk",
    "tower_",
)


def surface_stone(forge, parts, size=1024, samples=14):
    """Give every stone surface one shared, seamless tiling material.

    Baked ONCE and reused: a 725 m building cannot carry a unique map (that is
    ~3 px/m), and per-part bakes would multiply both texture memory and draw
    calls for a surface that is the same stone everywhere.

    `uv_scale` is fixed across all of them so texel density is identical from
    the podium to the attic — mismatched density between adjacent surfaces is
    the thing that makes a building read as assembled from spare parts.
    """
    stone = [p for p in parts if p.startswith(STONE_PREFIXES)]
    for index, part in enumerate(stone):
        forge.call(
            "material.tileable",
            object=part,
            base_color=STONE_SUN,
            roughness=0.84,
            detail_scale=5.5,
            dirt=0.45,
            dirt_color="#3a2f22",
            bump=0.5,
            tiles=1.0,
            uv_scale=3.0,
            size=size,
            samples=samples,
            stem="travertine",
            reuse=index > 0,
            _timeout=3600,
        )
    return stone


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quality", default="medium", choices=["low", "medium", "high"]
    )
    parser.add_argument("--render", action="store_true")
    parser.add_argument(
        "--pbr",
        action="store_true",
        help="Surface the stone with a shared seamless tiling PBR set "
        "(base colour, normal, roughness) instead of flat vertex colour",
    )
    parser.add_argument("--texture-size", type=int, default=1024)
    parser.add_argument(
        "--install",
        action="store_true",
        help="Overwrite the game's colosseum_track.glb",
    )
    parser.add_argument("--tile", type=int, default=420)
    parser.add_argument("--samples", type=int, default=28)
    args = parser.parse_args()

    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    forge = Forge(workdir=str(REPO), out_dir=str(REPO / "assets-generated" / "bforge"))
    try:
        forge.start()
        parts = build(forge, spec, args.quality)
        print(f"built {len(parts)} parts")

        if args.pbr:
            stone = surface_stone(forge, parts, size=args.texture_size)
            print(
                f"surfaced : {len(stone)} stone parts share one tiling travertine set"
            )

        # Collapse the pile of near-identical materials the prop recipes leave
        # behind BEFORE joining — every distinct material is a draw call.
        consolidated = forge.call("material.consolidate", tolerance=0.02, _timeout=600)
        print(
            f"materials: {consolidated['materials_before']} -> "
            f"{consolidated['materials_after']} "
            f"({consolidated['draw_calls_saved']} draw calls saved)"
        )

        merged = forge.call(
            "object.join", names=parts, into="colosseum_track", _timeout=900
        )
        print(
            f"joined   : {merged['triangles']} tris, "
            f"{len(merged['materials'])} materials, "
            f"extent {[round(v) for v in merged['bounds']['size']]} m"
        )

        budget = forge.call(
            "gameready.budget", profile="browser_webgpu", asset_class="environment"
        )
        critique = forge.call("check.critique", _timeout=900)
        print(
            f"budget   : {'within' if budget['within_budget'] else 'OVER'} "
            f"({budget['triangle_budget']} tris/object)"
        )
        print(
            f"critique : {critique['errors']} errors, {critique['warnings']} warnings"
        )
        for finding in critique["findings"][:5]:
            print(
                f"           [{finding['severity']}] {finding['issue']}: {finding['detail'][:90]}"
            )

        blend = forge.call("export.blend", out="chariot/colosseum_track.blend")
        glb = forge.call(
            "export.gltf",
            out="chariot/colosseum_track.glb",
            engine="godot",
            strict=False,
            _timeout=900,
        )
        print(f"export   : {glb['bytes'] // 1024} KB -> {glb['rel']}")
        print(f"master   : {blend['rel']}")

        if args.render:
            sheet = forge.call(
                "render.contact_sheet",
                out="chariot/hippodrome.png",
                tile=args.tile,
                samples=args.samples,
                panels=["hero", "low", "top", "wireframe"],
                columns=4,
                _timeout=2400,
            )
            print(f"overview : {sheet['rel']}")

            # Whole-object framing cannot show a 700 m building's detail, so
            # shoot the views the game actually uses: the broadcast camera down
            # the home straight, and a rider's eye at the first turn.
            radius = float(spec["turn_radius_m"])
            straight = float(spec["straight_m"])
            # Cameras go INSIDE the bowl. Shooting from outside just frames the
            # blank back wall of the stands, which tells you nothing about how
            # the venue plays.
            shots = [
                # Broadcast: infield, low, looking down the home straight.
                (
                    "broadcast",
                    [-straight * 0.30, -radius * 0.45, 18.0],
                    [straight * 0.34, -radius + 6.0, 3.0],
                    40.0,
                ),
                # Rider's eye entering the first turn.
                (
                    "turn",
                    [straight * 0.40, -radius + 12.0, 3.2],
                    [straight * 0.52, -radius + 2.0, 2.0],
                    30.0,
                ),
                # The spina furniture: obelisk, metae, dolphins.
                (
                    "spina",
                    [-straight * 0.16, -radius * 0.40, 14.0],
                    [0.0, 0.0, 9.0],
                    42.0,
                ),
                # Wide interior showing the bowl and the far stands.
                (
                    "bowl",
                    [-straight * 0.46, -radius * 0.20, 40.0],
                    [straight * 0.15, 0.0, 6.0],
                    26.0,
                ),
            ]
            for label, position, target, lens in shots:
                shot = forge.call(
                    "render.camera",
                    out=f"chariot/hippodrome_{label}.png",
                    position=position,
                    target=target,
                    lens=lens,
                    resolution=880,
                    aspect=1.78,
                    samples=args.samples,
                    _timeout=2400,
                )
                print(f"{label:9}: {shot['rel']}")

        if args.install:
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
