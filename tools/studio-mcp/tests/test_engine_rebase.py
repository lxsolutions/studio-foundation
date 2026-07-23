from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock

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
from patch_series import PatchSeriesError, verified_patches  # noqa: E402


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


def commit_file(repo: Path, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def fixture(root: Path, target_change: str) -> tuple[dict, str, str, Path, Path]:
    cache = root / "cache"
    official = cache / "godot-official"
    official.mkdir(parents=True)
    git(official, "init")
    git(official, "config", "user.name", "Engine Test")
    git(official, "config", "user.email", "engine@example.invalid")
    git(official, "config", "core.autocrlf", "false")
    base = commit_file(official, "shared.txt", "base\n", "base")

    patch_source = root / "patch-source"
    git(official, "worktree", "add", "--detach", str(patch_source), base)

    git(patch_source, "config", "user.name", "Engine Test")
    git(patch_source, "config", "user.email", "engine@example.invalid")
    commit_file(patch_source, "shared.txt", "integration\n", "integration")
    patch_text = (
        git(patch_source, "format-patch", "--stdout", "--binary", "--full-index", "-1") + "\n"
    )

    engine_dir = root / "engine"
    patch_file = engine_dir / "patches" / "0001-test.patch"
    patch_file.parent.mkdir(parents=True)
    patch_file.write_text(patch_text, encoding="utf-8")
    checksum = hashlib.sha256(patch_file.read_bytes()).hexdigest()

    if target_change == "conflict":
        target = commit_file(official, "shared.txt", "official\n", "official")
    elif target_change == "unrelated":
        target = commit_file(official, "official.txt", "new\n", "official")
    elif target_change == "base":
        target = base
    else:
        raise ValueError(target_change)

    lock = {
        "godot": {
            "official": {"commit": target},
            "webgpu": {"base_commit": base},
        },
        "patches": {
            "series": [
                {"file": "patches/0001-test.patch", "sha256": checksum},
            ]
        },
    }
    return lock, base, target, cache, engine_dir


class EngineRebaseTests(unittest.TestCase):
    def test_reports_up_to_date_without_creating_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock, base, target, cache, engine_dir = fixture(root, "base")
            result = engine_rebase.prepare_rebase(lock, cache_dir=cache, engine_dir=engine_dir)
            self.assertEqual(result["status"], "up_to_date")
            self.assertEqual(result["base_commit"], base)
            self.assertEqual(result["official_commit"], target)
            self.assertEqual(result["patches"], 1)
            self.assertFalse((cache / "rebases").exists())

    def test_dry_run_plans_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock, _base, _target, cache, engine_dir = fixture(root, "unrelated")
            result = engine_rebase.prepare_rebase(
                lock,
                workspace_name="next-release",
                branch="studio/next-release",
                dry_run=True,
                cache_dir=cache,
                engine_dir=engine_dir,
            )
            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["patches"], 1)
            self.assertFalse((cache / "rebases").exists())

    def test_applies_patch_series_to_nonconflicting_official_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock, _base, _target, cache, engine_dir = fixture(root, "unrelated")
            result = engine_rebase.prepare_rebase(
                lock,
                workspace_name="next-release",
                branch="studio/next-release",
                cache_dir=cache,
                engine_dir=engine_dir,
            )
            workspace = cache / "rebases" / "next-release"
            self.assertEqual(result["status"], "patches_applied")
            self.assertEqual(
                (workspace / "shared.txt").read_text(encoding="utf-8"),
                "integration\n",
            )

    def test_preserves_conflicted_worktree_and_reports_it_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock, _base, _target, cache, engine_dir = fixture(root, "conflict")
            result = engine_rebase.prepare_rebase(
                lock,
                workspace_name="next-release",
                branch="studio/next-release",
                cache_dir=cache,
                engine_dir=engine_dir,
            )
            workspace = cache / "rebases" / "next-release"
            self.assertEqual(result["status"], "conflicts")
            self.assertEqual(result["conflicts"], 1)
            self.assertEqual(result["failed_patch"], "patches/0001-test.patch")
            self.assertEqual(
                git(workspace, "diff", "--name-only", "--diff-filter=U"),
                "shared.txt",
            )

            resumed = engine_rebase.prepare_rebase(
                lock,
                workspace_name="next-release",
                branch="studio/next-release",
                cache_dir=cache,
                engine_dir=engine_dir,
            )
            self.assertEqual(resumed["status"], "conflicts")
            self.assertEqual(resumed["workspace"], str(workspace.resolve()))

            with self.assertRaisesRegex(engine_rebase.RebaseError, "branch does not match"):
                engine_rebase.prepare_rebase(
                    lock,
                    workspace_name="next-release",
                    branch="studio/different",
                    cache_dir=cache,
                    engine_dir=engine_dir,
                )

    def test_rejects_workspace_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock, _base, _target, cache, engine_dir = fixture(root, "unrelated")
            with self.assertRaisesRegex(engine_rebase.RebaseError, "workspace name"):
                engine_rebase.prepare_rebase(
                    lock,
                    workspace_name="../outside",
                    dry_run=True,
                    cache_dir=cache,
                    engine_dir=engine_dir,
                )


