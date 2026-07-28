"""Tests for build provenance: series identity, stamping, and lineage detection.

The detector's job is to be believed, so the tests weight false positives more
heavily than false negatives. Accusing an unrelated project of carrying our code
is the failure that matters.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pylib"))

from studio_tools.provenance import (  # noqa: E402
    STUDIO_SERIES_THRESHOLD,
    VERDICT_NONE,
    VERDICT_STUDIO_SERIES,
    VERDICT_WEBGPU_BACKEND,
    Marker,
    ProvenanceError,
    build_stamp,
    classify,
    load_markers,
    required_attribution,
    scan_artifact,
    series_from_lock,
    series_id,
)

DATA_DIR = REPO_ROOT / "tools" / "provenance"

BASE = "a13da4feb8d8aefc283c3763d33a2f170a18d541"
D1 = "1" * 64
D2 = "2" * 64

LOCK = {
    "godot": {
        "official": {"repo": "https://github.com/godotengine/godot"},
        "webgpu": {
            "base": "4.7.1-stable",
            "base_commit": BASE,
            "source_lineage_repo": "https://github.com/dwalter/godotwebgpu",
            "source_lineage_commit": "f329e39ce8db7acaa5c9d6628a530fb769969228",
        },
    },
    "toolchain": {"emscripten": "4.0.11", "scons": "4.9.1"},
    "patches": {
        "series": [
            {"file": "patches/0001-a.patch", "sha256": D1},
            {"file": "patches/0002-b.patch", "sha256": D2},
        ]
    },
}


class SeriesIdTests(unittest.TestCase):
    def test_id_is_deterministic(self) -> None:
        a = series_id(BASE, [("patches/0001-a.patch", D1)])
        b = series_id(BASE, [("patches/0001-a.patch", D1)])
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("sfwebgpu-1:"))

    def test_order_is_part_of_identity(self) -> None:
        """Same patches, different apply order, is a different engine."""
        forward = series_id(BASE, [("a.patch", D1), ("b.patch", D2)])
        reversed_ = series_id(BASE, [("b.patch", D2), ("a.patch", D1)])
        self.assertNotEqual(forward, reversed_)

    def test_content_change_changes_the_id(self) -> None:
        before = series_id(BASE, [("a.patch", D1)])
        after = series_id(BASE, [("a.patch", D2)])
        self.assertNotEqual(before, after)

    def test_separator_cannot_be_forged_through_a_filename(self) -> None:
        """A path containing the field separator must not collide with two patches."""
        sneaky = series_id(BASE, [(f"a.patch {D1}\n0002 b.patch", D2)])
        honest = series_id(BASE, [("a.patch", D1), ("b.patch", D2)])
        self.assertNotEqual(sneaky, honest)

    def test_path_separators_are_normalized(self) -> None:
        """A Windows checkout must produce the same id as a POSIX one."""
        self.assertEqual(
            series_id(BASE, [("patches\\0001-a.patch", D1)]),
            series_id(BASE, [("patches/0001-a.patch", D1)]),
        )

    def test_rejects_bad_input(self) -> None:
        with self.assertRaises(ProvenanceError):
            series_id("not-a-sha", [("a.patch", D1)])
        with self.assertRaises(ProvenanceError):
            series_id(BASE, [])
        with self.assertRaises(ProvenanceError):
            series_id(BASE, [("a.patch", "SHORT")])

    def test_reads_the_real_repository_lock(self) -> None:
        """The shipped lock must actually produce an id; a broken lock is a bug."""
        import tomllib

        lock_path = REPO_ROOT / "engine" / "engine-lock.toml"
        with lock_path.open("rb") as handle:
            lock = tomllib.load(handle)
        base, patches = series_from_lock(lock)
        self.assertTrue(series_id(base, patches).startswith("sfwebgpu-1:"))
        self.assertGreaterEqual(len(patches), 22)


class StampTests(unittest.TestCase):
    def test_stamp_records_the_series_and_lineage(self) -> None:
        stamp = build_stamp(LOCK)
        self.assertEqual(stamp["engine"]["patch_count"], 2)
        self.assertEqual(stamp["engine"]["base_commit"], BASE)
        self.assertTrue(stamp["attribution_required"])
        self.assertIn("dwalter", stamp["lineage"]["webgpu_backend_origin"])

    def test_attribution_names_every_upstream(self) -> None:
        text = required_attribution(build_stamp(LOCK))
        self.assertIn("MIT", text)
        self.assertIn("dwalter", text)
        self.assertIn("Godot Engine", text)
        self.assertIn("Juan Linietsky", text)
        self.assertIn(BASE, text)


class MarkerTableTests(unittest.TestCase):
    def test_shipped_table_loads_and_covers_both_tiers(self) -> None:
        markers = load_markers(DATA_DIR)
        tiers = {m.tier for m in markers}
        self.assertEqual(tiers, {"studio-series", "webgpu-backend"})
        self.assertGreaterEqual(
            sum(1 for m in markers if m.tier == "studio-series"),
            STUDIO_SERIES_THRESHOLD,
        )

    def test_every_marker_names_the_patch_that_introduced_it(self) -> None:
        for marker in load_markers(DATA_DIR):
            self.assertTrue(marker.introduced_by, f"{marker.name} has no provenance")
            self.assertTrue(
                (REPO_ROOT / "engine" / "patches" / marker.introduced_by).is_file(),
                f"{marker.name} cites a patch that does not exist: {marker.introduced_by}",
            )

    def test_studio_markers_really_appear_in_the_patch_they_cite(self) -> None:
        """A marker must be traceable to an added line, or it is folklore."""
        for marker in load_markers(DATA_DIR):
            if marker.tier != "studio-series":
                continue
            patch = (REPO_ROOT / "engine" / "patches" / marker.introduced_by).read_bytes()
            added = b"\n".join(
                line[1:]
                for line in patch.splitlines()
                if line.startswith(b"+") and not line.startswith(b"+++")
            )
            self.assertIn(
                marker.pattern,
                added,
                f"{marker.name} is not in an added line of {marker.introduced_by}",
            )

    def test_rejects_a_malformed_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "webgpu-markers.json"
            bad.write_text(json.dumps({"markers": [{"name": "x", "tier": "nope", "pattern": "y"}]}))
            with self.assertRaises(ProvenanceError):
                load_markers(Path(tmp))

    def test_rejects_duplicate_marker_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"name": "dup", "tier": "studio-series", "pattern": "z"}
            (Path(tmp) / "webgpu-markers.json").write_text(json.dumps({"markers": [entry, entry]}))
            with self.assertRaises(ProvenanceError):
                load_markers(Path(tmp))


def _markers() -> list[Marker]:
    return [
        Marker("s1", "studio-series", b"STUDIO_ONE", "0015-x.patch"),
        Marker("s2", "studio-series", b"STUDIO_TWO", "0018-x.patch"),
        Marker("b1", "webgpu-backend", b"BACKEND_ONE", "0001-x.patch"),
    ]


class DetectionTests(unittest.TestCase):
    def test_finds_markers_in_a_directory_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.wasm").write_bytes(b"junk STUDIO_ONE junk STUDIO_TWO BACKEND_ONE")
            result = scan_artifact(root, _markers())
            report = classify(result, _markers())
            self.assertEqual(report["verdict"], VERDICT_STUDIO_SERIES)
            self.assertTrue(report["attribution_required"])

    def test_finds_markers_inside_a_zip_without_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "template.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("godot.wasm", "x STUDIO_ONE x STUDIO_TWO x")
            report = classify(scan_artifact(archive, _markers()), _markers())
            self.assertEqual(report["verdict"], VERDICT_STUDIO_SERIES)

    def test_stock_engine_is_not_accused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "godot.wasm").write_bytes(b"an ordinary engine with none of it")
            report = classify(scan_artifact(root, _markers()), _markers())
            self.assertEqual(report["verdict"], VERDICT_NONE)
            self.assertFalse(report["attribution_required"])

    def test_one_marker_is_not_enough_to_claim_lineage(self) -> None:
        """A single string can be coincidence. Two is a claim."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "godot.wasm").write_bytes(b"only STUDIO_ONE here")
            report = classify(scan_artifact(root, _markers()), _markers())
            self.assertNotEqual(report["verdict"], VERDICT_STUDIO_SERIES)
            self.assertFalse(report["attribution_required"])

    def test_backend_only_build_is_reported_as_inconclusive(self) -> None:
        """Another WebGPU backend descendant is not automatically ours."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "godot.wasm").write_bytes(b"BACKEND_ONE and nothing else")
            report = classify(scan_artifact(root, _markers()), _markers())
            self.assertEqual(report["verdict"], VERDICT_WEBGPU_BACKEND)
            self.assertFalse(report["attribution_required"])

    def test_missing_path_is_an_error_not_a_clean_bill(self) -> None:
        with self.assertRaises(ProvenanceError):
            scan_artifact(Path("does-not-exist-anywhere"), _markers())

    def test_a_corrupt_zip_is_skipped_not_silently_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.zip").write_bytes(b"this is not a zip file at all")
            result = scan_artifact(root, _markers())
            self.assertTrue(result.skipped, "a corrupt archive must be reported")

    def test_stamp_is_read_back_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.wasm").write_bytes(b"STUDIO_ONE STUDIO_TWO")
            (root / "provenance.json").write_text(json.dumps(build_stamp(LOCK)))
            report = classify(scan_artifact(root, _markers()), _markers())
            self.assertEqual(report["stamp_series_id"], build_stamp(LOCK)["series_id"])

    def test_a_forged_stamp_does_not_change_the_marker_verdict(self) -> None:
        """Lineage comes from the bytes, not from a file anyone can write."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.wasm").write_bytes(b"STUDIO_ONE STUDIO_TWO")
            (root / "provenance.json").write_text(json.dumps({"series_id": "sfwebgpu-1:0000"}))
            report = classify(scan_artifact(root, _markers()), _markers())
            self.assertEqual(report["verdict"], VERDICT_STUDIO_SERIES)
            self.assertTrue(report["attribution_required"])

    def test_stripping_the_stamp_does_not_hide_the_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.wasm").write_bytes(b"STUDIO_ONE STUDIO_TWO")
            report = classify(scan_artifact(root, _markers()), _markers())
            self.assertEqual(report["verdict"], VERDICT_STUDIO_SERIES)
            self.assertIsNone(report["stamp_series_id"])


if __name__ == "__main__":
    unittest.main()
