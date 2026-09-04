#!/usr/bin/env python3
"""Prove the sim kernel is host-independent — the gate behind ADR 0019.

  python tools/sim/host_abi.py services/target/wasm32-unknown-unknown/release/sim_kernel.wasm

Godot cannot export a C#/.NET client to the browser because Godot's Emscripten
runtime and the .NET runtime both need to BE the WebAssembly main module, and a
page has one main-module slot. Studio Foundation does not fix that. It removes
the need for it: gameplay logic compiles to a *reactor* module that wants no
slot at all, and is instantiated by whichever runtime already holds one.

That only works if the kernel stays free of host coupling, which is a property
one careless dependency destroys silently — a `println!`, a `std::time` call, or
any crate that reaches for the clock or the filesystem drags in a WASI import,
and the module stops being loadable from inside a Godot web export. Nothing
about the build fails; the kernel simply refuses to instantiate months later, in
a browser, in someone else's product.

So the property is checked here, mechanically, on the built artifact:

  1. Zero imports.        Every import names a host that must supply it.
  2. The exact reactor ABI, with the exact signatures JavaScript hosts assume.
  3. An exported linear memory, so a host can pass bytes across the boundary.
  4. No start section.    A reactor is called, never self-starting.

Exits non-zero and explains which host the module accidentally bound itself to.
The parser is a stdlib-only reader of the sections this contract needs (ADR
0013 keeps tooling dependency-free); it is not a validator.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"\x00asm"
VERSION = b"\x01\x00\x00\x00"

SECTION_TYPE = 1
SECTION_IMPORT = 2
SECTION_FUNCTION = 3
SECTION_EXPORT = 7
SECTION_START = 8

KINDS = {0: "func", 1: "table", 2: "memory", 3: "global"}
VALTYPES = {
    0x7F: "i32",
    0x7E: "i64",
    0x7D: "f32",
    0x7C: "f64",
    0x7B: "v128",
    0x70: "funcref",
    0x6F: "externref",
}

# The contract JavaScript hosts are written against: tools/sim-viewer/adapter.js,
# tools/sim/parity_wasm.mjs, and studio_core's Godot host all assume exactly this.
REQUIRED_EXPORTS = {
    "memory": "memory",
    "sim_alloc": "func",
    "sim_free": "func",
    "sim_run": "func",
}
REQUIRED_SIGNATURES = {
    # wasm32: usize and every pointer are i32; sim_run packs (ptr << 32 | len).
    "sim_alloc": "(i32) -> (i32)",
    "sim_free": "(i32, i32) -> ()",
    "sim_run": "(i32, i32) -> (i64)",
}


class WasmFormatError(ValueError):
    """The bytes are not a WebAssembly module this reader can walk."""


@dataclass(frozen=True)
class Import:
    module: str
    field: str
    kind: str

    def __str__(self) -> str:
        return f"{self.module}.{self.field} ({self.kind})"


@dataclass(frozen=True)
class Module:
    imports: tuple[Import, ...]
    exports: dict[str, str]
    signatures: dict[str, str]
    has_start: bool


class _Reader:
    def __init__(self, data: bytes, offset: int = 0) -> None:
        self.data = data
        self.offset = offset

    def byte(self) -> int:
        if self.offset >= len(self.data):
            raise WasmFormatError("truncated module")
        value = self.data[self.offset]
        self.offset += 1
        return value

    def uleb(self) -> int:
        """Unsigned LEB128. Bounded at 5 bytes — every u32 this format uses."""
        result = 0
        for shift in range(0, 35, 7):
            byte = self.byte()
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result
        raise WasmFormatError("LEB128 value overruns u32")

    def take(self, count: int) -> bytes:
        if count < 0 or self.offset + count > len(self.data):
            raise WasmFormatError("truncated module")
        chunk = self.data[self.offset : self.offset + count]
        self.offset += count
        return chunk

    def name(self) -> str:
        raw = self.take(self.uleb())
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - malformed input
            raise WasmFormatError(f"non-UTF-8 name: {exc}") from exc


def _valtype(code: int) -> str:
    return VALTYPES.get(code, f"0x{code:02x}")


def _read_types(payload: bytes) -> list[str]:
    reader = _Reader(payload)
    signatures: list[str] = []
    for _ in range(reader.uleb()):
        if reader.byte() != 0x60:
            # Non-function types (GC//exception proposals) — index space must stay
            # aligned, so record a placeholder rather than guessing the encoding.
            signatures.append("<non-function type>")
            continue
        params = [_valtype(reader.byte()) for _ in range(reader.uleb())]
        results = [_valtype(reader.byte()) for _ in range(reader.uleb())]
        signatures.append(f"({', '.join(params)}) -> ({', '.join(results)})")
    return signatures


def _read_imports(payload: bytes) -> list[Import]:
    reader = _Reader(payload)
    imports: list[Import] = []
    for _ in range(reader.uleb()):
        module, field = reader.name(), reader.name()
        kind_code = reader.byte()
        imports.append(Import(module, field, KINDS.get(kind_code, f"0x{kind_code:02x}")))
        # Skip the descriptor; only its kind matters to this contract.
        if kind_code == 0:  # typeidx
            reader.uleb()
        elif kind_code == 1:  # tabletype: reftype + limits
            reader.byte()
            _skip_limits(reader)
        elif kind_code == 2:  # memtype: limits
            _skip_limits(reader)
        elif kind_code == 3:  # globaltype: valtype + mutability
            reader.byte()
            reader.byte()
        else:
            raise WasmFormatError(f"unknown import kind 0x{kind_code:02x}")
    return imports


def _skip_limits(reader: _Reader) -> None:
    flags = reader.byte()
    reader.uleb()
    if flags & 0x01:
        reader.uleb()


def _read_functions(payload: bytes) -> list[int]:
    reader = _Reader(payload)
    return [reader.uleb() for _ in range(reader.uleb())]


def _read_exports(payload: bytes) -> list[tuple[str, str, int]]:
    reader = _Reader(payload)
    exports: list[tuple[str, str, int]] = []
    for _ in range(reader.uleb()):
        name = reader.name()
        kind_code = reader.byte()
        exports.append((name, KINDS.get(kind_code, f"0x{kind_code:02x}"), reader.uleb()))
    return exports


def parse(data: bytes) -> Module:
    """Walk the sections the host-independence contract depends on."""
    if data[:4] != MAGIC:
        raise WasmFormatError("not a WebAssembly module (bad magic)")
    if data[4:8] != VERSION:
        raise WasmFormatError(f"unsupported WebAssembly version {data[4:8]!r}")

    reader = _Reader(data, 8)
    types: list[str] = []
    imports: list[Import] = []
    functions: list[int] = []
    raw_exports: list[tuple[str, str, int]] = []
    has_start = False

    while reader.offset < len(data):
        section_id = reader.byte()
        payload = reader.take(reader.uleb())
        if section_id == SECTION_TYPE:
            types = _read_types(payload)
        elif section_id == SECTION_IMPORT:
            imports = _read_imports(payload)
        elif section_id == SECTION_FUNCTION:
            functions = _read_functions(payload)
        elif section_id == SECTION_EXPORT:
            raw_exports = _read_exports(payload)
        elif section_id == SECTION_START:
            has_start = True

    imported_funcs = sum(1 for entry in imports if entry.kind == "func")
    exports: dict[str, str] = {}
    signatures: dict[str, str] = {}
    for name, kind, index in raw_exports:
        exports[name] = kind
        if kind != "func":
            continue
        defined = index - imported_funcs
        if 0 <= defined < len(functions):
            type_index = functions[defined]
            if 0 <= type_index < len(types):
                signatures[name] = types[type_index]

    return Module(tuple(imports), exports, signatures, has_start)


def violations(module: Module) -> list[str]:
    """Every way this module has stopped being loadable by an arbitrary host."""
    problems: list[str] = []

    if module.imports:
        named = ", ".join(str(entry) for entry in module.imports)
        hosts = sorted({entry.module for entry in module.imports})
        problems.append(
            f"the kernel imports {named}. An import is a demand on the host: only a "
            f"runtime that supplies {', '.join(hosts)} can instantiate this module, so "
            "it can no longer be loaded from inside a Godot web export (or any other "
            "host that already owns the main-module slot). Usual causes: println!/"
            "eprintln!, std::time, std::fs, rand, or a crate that reaches for one of "
            "them. Keep the kernel's wasm path free of std side effects."
        )

    for name, kind in REQUIRED_EXPORTS.items():
        actual = module.exports.get(name)
        if actual is None:
            problems.append(
                f"missing export `{name}` ({kind}). Every JavaScript host in this "
                "repository binds it by name; without it the kernel cannot be driven "
                "from a browser at all."
            )
        elif actual != kind:
            problems.append(f"export `{name}` is a {actual}, expected a {kind}")

    for name, expected in REQUIRED_SIGNATURES.items():
        if name not in module.exports:
            continue  # already reported as missing
        actual = module.signatures.get(name)
        if actual is None:
            problems.append(f"could not resolve the signature of `{name}`")
        elif actual != expected:
            problems.append(
                f"export `{name}` has signature {actual}, expected {expected}. "
                "Changing the ABI silently breaks every host that already speaks it; "
                "version the contract instead."
            )

    if module.has_start:
        problems.append(
            "the module has a start section. A reactor module must do nothing until "
            "a host calls it — self-starting code runs before the host has set up the "
            "memory it is about to be handed."
        )

    return problems


def report(module: Module) -> dict:
    return {
        "imports": [str(entry) for entry in module.imports],
        "exports": dict(sorted(module.exports.items())),
        "signatures": dict(sorted(module.signatures.items())),
        "has_start_section": module.has_start,
        "host_independent": not violations(module),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wasm", type=Path, help="path to sim_kernel.wasm")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args(argv)

    if not args.wasm.is_file():
        print(f"error: {args.wasm} does not exist (build it: `just sim-parity`)", file=sys.stderr)
        return 2

    try:
        module = parse(args.wasm.read_bytes())
    except WasmFormatError as exc:
        print(f"error: {args.wasm}: {exc}", file=sys.stderr)
        return 2

    problems = violations(module)
    if args.json:
        print(json.dumps(report(module), indent=2))
    else:
        print(f"{args.wasm} ({args.wasm.stat().st_size} bytes)")
        print(
            f"  imports:   {len(module.imports)}"
            + (" — none, host-independent" if not module.imports else "")
        )
        for entry in module.imports:
            print(f"    - {entry}")
        print("  exports:")
        for name, kind in sorted(module.exports.items()):
            signature = module.signatures.get(name)
            print(f"    - {name} ({kind})" + (f" {signature}" if signature else ""))
        print(f"  start section: {'yes' if module.has_start else 'no'}")

    if problems:
        print("\nhost-independence gate FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nWhy this gate exists: docs/adr/0019-compiled-gameplay-on-the-web.md",
            file=sys.stderr,
        )
        return 1

    print("\nhost-independence gate OK — any WebAssembly host can instantiate this kernel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
