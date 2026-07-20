# Bootstrap Report — what verifiably works, and on which machine

Last verified: 2026-07-20, Windows 10 AMD64 (local dev machine "Awesom-o").
Nothing below is claimed without a recorded command run on this date.

## Environment (just doctor)

| Tool | Status |
|---|---|
| Windows 10 AMD64, Python 3.11.3, Git 2.40, just 1.57, uv 0.8.22 | OK (required) |
| Rust cargo 1.97.1 `x86_64-pc-windows-gnu` | OK — links via WinLibs MinGW (see fix below) |
| Godot 4.7.1.stable.official.a13da4feb (winget) + official web export templates | OK |
| Blender 5.2.0 | OK (manual) |
| Node 22.20.0 | OK (optional) |
| Docker client 29.6.1 | BLOCKED — "Virtualization support not detected": VT-x/AMD-V disabled in BIOS/UEFI; needs firmware toggle + reboot (user action) |
| PostgreSQL 127.0.0.1:5432 | not listening (blocked on Docker/virtualization above) |
| WebGPU fork export templates | sources fetchable via `just engine-fetch` (implemented today); templates NOT built (needs scons+emsdk 4.0.11, hours) |
| Android SDK | not installed |
| Playwright (playwright-core, system Chrome) | OK — installed + smoke passing (see below) |
| studio-mcp config | missing (server self-check passes) |

## Test evidence (just test — green, exit 0)

- **Rust workspace** (`services/`): full `cargo test --workspace` passes, including
  websocket handshake/echo and stale-protocol rejection. DB round-trip tests are
  present but `ignored` (require live PostgreSQL).
- **Python/studio-mcp**: 34 tests pass (protocol surface, path/SQL/timeout
  security, registry boundaries).
- **Protocol golden fixtures**: `tools/asset-pipeline/check_fixtures.py` passes.
- **Godot headless** (template project): 8 files, 24 test methods, 129 asserts,
  0 failures. Godot prints expected ERROR/WARNING lines for negative-path tests
  (newer-schema save rejection, JSON garbage rejection) plus known engine-exit
  resource-leak warnings — none are failures.

## Fixes applied on 2026-07-20

1. **windows-gnu link failure** — `ld: cannot find dllcrt2.o / -lkernel32` broke
   every cargo build. Root cause: rustup's self-contained MinGW gcc lacks CRT
   objects; a real MinGW (WinLibs UCRT, installed via winget) must be on PATH.
   Fixes:
   - `tools/pylib/studio_tools/env.py`: `find_mingw_gcc()` / `mingw_bin_dir()`
     discovery (PATH → winget WinLibs → MSYS2), explicitly ignoring rustup's
     self-contained gcc.
   - `tools/cargo_env.py`: wrapper that injects the MinGW bin dir into PATH for
     any cargo invocation.
   - `justfile`: `test-rust`, `build-rust`, `lint-rust`, `db-migrate`,
     `test-generated` now route cargo through the wrapper.
   - `tools/doctor/doctor.py`: new **required** `mingw-linker` check so the
     failure is diagnosed before a build, not during one.
2. **`test-python` ran zero tests** (unittest discovery found nothing at
   `tools/` top level) — recipe now targets `tools/studio-mcp/tests`, matching
   `test-mcp`.
3. **studio-mcp INVALID_PARAMS bug** — `params.arguments: []` was coerced to
   `{}` by `or {}` and never rejected. Fixed in
   `tools/pylib/studio_tools/mcp/server_core.py`; the existing
   `test_tools_call_bad_params_shape` now passes.

## Browser export + smoke (verified 2026-07-20, second session)

- `just export-browser-webgl` — template project exported: index.html 5 KiB,
  index.wasm 38.6 MiB, index.pck 113 KiB (37.8 MiB total).
- `just run-browser-smoke` — **PASS**: playwright-core drove system Chrome,
  Godot canvas rendered live at 127.0.0.1:8060, zero fatal console errors.
  Tooling created today: `tests/browser/package.json` + `smoke.mjs` (spawns
  `serve_web.py`, waits for canvas with non-zero GL size, pattern-matches fatal
  console errors) and the `tools/godot/run_browser_smoke.py` wrapper the
  justfile always referenced. doctor's browser-testing check now looks for
  `playwright-core` and its fix text is accurate.
- `just engine-versions` / `just engine-fetch` — implemented
  `engine/scripts/engine.py` (pins report; blob-filtered clone + pinned-commit
  checkout of official Godot 4.7.1 and the dwalter/godotwebgpu fork into
  `engine/.cache`, patch-series application point included). `build`/`rebase`
  deliberately refuse with guidance until the scons+emsdk toolchain is set up.

## Honest gaps (not yet evidenced)

- Live PostgreSQL path (`services-up`, `test-db`, migrations) — blocked on
  firmware virtualization; Docker Desktop cannot start until VT-x/AMD-V is
  enabled in BIOS/UEFI and the machine reboots.
- WebGPU browser export — fork sources fetched; templates not built (scons
  4.9.1 + emsdk 4.0.11 not installed; multi-hour build). No WebGPU claim.
- Android/iOS exports — no SDK / no macOS.
- Safari/iOS anything — requires real hardware, per policy.

## Strategy docs added 2026-07-20

- `docs/adr/0007-one-persistent-world-many-scales.md` — the studio's defining
  thesis: one world simulation, many gameplay scales; design laws included.
- `docs/architecture/asha-platform-strategy.md` — Godot distribution (not a
  merged multi-engine) decision; what we own vs. borrow.
- `docs/architecture/vertical-slice.md` — the closed-loop campaign sector
  (extraction → economy → production → strategy → battle → territory) as the
  first milestone.
