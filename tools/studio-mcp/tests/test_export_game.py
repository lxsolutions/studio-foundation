from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO / "tools" / "godot" / "export_game.py"
SPEC = importlib.util.spec_from_file_location("studio_export_game", MODULE_PATH)
assert SPEC and SPEC.loader
export_game = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_game)


class ConfigureWebRendererTests(unittest.TestCase):
    def _html(self, root: Path, args: list[str] | None = None) -> Path:
        config = {
            "args": args or [],
            "executable": "index",
            "fileSizes": {"index.wasm": 42},
        }
        path = root / "index.html"
        path.write_text(
            "<script>\nconst GODOT_CONFIG = "
            + json.dumps(config, separators=(",", ":"))
            + ";\n</script>\n",
            encoding="utf-8",
        )
        return path

    def _config(self, path: Path) -> dict[str, object]:
        match = re.search(
            r"const GODOT_CONFIG = (\{[^\n]+\});",
            path.read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def test_webgpu_binds_mobile_renderer_and_webgpu_driver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            html = self._html(Path(directory), ["--verbose"])
            export_game.configure_web_renderer(html, "web-webgpu")
            config = self._config(html)
            self.assertEqual(config["renderingDriver"], "webgpu")
            self.assertEqual(
                config["args"],
                [
                    "--verbose",
                    "--rendering-method",
                    "mobile",
                    "--rendering-driver",
                    "webgpu",
                ],
            )

    def test_webgl_binds_compatibility_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            html = self._html(Path(directory))
            export_game.configure_web_renderer(html, "web-webgl")
            config = self._config(html)
            self.assertEqual(config["renderingDriver"], "opengl3")
            self.assertEqual(
                config["args"],
                [
                    "--rendering-method",
                    "gl_compatibility",
                    "--rendering-driver",
                    "opengl3",
                ],
            )
