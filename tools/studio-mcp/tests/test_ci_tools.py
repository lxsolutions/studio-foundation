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
workflow_validation = load_script(
    "studio_ci_workflow_validation", REPO / "tools" / "ci" / "validate_workflows.py"
)


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
        self.assertEqual(called, ["test", "lint", "secret-scan", "check-claims"])

    def test_nightly_extends_pr_with_slow_gates(self) -> None:
        called: list[str] = []

        def runner(recipe: str) -> int:
            called.append(recipe)
            return 0

        self.assertEqual(self.run_silently("nightly", runner), 0)
        self.assertEqual(
            called,
            [
                "test",
                "lint",
                "secret-scan",
                "check-claims",
                "test-generated",
                "test-db",
                "release-validate",
                "audit",
                "sbom",
                "attribution",
            ],
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


class WorkflowPolicyTests(unittest.TestCase):
    def validate_text(self, content: str, name: str = "policy.yml") -> list[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / name
            path.write_text(content, encoding="utf-8")
            return workflow_validation.validate_file(path)

    def test_representative_studio_workflow_satisfies_policy(self) -> None:
        problems = self.validate_text(
            """on:
  push:
  pull_request:
  schedule:
    - cron: "17 6 * * *"
  workflow_dispatch:
permissions:
  contents: read
jobs:
  pr-policy:
    runs-on: ubuntu-latest
    steps:
      - run: python tools/ci/validate_workflows.py
      - run: python tools/ci/secret_scan.py
  trusted-ci:
    if: github.event_name == 'push'
    runs-on: [self-hosted, windows]
    steps:
      - run: npm.cmd ci --prefix infra/nakama
      - run: npm.cmd ci --prefix tests/browser
      - run: just ci-local
      - run: python scripts/ci/run_all.py --stage nightly
  engine-validate:
    if: github.event_name == 'push'
    needs: trusted-ci
    runs-on: [self-hosted, windows]
    steps:
      - run: npm.cmd ci --prefix tests/browser
      - run: just engine-fetch
      - run: just engine-build
      - run: just engine-validate
""",
            name="validate.yml",
        )
        self.assertEqual(problems, [])

    def test_untrusted_pull_request_cannot_use_self_hosted_runner(self) -> None:
        problems = self.validate_text(
            """on:
  pull_request:
jobs:
  unsafe:
    runs-on: [self-hosted, windows]
    steps:
      - run: echo unsafe
"""
        )
        self.assertTrue(any("not restricted to trusted pushes" in item for item in problems))

    def test_external_actions_require_immutable_commit_pin(self) -> None:
        problems = self.validate_text(
            """on:
  push:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
        )
        self.assertTrue(any("not pinned to a full commit" in item for item in problems))


check_claims = load_script("studio_ci_check_claims", REPO / "tools" / "ci" / "check_claims.py")


class CheckClaimsTests(unittest.TestCase):
    def make_repo(self, root: Path) -> Path:
        """A minimal synthetic repo with one op, one test, one patch."""
        (root / "tools" / "bforge" / "tests").mkdir(parents=True)
        (root / "engine").mkdir(parents=True)
        (root / "docs").mkdir(parents=True)
        (root / "tools" / "bforge" / "catalog.json").write_text(
            '{"version": 1, "ops": [{"name": "build.box", "summary": "s",'
            ' "inputSchema": {"type": "object", "properties": {}}}]}'
        )
        (root / "tools" / "bforge" / "tests" / "test_x.py").write_text(
            "def test_one():\n    pass\n"
        )
        (root / "engine" / "engine-lock.toml").write_text(
            '[patches]\nseries = [{ file = "patches/0001-x.patch", sha256 = "ab" }]\n'
        )
        (root / "docs" / "claims.toml").write_text(
            '[[surface]]\nfile = "README.md"\nkey = "bforge.ops"\n'
            'patterns = ["(\\\\d+) whitelisted operations"]\n'
            '[[forbidden]]\nfiles = ["README.md"]\n'
            'phrase = "only public"\nreason = "absolute claims are not defensible"\n'
        )
        return root

    def test_derives_values_from_the_real_artifacts(self) -> None:
        derived = check_claims.derive_values(REPO)
        self.assertGreaterEqual(derived["bforge.ops"], 80)
        self.assertGreaterEqual(derived["bforge.tests"], 80)
        self.assertGreaterEqual(derived["engine.patches"], 1)
        self.assertGreaterEqual(derived["bforge.namespaces"], 10)

    def test_the_repository_s_own_surfaces_are_consistent(self) -> None:
        self.assertEqual(check_claims.check(REPO), [])

    def test_green_when_prose_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_repo(Path(temp_dir))
            (root / "README.md").write_text("1 whitelisted operations, honestly.\n")
            self.assertEqual(check_claims.check(root), [])

    def test_flags_a_number_that_drifted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_repo(Path(temp_dir))
            (root / "README.md").write_text("9 whitelisted operations, aspirationally.\n")
            problems = check_claims.check(root)
            self.assertTrue(any("claims 9" in problem for problem in problems))

    def test_flags_a_missing_pattern_and_a_forbidden_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_repo(Path(temp_dir))
            (root / "README.md").write_text("the only public implementation\n")
            problems = check_claims.check(root)
            self.assertTrue(any("pattern not found" in problem for problem in problems))
            self.assertTrue(any("forbidden claim" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