class EngineBuildToolchainTests(unittest.TestCase):
    def test_accepts_template_with_compiled_webgpu_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "template.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("godot.js", b"const importJsDevice = true;")
                bundle.writestr("godot.wasm", b"WebGPU: Device imported from JS successfully.")
            engine_tool._validate_webgpu_template(archive)

    def test_rejects_mislabeled_webgl_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "template.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("godot.js", b"ordinary loader")
                bundle.writestr("godot.wasm", b"ordinary WebGL runtime")
            with self.assertRaisesRegex(RuntimeError, "missing"):
                engine_tool._validate_webgpu_template(archive)

    def test_records_complete_template_pair_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock_path = root / "engine-lock.toml"
            lock_path.write_text(
                '[artifacts.export_templates]\n# empty\n\n[installed.editor]\nversion = "test"\n',
                encoding="utf-8",
            )
            artifact_dir = root / "templates"
            artifact_dir.mkdir()
            release = artifact_dir / engine_tool.TEMPLATE_ARTIFACTS["web_webgpu_release"]
            debug = artifact_dir / engine_tool.TEMPLATE_ARTIFACTS["web_webgpu_debug"]
            release.write_bytes(b"release-template")
            debug.write_bytes(b"debug-template")

            records = engine_tool.record_artifacts(
                lock_path=lock_path,
                artifact_dir=artifact_dir,
            )
            first = lock_path.read_text(encoding="utf-8")
            parsed = tomllib.loads(first)["artifacts"]["export_templates"]

            self.assertEqual(parsed, records)
            self.assertEqual(records["web_webgpu_release"]["bytes"], len(b"release-template"))
            self.assertEqual(
                records["web_webgpu_debug"]["sha256"],
                hashlib.sha256(b"debug-template").hexdigest(),
            )
            engine_tool.record_artifacts(
                lock_path=lock_path,
                artifact_dir=artifact_dir,
            )
            self.assertEqual(lock_path.read_text(encoding="utf-8"), first)

    def test_refuses_to_record_partial_template_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock_path = root / "engine-lock.toml"
            original = (
                '[artifacts.export_templates]\n# empty\n\n[installed.editor]\nversion = "test"\n'
            )
            lock_path.write_text(original, encoding="utf-8")
            artifact_dir = root / "templates"
            artifact_dir.mkdir()
            (artifact_dir / engine_tool.TEMPLATE_ARTIFACTS["web_webgpu_release"]).write_bytes(
                b"release-template"
            )

            with self.assertRaisesRegex(FileNotFoundError, "debug"):
                engine_tool.record_artifacts(
                    lock_path=lock_path,
                    artifact_dir=artifact_dir,
                )
            self.assertEqual(lock_path.read_text(encoding="utf-8"), original)

    def test_explicit_emsdk_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            explicit = root / "workspace-emsdk"
            home = root / "home"
            (explicit / "upstream" / "emscripten").mkdir(parents=True)
            (explicit / "emsdk_env.bat").write_text("", encoding="utf-8")
            (explicit / "upstream" / "emscripten" / "emscripten-version.txt").write_text(
                '"4.0.11"\n', encoding="utf-8"
            )
            home_sdk = home / "emsdk"
            (home_sdk / "upstream" / "emscripten").mkdir(parents=True)
            (home_sdk / "emsdk_env.bat").write_text("", encoding="utf-8")
            (home_sdk / "upstream" / "emscripten" / "emscripten-version.txt").write_text(
                '"4.0.11"\n', encoding="utf-8"
            )

            with (
                mock.patch.dict(os.environ, {"EMSDK": str(explicit)}),
                mock.patch.object(engine_tool.Path, "home", return_value=home),
            ):
                self.assertEqual(
                    engine_tool._find_emsdk_env_bat("4.0.11"),
                    explicit / "emsdk_env.bat",
                )

    def test_explicit_emsdk_must_match_locked_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            explicit = Path(temp_dir) / "workspace-emsdk"
            (explicit / "upstream" / "emscripten").mkdir(parents=True)
            (explicit / "emsdk_env.bat").write_text("", encoding="utf-8")
            (explicit / "upstream" / "emscripten" / "emscripten-version.txt").write_text(
                '"4.0.10"\n', encoding="utf-8"
            )

            with mock.patch.dict(os.environ, {"EMSDK": str(explicit)}):
                self.assertIsNone(engine_tool._find_emsdk_env_bat("4.0.11"))

    def test_invalid_explicit_emsdk_does_not_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            home_sdk = home / "emsdk"
            (home_sdk / "upstream" / "emscripten").mkdir(parents=True)
            (home_sdk / "emsdk_env.bat").write_text("", encoding="utf-8")
            (home_sdk / "upstream" / "emscripten" / "emscripten-version.txt").write_text(
                '"4.0.11"\n', encoding="utf-8"
            )

            with (
                mock.patch.dict(os.environ, {"EMSDK": str(root / "missing")}),
                mock.patch.object(engine_tool.Path, "home", return_value=home),
            ):
                self.assertIsNone(engine_tool._find_emsdk_env_bat("4.0.11"))


