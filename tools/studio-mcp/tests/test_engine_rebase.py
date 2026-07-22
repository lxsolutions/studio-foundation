from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "engine" / "scripts"))


def load_rebase_module():
    path = REPO / "engine" / "scripts" / "rebase.py"
    spec = importlib.util.spec_from_file_location("studio_engine_rebase", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["studio_engine_rebase"] = module
    spec.loader.exec_module(module)
    return module


engine_rebase = load_rebase_module()
import engine as engine_tool  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()


def commit(repo: Path, content: str, message: str) -> str:
    (repo / "shared.txt").write_text(content, encoding="utf-8")
    git(repo, "add", "shared.txt")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def fixture(cache: Path, divergent: bool) -> tuple[dict, str, str]:
    official = cache / "godot-official"
    official.mkdir(parents=True)
    git(official, "init")
    git(official, "config", "user.name", "Engine Test")
    git(official, "config", "user.email", "engine@example.invalid")
    base = commit(official, "base\n", "base")
    target = commit(official, "official\n", "official")

    fork = cache / "godot-webgpu"
    git(cache, "clone", str(official), str(fork))
    git(fork, "config", "user.name", "Engine Test")
    git(fork, "config", "user.email", "engine@example.invalid")
    if divergent:
        git(fork, "checkout", "-b", "fork-line", base)
        fork_commit = commit(fork, "fork\n", "fork")
    else:
        git(fork, "checkout", "-b", "fork-line", target)
        (fork / "fork-only.txt").write_text("fork\n", encoding="utf-8")
        git(fork, "add", "fork-only.txt")
        git(fork, "commit", "-m", "fork")
        fork_commit = git(fork, "rev-parse", "HEAD")
    lock = {
        "godot": {
            "official": {"commit": target},
            "webgpu_fork": {"commit": fork_commit},
        }
    }
    return lock, target, fork_commit


class EngineRebaseTests(unittest.TestCase):
    def test_reports_up_to_date_without_creating_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir)
            lock, target, fork_commit = fixture(cache, divergent=False)
            result = engine_rebase.prepare_rebase(lock, cache_dir=cache)
            self.assertEqual(result["status"], "up_to_date")
            self.assertEqual(result["official_commit"], target)
            self.assertEqual(result["fork_commit"], fork_commit)
            self.assertFalse((cache / "rebases").exists())

    def test_dry_run_plans_without_fetching_or_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir)
            lock, _target, _fork_commit = fixture(cache, divergent=True)
            result = engine_rebase.prepare_rebase(
                lock,
                workspace_name="next-release",
                branch="studio/next-release",
                dry_run=True,
                cache_dir=cache,
            )
            self.assertEqual(result["status"], "planned")
            self.assertFalse(result["fetch_official_into_fork"])
            self.assertFalse((cache / "rebases").exists())

    def test_prepares_conflicted_worktree_and_resumes_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir)
            lock, _target, _fork_commit = fixture(cache, divergent=True)
            result = engine_rebase.prepare_rebase(
                lock,
                workspace_name="next-release",
                branch="studio/next-release",
                cache_dir=cache,
            )
            workspace = cache / "rebases" / "next-release"
            self.assertEqual(result["status"], "conflicts")
            self.assertEqual(result["conflicts"], 1)
            self.assertTrue((workspace / ".git").is_file())
            self.assertEqual(git(workspace, "diff", "--name-only", "--diff-filter=U"), "shared.txt")

            resumed = engine_rebase.prepare_rebase(
                lock,
                workspace_name="next-release",
                branch="studio/next-release",
                cache_dir=cache,
            )
            self.assertEqual(resumed["status"], "conflicts")
            self.assertEqual(resumed["workspace"], str(workspace.resolve()))

            with self.assertRaisesRegex(engine_rebase.RebaseError, "branch does not match"):
                engine_rebase.prepare_rebase(
                    lock,
                    workspace_name="next-release",
                    branch="studio/different-branch",
                    cache_dir=cache,
                )

    def test_rejects_workspace_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir)
            lock, _target, _fork_commit = fixture(cache, divergent=True)
            with self.assertRaisesRegex(engine_rebase.RebaseError, "workspace name"):
                engine_rebase.prepare_rebase(
                    lock, workspace_name="../outside", dry_run=True, cache_dir=cache
                )

    def test_candidate_artifacts_do_not_replace_pinned_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine_dir = Path(temp_dir)
            candidate = engine_dir / ".cache" / "rebases" / "next-release"
            self.assertEqual(
                engine_tool.artifact_destination(None, engine_dir),
                engine_dir / "artifacts" / "templates",
            )
            self.assertEqual(
                engine_tool.artifact_destination(candidate, engine_dir),
                engine_dir / "artifacts" / "candidates" / "next-release" / "templates",
            )


if __name__ == "__main__":
    unittest.main()
