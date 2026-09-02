"""The browser kernel host has to actually reach the browser.

`sim_kernel_host.js` is the file StudioSimKernel injects on web. It is not a
Godot resource, so `export_filter="all_resources"` walks straight past it: unless
a web preset's `include_filter` names it, the export succeeds, the game boots,
and the kernel simply never becomes ready — in production, on someone else's
machine, with nothing in the build log.

There is no Godot in the fast suite to catch that, so the packaging contract is
asserted against the files themselves.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ADDON = REPO / "shared" / "godot-addons" / "studio_core" / "sim"
HOST_JS = ADDON / "sim_kernel_host.js"
HOST_GD = ADDON / "sim_kernel.gd"


def presets(cfg: Path) -> list[tuple[str, str]]:
    """(name, include_filter) for every preset block in an export_presets.cfg."""
    found = []
    for block in re.split(r"(?m)^(?=\[preset\.)", cfg.read_text(encoding="utf-8")):
        name = re.search(r'(?m)^name="([^"]+)"', block)
        include = re.search(r'(?m)^include_filter="([^"]*)"', block)
        if name and include:
            found.append((name.group(1), include.group(1)))
    return found


class Packaging(unittest.TestCase):
    def test_the_host_script_and_its_gdscript_wrapper_exist(self):
        self.assertTrue(HOST_JS.is_file(), f"{HOST_JS} is missing")
        self.assertTrue(HOST_GD.is_file(), f"{HOST_GD} is missing")

    def test_every_web_preset_ships_js(self):
        configs = sorted(REPO.glob("*/*/project/export_presets.cfg"))
        self.assertTrue(configs, "no export_presets.cfg found")
        checked = 0
        for cfg in configs:
            for name, include in presets(cfg):
                if not name.startswith("web"):
                    continue
                checked += 1
                self.assertIn(
                    "*.js",
                    include,
                    f"{cfg.relative_to(REPO)} preset '{name}' does not ship *.js, so "
                    "StudioSimKernel cannot load its host script in an exported build",
                )
        self.assertGreaterEqual(checked, 2, "expected at least the two web presets")

    def test_the_gdscript_and_js_contract_versions_agree(self):
        """One number, two files: a drifted pair fails at runtime, in a browser."""
        gd = re.search(r"const HOST_CONTRACT: int = (\d+)", HOST_GD.read_text(encoding="utf-8"))
        js = re.search(r"contract: (\d+)", HOST_JS.read_text(encoding="utf-8"))
        self.assertIsNotNone(gd, "HOST_CONTRACT not found in sim_kernel.gd")
        self.assertIsNotNone(js, "contract not found in sim_kernel_host.js")
        self.assertEqual(gd.group(1), js.group(1))

    def test_the_gdscript_path_matches_where_sync_puts_the_file(self):
        gd_source = HOST_GD.read_text(encoding="utf-8")
        path = re.search(r'const HOST_JS: String = "res://([^"]+)"', gd_source)
        self.assertIsNotNone(path, "HOST_JS constant not found")
        # sync_addons.py copies shared/godot-addons/<addon>/** to project/addons/<addon>/**
        self.assertEqual(
            path.group(1),
            "addons/studio_core/sim/sim_kernel_host.js",
            "HOST_JS does not point at where sync_addons.py places the file",
        )

    def test_the_host_script_is_a_classic_script(self):
        """JavaScriptBridge.eval() runs page-global code; module syntax is fatal there."""
        source = HOST_JS.read_text(encoding="utf-8")
        for token in ("\nimport ", "\nexport ", "\nexport{"):
            self.assertNotIn(token, source, f"module syntax ({token.strip()}) breaks eval()")

    def test_sync_addons_carries_the_js_into_projects(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "tools" / "godot" / "sync_addons.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for project in sorted(REPO.glob("*/*/project/project.godot")):
            synced = project.parent / "addons" / "studio_core" / "sim" / "sim_kernel_host.js"
            self.assertTrue(synced.is_file(), f"{synced} was not synced")
            self.assertEqual(synced.read_bytes(), HOST_JS.read_bytes())


if __name__ == "__main__":
    unittest.main()
