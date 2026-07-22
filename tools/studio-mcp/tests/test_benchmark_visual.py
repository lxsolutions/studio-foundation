from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "pylib"))


def load_script(name: str, relative: str):
    path = REPO / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


benchmark = load_script("studio_benchmark", "tools/benchmark/run_benchmark.py")
visual = load_script("studio_visual_regression", "tools/screenshots/visual_regression.py")


class BenchmarkTests(unittest.TestCase):
    def test_extracts_last_structured_result(self) -> None:
        result = {
            "scene": "res://scenes/game.tscn",
            "warmup_frames": 2,
            "sample_frames": 4,
            "duration_ms": 8.0,
            "fps": 500.0,
        }
        output = "noise\n" + benchmark.RESULT_PREFIX + json.dumps(result)
        self.assertEqual(benchmark.extract_result(output), result)

    def test_rejects_incomplete_result(self) -> None:
        with self.assertRaisesRegex(benchmark.BenchmarkError, "missing fields"):
            benchmark.extract_result(benchmark.RESULT_PREFIX + '{"scene":"x"}')

    def test_project_path_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(benchmark.BenchmarkError, "inside the repository"):
                benchmark.project_dir("../outside", root)


class VisualTests(unittest.TestCase):
    def test_project_path_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(visual.VisualError, "inside the repository"):
                visual.project_dir("../outside", root)

    def test_artifacts_separate_versioned_baseline_and_generated_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            project = root / "games" / "sample" / "project"
            baseline, candidate = visual.artifact_paths(project, "web-webgl", root)
            self.assertEqual(baseline, project / "captures" / "visual-web-webgl-baseline.png")
            self.assertEqual(
                candidate,
                root / "build" / "visual" / "games__sample" / "visual-web-webgl-candidate.png",
            )


if __name__ == "__main__":
    unittest.main()
