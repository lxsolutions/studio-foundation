"""Recipe IR (bforge cook) tests.

Unit tests run anywhere; the live test boots a real Blender daemon through
the compiler and proves the full path: recipe -> gates -> export -> proof,
with a content-addressed cache hit on the second run and byte-identical
artifacts on a forced rebuild.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge.client import DaemonError, Forge, find_blender  # noqa: E402

from bforge import recipe as recipe_mod  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "tools" / "bforge" / "examples" / "recipes"


def base_recipe() -> dict:
    return {
        "recipe_version": 1,
        "asset_id": "widget",
        "steps": [{"op": "build.box", "args": {"name": "widget", "size": [1, 1, 1]}}],
        "requirements": {"max_triangles": 2000},
        "export": {"engine": "godot", "category": "prop"},
    }


class FakeForge:
    """A started-or-startable worker double; records calls, returns gates."""

    instances: list[FakeForge] = []
    gate_ok = True
    budget_ok = True
    reported_blender: str = ""  # set in setUp from the lock

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.stopped = False
        FakeForge.instances.append(self)

    def start(self) -> dict:
        return {"blender": FakeForge.reported_blender, "python": "fake", "ops": 136}

    def stop(self):
        self.stopped = True

    def call(self, op, _timeout=None, **args):
        self.calls.append((op, args))
        if op == "check.asset":
            return {"ok": FakeForge.gate_ok, "errors": 0 if FakeForge.gate_ok else 1}
        if op == "gameready.budget":
            if FakeForge.budget_ok is None:
                return {"profile": "browser_webgpu"}  # malformed: no verdict
            return {"within_budget": FakeForge.budget_ok}
        if op == "export.asset":  # stand in for the artifact the daemon would write
            out = Path(args["out_dir"]) / "pkg" / "widget.glb"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"glTF-fake-bytes")
            return {"ok": True, "glb": str(out)}
        return {"ok": True}


class Canon(unittest.TestCase):
    def test_canonicalize_ignores_key_order_and_whitespace(self):
        a = json.loads(json.dumps(base_recipe(), indent=2))
        b = json.loads(json.dumps(base_recipe()))
        b["steps"][0]["args"] = dict(reversed(list(b["steps"][0]["args"].items())))
        self.assertEqual(recipe_mod.canonicalize(a), recipe_mod.canonicalize(b))

    def test_content_hash_tracks_step_args(self):
        recipe = base_recipe()
        changed = base_recipe()
        changed["steps"][0]["args"]["size"] = [2, 1, 1]
        self.assertNotEqual(
            recipe_mod.content_hash(recipe, {}), recipe_mod.content_hash(changed, {})
        )

    def test_content_hash_covers_input_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "in.bin"
            path.write_bytes(b"v1")
            recipe = base_recipe()
            recipe["inputs"] = {"data": {"path": "in.bin"}}
            first = recipe_mod.content_hash(recipe, recipe_mod.hash_inputs(recipe, Path(tmp)))
            path.write_bytes(b"v2")
            second = recipe_mod.content_hash(recipe, recipe_mod.hash_inputs(recipe, Path(tmp)))
            self.assertNotEqual(first, second)


class Validation(unittest.TestCase):
    def write(self, tmp: str, recipe) -> Path:
        path = Path(tmp) / "r.json"
        path.write_text(json.dumps(recipe))
        return path

    def test_rejects_wrong_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe = base_recipe()
            recipe["recipe_version"] = 99
            with self.assertRaises(recipe_mod.RecipeError):
                recipe_mod.load_recipe(self.write(tmp, recipe))

    def test_rejects_empty_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe = base_recipe()
            recipe["steps"] = []
            with self.assertRaises(recipe_mod.RecipeError):
                recipe_mod.load_recipe(self.write(tmp, recipe))

    def test_input_hash_mismatch_is_a_hard_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "in.bin").write_bytes(b"actual")
            recipe = base_recipe()
            recipe["inputs"] = {"data": {"path": "in.bin", "sha256": "0" * 64}}
            with self.assertRaises(recipe_mod.RecipeError):
                recipe_mod.hash_inputs(recipe, Path(tmp))


class CookFakeWorker(unittest.TestCase):
    def setUp(self):
        FakeForge.instances = []
        FakeForge.gate_ok = True
        FakeForge.budget_ok = True
        FakeForge.reported_blender = recipe_mod.pinned_blender_version() or "unknown"

    def cook(self, tmp: str, recipe: dict | None = None, **kwargs) -> dict:
        path = Path(tmp) / "r.json"
        if recipe is not None or not path.exists():
            path.write_text(json.dumps(recipe if recipe is not None else base_recipe()))
        return recipe_mod.cook(
            path, cache_dir=Path(tmp) / "cache", forge_factory=FakeForge, **kwargs
        )

    def test_miss_runs_steps_gates_export_and_writes_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            proof = self.cook(tmp)
            self.assertEqual(proof["status"], "pass")
            self.assertFalse(proof["cache"]["hit"])
            ops = [op for op, _ in FakeForge.instances[0].calls]
            self.assertEqual(ops[0], "session.reset")
            self.assertIn("build.box", ops)
            self.assertIn("check.asset", ops)  # from requirements.max_triangles
            self.assertIn("export.asset", ops)
            self.assertTrue(FakeForge.instances[0].stopped)
            on_disk = json.loads((Path(proof["cache"]["dir"]) / "proof.json").read_text())
            self.assertEqual(on_disk["recipe_hash"], proof["recipe_hash"])
            self.assertTrue((Path(proof["cache"]["dir"]) / "recipe.canonical.json").is_file())

    def test_hit_returns_proof_without_a_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.cook(tmp)
            self.assertEqual(len(FakeForge.instances), 1)
            second = self.cook(tmp)
            self.assertTrue(second["cache"]["hit"])
            self.assertEqual(len(FakeForge.instances), 1, "cache hit must not boot a worker")
            self.assertEqual(first["recipe_hash"], second["recipe_hash"])

    def test_no_cache_forces_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.cook(tmp)
            self.cook(tmp, no_cache=True)
            self.assertEqual(len(FakeForge.instances), 2)

    def test_gate_failure_raises_and_is_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            FakeForge.gate_ok = False
            with self.assertRaises(recipe_mod.RecipeError):
                self.cook(tmp)
            FakeForge.gate_ok = True
            proof = self.cook(tmp)  # a failed proof must not satisfy the cache
            self.assertEqual(proof["status"], "pass")
            self.assertEqual(len(FakeForge.instances), 2)

    def test_compiler_fingerprint_change_is_a_cache_miss(self):
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            self.cook(tmp)
            self.assertEqual(len(FakeForge.instances), 1)
            different = dict(recipe_mod.compiler_fingerprint(), python="0.0.0-different")
            with mock.patch.object(recipe_mod, "compiler_fingerprint", return_value=different):
                proof = self.cook(tmp)
            self.assertEqual(
                len(FakeForge.instances), 2, "a changed compiler must not reuse the cache"
            )
            self.assertFalse(proof["cache"]["hit"])

    def test_tampered_artifact_invalidates_the_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            proof = self.cook(tmp)
            artifact = Path(proof["cache"]["dir"]) / "pkg" / "widget.glb"
            artifact.write_bytes(b"tampered")
            self.cook(tmp)
            self.assertEqual(
                len(FakeForge.instances), 2, "a tampered artifact must force a rebuild"
            )

    def test_artifact_paths_are_relative_not_basenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            proof = self.cook(tmp)
            paths = [a["path"] for a in proof["artifacts"]]
            self.assertIn("pkg/widget.glb", paths)
            self.assertNotIn("widget.glb", paths)

    def test_over_budget_fails_closed(self):
        recipe = base_recipe()
        recipe["requirements"]["platform"] = "browser_webgpu"
        with tempfile.TemporaryDirectory() as tmp:
            FakeForge.budget_ok = False
            with self.assertRaises(recipe_mod.RecipeError):
                self.cook(tmp, recipe)
            FakeForge.budget_ok = True
            proof = self.cook(tmp, recipe)  # a budget failure must not satisfy the cache
            self.assertEqual(proof["status"], "pass")

    def test_malformed_budget_result_fails_closed(self):
        recipe = base_recipe()
        recipe["requirements"]["platform"] = "browser_webgpu"
        with tempfile.TemporaryDirectory() as tmp:
            FakeForge.budget_ok = None  # no within_budget verdict at all
            with self.assertRaises(recipe_mod.RecipeError):
                self.cook(tmp, recipe)

    def test_unpinned_blender_is_rejected_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            FakeForge.reported_blender = "9.9.9"
            with self.assertRaises(recipe_mod.RecipeError):
                self.cook(tmp)
            self.assertFalse(
                any((Path(tmp) / "cache").rglob("proof.json")),
                "an unpinned build must not write into the content-addressed store",
            )

    def test_allow_unpinned_diverts_and_never_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            FakeForge.reported_blender = "9.9.9"
            proof = self.cook(tmp, allow_unpinned=True)
            self.assertEqual(proof["status"], "pass")
            self.assertFalse(proof["cache"]["cacheable"])
            self.assertTrue(proof["cache"]["ephemeral"])
            self.assertIn("staging", proof["cache"]["dir"])
            self.cook(tmp, allow_unpinned=True)
            self.assertEqual(
                len(FakeForge.instances), 2, "unpinned results must never be cache hits"
            )

    def test_proof_metadata_tamper_forces_rebuild_and_quarantine(self):
        """Editing the proof's toolchain/gates/identity must invalidate the
        entry — verifying only the artifacts a proof NAMES is not a chain."""
        with tempfile.TemporaryDirectory() as tmp:
            first = self.cook(tmp)
            proof_path = Path(first["cache"]["dir"]) / "proof.json"
            tampered = json.loads(proof_path.read_text())
            tampered["toolchain"]["blender"] = "tampered-9.9.9"
            proof_path.write_text(json.dumps(tampered, indent=2) + "\n")
            second = self.cook(tmp)
            self.assertEqual(len(FakeForge.instances), 2, "tampered metadata must force a rebuild")
            self.assertEqual(second["toolchain"]["blender"], FakeForge.reported_blender)
            quarantined = list((Path(tmp) / "cache" / "failures").glob("corrupt-*"))
            self.assertTrue(quarantined, "the tampered entry must be quarantined, not reused")

    def test_stale_file_in_the_store_invalidates_the_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.cook(tmp)
            (Path(first["cache"]["dir"]) / "leftover.txt").write_text("from an older build")
            self.cook(tmp)
            self.assertEqual(
                len(FakeForge.instances), 2, "an unrecorded file must invalidate the entry"
            )

    def test_strict_json_rejects_non_finite_constants(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe = base_recipe()
            text = json.dumps(recipe).replace('"max_triangles": 2000', '"max_triangles": NaN')
            path = Path(tmp) / "r.json"
            path.write_text(text)
            with self.assertRaises(recipe_mod.RecipeError):
                self.cook(tmp)


BLENDER = None
try:
    if not os.environ.get("BFORGE_SKIP_LIVE"):
        BLENDER = find_blender()
except DaemonError:
    BLENDER = None


@unittest.skipIf(BLENDER is None, "Blender not available")
class CookLive(unittest.TestCase):
    def test_crate_recipe_end_to_end(self):
        tmp = Path(tempfile.mkdtemp(prefix="bforge_recipe_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        cache = tmp / "cache"

        def factory() -> Forge:
            return Forge(workdir=str(tmp), out_dir=str(tmp / "out"))

        recipe_path = EXAMPLES / "crate.json"
        proof = recipe_mod.cook(recipe_path, cache_dir=cache, forge_factory=factory)
        self.assertEqual(proof["status"], "pass")
        self.assertTrue(proof["artifacts"], "export must produce hashed artifacts")
        glb = next(a for a in proof["artifacts"] if a["path"].endswith(".glb"))

        cached = recipe_mod.cook(recipe_path, cache_dir=cache, forge_factory=factory)
        self.assertTrue(cached["cache"]["hit"])

        rebuilt = recipe_mod.cook(
            recipe_path, cache_dir=cache, no_cache=True, forge_factory=factory
        )
        glb_again = next(a for a in rebuilt["artifacts"] if a["path"].endswith(".glb"))
        self.assertEqual(
            glb["sha256"], glb_again["sha256"], "same recipe must rebuild byte-identical GLB"
        )


if __name__ == "__main__":
    unittest.main()
