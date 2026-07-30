"""Live Blender integration tests.

These start a real Blender daemon and assert on real geometry, so they are the
tests that actually prove the toolset works. They skip cleanly when Blender is
absent or when BFORGE_SKIP_LIVE is set, so CI without Blender stays green.

One daemon is shared across the whole module: booting Blender costs ~5 s and
paying that per test would make the suite unusable.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge.client import DaemonError, Forge, ForgeError, find_blender  # noqa: E402

FORGE: Forge | None = None
TEMP: tempfile.TemporaryDirectory | None = None


def setUpModule():
    global FORGE, TEMP
    if os.environ.get("BFORGE_SKIP_LIVE"):
        raise unittest.SkipTest("BFORGE_SKIP_LIVE is set")
    try:
        find_blender()
    except DaemonError as exc:
        raise unittest.SkipTest(f"Blender not available: {exc}") from exc
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_test_")
    FORGE = Forge(workdir=TEMP.name, out_dir=str(Path(TEMP.name) / "out"))
    FORGE.start()


def tearDownModule():
    if FORGE is not None:
        FORGE.stop()
    if TEMP is not None:
        TEMP.cleanup()


class ForgeCase(unittest.TestCase):
    def setUp(self):
        FORGE.call("session.reset")

    @property
    def forge(self) -> Forge:
        return FORGE


class Daemon(ForgeCase):
    def test_daemon_reports_its_environment(self):
        self.assertIn("blender", FORGE.info)
        self.assertGreaterEqual(FORGE.info["ops"], 80)

    def test_catalog_matches_the_committed_snapshot(self):
        from bforge import schema as schema_mod

        live = {op["name"] for op in FORGE.catalog()}
        committed = {op["name"] for op in schema_mod.load_catalog()}
        self.assertEqual(
            live,
            committed,
            "catalog.json is stale — run `bforge catalog --refresh`",
        )

    def test_unknown_op_gives_a_helpful_error(self):
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("prop.nonexistent")
        self.assertIn("prop.", str(ctx.exception))

    def test_bad_parameter_name_is_rejected_with_the_valid_list(self):
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("build.box", nonsense=1)
        self.assertIn("nonsense", str(ctx.exception))
        self.assertIn("Valid parameters", str(ctx.exception))

    def test_wrong_parameter_type_is_rejected(self):
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("build.box", size="huge")
        self.assertIn("size", str(ctx.exception))

    def test_daemon_survives_an_op_failure(self):
        with self.assertRaises(ForgeError):
            self.forge.call("object.inspect", name="does_not_exist")
        self.assertEqual(self.forge.call("build.box", name="after")["name"], "after")

    def test_missing_object_name_is_a_clean_error_not_a_systemerror(self):
        # bpy_prop_collection.get(None) raises a raw SystemError from C; the
        # object lookup must guard before bpy so the caller gets the normal
        # helpful message (found by Riftline's hellenic pack build).
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("object.inspect", name=None)
        self.assertIn("name", str(ctx.exception).lower())
        self.assertNotIn("SystemError", str(ctx.exception))


class Geometry(ForgeCase):
    def test_box_dimensions_are_exact(self):
        result = self.forge.call("build.box", name="b", size=[2.0, 1.0, 0.5], bevel=0.0)
        self.assertEqual(result["bounds"]["size"], [2.0, 1.0, 0.5])

    def test_bevel_adds_geometry_without_changing_size(self):
        plain = self.forge.call("build.box", name="plain", size=[1, 1, 1], bevel=0.0)
        self.forge.call("session.reset")
        chamfered = self.forge.call("build.box", name="cham", size=[1, 1, 1], bevel=0.03)
        self.assertGreater(chamfered["triangles"], plain["triangles"])
        self.assertEqual(chamfered["bounds"]["size"], [1.0, 1.0, 1.0])

    def test_generation_is_deterministic(self):
        first = self.forge.call("prop.rock", name="r", seed=42)
        self.forge.call("session.reset")
        second = self.forge.call("prop.rock", name="r", seed=42)
        self.assertEqual(first["triangles"], second["triangles"])
        self.assertEqual(first["bounds"], second["bounds"])

    def test_different_seeds_give_different_assets(self):
        first = self.forge.call("prop.rock", name="r", seed=1)
        self.forge.call("session.reset")
        second = self.forge.call("prop.rock", name="r", seed=2)
        self.assertNotEqual(first["bounds"], second["bounds"])

    def test_rock_formations_are_grounded_distinct_and_deterministic(self):
        results = {}
        for formation in ("boulder", "slab", "outcrop", "scree"):
            self.forge.call("session.reset")
            results[formation] = self.forge.call(
                "prop.rock",
                name=formation,
                seed=29,
                formation=formation,
                size=[1.8, 1.35, 1.05],
                detail=2,
                roughness=0.24,
                strata=0.62,
                angular=True,
            )
            self.assertEqual(results[formation]["formation"], formation)
            self.assertAlmostEqual(results[formation]["bounds"]["min"][2], 0.0, places=3)

        self.assertEqual(results["boulder"]["piece_count"], 1)
        self.assertEqual(results["slab"]["piece_count"], 2)
        self.assertEqual(results["outcrop"]["piece_count"], 3)
        self.assertEqual(results["scree"]["piece_count"], 5)
        self.assertLess(
            results["slab"]["bounds"]["size"][2], results["boulder"]["bounds"]["size"][2]
        )
        self.assertGreater(results["slab"]["bounds"]["size"][2], 0.3)
        self.assertGreater(results["outcrop"]["triangles"], results["boulder"]["triangles"])
        self.assertGreater(results["scree"]["triangles"], results["outcrop"]["triangles"])
        self.assertGreater(results["scree"]["bounds"]["size"][0], 1.2)
        self.assertEqual(len({tuple(result["bounds"]["size"]) for result in results.values()}), 4)

        self.forge.call("session.reset")
        repeated = self.forge.call(
            "prop.rock",
            name="outcrop",
            seed=29,
            formation="outcrop",
            size=[1.8, 1.35, 1.05],
            detail=2,
            roughness=0.24,
            strata=0.62,
            angular=True,
        )
        self.assertEqual(results["outcrop"]["triangles"], repeated["triangles"])
        self.assertEqual(results["outcrop"]["bounds"], repeated["bounds"])

    def test_natural_tree_styles_are_deterministic_branch_readable_assets(self):
        olive = self.forge.call(
            "prop.tree",
            name="olive",
            seed=17,
            canopy_style="olive",
            age="ancient",
            height=5.2,
            canopy_radius=1.8,
            detail=2,
        )
        self.assertGreater(olive["triangles"], 1200)
        self.assertLess(olive["triangles"], 4200)
        self.assertEqual(len(olive["materials"]), 2)
        self.assertAlmostEqual(olive["bounds"]["min"][2], 0.0, places=3)
        self.assertEqual(olive["species"], "olive")
        self.assertEqual(olive["age"], "ancient")
        self.assertEqual(olive["silhouette"], "ancient_windswept_olive")
        self.assertGreaterEqual(olive["branch_count"], 30)
        self.assertGreaterEqual(olive["foliage_masses"], 60)

        self.forge.call("session.reset")
        repeated = self.forge.call(
            "prop.tree",
            name="olive",
            seed=17,
            canopy_style="olive",
            age="ancient",
            height=5.2,
            canopy_radius=1.8,
            detail=2,
        )
        self.assertEqual(olive["triangles"], repeated["triangles"])
        self.assertEqual(olive["bounds"], repeated["bounds"])

        self.forge.call("session.reset")
        cypress = self.forge.call(
            "prop.tree",
            name="cypress",
            seed=23,
            canopy_style="cypress",
            age="ancient",
            height=7.0,
            canopy_radius=1.05,
            detail=2,
        )
        self.assertGreater(cypress["triangles"], 1200)
        self.assertLess(cypress["triangles"], 4200)
        self.assertEqual(len(cypress["materials"]), 2)
        self.assertGreater(cypress["bounds"]["size"][2], cypress["bounds"]["size"][0] * 2.5)
        self.assertEqual(cypress["species"], "cypress")
        self.assertEqual(cypress["age"], "ancient")
        self.assertEqual(cypress["silhouette"], "ancient_columnar_cypress")
        self.assertGreaterEqual(cypress["branch_count"], 28)
        self.assertGreaterEqual(cypress["foliage_masses"], 70)

        self.forge.call("session.reset")
        young = self.forge.call(
            "prop.tree",
            name="cypress",
            seed=23,
            canopy_style="cypress",
            age="young",
            height=7.0,
            canopy_radius=1.05,
            detail=2,
        )
        self.assertEqual(young["silhouette"], "young_columnar_cypress")
        self.assertNotEqual(cypress["branch_count"], young["branch_count"])
        self.assertNotEqual(cypress["foliage_masses"], young["foliage_masses"])
        self.assertNotEqual(cypress["bounds"], young["bounds"])

    def test_origin_modes_place_the_pivot_correctly(self):
        result = self.forge.call("build.box", name="b", size=[1, 1, 2], origin="bottom")
        self.assertAlmostEqual(result["bounds"]["min"][2], 0.0, places=4)
        self.forge.call("session.reset")
        centred = self.forge.call("build.box", name="b", size=[1, 1, 2], origin="center")
        self.assertAlmostEqual(centred["bounds"]["min"][2], -1.0, places=4)

    def test_join_keeps_the_requested_name(self):
        self.forge.call("build.box", name="part_a", location=[0, 0, 0])
        self.forge.call("build.box", name="part_b", location=[2, 0, 0])
        merged = self.forge.call("object.join", names=["part_a", "part_b"], into="merged")
        self.assertEqual(merged["name"], "merged")

    def test_join_preserves_world_positions(self):
        self.forge.call("build.box", name="a", size=[1, 1, 1], location=[0, 0, 0])
        self.forge.call("build.box", name="b", size=[1, 1, 1], location=[5, 0, 0])
        merged = self.forge.call("object.join", names=["a", "b"], into="m")
        self.assertGreater(merged["bounds"]["size"][0], 5.0)

    def test_array_multiplies_geometry(self):
        one = self.forge.call("build.box", name="unit", size=[1, 1, 1])
        result = self.forge.call("build.array", name="unit", counts=[4], spacing=[2, 0, 0])
        self.assertAlmostEqual(result["triangles"], one["triangles"] * 4)


class Architecture(ForgeCase):
    def test_civic_hall_is_a_deterministic_material_disciplined_mine_town_centre(self):
        first = self.forge.call(
            "arch.civic_hall",
            name="laurion",
            style="greek_mine",
            width=10.4,
            depth=8.4,
            height=6.8,
            columns=6,
            tile_rows=7,
        )
        self.assertEqual(first["style"], "greek_mine")
        self.assertTrue(first["mine_portal"])
        self.assertTrue(first["hoist"])
        self.assertEqual(first["columns"], 6)
        self.assertEqual(first["tile_rows"], 7)
        self.assertGreaterEqual(first["parts"], 90)
        self.assertGreater(first["portal_width"], 2.0)
        self.assertGreater(first["triangles"], 3_000)
        self.assertLess(first["triangles"], 18_000)
        self.assertEqual(
            first["materials"],
            [
                "m_civic_stone",
                "m_civic_foundation",
                "m_civic_roof",
                "m_civic_timber",
                "m_civic_metal",
                "m_civic_cloth",
                "m_civic_void",
            ],
        )
        self.assertAlmostEqual(first["bounds"]["min"][2], 0.0, places=3)
        self.assertGreater(first["bounds"]["size"][0], 10.0)
        self.assertGreater(first["bounds"]["size"][1], 8.0)

        self.forge.call("session.reset")
        repeated = self.forge.call(
            "arch.civic_hall",
            name="laurion",
            style="greek_mine",
            width=10.4,
            depth=8.4,
            height=6.8,
            columns=6,
            tile_rows=7,
        )
        self.assertEqual(first["triangles"], repeated["triangles"])
        self.assertEqual(first["bounds"], repeated["bounds"])

    def test_polis_style_removes_mine_only_parts(self):
        polis = self.forge.call(
            "arch.civic_hall",
            name="polis",
            style="greek_polis",
        )
        self.assertEqual(polis["style"], "greek_polis")
        self.assertFalse(polis["mine_portal"])
        self.assertFalse(polis["hoist"])
        self.assertEqual(polis["portal_width"], 0.0)
        self.assertLess(polis["parts"], 110)

    def test_defense_tower_family_has_distinct_deterministic_silhouettes(self):
        expected = {
            "arrow": "elevated_archer_crown",
            "ballista": "horizontal_torsion_engine",
            "storm": "vertical_bronze_conductor",
        }
        family = {}
        for style, silhouette in expected.items():
            self.forge.call("session.reset")
            tower = self.forge.call(
                "arch.defense_tower",
                name=f"{style}_tower",
                style=style,
                width=3.0,
                height=5.2,
            )
            family[style] = tower
            self.assertEqual(tower["style"], style)
            self.assertEqual(tower["silhouette"], silhouette)
            self.assertGreaterEqual(tower["parts"], 20)
            self.assertGreater(tower["triangles"], 500)
            self.assertLess(tower["triangles"], 9_000)
            self.assertAlmostEqual(tower["bounds"]["min"][2], 0.0, places=3)
            self.assertGreater(tower["bounds"]["size"][0], 2.7)
            self.assertGreater(tower["bounds"]["size"][1], 2.7)
            self.assertEqual(
                tower["materials"],
                [
                    "m_defense_stone",
                    "m_defense_foundation",
                    "m_defense_timber",
                    "m_defense_metal",
                    "m_defense_cloth",
                    "m_defense_energy",
                ],
            )

        self.assertGreater(
            family["storm"]["bounds"]["size"][2],
            family["ballista"]["bounds"]["size"][2],
        )
        self.assertGreater(
            family["ballista"]["bounds"]["size"][0],
            family["storm"]["bounds"]["size"][0],
        )

        self.forge.call("session.reset")
        repeated = self.forge.call(
            "arch.defense_tower",
            name="arrow_tower",
            style="arrow",
            width=3.0,
            height=5.2,
        )
        self.assertEqual(family["arrow"]["triangles"], repeated["triangles"])
        self.assertEqual(family["arrow"]["bounds"], repeated["bounds"])

    def test_field_building_family_is_serious_distinct_and_deterministic(self):
        expected = {
            "farm": ("furrowed_olive_plot", 3.4, 3.4, 1.8),
            "barracks": ("hoplite_training_hall", 3.2, 2.6, 2.8),
            "wall": ("ashlar_parapet_segment", 2.4, 0.6, 2.2),
            "waymarker": ("weathered_road_stele", 1.25, 1.1, 2.4),
        }
        family = {}
        for style, (silhouette, width, depth, height) in expected.items():
            self.forge.call("session.reset")
            building = self.forge.call(
                "arch.field_building",
                name=f"greek_{style}",
                style=style,
                width=width,
                depth=depth,
                height=height,
            )
            family[style] = building
            self.assertEqual(building["style"], style)
            self.assertEqual(building["silhouette"], silhouette)
            self.assertGreaterEqual(building["parts"], 10)
            self.assertGreater(building["triangles"], 150)
            self.assertLess(building["triangles"], 6_000)
            self.assertAlmostEqual(
                building["bounds"]["min"][2],
                0.0,
                places=3,
                msg=f"{style} must sit on the ground",
            )
            self.assertEqual(
                building["materials"],
                [
                    "m_field_stone",
                    "m_field_foundation",
                    "m_field_timber",
                    "m_field_roof",
                    "m_field_metal",
                    "m_field_crop",
                ],
            )

        self.assertGreater(family["farm"]["bounds"]["size"][0], 3.2)
        self.assertGreater(family["barracks"]["bounds"]["size"][2], 2.4)
        self.assertLess(family["wall"]["bounds"]["size"][1], 0.8)
        self.assertGreater(family["waymarker"]["bounds"]["size"][2], 2.0)

        self.forge.call("session.reset")
        repeated = self.forge.call(
            "arch.field_building",
            name="greek_wall_repeat",
            style="wall",
            width=2.4,
            depth=0.6,
            height=2.2,
        )
        self.assertEqual(family["wall"]["triangles"], repeated["triangles"])
        self.assertEqual(family["wall"]["bounds"], repeated["bounds"])


class Transforms(ForgeCase):
    def test_apply_clears_rotation_and_scale(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        result = self.forge.call(
            "object.transform", name="b", rotation=[0, 0, 45], scale=[2, 2, 2], apply=True
        )
        self.assertEqual([round(v, 4) for v in result["scale"]], [1.0, 1.0, 1.0])
        self.assertEqual([round(v, 3) for v in result["rotation_deg"]], [0.0, 0.0, 0.0])

    def test_applied_scale_actually_grows_the_mesh(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1], origin="center")
        result = self.forge.call("object.transform", name="b", scale=[3, 3, 3], apply=True)
        self.assertAlmostEqual(result["bounds"]["size"][0], 3.0, places=3)

    def test_pivot_to_origin_satisfies_the_studio_validator(self):
        """Regression: a master whose root object is not at (0,0,0) is rejected
        by tools/blender/validate.py, and check.asset used to only warn."""
        self.forge.call("prop.crate", name="crate", location=[3.0, 2.0, 0.0])
        self.forge.call("gameready.pivot", objects=["crate"], origin="bottom", to_origin=True)
        report = self.forge.call("check.asset", triangle_budget=5000)
        origin_checks = [c for c in report["checks"] if c["id"].startswith("origin:")]
        self.assertTrue(origin_checks)
        self.assertTrue(all(c["level"] == "ok" for c in origin_checks), origin_checks)

    def test_off_origin_root_is_an_error_not_a_warning(self):
        self.forge.call("prop.crate", name="crate", location=[5.0, 0.0, 0.0])
        report = self.forge.call("check.asset", triangle_budget=5000)
        origin_fail = [f for f in report["failures"] if f["id"].startswith("origin:")]
        self.assertTrue(origin_fail, "an off-origin root must be reported")
        self.assertEqual(origin_fail[0]["level"], "error")
        self.assertFalse(report["ok"])

    def test_multi_part_recipe_keeps_its_full_extent(self):
        """Regression: a stale matrix_world used to collapse assemblies to a point."""
        room = self.forge.call("kit.room", name="room", size=[2, 2], grid=4.0)
        self.assertGreater(room["bounds"]["size"][0], 7.0)
        self.assertGreater(room["bounds"]["size"][1], 7.0)

    def test_joined_recipes_stay_where_they_were_placed(self):
        """Regression: joined props (barrel, chest, torch) teleported to the origin.

        `join` used to bake world coordinates into a mesh on an object sitting at
        (0,0,0); the object transform was then a lie and set_origin dragged the
        geometry back. Single-part props were unaffected, so a scene came out
        with half its clutter piled in one corner.
        """
        for recipe in ("prop.barrel", "prop.chest", "prop.torch", "prop.tree"):
            with self.subTest(recipe=recipe):
                self.forge.call("session.reset")
                result = self.forge.call(recipe, name="placed", location=[6.0, 4.0, 0.0], seed=1)
                centre_x = (result["bounds"]["min"][0] + result["bounds"]["max"][0]) * 0.5
                centre_y = (result["bounds"]["min"][1] + result["bounds"]["max"][1]) * 0.5
                self.assertAlmostEqual(centre_x, 6.0, delta=0.6)
                self.assertAlmostEqual(centre_y, 4.0, delta=0.6)

    def test_join_result_reports_a_meaningful_transform(self):
        self.forge.call("build.box", name="a", size=[1, 1, 1], location=[4, 0, 0])
        self.forge.call("build.box", name="b", size=[1, 1, 1], location=[6, 0, 0])
        self.forge.call("object.join", names=["a", "b"], into="m")
        info = self.forge.call("object.inspect", name="m")
        self.assertAlmostEqual(info["location"][0], 4.0, places=4)


class Sweep(ForgeCase):
    def test_oval_sweep_closes_without_twisting(self):
        """A Frenet frame flips at inflections and Mobius-strips a closed loop."""
        result = self.forge.call(
            "build.sweep",
            name="track",
            profile=[-10, 0, 10, 0, 10, 0.5, -10, 0.5],
            path_shape="oval",
            straight=40,
            radius=12,
            segments=16,
        )
        size = result["bounds"]["size"]
        self.assertAlmostEqual(size[0], 40 + 2 * 22, delta=0.5)  # straight + 2*(r+width)
        self.assertAlmostEqual(size[2], 0.5, delta=0.05)  # stays flat: no twist

    def test_line_sweep_matches_requested_length(self):
        result = self.forge.call(
            "build.sweep",
            name="wall",
            profile=[-0.5, 0, 0.5, 0, 0.5, 3, -0.5, 3],
            path_shape="line",
            length=20.0,
            segments=8,
        )
        self.assertAlmostEqual(result["bounds"]["size"][0], 20.0, delta=0.1)

    def test_bad_profile_is_rejected_with_an_example(self):
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("build.sweep", name="x", profile=[1, 2, 3])
        self.assertIn("pairs", str(ctx.exception))

    def test_custom_path_requires_points(self):
        with self.assertRaises(ForgeError):
            self.forge.call(
                "build.sweep", name="x", profile=[0, 0, 1, 0, 1, 1], path_shape="custom", path=[]
            )


class Materials(ForgeCase):
    def test_same_preset_with_different_colours_stays_different(self):
        """Regression: a name-keyed material cache silently returned the FIRST
        colour for every later request, so a whole scene came out one shade."""
        self.forge.call("build.box", name="warm", material="stone", color="wood_oak")
        self.forge.call(
            "build.box", name="cool", material="stone", color="ice_blue", location=[3, 0, 0]
        )
        warm = self.forge.call("object.inspect", name="warm")["materials"]
        cool = self.forge.call("object.inspect", name="cool")["materials"]
        self.assertNotEqual(warm, cool, "distinct colours must not share a material")

    def test_identical_requests_still_share_one_material(self):
        self.forge.call("build.box", name="a", material="stone", color="stone_grey")
        self.forge.call(
            "build.box", name="b", material="stone", color="stone_grey", location=[3, 0, 0]
        )
        self.assertEqual(
            self.forge.call("object.inspect", name="a")["materials"],
            self.forge.call("object.inspect", name="b")["materials"],
        )

    def test_palette_names_are_gamma_converted_like_hex(self):
        """Palette entries are authored in sRGB; Blender sockets are linear.
        Converting only hex colours would make the two disagree visibly."""
        palette = self.forge.call("meta.palette")
        leaf = palette["colors"]["leaf_green"]
        # sRGB 0.19/0.36/0.14 -> linear is markedly darker; if the conversion is
        # skipped the authored value comes straight back out.
        self.assertLess(leaf[1], 0.20, f"leaf_green looks unconverted: {leaf}")
        self.assertTrue(palette["hex"]["leaf_green"].startswith("#"))

    def test_reported_palette_colour_round_trips(self):
        """meta.palette's numbers must reproduce the named colour when passed
        back verbatim, or an agent reading the palette gets a different shade
        than one that used the name."""
        reported = self.forge.call("meta.palette")["colors"]["ice_blue"]
        hex_form = self.forge.call("meta.palette")["hex"]["ice_blue"]

        self.forge.call("build.box", name="by_name", material="stone", color="ice_blue")
        self.forge.call(
            "build.box", name="by_value", material="stone", color=hex_form, location=[3, 0, 0]
        )
        # Same colour by two routes must collapse to a single material.
        merged = self.forge.call("material.consolidate", tolerance=0.01)
        self.assertEqual(
            merged["materials_after"],
            1,
            f"palette name and its reported hex disagree: {reported} / {hex_form} "
            f"-> {merged['remaining']}",
        )

    def test_consolidate_merges_duplicates_only(self):
        self.forge.call("build.box", name="a", material="stone", color="stone_grey")
        self.forge.call(
            "build.box", name="b", material="stone", color="stone_grey", location=[3, 0, 0]
        )
        self.forge.call("build.box", name="c", material="gold", location=[6, 0, 0])
        result = self.forge.call("material.consolidate")
        self.assertEqual(result["materials_after"], 2, result["remaining"])

    def test_consolidate_dry_run_changes_nothing(self):
        self.forge.call("build.box", name="a", material="stone", color="stone_grey")
        self.forge.call(
            "build.box", name="b", material="stone", color="stone_grey", location=[3, 0, 0]
        )
        before = self.forge.call("material.list")["count"]
        self.forge.call("material.consolidate", dry_run=True)
        self.assertEqual(self.forge.call("material.list")["count"], before)


class ImportExisting(ForgeCase):
    def test_round_trip_through_glb_preserves_geometry(self):
        source = self.forge.call("prop.barrel", name="barrel", seed=3)
        exported = self.forge.call("export.gltf", out="roundtrip.glb", strict=False)
        self.forge.call("session.reset")
        imported = self.forge.call("session.import", path=exported["path"])
        self.assertEqual(imported["triangles"], source["triangles"])

    def test_rig_import_ignores_blender_armature_display_helper(self):
        source = self.forge.call(
            "char.humanoid",
            name="hero",
            height=1.8,
            build="realistic",
        )
        rig = self.forge.call("char.rig", name="hero", build="realistic")
        self.forge.call(
            "char.animate",
            rig=rig["armature"],
            clip="walk",
            length=20,
        )
        exported = self.forge.call("export.gltf", out="rigged.glb", strict=False)
        self.forge.call("session.reset")
        imported = self.forge.call("session.import", path=exported["path"])
        self.assertEqual(imported["meshes"], 1, imported["objects"])
        self.assertEqual(imported["triangles"], source["triangles"])
        self.assertNotIn("Icosphere", " ".join(imported["objects"]))

    def test_import_of_a_missing_file_is_a_clear_error(self):
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("session.import", path="does/not/exist.glb")
        self.assertIn("no file at", str(ctx.exception))

    def test_unsupported_extension_lists_what_is_supported(self):
        target = Path(TEMP.name) / "thing.xyz"
        target.write_text("not a model", encoding="utf-8")
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("session.import", path=str(target))
        self.assertIn(".glb", str(ctx.exception))


class ExplicitCamera(ForgeCase):
    def test_camera_render_writes_an_image_at_the_requested_aspect(self):
        self.forge.call("prop.crate", name="crate", seed=1)
        result = self.forge.call(
            "render.camera",
            out="cam.png",
            position=[4, -4, 3],
            target=[0, 0, 0.5],
            resolution=192,
            aspect=1.78,
            samples=4,
            _timeout=600,
        )
        self.assertEqual(result["resolution"][0], 192)
        self.assertEqual(result["resolution"][1], int(192 / 1.78))
        self.assertTrue(Path(result["path"]).is_file())

    def test_camera_render_of_an_empty_scene_errors(self):
        with self.assertRaises(ForgeError):
            self.forge.call("render.camera", out="x.png", position=[1, 1, 1], samples=1)


class UVs(ForgeCase):
    def test_unwrap_creates_usable_uvs(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        result = self.forge.call("uv.unwrap", object="b", style="smart_packed")
        self.assertTrue(result["stats"]["has_uvs"])
        self.assertGreater(result["stats"]["texel_density_px_per_m"], 0)

    def test_box_projection_scale_controls_texel_density(self):
        self.forge.call("build.box", name="b", size=[1, 1, 1])
        fine = self.forge.call("uv.unwrap", object="b", style="box", scale=1.0)
        coarse = self.forge.call("uv.unwrap", object="b", style="box", scale=4.0)
        self.assertGreater(
            fine["stats"]["texel_density_px_per_m"],
            coarse["stats"]["texel_density_px_per_m"],
        )

    def test_report_needs_uvs(self):
        self.forge.call("build.box", name="b", uv="none", material="")
        with self.assertRaises(ForgeError):
            self.forge.call("uv.report", object="b")


class GameReady(ForgeCase):
    def test_lod_chain_reduces_monotonically(self):
        self.forge.call("prop.rock", name="rock", detail=3, seed=1)
        result = self.forge.call("gameready.lod", name="rock", levels=3)
        counts = [level["triangles"] for level in result["levels"]]
        self.assertEqual(len(counts), 4)
        for higher, lower in zip(counts, counts[1:], strict=False):
            self.assertLess(lower, higher, f"LOD chain not decreasing: {counts}")

    def test_convex_collision_is_cheaper_than_the_source(self):
        self.forge.call("prop.rock", name="rock", detail=3, seed=2)
        result = self.forge.call("gameready.collision", name="rock", mode="convex")
        self.assertTrue(result["proxy"].endswith("-convcol"))
        self.assertLessEqual(result["triangles"], result["source_triangles"])

    def test_box_collision_matches_the_source_bounds(self):
        source = self.forge.call("prop.crate", name="crate", size=[1.0, 0.8, 0.6])
        proxy = self.forge.call("gameready.collision", name="crate", mode="box")
        for axis in range(3):
            self.assertAlmostEqual(
                proxy["bounds"]["size"][axis], source["bounds"]["size"][axis], places=2
            )

    def test_collision_proxy_naming_matches_studio_convention(self):
        self.forge.call("build.box", name="thing")
        simplified = self.forge.call("gameready.collision", name="thing", mode="simplified")
        self.assertEqual(simplified["proxy"], "thing-col")

    def test_budget_flags_an_over_budget_asset_with_advice(self):
        self.forge.call("env.terrain", name="terrain", resolution=60)
        report = self.forge.call("gameready.budget", profile="mobile_low", asset_class="prop")
        self.assertFalse(report["within_budget"])
        self.assertTrue(report["advice"])

    def test_atlas_collapses_materials_to_one(self):
        self.forge.call("prop.crate", name="a", material="wood")
        self.forge.call("prop.rock", name="b", material="rock", location=[3, 0, 0])
        result = self.forge.call("gameready.atlas", objects=["a", "b"], name="atlased")
        self.assertEqual(len(result["materials_after"]), 1)
        self.assertGreaterEqual(result["draw_calls_saved"], 1)


class Characters(ForgeCase):
    def test_rig_has_one_root_and_skins_the_mesh(self):
        self.forge.call("char.humanoid", name="hero", height=1.8)
        rig = self.forge.call("char.rig", name="hero")
        self.assertEqual(rig["root_bones"], ["hips"])
        self.assertGreater(rig["weighted_vertices"], 0)
        self.assertIn("hand_r", rig["bones"])

    def test_bone_names_satisfy_the_studio_validator(self):

        self.forge.call("char.humanoid", name="hero")
        rig = self.forge.call("char.rig", name="hero")
        for bone in rig["bones"]:
            self.assertRegex(bone, r"^[a-z][a-z0-9_.]*$")

    def test_animation_clips_produce_keyframes(self):
        self.forge.call("char.humanoid", name="hero")
        rig = self.forge.call("char.rig", name="hero")
        for clip in ("idle", "walk", "run", "attack"):
            result = self.forge.call("char.animate", rig=rig["armature"], clip=clip, length=16)
            with self.subTest(clip=clip):
                self.assertGreater(result["keyframes"], 0)
                self.assertGreater(result["fcurves"], 0)

    def test_build_proportions_differ(self):
        chibi = self.forge.call("char.humanoid", name="a", height=1.8, build="chibi")
        self.forge.call("session.reset")
        heroic = self.forge.call("char.humanoid", name="b", height=1.8, build="heroic")
        self.assertGreater(chibi["head_unit_m"], heroic["head_unit_m"])

    def test_greek_outfit_is_riggable_multi_material_game_geometry(self):
        body = self.forge.call(
            "char.humanoid",
            name="delver",
            height=1.9,
            build="realistic",
            detail=8,
        )
        self.assertEqual(body["anatomy"], "shaped_adult")
        self.assertEqual(body["facial_parts"], 5)
        outfit = self.forge.call(
            "char.outfit",
            name="delver",
            style="greek_delver",
            detail=10,
        )
        self.assertGreater(outfit["triangles"], body["triangles"])
        self.assertLess(outfit["triangles"], 8000)
        self.assertGreaterEqual(outfit["armour_parts"], 20)
        self.assertGreaterEqual(len(outfit["materials"]), 5)
        self.assertAlmostEqual(outfit["bounds"]["min"][2], 0.0, places=3)
        self.assertEqual(outfit["silhouette"], "open_faced_mining_commander")
        self.assertEqual(
            outfit["facial_readability"],
            "open_crown_cheeks_eyes_trimmed_beard",
        )
        self.assertEqual(outfit["work_gear_parts"], 4)
        self.assertLess(outfit["bounds"]["size"][1], outfit["bounds"]["size"][0] * 0.9)

        rig = self.forge.call("char.rig", name="delver", build="realistic")
        self.assertEqual(rig["weighted_vertices"], outfit["vertices"])
        animated = self.forge.call(
            "char.animate",
            rig=rig["armature"],
            clip="walk",
            length=20,
        )
        self.assertGreater(animated["keyframes"], 0)
        posed = self.forge.call("char.pose", rig=rig["armature"], preset="rest")
        self.assertEqual(posed["cleared_active_action"], animated["action"])
        self.assertIn(animated["action"], posed["available_actions"])
        self.assertEqual(posed["posed_bones"], [])

    def test_rts_archer_and_heavy_guard_are_distinct_riggable_outfits(self):
        self.forge.call(
            "char.humanoid",
            name="toxotes",
            height=1.82,
            build="lithe",
            detail=8,
        )
        archer = self.forge.call(
            "char.outfit",
            name="toxotes",
            style="toxotes",
            detail=9,
        )
        self.assertEqual(archer["style"], "toxotes")
        self.assertGreaterEqual(archer["armour_parts"], 28)
        self.assertIn("m_outfit_leather", archer["materials"])
        archer_rig = self.forge.call(
            "char.rig",
            name="toxotes",
            height=1.82,
            build="lithe",
        )
        self.assertEqual(archer_rig["weighted_vertices"], archer["vertices"])

        self.forge.call("session.reset")
        self.forge.call(
            "char.humanoid",
            name="hypaspist",
            height=1.94,
            build="heroic",
            detail=8,
        )
        guard = self.forge.call(
            "char.outfit",
            name="hypaspist",
            style="hypaspist",
            detail=10,
        )
        self.assertEqual(guard["style"], "hypaspist")
        self.assertGreater(guard["triangles"], archer["triangles"])
        self.assertGreater(guard["armour_parts"], archer["armour_parts"])
        guard_rig = self.forge.call(
            "char.rig",
            name="hypaspist",
            height=1.94,
            build="heroic",
        )
        self.assertEqual(guard_rig["weighted_vertices"], guard["vertices"])

    def test_outfit_must_be_added_before_rigging(self):
        self.forge.call("char.humanoid", name="hero")
        self.forge.call("char.rig", name="hero")
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("char.outfit", name="hero")
        self.assertIn("before char.rig", str(ctx.exception))

    def test_boss_outfits_have_distinct_riggable_serious_silhouettes(self):
        self.forge.call(
            "char.skeleton",
            name="strategos",
            height=2.2,
            build="heroic",
            detail=8,
        )
        commander = self.forge.call(
            "char.outfit",
            name="strategos",
            style="strategos",
            detail=10,
        )
        self.assertEqual(commander["style"], "strategos")
        self.assertGreaterEqual(commander["armour_parts"], 35)
        self.assertIn("m_outfit_accent", commander["materials"])
        self.assertNotIn("m_outfit_glow", commander["materials"])
        commander_rig = self.forge.call(
            "char.rig",
            name="strategos",
            height=2.2,
            build="heroic",
        )
        self.assertEqual(commander_rig["weighted_vertices"], commander["vertices"])

        self.forge.call("session.reset")
        self.forge.call(
            "char.humanoid",
            name="warlock",
            height=2.05,
            build="lithe",
            detail=8,
        )
        ritualist = self.forge.call(
            "char.outfit",
            name="warlock",
            style="warlock",
            detail=10,
        )
        self.assertEqual(ritualist["style"], "warlock")
        self.assertGreaterEqual(ritualist["armour_parts"], 30)
        self.assertIn("m_outfit_accent", ritualist["materials"])
        self.assertIn("m_outfit_glow", ritualist["materials"])
        ritualist_rig = self.forge.call(
            "char.rig",
            name="warlock",
            height=2.05,
            build="lithe",
        )
        self.assertEqual(ritualist_rig["weighted_vertices"], ritualist["vertices"])

    def test_skeleton_body_outfits_rigs_and_animates(self):
        bones = self.forge.call(
            "char.skeleton",
            name="peltast",
            height=1.86,
            build="lithe",
            detail=8,
        )
        self.assertEqual(bones["anatomy"], "joined_bone_body")
        self.assertEqual(len(bones["materials"]), 2)
        self.assertGreater(bones["triangles"], 1000)
        self.assertLess(bones["triangles"], 5000)
        self.assertAlmostEqual(bones["bounds"]["min"][2], 0.0, places=3)

        dressed = self.forge.call(
            "char.outfit",
            name="peltast",
            style="peltast",
            detail=8,
        )
        self.assertGreater(dressed["triangles"], bones["triangles"])
        self.assertGreaterEqual(len(dressed["materials"]), 6)
        rig = self.forge.call(
            "char.rig",
            name="peltast",
            height=1.86,
            build="lithe",
        )
        self.assertEqual(rig["weighted_vertices"], dressed["vertices"])
        walk = self.forge.call(
            "char.animate",
            rig=rig["armature"],
            clip="walk",
            length=24,
        )
        self.assertGreater(walk["keyframes"], 0)


class Creatures(ForgeCase):
    def test_hound_is_deterministic_grounded_multi_material_geometry(self):
        first = self.forge.call(
            "creature.hound",
            name="hound",
            length=1.75,
            shoulder_height=1.0,
            detail=8,
        )
        self.assertEqual(first["creature"], "hound")
        self.assertEqual(len(first["materials"]), 4)
        self.assertGreater(first["triangles"], 700)
        self.assertLess(first["triangles"], 5000)
        self.assertAlmostEqual(first["bounds"]["min"][2], 0.0, places=3)
        self.assertGreater(first["bounds"]["size"][1], first["bounds"]["size"][2])

        self.forge.call("session.reset")
        second = self.forge.call(
            "creature.hound",
            name="hound",
            length=1.75,
            shoulder_height=1.0,
            detail=8,
        )
        self.assertEqual(first["triangles"], second["triangles"])
        self.assertEqual(first["bounds"], second["bounds"])

    def test_scarab_is_low_wide_grounded_multi_material_geometry(self):
        scarab = self.forge.call(
            "creature.scarab",
            name="scarab",
            length=1.55,
            width=0.95,
            height=0.62,
            detail=8,
        )
        self.assertEqual(scarab["creature"], "scarab")
        self.assertEqual(len(scarab["materials"]), 4)
        self.assertGreater(scarab["triangles"], 700)
        self.assertLess(scarab["triangles"], 5000)
        self.assertAlmostEqual(scarab["bounds"]["min"][2], 0.0, places=3)
        self.assertGreater(scarab["bounds"]["size"][0], scarab["bounds"]["size"][2])
        self.assertGreater(scarab["bounds"]["size"][1], scarab["bounds"]["size"][2])


class Validation(ForgeCase):
    def test_generated_props_pass_studio_validation(self):
        for recipe in ("prop.crate", "prop.barrel", "prop.rock", "prop.pillar"):
            with self.subTest(recipe=recipe):
                self.forge.call("session.reset")
                self.forge.call(recipe, name="asset", seed=1)
                report = self.forge.call("check.asset", triangle_budget=5000, material_budget=3)
                self.assertTrue(
                    report["ok"],
                    f"{recipe} failed validation: {report['failures']}",
                )

    def test_critique_finds_a_missing_uv_set(self):
        self.forge.call("build.box", name="b", uv="none", material="")
        report = self.forge.call("check.critique")
        issues = {f["issue"] for f in report["findings"]}
        self.assertIn("no UVs", issues)

    def test_critique_is_clean_on_a_good_asset(self):
        self.forge.call("prop.barrel", name="barrel", seed=1)
        report = self.forge.call("check.critique")
        self.assertEqual(report["errors"], 0, f"unexpected errors: {report['findings']}")

    def test_silhouette_scoring_distinguishes_a_box_from_a_tree(self):
        self.forge.call("build.box", name="boxy", size=[1, 1, 1], bevel=0.0)
        boxy = self.forge.call("check.silhouette", name="boxy", samples=24)
        self.forge.call("session.reset")
        self.forge.call("prop.tree", name="tree", seed=1)
        tree = self.forge.call("check.silhouette", name="tree", samples=24)
        self.assertGreater(boxy["average_fill"], tree["average_fill"])


class Export(ForgeCase):
    def test_glb_is_a_valid_container(self):
        self.forge.call("prop.crate", name="crate", seed=1)
        result = self.forge.call("export.gltf", out="crate.glb")
        data = Path(result["path"]).read_bytes()
        magic, version, length = struct.unpack_from("<III", data, 0)
        self.assertEqual(magic, 0x46546C67, "GLB magic")
        self.assertEqual(version, 2)
        self.assertEqual(length, len(data))

    def test_strict_export_blocks_unapplied_scale(self):
        self.forge.call("build.box", name="b")
        self.forge.call("object.transform", name="b", scale=[2, 2, 2], apply=False)
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("export.gltf", out="bad.glb", strict=True)
        self.assertIn("unapplied scale", str(ctx.exception))

    def test_bone_attachment_rotation_is_not_an_export_warning(self):
        self.forge.call("char.humanoid", name="hero")
        rig = self.forge.call("char.rig", name="hero")
        self.forge.call(
            "build.cylinder",
            name="spear",
            radius=0.025,
            depth=1.8,
            location=[-0.2, 0.0, 0.9],
        )
        self.forge.call(
            "char.attach",
            prop="spear",
            rig=rig["armature"],
            bone="hand_r",
            keep_transform=True,
        )
        report = self.forge.call("check.asset", triangle_budget=5000)
        transform = next(check for check in report["checks"] if check["id"] == "transforms:spear")
        self.assertEqual(transform["level"], "ok")
        exported = self.forge.call("export.gltf", out="attached.glb", strict=True)
        self.assertFalse(
            any("spear" in warning and "rotation" in warning for warning in exported["warnings"])
        )

    def test_strict_export_blocks_unbaked_procedural_materials(self):
        self.forge.call("build.box", name="b")
        self.forge.call("material.procedural", object="b", kind="noise")
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("export.gltf", out="bad.glb", strict=True)
        self.assertIn("material.bake", str(ctx.exception))

    def test_meta_sidecar_declares_ai_provenance(self):
        self.forge.call("prop.crate", name="crate")
        result = self.forge.call(
            "export.meta", out="crate.meta.json", asset_id="crate_a", ai_prompt="a wooden crate"
        )
        meta = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(meta["asset_id"], "crate_a")
        self.assertEqual(meta["provenance"]["method"], "ai_generated")
        self.assertEqual(meta["provenance"]["ai"]["prompt"], "a wooden crate")

    def test_crossbow_styles_add_real_construction_with_one_joined_mesh(self):
        previous_tris = 0
        for style in ("pilgrim", "repeater", "daedalus", "aegis"):
            self.forge.call("session.reset")
            result = self.forge.call(
                "prop.crossbow",
                name=f"crossbow_{style}",
                style=style,
                length=1.18,
                span=0.92,
                scope=True,
                seed=17,
            )
            self.assertGreater(result["triangles"], 1600)
            self.assertLessEqual(result["triangles"], 6500)
            self.assertGreater(result["triangles"], previous_tris)
            self.assertEqual(len(result["materials"]), 5)
            self.assertGreater(result["bounds"]["size"][0], 0.85)
            self.assertGreater(result["bounds"]["size"][2], 1.1)
            self.assertTrue(result["scope"])
            self.assertEqual(result["magazine"], style != "pilgrim")
            self.assertEqual(result["gearing"], style in ("daedalus", "aegis"))
            self.assertEqual(result["power_core"], style == "aegis")
            previous_tris = result["triangles"]

    def test_recurve_bow_has_a_grip_pivot_string_and_nocked_arrow(self):
        result = self.forge.call(
            "prop.bow",
            name="toxotes_bow",
            length=1.42,
            reflex=0.16,
            draw=0.24,
            arrow=True,
            seed=19,
        )
        self.assertGreater(result["triangles"], 500)
        self.assertLessEqual(result["triangles"], 1800)
        self.assertEqual(len(result["materials"]), 3)
        self.assertGreater(result["bounds"]["size"][2], 1.35)
        self.assertGreater(result["bounds"]["size"][1], 0.45)
        self.assertTrue(result["arrow"])
        self.assertGreaterEqual(result["parts"], 14)

    def test_export_asset_writes_the_full_hand_off(self):
        self.forge.call("prop.barrel", name="barrel", seed=1)
        result = self.forge.call(
            "export.asset", asset_id="barrel_a", contact_sheet=False, _timeout=600
        )
        for kind in ("blend", "glb", "meta"):
            self.assertIn(kind, result["outputs"])
        meta_path = Path(result["detail"]["meta"]["path"])
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(
            meta["budgets"]["materials"],
            len(meta["measured"]["materials"]),
            "export.asset must not hard-code a budget that contradicts its measured asset",
        )


class Rendering(ForgeCase):
    def test_render_produces_a_non_empty_image(self):
        self.forge.call("prop.crate", name="crate", seed=1)
        result = self.forge.call(
            "render.view", out="shot.png", resolution=128, samples=4, _timeout=600
        )
        path = Path(result["path"])
        self.assertTrue(path.is_file())
        self.assertGreater(path.stat().st_size, 1000)

    def test_contact_sheet_tiles_every_requested_panel(self):
        self.forge.call("prop.crate", name="crate", seed=1)
        result = self.forge.call(
            "render.contact_sheet",
            out="sheet.png",
            tile=96,
            samples=4,
            panels=["hero", "front", "wireframe", "checker"],
            columns=2,
            _timeout=900,
        )
        self.assertEqual(result["panels"], ["hero", "front", "wireframe", "checker"])
        self.assertEqual(result["layout"], "2x2")
        self.assertTrue(Path(result["path"]).is_file())

    def test_render_of_an_empty_scene_is_a_clear_error(self):
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("render.view", out="empty.png", resolution=64, samples=1)
        self.assertIn("no mesh objects", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
