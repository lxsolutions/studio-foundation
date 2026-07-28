"""Tests for the generated renderer-status table.

The generator exists to stop a documented renderer state from being more
optimistic than the last measurement, so these tests mostly assert that it
refuses to flatter a result.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "verification"))

import render_report as rr  # noqa: E402


def _probe(**overrides) -> dict:
    base = {
        "label": "probe",
        "frame_rendered": True,
        "gpu_validation_errors": 0,
        "gpu_validation_by_class": {},
        "adapter": {"vendor": "nvidia", "architecture": "pascal"},
    }
    base.update(overrides)
    return base


def _dir_with(probes: list[dict], tmp: str) -> Path:
    root = Path(tmp)
    for i, probe in enumerate(probes):
        (root / f"{i}.json").write_text(json.dumps(probe), encoding="utf-8")
    return root


class VerdictTests(unittest.TestCase):
    def test_clean_render_is_reported_as_clean(self) -> None:
        self.assertEqual(rr._verdict(_probe()), "renders clean")

    def test_compiling_without_pixels_is_not_a_render(self) -> None:
        """Zero errors and a blank canvas is still a failure."""
        probe = _probe(frame_rendered=False, gpu_validation_errors=0)
        self.assertEqual(rr._verdict(probe), "does not render")

    def test_rendering_with_errors_is_not_called_clean(self) -> None:
        probe = _probe(gpu_validation_errors=3)
        self.assertEqual(rr._verdict(probe), "renders, with validation errors")

    def test_missing_flag_is_not_treated_as_success(self) -> None:
        probe = _probe()
        del probe["frame_rendered"]
        self.assertEqual(rr._verdict(probe), "does not render")

    def test_unmeasured_errors_are_not_reported_as_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _dir_with([_probe(gpu_validation_errors=None)], tmp)
            table = rr.render_table(rr.load_probes(root))
            self.assertIn("not measured", table)
            self.assertNotIn("| 0 |", table)


class LoadTests(unittest.TestCase):
    def test_missing_directory_is_an_error(self) -> None:
        with self.assertRaises(rr.ReportError):
            rr.load_probes(Path("no-such-directory-anywhere"))

    def test_empty_directory_is_an_error_not_an_empty_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(rr.ReportError):
                rr.load_probes(Path(tmp))

    def test_unrelated_json_is_skipped_not_misread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name": "not-a-probe"}', encoding="utf-8")
            (root / "probe.json").write_text(json.dumps(_probe()), encoding="utf-8")
            self.assertEqual(len(rr.load_probes(root)), 1)

    def test_malformed_json_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(rr.ReportError):
                rr.load_probes(Path(tmp))


class SpliceTests(unittest.TestCase):
    def test_replaces_an_existing_block_without_duplicating(self) -> None:
        table = rr.render_table([_probe(label="one")])
        doc = "# Title\n\n" + table + "\n\ntrailing prose\n"
        newer = rr.render_table([_probe(label="two")])
        updated = rr.splice(doc, newer)
        self.assertEqual(updated.count(rr.MARK_BEGIN), 1)
        self.assertIn("two", updated)
        self.assertNotIn("`one`", updated)
        self.assertIn("trailing prose", updated)

    def test_appends_when_no_block_is_present(self) -> None:
        table = rr.render_table([_probe()])
        updated = rr.splice("# Title\n", table)
        self.assertIn(rr.MARK_BEGIN, updated)
        self.assertTrue(updated.startswith("# Title"))

    def test_splice_is_idempotent(self) -> None:
        table = rr.render_table([_probe()])
        once = rr.splice("# Title\n", table)
        twice = rr.splice(once, table)
        self.assertEqual(once, twice)


class CheckModeTests(unittest.TestCase):
    def test_check_fails_on_a_stale_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _dir_with([_probe(frame_rendered=False, gpu_validation_errors=9)], tmp)
            doc = Path(tmp) / "status.md"
            doc.write_text("# Renderer\n\nAll good!\n", encoding="utf-8")
            rc = rr.main(["--probe", str(root), "--out", str(doc), "--check"])
            self.assertEqual(rc, 1)

    def test_check_passes_right_after_a_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _dir_with([_probe()], tmp)
            doc = Path(tmp) / "status.md"
            self.assertEqual(rr.main(["--probe", str(root), "--out", str(doc)]), 0)
            self.assertEqual(rr.main(["--probe", str(root), "--out", str(doc), "--check"]), 0)

    def test_check_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _dir_with([_probe()], tmp)
            doc = Path(tmp) / "status.md"
            doc.write_text("# Renderer\n", encoding="utf-8")
            rr.main(["--probe", str(root), "--out", str(doc), "--check"])
            self.assertEqual(doc.read_text(encoding="utf-8"), "# Renderer\n")


if __name__ == "__main__":
    unittest.main()
