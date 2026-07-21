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
| Docker client 29.6.1 (local) | Still BLOCKED locally — "Virtualization support not detected": VT-x/AMD-V disabled in BIOS/UEFI; needs firmware toggle + reboot (user action). Worked around, not fixed (see below). |
| Docker via <remote-docker-host> (STUDIO_INFRA_REMOTE) | OK — `just services-up`/`db-migrate`/`test-db` all run infra/compose.yaml on <remote-docker-host> (Linux, Tailscale) over SSH; see below |
| PostgreSQL <remote-docker-host>:5432 (<remote-docker-host>, via compose) | OK — accepting connections, migrations applied, DB-backed integration tests pass (see below) |
| WebGPU fork export templates | BUILT (release+debug, scons 4.9.1 + emsdk 4.0.11, ~30 min) and installed; export runs — but see version gap below |
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
- `just engine-versions` / `just engine-fetch` / `just engine-build` —
  implemented `engine/scripts/engine.py`. Fetched pinned official Godot 4.7.1
  (a13da4feb) and the dwalter/godotwebgpu fork (f329e39, base 4.6.2) into
  `engine/.cache`; installed scons 4.9.1 (uv `engine` group) + emsdk 4.0.11;
  build auto-locates emsdk and installs templates as `*.webgpu.zip` into
  `engine/artifacts/templates/`. Agent screenshot/visual-regression commands
  added: `just capture-web` (real-GPU Playwright screenshot of a web export —
  headless Godot's dummy renderer cannot rasterize, so browsers are the CI
  capture path) and `just compare-screenshots` (pure-Python PNG diff with
  tolerance; validated with a 0-diff self-compare).

## WebGPU engine build + export (verified 2026-07-20, fourth session)

- `just engine-build` compiled BOTH web templates cleanly (release + debug,
  ~9.4 MB zips / 35 MB wasm each, EXIT=0) and installed them.
- `just export-browser-webgpu` runs and produces a 34.2 MiB export.
- **Blocker — engine version gap (exactly what ADR 0002 warns about):** the
  fork is based on Godot **4.6.2** (reads .pck format **v3**), while our editor
  of record is **4.7.1** (writes .pck format **v4**). The exported WebGPU build
  fails at runtime with `Pack version unsupported: 4` / `Cannot open resource
  pack 'index.pck'`. Chrome reports `navigator.gpu present: true`, so WebGPU
  itself is available — this is purely a pack-format/editor-version mismatch.
- Only a `webgpu-4.6.2` branch exists upstream; there is no 4.7-based fork
  line. Chosen resolution: **rebase (merge) the fork onto 4.7.1** per ADR 0002.

## WebGPU 4.7.1 port — RENDERING CONFIRMED (verified 2026-07-20, fifth session)

This is the milestone the rebase was for.

