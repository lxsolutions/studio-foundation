from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import engine  # noqa: E402


def _lock(artifacts: dict) -> dict:
    published_record = {"file": "template.zip", "bytes": 42, "sha256": "e" * 64}
    return {
        "godot": {
            "official": {
                "tag": "4.7.1-stable",
                "commit": "a" * 40,
                "repo": "https://example.invalid/godot",
            },
            "webgpu": {
                "base": "official",
                "base_commit": "a" * 40,
                "status": "beta",
                "source_lineage_commit": "b" * 40,
                "source_lineage_repo": "https://example.invalid/lineage",
            },
        },
        "toolchain": {
            "emscripten": "4.0.11",
            "scons": "4.9.1",
            "python": "3.11",
            "rust": "1.97.1",
            "emdawnwebgpu": {
                "version": "v1",
                "revision": "c" * 40,
                "upstream_fix_commit": "d" * 40,
            },
        },
        "patches": {"series": [{"file": "one"}]},
        "artifacts": {
            "export_templates": artifacts,
            "export_templates_provenance": {
                "patch_through": 14,
                "renderer": "Forward Mobile",
            },
        },
        "releases": {
            "godot_4_7_1_webgpu_p0014": {
                "tag": "godot-4.7.1-webgpu-p0014",
                "patch_through": 14,
                "web_webgpu_release": published_record,
                "web_webgpu_debug": published_record,
            }
        },
        "development": {
            "webgpu_forward_plus": {
                "patch_through": 22,
                "gpu_validation_errors": 18,
                "rendered_frame": False,
            }
        },
    }


class EngineVersionsTests(unittest.TestCase):
    def output(self, artifacts: dict) -> str:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(engine.cmd_versions(_lock(artifacts)), 0)
        return stream.getvalue()

    def test_blocked_metadata_is_not_counted_as_templates(self) -> None:
        output = self.output(
            {"status": "blocked", "blocker": "browser verification pending"}
        )
        self.assertIn(
            "artifact records: 0 template(s) (blocked: browser verification pending)",
            output,
        )

    def test_counts_only_complete_template_records(self) -> None:
        record = {"file": "template.zip", "bytes": 42, "sha256": "e" * 64}
        output = self.output(
            {"release": record, "debug": record, "unrelated": "ignored"}
        )
        self.assertIn("artifact records: 2 template(s)", output)

    def test_reports_accepted_and_published_patch_boundaries(self) -> None:
        output = self.output({})
        self.assertIn("accepted build  : through patch 0014 (Forward Mobile)", output)
        self.assertIn(
            "published      : godot-4.7.1-webgpu-p0014 through patch 0014 "
            "(2 template(s))",
            output,
        )
        self.assertIn(
            "forward+ dev   : patch 0022, 18 validation error(s), no frame",
            output,
        )


if __name__ == "__main__":
    unittest.main()