class TemplateInstallTests(unittest.TestCase):
    @staticmethod
    def _write_template(path: Path, marker: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("godot.js", b"importJsDevice" + marker)
            bundle.writestr(
                "godot.wasm",
                b"WebGPU: Device imported from JS successfully." + marker,
            )

    def test_installs_only_lock_matching_no_threads_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            dest = root / "dest"
            for profile in ("release", "debug"):
                self._write_template(
                    source / "bin" / f"godot.web.template_{profile}.wasm32.zip",
                    b"-threaded",
                )
                self._write_template(
                    source / "bin" / f"godot.web.template_{profile}.wasm32.nothreads.zip",
                    b"-no-threads",
                )

            engine_tool._install_templates(source, dest, threads_enabled=False)

            self.assertEqual(
                sorted(path.name for path in dest.iterdir()),
                [
                    "godot.web.template_debug.webgpu.zip",
                    "godot.web.template_release.webgpu.zip",
                ],
            )
            for profile in ("release", "debug"):
                with zipfile.ZipFile(dest / f"godot.web.template_{profile}.webgpu.zip") as bundle:
                    self.assertTrue(bundle.read("godot.js").endswith(b"-no-threads"))


class PatchSeriesTests(unittest.TestCase):
    def test_verifies_checksum_and_prepares_reusable_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock, _base, _target, cache, engine_dir = fixture(root, "unrelated")
            patches = verified_patches(lock, engine_dir)
            source = engine_tool.prepare_patched_source(
                lock,
                cache / "godot-official",
                patches,
                cache_dir=cache,
            )
            self.assertEqual(
                (source / "shared.txt").read_text(encoding="utf-8"),
                "integration\n",
            )
            self.assertEqual(
                engine_tool.prepare_patched_source(
                    lock,
                    cache / "godot-official",
                    patches,
                    cache_dir=cache,
                ),
                source,
            )

    def test_rejects_tampered_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock, _base, _target, _cache, engine_dir = fixture(root, "base")
            patch = engine_dir / "patches" / "0001-test.patch"
            patch.write_text(patch.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(PatchSeriesError, "checksum mismatch"):
                verified_patches(lock, engine_dir)

    def test_rejects_patch_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock, _base, _target, _cache, engine_dir = fixture(root, "base")
            lock["patches"]["series"][0]["file"] = "patches/../outside.patch"
            with self.assertRaisesRegex(PatchSeriesError, "escapes"):
                verified_patches(lock, engine_dir)

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