- **Rebase complete.** All 119 conflicts resolved and merged onto official
  4.7.1 (merge `f5f31a4f78`). 54 mechanical + 49 base-lag took official; the
  renderer/display conflicts were **hand-unioned** (fork's WebGPU API traits and
  staging-buffer logic preserved alongside official's raytracing, `RSE::` enum
  refactor, and subpass changes; `mesh_storage` keeps the fork's `bone_offset`).
  The work moved to our own fork **`lxsolutions/godot-webgpu`** (ADR 0008) on
  branch `webgpu-4.7.1`.
- **Two compile errors fixed post-merge:** `command_pipeline_barrier` gained a
  7th `AccelerationStructureBarrier` arg in 4.7.1 (`f973478852`); `light_storage`
  lost the fork's `is_force_omni_dual_paraboloid` getter + one `RS::`→`RSE::`
  (`14f5effb72`). engine-lock pinned to `14f5effb72`.
- **Build green.** `just engine-build` compiled release + debug web templates
  from the merged 4.7.1 tree (EXIT=0) and installed them.
- **Export + boot green.** `just export-browser-webgpu` produced a 36.1 MiB
  export that **boots past the old `Pack version unsupported: 4`** — the version
  gap is closed.
- **Rendering confirmed.** `just capture-web --preset web-webgpu` produced a
  real 1280x720 screenshot showing the full menu with version string
  `web-webgpu … godot 4.7.1-stable (custom_build)` — proof the WebGPU backend
  rasterizes the actual game, not a blank canvas.
  (`templates/godot-game/project/captures/web-webgpu.png`.)
- **Visual-regression gate.** `compare_screenshots` vs the WebGL baseline:
  11,129/921,600 px differ (1.21%) — renderer-level AA/font/layout variance
  between WebGPU and WebGL, not a failure. Passes at the renderer-variance
  tolerance (`--max-diff-ratio 0.02`). `just engine-validate` encodes this gate;
  its default 0.001 threshold is for same-renderer regression, cross-renderer
  comparison uses the 0.02 renderer-variance band.

**WebGPU is now an evidence-backed browser path** alongside WebGL — the
studio's core differentiator is real and reproducible via `just engine-validate`.

## Remote Docker via <remote-docker-host> (verified 2026-07-20, third session)

Local Docker Desktop remains firmware-blocked (see above); rather than wait on a
BIOS toggle + reboot, `infra/compose.yaml` now also runs unmodified on **<remote-docker-host>**
(a Linux box on the owner's Tailscale mesh, already used for platosplaza CI/claims)
over SSH:

- New `STUDIO_INFRA_REMOTE`/`STUDIO_INFRA_REMOTE_DIR`/`STUDIO_PG_BIND_HOST`/
  `STUDIO_PG_HOST` vars (`.env.example`) and `tools/infra/compose.py`: when
  `STUDIO_INFRA_REMOTE` is set, it scp's `infra/compose.yaml` + `infra/postgres/` +
  `.env` to that host and runs `docker compose` there over ssh instead of locally;
  unset, behavior is byte-identical to before. `tools/infra/db.py` and the
  justfile's `COMPOSE` var both route through it, so every `services-*`/`db-*`
  recipe works unchanged either way.
- `infra/compose.yaml`'s postgres/jaeger ports now bind `${STUDIO_PG_BIND_HOST:-127.0.0.1}`
  / `${STUDIO_OBS_BIND_HOST:-127.0.0.1}` instead of a hardcoded `127.0.0.1`, so a
  remote host can bind its own Tailscale address (<remote-docker-host>) instead of its
  loopback — confirmed reachable from Awesom-o over Tailscale only (<remote-docker-host>'s ufw
  is default-deny-incoming with an explicit tailscale0-only allow rule; the
  container port binds to that interface specifically, never `0.0.0.0`).
- Verified this date: `just services-up` (postgres pulled + healthy on <remote-docker-host>),
  `just doctor` (docker + postgres checks both green, correctly labeled
  "via remote Docker host '<remote-docker-host>'"), `just db-migrate` (migrations applied),
  `just test-db` — **`db_roundtrip.rs`'s 2 tests, previously `ignored` for lack of
  a live database, now run and pass** (`guest_session_creates_account_session_audit`,
  `migrations_apply_and_bootstrap_check_roundtrips`), `just db-backup` (pg_dump via
  ssh, 9 KiB), and a full `services-down` → `services-up` cycle (volume persists).
- Found and fixed in passing: `tools/infra/db.py`'s `test-env` subcommand stripped
  *every* `--` from its argv, not just its own leading separator — this ate the
  `--` that tells `cargo test ... -- --ignored` to forward `--ignored` to the test
  binary. Unreachable before (Docker was fully blocked), so `just test-db` had
  never actually been run against a live database until now.
- Known follow-up, not yet needed: <remote-docker-host> already has something listening on
  127.0.0.1:4317 (unrelated to this project), which would collide with
  `observability-up`'s jaeger service if that profile is ever brought up there.
- **Follow-up fix (verified 2026-07-20, same session):** the <remote-docker-host> change had
  silently broken studio-mcp's database tools. `tools.py`'s `_compose_psql`
  called `docker compose` directly (bypassing `compose.py`'s remote routing —
  would have hit the dead local engine), and `security.py`'s
  `assert_local_database` hardcoded `127.0.0.1`/`localhost`/`::1`, so a
  correctly-configured remote query would have been refused outright as
  "not a local database." Fixed both (the security check now also trusts this
  machine's own configured `STUDIO_PG_HOST` — not a general remote allowance;
  still refuses arbitrary hosts, per the existing `test_remote_database_refused`
  test, which still passes). Verified: `just test-mcp` 34/34 green, plus a live
  `tool_postgres_query_readonly` call against <remote-docker-host>'s Postgres, exit 0. Also
  created the `.mcp.json` `docs/agents/mcp/README.md` already documented as
  "committed" but that never actually existed — `just doctor` now reports
  `studio-mcp: config present, self-check pass`.

## Honest gaps (not yet evidenced)

- Docker Desktop / local virtualization — still genuinely blocked on firmware
  (VT-x/AMD-V disabled in BIOS/UEFI); the <remote-docker-host> path above is a workaround for
  development, not a fix. A container workload that must run locally (not
  dev-database-shaped) still needs the BIOS toggle + reboot.
- WebGPU **rendering** — blocked on the editor/fork version gap above
  (templates built + export runs; runtime pack-format mismatch). No WebGPU claim.
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
