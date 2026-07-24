from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ENGINE_DIR = SCRIPTS.parent
VERIFIER = SCRIPTS / "verify_patch_series.py"


def _run(engine_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run the verifier against a copy of engine/ staged at engine_dir."""
    return subprocess.run(
        [sys.executable, str(engine_dir / "scripts" / "verify_patch_series.py")],
        capture_output=True,
        text=True,
        check=False,
    )


class VerifyPatchSeriesTests(unittest.TestCase):
    """The patch series is the project's core reproducibility claim, so the check
    that guards it needs its own teeth verified — a checker that always passes is
    worse than none."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = Path(self._tmp.name) / "engine"
        shutil.copytree(ENGINE_DIR, self.engine, symlinks=True)
        self.patches = self.engine / "patches"
        self.addCleanup(self._tmp.cleanup)

    def _a_patch(self) -> Path:
        candidates = sorted(self.patches.glob("*.patch"))
        self.assertTrue(candidates, "expected at least one patch in engine/patches")
        return candidates[-1]

    def test_real_series_is_intact(self) -> None:
        result = _run(self.engine)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("patch series OK", result.stdout)

    def test_modified_patch_is_rejected(self) -> None:
        target = self._a_patch()
        target.write_bytes(target.read_bytes() + b"\n")
        result = _run(self.engine)
        self.assertEqual(result.returncode, 1)
        self.assertIn("checksum mismatch", result.stderr)

    def test_unlocked_patch_file_is_rejected(self) -> None:
        rogue = self.patches / "9999-not-in-the-lock.patch"
        rogue.write_text("not a real patch\n", encoding="utf-8")
        result = _run(self.engine)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not locked", result.stderr)

    def test_missing_patch_file_is_rejected(self) -> None:
        self._a_patch().unlink()
        result = _run(self.engine)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
