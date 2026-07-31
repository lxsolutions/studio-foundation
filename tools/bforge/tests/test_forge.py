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
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge.client import DaemonError, Forge, ForgeError, find_blender  # noqa: E402

FORGE: Forge | None = None
TEMP: tempfile.TemporaryDirectory | None = None


def _write_rgba_png(path: Path, width: int, height: int, pixel):
    """Write a tiny fixture without adding Pillow to the stdlib-only toolchain."""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(pixel(x, y))
        rows.append(bytes(row))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


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

    def test_export_asset_writes_the_full_hand_off(self):
        self.forge.call("prop.barrel", name="barrel", seed=1)
        result = self.forge.call(
            "export.asset", asset_id="barrel_a", contact_sheet=False, _timeout=600
        )
        for kind in ("blend", "glb", "meta"):
            self.assertIn(kind, result["outputs"])


class Rendering(ForgeCase):
    def test_render_produces_a_non_empty_image(self):
        self.forge.call("prop.crate", name="crate", seed=1)
        result = self.forge.call(
            "render.view", out="shot.png", resolution=128, samples=4, _timeout=600
        )
        path = Path(result["path"])
        self.assertTrue(path.is_file())
        self.assertGreater(path.stat().st_size, 1000)

    def test_ui_card_has_alpha_and_measured_subject_coverage(self):
        self.forge.call("prop.crate", name="crate", seed=1)
        result = self.forge.call(
            "render.ui_card",
            out="crate_card.png",
            resolution=128,
            samples=4,
            padding=1.2,
            _timeout=600,
        )
        path = Path(result["path"])
        self.assertTrue(path.is_file())
        self.assertGreater(path.stat().st_size, 1000)
        self.assertTrue(result["alpha"])
        self.assertGreater(result["subject_coverage"], 0.08)
        self.assertLess(result["subject_coverage"], 0.9)

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

    def test_environment_audit_finds_dominant_repeating_bands(self):
        fixture = Path(TEMP.name) / "striped-water.png"
        _write_rgba_png(
            fixture,
            96,
            64,
            lambda x, _y: (18, 58, 73, 255) if (x // 4) % 2 else (72, 161, 183, 255),
        )
        result = self.forge.call("check.environment", path=str(fixture), grid=4, ui_margin=0.0)
        self.assertGreater(result["periodicity"]["p90_peak_share"], 0.34)
        self.assertIn(
            "dominant periodic texture pattern",
            {finding["issue"] for finding in result["findings"]},
        )
        self.assertEqual(result["periodicity"]["method"], "windowed_cell_fft")

    def test_sprite_audit_measures_alpha_padding_and_clipping(self):
        centred = Path(TEMP.name) / "centred-sprite.png"
        _write_rgba_png(
            centred,
            64,
            64,
            lambda x, y: (126, 83, 52, 255)
            if 16 <= x < 48 and 8 <= y < 56 else (0, 0, 0, 0),
        )
        result = self.forge.call(
            "check.sprite",
            path=str(centred),
            min_coverage=0.08,
            max_coverage=0.82,
            edge_guard=2,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["padding"], {"left": 16, "right": 16, "top": 8, "bottom": 8})
        self.assertAlmostEqual(result["subject_coverage"], 0.375)

        clipped = Path(TEMP.name) / "clipped-sprite.png"
        _write_rgba_png(
            clipped,
            64,
            64,
            lambda x, y: (126, 83, 52, 255)
            if x < 32 and 8 <= y < 56 else (0, 0, 0, 0),
        )
        result = self.forge.call("check.sprite", path=str(clipped), edge_guard=2)
        self.assertFalse(result["ok"])
        self.assertIn(
            "sprite touches crop edge",
            {finding["issue"] for finding in result["findings"]},
        )
        self.assertEqual(result["padding"]["left"], 0)

        spilled = Path(TEMP.name) / "spilled-sprite.png"
        _write_rgba_png(
            spilled,
            64,
            64,
            lambda x, y: (255, 0, 255, 255)
            if 16 <= x < 48 and 8 <= y < 56 else (0, 0, 0, 0),
        )
        result = self.forge.call(
            "check.sprite",
            path=str(spilled),
            forbidden_color=[1.0, 0.0, 1.0, 1.0],
            color_tolerance=0.08,
            max_forbidden_share=0.002,
        )
        self.assertFalse(result["ok"])
        self.assertGreater(result["forbidden_color_share"], 0.99)
        self.assertIn(
            "forbidden color spill",
            {finding["issue"] for finding in result["findings"]},
        )

    def test_render_of_an_empty_scene_is_a_clear_error(self):
        with self.assertRaises(ForgeError) as ctx:
            self.forge.call("render.view", out="empty.png", resolution=64, samples=1)
        self.assertIn("no mesh objects", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
