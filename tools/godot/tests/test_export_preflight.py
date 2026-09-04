"""The C#/.NET web export refusal must fire exactly when it should, and explain.

Godot's own message for this is `export failed: cannot combine Mono runtime with
the web platform`, which sends teams looking for a template to download. The
preflight exists to replace that with the actual constraint and a way forward
(ADR 0019), so what is asserted here is not only that it fires, but that the
message carries the mechanism and the alternative — the parts that make it worth
having at all.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "godot"))
sys.path.insert(0, str(REPO / "tools" / "pylib"))

import export_game  # noqa: E402

GDSCRIPT_PROJECT = 'config_version=5\n\n[application]\n\nconfig/name="Neutral"\n'
DOTNET_PROJECT = GDSCRIPT_PROJECT + '\n[dotnet]\n\nproject/assembly_name="Neutral"\n'


class Project:
    """A throwaway project tree; only the files the preflight reads."""

    def __init__(self, settings: str, files: dict[str, str] | None = None):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name)
        (self.path / "project.godot").write_text(settings, encoding="utf-8")
        for name, content in (files or {}).items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *exc) -> None:
        self._tmp.cleanup()


class WebPresets(unittest.TestCase):
    def test_a_dotnet_project_is_refused_for_every_web_preset(self):
        with Project(DOTNET_PROJECT, {"Neutral.csproj": "<Project/>"}) as project:
            for preset in ("web-webgl", "web-webgpu"):
                with self.subTest(preset=preset):
                    problem = export_game.dotnet_web_problem(project, preset)
                    self.assertIsNotNone(problem, f"{preset} should refuse a .NET project")

    def test_the_refusal_names_the_mechanism_not_just_the_symptom(self):
        with Project(DOTNET_PROJECT, {"Neutral.csproj": "<Project/>"}) as project:
            problem = export_game.dotnet_web_problem(project, "web-webgl")
            self.assertIn("main module", problem)
            self.assertIn("cannot combine Mono runtime with the web platform", problem)
            # The point the WebGPU work does NOT address, said out loud.
            self.assertIn("WebGPU", problem)

    def test_the_refusal_offers_the_path_forward(self):
        with Project(DOTNET_PROJECT) as project:
            problem = export_game.dotnet_web_problem(project, "web-webgpu")
            self.assertIn("docs/adr/0019-compiled-gameplay-on-the-web.md", problem)
            self.assertIn("sim-kernel", problem)
            self.assertIn("GDScript", problem)

    def test_the_refusal_quotes_the_evidence_it_found(self):
        files = {"Neutral.csproj": "<Project/>", "src/Player.cs": "class Player {}"}
        with Project(DOTNET_PROJECT, files) as project:
            problem = export_game.dotnet_web_problem(project, "web-webgl")
            self.assertIn("Neutral.csproj", problem)
            self.assertIn("src/Player.cs", problem)
            self.assertIn("[dotnet]", problem)


class WhatMustNotBeRefused(unittest.TestCase):
    def test_a_gdscript_project_exports_to_the_web_untouched(self):
        with Project(GDSCRIPT_PROJECT, {"main.gd": "extends Node\n"}) as project:
            for preset in ("web-webgl", "web-webgpu"):
                self.assertIsNone(export_game.dotnet_web_problem(project, preset))

    def test_native_presets_keep_csharp(self):
        """C# is only blocked in the browser; refusing it elsewhere would be wrong."""
        with Project(DOTNET_PROJECT, {"Neutral.csproj": "<Project/>"}) as project:
            for preset in ("android", "ios", "windows", "linux"):
                with self.subTest(preset=preset):
                    self.assertIsNone(export_game.dotnet_web_problem(project, preset))

    def test_build_output_does_not_count_as_evidence(self):
        """Generated obj/bin trees and .godot caches must not conjure a .NET project."""
        noise = {
            "obj/Debug/Neutral.AssemblyInfo.cs": "// generated",
            "bin/Debug/x.cs": "// generated",
            ".godot/mono/Api.cs": "// generated",
        }
        with Project(GDSCRIPT_PROJECT, noise) as project:
            self.assertIsNone(export_game.dotnet_web_problem(project, "web-webgl"))

    def test_the_repository_template_still_exports(self):
        """The shipped neutral template must never trip its own preflight."""
        template = REPO / "templates" / "godot-game" / "project"
        self.assertTrue((template / "project.godot").is_file(), "template moved")
        self.assertIsNone(export_game.dotnet_web_problem(template, "web-webgl"))
        self.assertEqual(export_game.dotnet_signals(template), [])


if __name__ == "__main__":
    unittest.main()
