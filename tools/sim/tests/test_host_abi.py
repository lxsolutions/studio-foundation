"""The host-independence gate must catch the ways a kernel binds itself to a host.

A gate that only ever sees a passing artifact is untested. These fixtures are
hand-assembled WebAssembly modules — the smallest bytes that express each way
the contract in ADR 0019 can break — so the gate is proven to fail, not just
proven to agree with today's build.

The final test runs the gate against the real `sim_kernel.wasm` when a
wasm-capable Rust toolchain is present, and is required (never skipped) under
SIM_REQUIRE_PARITY=1 — the CI job that substantiates the public claim.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "sim"))

import host_abi  # noqa: E402

WASM = REPO / "services" / "target" / "wasm32-unknown-unknown" / "release" / "sim_kernel.wasm"
REQUIRE = bool(os.environ.get("SIM_REQUIRE_PARITY"))

I32, I64 = 0x7F, 0x7E


def uleb(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def vec(items: list[bytes]) -> bytes:
    return uleb(len(items)) + b"".join(items)


def name(text: str) -> bytes:
    raw = text.encode("utf-8")
    return uleb(len(raw)) + raw


def section(section_id: int, payload: bytes) -> bytes:
    return bytes([section_id]) + uleb(len(payload)) + payload


def functype(params: list[int], results: list[int]) -> bytes:
    return b"\x60" + vec([bytes([p]) for p in params]) + vec([bytes([r]) for r in results])


def module(
    *,
    types: list[bytes],
    imports: list[bytes] = (),
    functions: list[int] = (),
    memories: int = 1,
    exports: list[bytes] = (),
    start: int | None = None,
) -> bytes:
    out = host_abi.MAGIC + host_abi.VERSION
    out += section(1, vec(types))
    if imports:
        out += section(2, vec(list(imports)))
    if functions:
        out += section(3, vec([uleb(index) for index in functions]))
    if memories:
        out += section(5, vec([b"\x00" + uleb(17)] * memories))
    if exports:
        out += section(7, vec(list(exports)))
    if start is not None:
        out += section(8, uleb(start))
    return out


def func_import(mod: str, field: str, type_index: int) -> bytes:
    return name(mod) + name(field) + b"\x00" + uleb(type_index)


def export(export_name: str, kind: int, index: int) -> bytes:
    return name(export_name) + bytes([kind]) + uleb(index)


# The three kernel signatures, in the order the reactor ABI declares them.
ALLOC, FREE, RUN = functype([I32], [I32]), functype([I32, I32], []), functype([I32, I32], [I64])


def conforming(**overrides) -> bytes:
    base = {
        "types": [ALLOC, FREE, RUN],
        "functions": [0, 1, 2],
        "exports": [
            export("memory", 2, 0),
            export("sim_alloc", 0, 0),
            export("sim_free", 0, 1),
            export("sim_run", 0, 2),
        ],
    }
    base.update(overrides)
    return module(**base)


class HandBuiltFixtures(unittest.TestCase):
    def test_a_conforming_reactor_module_passes(self):
        parsed = host_abi.parse(conforming())
        self.assertEqual(host_abi.violations(parsed), [])
        self.assertEqual(parsed.signatures["sim_run"], "(i32, i32) -> (i64)")
        self.assertTrue(host_abi.report(parsed)["host_independent"])

    def test_any_import_fails_and_names_the_host_it_bound_to(self):
        """The failure this gate exists for: one std side effect pulls in WASI."""
        parsed = host_abi.parse(
            conforming(
                imports=[func_import("wasi_snapshot_preview1", "fd_write", 0)],
                # An imported function occupies index 0, so the defined functions
                # this module exports start at 1 — the gate must follow that shift.
                exports=[
                    export("memory", 2, 0),
                    export("sim_alloc", 0, 1),
                    export("sim_free", 0, 2),
                    export("sim_run", 0, 3),
                ],
            )
        )
        problems = host_abi.violations(parsed)
        self.assertEqual(len(problems), 1, f"only the import should fail: {problems}")
        self.assertIn("wasi_snapshot_preview1.fd_write", problems[0])
        self.assertIn("main-module slot", problems[0])
        self.assertFalse(host_abi.report(parsed)["host_independent"])

    def test_imported_functions_shift_the_signature_lookup(self):
        """Index-space arithmetic, isolated: get this wrong and a broken ABI reads clean."""
        parsed = host_abi.parse(
            conforming(
                imports=[func_import("env", "abort", 0), func_import("env", "now", 0)],
                exports=[
                    export("memory", 2, 0),
                    export("sim_alloc", 0, 2),
                    export("sim_free", 0, 3),
                    export("sim_run", 0, 4),
                ],
            )
        )
        self.assertEqual(parsed.signatures["sim_alloc"], "(i32) -> (i32)")
        self.assertEqual(parsed.signatures["sim_free"], "(i32, i32) -> ()")
        self.assertEqual(parsed.signatures["sim_run"], "(i32, i32) -> (i64)")

    def test_a_missing_export_fails(self):
        parsed = host_abi.parse(
            conforming(
                functions=[0, 1],
                exports=[
                    export("memory", 2, 0),
                    export("sim_alloc", 0, 0),
                    export("sim_free", 0, 1),
                ],
            )
        )
        problems = host_abi.violations(parsed)
        self.assertTrue(any("missing export `sim_run`" in p for p in problems), problems)

    def test_a_missing_memory_export_fails(self):
        """Without exported memory a host cannot pass bytes across the boundary."""
        parsed = host_abi.parse(
            conforming(
                exports=[
                    export("sim_alloc", 0, 0),
                    export("sim_free", 0, 1),
                    export("sim_run", 0, 2),
                ]
            )
        )
        problems = host_abi.violations(parsed)
        self.assertTrue(any("missing export `memory`" in p for p in problems), problems)

    def test_a_changed_signature_fails(self):
        """sim_run must keep returning the packed i64 every JS host unpacks."""
        parsed = host_abi.parse(conforming(types=[ALLOC, FREE, functype([I32, I32], [I32])]))
        problems = host_abi.violations(parsed)
        self.assertTrue(any("`sim_run` has signature" in p for p in problems), problems)
        self.assertIn("(i32, i32) -> (i32)", " ".join(problems))

    def test_a_start_section_fails(self):
        parsed = host_abi.parse(conforming(start=0))
        problems = host_abi.violations(parsed)
        self.assertTrue(any("start section" in p for p in problems), problems)

    def test_non_wasm_bytes_are_rejected_clearly(self):
        with self.assertRaises(host_abi.WasmFormatError):
            host_abi.parse(b"<!doctype html>\n<html></html>")

    def test_a_truncated_module_is_rejected_not_misread(self):
        with self.assertRaises(host_abi.WasmFormatError):
            host_abi.parse(conforming()[:40])


@unittest.skipIf(not WASM.is_file() and not REQUIRE, "sim_kernel.wasm is not built")
class BuiltKernel(unittest.TestCase):
    """The claim in README/ADR 0019 is about the real artifact, so check it."""

    def test_the_shipped_kernel_is_host_independent(self):
        self.assertTrue(WASM.is_file(), f"{WASM} missing under SIM_REQUIRE_PARITY=1")
        parsed = host_abi.parse(WASM.read_bytes())
        self.assertEqual(
            [str(entry) for entry in parsed.imports],
            [],
            "the sim kernel acquired an import — see docs/adr/0019-compiled-gameplay-on-the-web.md",
        )
        self.assertEqual(host_abi.violations(parsed), [])

    def test_the_cli_exits_zero_and_says_so(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "tools" / "sim" / "host_abi.py"), str(WASM)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("host-independence gate OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
