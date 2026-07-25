from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tools" / "ci" / "validate_public_evidence.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("public_evidence_validator", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class PublicEvidenceValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lock = validator.read_lock(REPO)
        cls.readme = validator.read_text(REPO, validator.README_PATH)
        cls.evidence = validator.read_text(REPO, validator.EVIDENCE_PATH)
        cls.pages = validator.read_text(REPO, validator.PAGES_PATH)

    def test_real_public_evidence_is_consistent(self) -> None:
        self.assertEqual(validator.validate(REPO), [])

    def test_current_main_patch_count_drift_is_rejected(self) -> None:
        changed = self.readme.replace(
            "`0001–0022` (22 patches)",
            "`0001–0021` (21 patches)",
            1,
        )
        problems = validator.validate_current_table(changed, self.lock)
        self.assertTrue(any("current-main patch range/count" in item for item in problems))

    def test_public_commit_drift_is_rejected(self) -> None:
        official = self.lock["godot"]["official"]["commit"]
        changed = self.readme.replace(official, "0" * 40, 1)
        problems = validator.validate_pins(
            {
                Path("README.md"): changed,
                Path("NOTICE.md"): validator.read_text(REPO, Path("NOTICE.md")),
            },
            self.lock,
        )
        self.assertTrue(any("locked official commit" in item for item in problems))

    def test_lineage_commit_drift_is_rejected(self) -> None:
        lineage = self.lock["godot"]["webgpu"]["source_lineage_commit"]
        notice = validator.read_text(REPO, Path("NOTICE.md")).replace(lineage, "f" * 40, 1)
        problems = validator.validate_pins({Path("NOTICE.md"): notice}, self.lock)
        self.assertTrue(any("locked lineage commit" in item for item in problems))

    def test_published_hash_drift_is_rejected(self) -> None:
        digest = self.lock["releases"]["godot_4_7_1_webgpu_p0014"]["web_webgpu_release"]["sha256"]
        changed = self.evidence.replace(digest, "a" * 64, 1)
        problems = validator.validate_release_assets(changed, self.lock)
        self.assertTrue(any("does not match lock SHA-256" in item for item in problems))

    def test_p0014_cannot_inherit_current_main_patch_count(self) -> None:
        changed = copy.deepcopy(self.lock)
        changed["releases"]["godot_4_7_1_webgpu_p0014"]["patch_through"] = len(
            changed["patches"]["series"]
        )
        problems = validator.validate_release_boundary(changed)
        self.assertTrue(any("must stop at patch 14" in item for item in problems))
        self.assertTrue(any("must not implicitly inherit" in item for item in problems))

    def test_stale_phrase_is_rejected_only_inside_current_section(self) -> None:
        current_changed = self.readme.replace(
            "<!-- public-evidence-current-status:end -->",
            "Forward+ not hardware tested\n<!-- public-evidence-current-status:end -->",
            1,
        )
        self.assertTrue(
            any(
                "stale phrase" in item
                for item in validator.validate_current_table(current_changed, self.lock)
            )
        )

        historical_changed = self.readme + "\n## Historical\nForward+ not hardware tested\n"
        self.assertEqual(validator.validate_current_table(historical_changed, self.lock), [])

    def test_required_attribution_is_enforced(self) -> None:
        changed = self.pages.replace("David Walter", "the historical author", 1)
        problems = validator.validate_attribution(self.readme, changed)
        self.assertTrue(any("David Walter" in item for item in problems))

    def test_pages_links_and_counts_are_enforced(self) -> None:
        changed = self.pages.replace('data-current-main-patches="22"', "", 1)
        changed = changed.replace(
            "https://github.com/lxsolutions/studio-foundation/releases/tag/"
            "godot-4.7.1-webgpu-p0014",
            "#release",
            1,
        )
        problems = validator.validate_pages(changed, self.lock)
        self.assertTrue(any("current-main patch count" in item for item in problems))
        self.assertTrue(any("required public link" in item for item in problems))

    def test_broken_local_markdown_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            problems = validator.markdown_link_problems(
                root,
                Path("docs/check.md"),
                "[missing](missing.md)",
            )
        self.assertEqual(problems, ["docs/check.md: broken local link: missing.md"])


if __name__ == "__main__":
    unittest.main()
