from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


run_all = load_script("studio_ci_run_all", REPO / "scripts" / "ci" / "run_all.py")
secret_scan = load_script("studio_ci_secret_scan", REPO / "tools" / "ci" / "secret_scan.py")


class CiRunnerTests(unittest.TestCase):
    def run_silently(self, stage: str, runner) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return run_all.run_stage(stage, runner)

    def test_pr_stage_runs_documented_recipes_in_order(self) -> None:
        called: list[str] = []

        def runner(recipe: str) -> int:
            called.append(recipe)
            return 0

        self.assertEqual(self.run_silently("pr", runner), 0)
        self.assertEqual(called, ["test", "lint", "secret-scan"])

    def test_nightly_extends_pr_with_slow_gates(self) -> None:
        called: list[str] = []

        def runner(recipe: str) -> int:
            called.append(recipe)
            return 0

        self.assertEqual(self.run_silently("nightly", runner), 0)
        self.assertEqual(
            called,
            ["test", "lint", "secret-scan", "test-db", "audit", "attribution"],
        )

    def test_stage_stops_and_propagates_failure(self) -> None:
        called: list[str] = []

        def runner(recipe: str) -> int:
            called.append(recipe)
            return 9 if recipe == "lint" else 0

        self.assertEqual(self.run_silently("pr", runner), 9)
        self.assertEqual(called, ["test", "lint"])


class SecretScanTests(unittest.TestCase):
    def test_reviewable_scan_includes_untracked_and_excludes_ignored(self) -> None:
        credential = "ghp_" + "A" * 40
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            (repo / "tracked.txt").write_text("safe\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore", "tracked.txt"], cwd=repo, check=True)
            (repo / "untracked.txt").write_text(credential, encoding="utf-8")
            (repo / "ignored.txt").write_text(credential, encoding="utf-8")

            paths = secret_scan.reviewable_paths(repo)
            findings = secret_scan.scan_repository(repo, paths)

        self.assertIn(Path("tracked.txt"), paths)
        self.assertIn(Path("untracked.txt"), paths)
        self.assertNotIn(Path("ignored.txt"), paths)
        self.assertEqual(findings, [(Path("untracked.txt"), "possible GitHub token")])

    def test_detects_token_without_returning_credential(self) -> None:
        credential = "ghp_" + "A" * 40
        findings = secret_scan.scan_text("value=" + credential)
        self.assertEqual(findings, ["GitHub token"])
        self.assertNotIn(credential, repr(findings))

    def test_exempts_documentation_and_placeholders(self) -> None:
        credential = "ghp_" + "A" * 40
        self.assertEqual(secret_scan.scan_bytes(Path("guide.md"), credential.encode()), [])
        self.assertEqual(secret_scan.scan_text('api_key="placeholder"'), [])

    def test_binary_content_is_skipped(self) -> None:
        credential = ("ghp_" + "A" * 40).encode()
        self.assertEqual(secret_scan.scan_bytes(Path("image.bin"), b"\0" + credential), [])

    def test_tracked_env_policy(self) -> None:
        self.assertEqual(secret_scan.path_problem(Path(".env")), "environment file")
        self.assertEqual(secret_scan.path_problem(Path(".env.local")), "environment file")
        self.assertIsNone(secret_scan.path_problem(Path(".env.example")))


if __name__ == "__main__":
    unittest.main()
