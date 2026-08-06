"""Native/Wasm parity for the sim kernel — full-structure comparison.

The contract (docs/specs/sim-replay-v0.1.md): same initial state + same event
stream must yield the same COMPLETE output — final state, per-tick hash log,
navigation, and final hash — under the canonical Python kernel, the native
Rust kernel, and the Wasm kernel, for every conformance fixture.

Skips cleanly when no wasm-capable Rust toolchain is available — except under
SIM_REQUIRE_PARITY=1 (the CI job that substantiates the claim), where a
missing toolchain is a failure, not a skip.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "tools" / "sim" / "conformance" / "v0.1"
WASM_HARNESS = REPO / "tools" / "sim" / "parity_wasm.mjs"
TOOLCHAIN = Path.home() / "AIWorkspace" / ".toolchain" / "cargo" / "bin"
REQUIRE = bool(os.environ.get("SIM_REQUIRE_PARITY"))


def cargo_env() -> dict:
    env = os.environ.copy()
    rustup_home = Path.home() / "AIWorkspace" / ".toolchain" / "rustup"
    cargo_home = Path.home() / "AIWorkspace" / ".toolchain" / "cargo"
    if rustup_home.is_dir():
        env.setdefault("RUSTUP_HOME", str(rustup_home))
        env.setdefault("CARGO_HOME", str(cargo_home))
        env["PATH"] = f"{cargo_home / 'bin'}:{env['PATH']}"
    return env


def find_cargo() -> str | None:
    cargo = shutil.which("cargo")
    if not cargo:
        candidate = TOOLCHAIN / "cargo"
        cargo = str(candidate) if candidate.is_file() else None
    if not cargo:
        return None
    # the wasm target must be installed, not just cargo (a bare hosted runner
    # ships Rust without wasm32 — and rustc happily PRINTS a libdir for a
    # target that is not installed, so check the directory exists)
    try:
        probe = subprocess.run(
            ["rustc", "--print", "target-libdir", "--target", "wasm32-unknown-unknown"],
            env=cargo_env(),
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    installed = probe.returncode == 0 and Path(probe.stdout.strip()).is_dir()
    return cargo if installed else None


CARGO = None if os.environ.get("SIM_SKIP_PARITY") else find_cargo()


def python_output(replay: Path) -> dict:
    out = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            "tools",
            "python",
            "tools/sim/kernel.py",
            "replay",
            str(replay),
            "--full",
        ],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


class ParityBase(unittest.TestCase):
    def assert_three_way(self, replay: Path):
        expected = python_output(replay)
        native = subprocess.run(
            [str(REPO / "services" / "target" / "release" / "sim-kernel"), str(replay)],
            check=True,
            capture_output=True,
            text=True,
            env=cargo_env(),
        ).stdout
        wasm = subprocess.run(
            [
                "node",
                str(WASM_HARNESS),
                str(
                    REPO
                    / "services"
                    / "target"
                    / "wasm32-unknown-unknown"
                    / "release"
                    / "sim_kernel.wasm"
                ),
                str(replay),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=cargo_env(),
        ).stdout
        for key in ("final_state", "state_hash", "hash_log", "navigation"):
            self.assertEqual(
                json.loads(native)[key], expected[key], f"native {key} ({replay.name})"
            )
            self.assertEqual(json.loads(wasm)[key], expected[key], f"wasm {key} ({replay.name})")


@unittest.skipIf(CARGO is None and not REQUIRE, "no wasm-capable Rust toolchain available")
class Parity(ParityBase):
    @classmethod
    def setUpClass(cls):
        if CARGO is None:
            raise unittest.SkipTest  # unreachable when REQUIRE; guarded below
        env = cargo_env()
        services = REPO / "services"
        subprocess.run(
            [CARGO, "build", "-p", "sim-kernel", "--release"],
            cwd=services,
            env=env,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [CARGO, "build", "-p", "sim-kernel", "--release", "--target", "wasm32-unknown-unknown"],
            cwd=services,
            env=env,
            check=True,
            capture_output=True,
        )

    def test_every_valid_conformance_fixture_matches_three_ways(self):
        fixtures = sorted((CORPUS / "valid").glob("*.json"))
        self.assertGreaterEqual(len(fixtures), 5)
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                self.assert_three_way(fixture)

    def test_every_invalid_conformance_fixture_fails_three_ways(self):
        """Invalid inputs: identical stable error codes from Python, native
        Rust, and Wasm — rejection parity, not just success parity."""
        fixtures = sorted((CORPUS / "invalid").glob("*.json"))
        self.assertGreaterEqual(len(fixtures), 8)
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                expected = json.loads(fixture.read_text()).get("expect_error")
                if expected is None:  # raw-text fixtures carry it unparseable
                    text = fixture.read_text()
                    marker = '"expect_error": "'
                    start = text.index(marker) + len(marker)
                    expected = text[start : text.index('"', start)]
                codes = {"python": None, "native": None, "wasm": None}

                python_proc = subprocess.run(
                    ["uv", "run", "--project", "tools", "python", "tools/sim/kernel.py",
                     "replay", str(fixture)],
                    cwd=REPO, capture_output=True, text=True,
                )
                self.assertNotEqual(python_proc.returncode, 0)
                codes["python"] = json.loads(python_proc.stderr)["code"]

                native_proc = subprocess.run(
                    [str(REPO / "services" / "target" / "release" / "sim-kernel"), str(fixture)],
                    capture_output=True, text=True, env=cargo_env(),
                )
                self.assertNotEqual(native_proc.returncode, 0)
                codes["native"] = json.loads(native_proc.stdout)["code"]

                wasm_proc = subprocess.run(
                    ["node", str(WASM_HARNESS),
                     str(REPO / "services" / "target" / "wasm32-unknown-unknown"
                          / "release" / "sim_kernel.wasm"),
                     str(fixture)],
                    capture_output=True, text=True, env=cargo_env(),
                )
                codes["wasm"] = json.loads(wasm_proc.stdout)["code"]

                self.assertEqual(codes["python"], expected, f"python ({fixture.name})")
                self.assertEqual(codes["native"], expected, f"native ({fixture.name})")
                self.assertEqual(codes["wasm"], expected, f"wasm ({fixture.name})")


if REQUIRE and CARGO is None:
    raise RuntimeError("SIM_REQUIRE_PARITY=1 but no wasm-capable Rust toolchain is available")

if __name__ == "__main__":
    unittest.main()
