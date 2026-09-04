# Studio Foundation task runner — the single front door for humans, AI agents, and CI.
# `just` (no args) lists recipes. Business logic lives in scripts/tools, never here.

set dotenv-load := true
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set shell := ["bash", "-cu"]

PY := if os() == "windows" { "python" } else { "python3" }
NPM := if os() == "windows" { "npm.cmd" } else { "npm" }
# Routes through tools/infra/compose.py, which runs Docker locally by default or,
# with STUDIO_INFRA_REMOTE set in .env, over SSH on a remote Docker host.
COMPOSE := PY + " tools/infra/compose.py"

# Overridable variables: `just NAME=my_game DISPLAY_NAME="My Game" new-game`
NAME := ""
DISPLAY_NAME := ""
GAME := "templates/godot-game"
PROFILE := "desktop_high"
DEST := ""
# bforge (ADR 0014): `just NAME=crate_a RECIPE=prop.crate bforge-make`
RECIPE := "prop.crate"
TAG := ""
SEARCH := ""
FILE := ""

default:
    @just --list

# ------------------------------------------------------------------ environment

# Report tool/platform readiness (add --json or --strict; --strict fails on missing required)
doctor *ARGS:
    {{PY}} tools/doctor/doctor.py {{ARGS}}

[windows]
bootstrap:
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1

[unix]
bootstrap:
    sh scripts/bootstrap.sh

# Enable repo guardrail hooks (pre-commit secret/large-file/generated-dir checks)
hooks-install:
    git config core.hooksPath .githooks
    @echo "hooks enabled (core.hooksPath=.githooks)"

# ------------------------------------------------------------------ local services

services-up:
    {{COMPOSE}} up -d --wait postgres

services-down:
    {{COMPOSE}} down

services-logs:
    {{COMPOSE}} logs --tail 100

# Optional Jaeger tracing UI at http://127.0.0.1:16686 (profile: observability)
observability-up:
    {{COMPOSE}} --profile observability up -d

# Optional mechanics-neutral Nakama identity and application RPC bridge.
nakama-build:
    {{NPM}} --prefix infra/nakama run build

nakama-test:
    {{NPM}} --prefix infra/nakama test
    {{PY}} -m unittest discover -s infra/nakama/tests -p "test_*.py" -v

nakama-up: nakama-build
    {{COMPOSE}} --profile nakama up -d --wait nakama

nakama-probe *ARGS:
    {{PY}} infra/nakama/live_probe.py {{ARGS}}

db-migrate:
    {{PY}} tools/cargo_env.py run --manifest-path services/Cargo.toml -p studio-admin-cli -- migrate

db-seed:
    {{PY}} tools/infra/db.py seed

# Drop and recreate the dev database volume, re-run init + migrations + seed
db-reset:
    {{PY}} tools/infra/db.py reset

db-backup:
    {{PY}} tools/infra/db.py backup

db-restore:
    {{PY}} tools/infra/db.py restore --file "{{FILE}}"

db-psql *ARGS:
    {{PY}} tools/infra/db.py psql {{ARGS}}

# ------------------------------------------------------------------ test

# Fast suite: Rust + Python + protocol + Godot headless (needs Docker only for test-db)
test: test-rust test-python test-protocol nakama-test test-godot

test-rust:
    {{PY}} tools/cargo_env.py test --manifest-path services/Cargo.toml --workspace

# Python unit tests (currently the studio-mcp suite; add top-level test_*.py under
# tools/ to grow this back into a broader discovery run)
test-python:
    uv run --project tools python -m unittest discover -s tools/studio-mcp/tests -p "test_*.py" -v
    uv run --project tools python -m unittest discover -s tools/infra/tests -p "test_*.py" -v
    {{PY}} -m unittest discover -s engine/scripts/tests -p "test_*.py" -v
    uv run --project tools python -m unittest discover -s tools/bforge/tests -p "test_schema.py" -v
    uv run --project tools python -m unittest discover -s tools/bforge/tests -p "test_mcp.py" -v
    uv run --project tools python -m unittest discover -s tools/asset-pipeline/tests -p "test_*.py" -v
    uv run --project tools python -m unittest discover -s tools/provenance/tests -p "test_*.py" -v
    uv run --project tools python -m unittest discover -s tools/verification/tests -p "test_*.py" -v
    uv run --project tools python -m unittest discover -s tools/worldc/tests -p "test_*.py" -v
    uv run --project tools python -m unittest discover -s tools/sim/tests -p "test_*.py" -v
    uv run --project tools python -m unittest discover -s tools/godot/tests -p "test_*.py" -v

# Cross-language protocol golden-fixture checks (Rust side runs in test-rust too)
test-protocol:
    uv run --project tools python tools/asset-pipeline/check_fixtures.py

test-godot:
    {{PY}} tools/godot/run_godot.py --game "{{GAME}}" --tests

# Fail a game whose main scene exceeds the budgets its render profile declares.
# PROFILE defaults to the browser, which is the tightest tier we actually ship.
budget-godot PROFILE="browser_webgpu":
    {{PY}} tools/godot/run_godot.py --game "{{GAME}}" --budget --profile "{{PROFILE}}"

# Render the game's declared QA shots through the real renderer and MEASURE
# them (exposure, palette probes, HUD on-screen/tap-size). Not headless; works
# GPU-less via ANGLE. Shots live in the game's res://tests/qa_shots.gd.
qa-godot *ARGS:
    {{PY}} tools/godot/qa_capture.py --game "{{GAME}}" {{ARGS}}

# DB-backed integration tests (requires `just services-up`)
test-db:
    {{PY}} tools/infra/db.py test-env -- {{PY}} tools/cargo_env.py test --manifest-path services/Cargo.toml -p studio-integration-tests -- --ignored

test-mcp:
    uv run --project tools python -m unittest discover -s tools/studio-mcp/tests -v

# Generate a temporary game and run its Godot + Rust suites.
test-generated:
    {{PY}} tools/build/test_generated.py

# ------------------------------------------------------------------ lint / format

lint: lint-rust lint-python lint-workflows

lint-rust:
    {{PY}} tools/cargo_env.py fmt --manifest-path services/Cargo.toml --all -- --check
    {{PY}} tools/cargo_env.py clippy --manifest-path services/Cargo.toml --workspace --all-targets -- -D warnings

lint-python:
    uv run --project tools ruff check tools infra/nakama/live_probe.py infra/nakama/tests/test_live_probe.py
    uv run --project tools ruff format --check tools infra/nakama/live_probe.py infra/nakama/tests/test_live_probe.py

lint-workflows:
    uv run --project tools python tools/ci/validate_workflows.py

fmt:
    cargo fmt --manifest-path services/Cargo.toml --all
    uv run --project tools ruff format tools infra/nakama/live_probe.py infra/nakama/tests/test_live_probe.py

# ------------------------------------------------------------------ build

build: build-rust godot-sync-addons

build-rust:
    {{PY}} tools/cargo_env.py build --manifest-path services/Cargo.toml --workspace

# Copy shared/godot-addons/* into every game project (addons/ dirs are generated)
godot-sync-addons:
    {{PY}} tools/godot/sync_addons.py

# Headless import of a game project; fails on script errors
godot-import:
    {{PY}} tools/godot/run_godot.py --game "{{GAME}}" --import-only

# ------------------------------------------------------------------ assets (Blender pipeline)

asset-validate:
    uv run --project tools python tools/asset-pipeline/pipeline.py validate "{{FILE}}"

asset-export:
    uv run --project tools python tools/asset-pipeline/pipeline.py export "{{FILE}}"

# Cook all assets of GAME for PROFILE (desktop_high|browser_webgpu|browser_webgl|mobile_high|mobile_low)
asset-cook:
    uv run --project tools python tools/asset-pipeline/pipeline.py cook --profile "{{PROFILE}}" --game "{{GAME}}"

# Cook GAME's assets and sync the pack + manifest into DEST (a consuming repo's
# asset dir, ADR 0015) instead of the game's own project tree. Example:
#   just PROFILE=browser_webgl GAME=games/asha_world DEST=../platosplaza/games/the-deep/assets asset-cook-to
asset-cook-to:
    uv run --project tools python tools/asset-pipeline/pipeline.py cook --profile "{{PROFILE}}" --game "{{GAME}}" --dest "{{DEST}}"

asset-preview:
    uv run --project tools python tools/asset-pipeline/pipeline.py preview "{{FILE}}"

asset-report:
    uv run --project tools python tools/asset-pipeline/pipeline.py report

# ------------------------------------------------------------------ bforge (agent asset authoring, ADR 0014)

# Verify the whole Blender chain: daemon, build, render, validate, export.
bforge-doctor:
    uv run --project tools python tools/bforge/bforge/cli.py doctor

# List operations. Filter with TAG=prop or SEARCH=rock.
bforge-ops:
    uv run --project tools python tools/bforge/bforge/cli.py ops --tag "{{TAG}}" --search "{{SEARCH}}"

# Recipe -> validated, collided, exported asset. Example:
#   just NAME=crate_a RECIPE=prop.crate bforge-make
bforge-make:
    uv run --project tools python tools/bforge/bforge/cli.py make "{{NAME}}" --recipe "{{RECIPE}}" --export

# Fast suites: catalog/schema + MCP protocol. No Blender needed.
bforge-test:
    uv run --project tools python -m unittest discover -s tools/bforge/tests -p "test_schema.py" -v
    uv run --project tools python -m unittest discover -s tools/bforge/tests -p "test_mcp.py" -v

# Live Blender integration suite (skips cleanly when Blender is absent).
bforge-test-live:
    uv run --project tools python -m unittest discover -s tools/bforge/tests -p "test_forge.py" -v

# Regenerate the visual review gallery + the committed op catalog.
bforge-gallery:
    uv run --project tools python tools/bforge/tests/gallery.py

bforge-catalog:
    uv run --project tools python tools/bforge/bforge/cli.py catalog --refresh --reference docs/bforge/OPS.md

# Compile a Recipe IR document (ADR 0018): content hash -> cache -> gates -> proof capsule.
#   just RECIPE=tools/bforge/examples/recipes/crate.json bforge-cook
bforge-cook:
    uv run --project tools python tools/bforge/bforge/cli.py cook "{{RECIPE}}"

# Compile a World IR entity (spec: docs/specs/world-ir-v0.1.md) to a proof-carrying package.
#   just ENTITY=tools/worldc/examples/fortress_gate.json worldc-compile
worldc-compile:
    uv run --project tools python tools/worldc/worldc.py compile "{{ENTITY}}"

# Compile a whole world (entities + deterministic scenario) to a world proof capsule.
#   just WORLD=tools/worldc/examples/fortress_world.json worldc-world
worldc-world:
    uv run --project tools python tools/worldc/worldc.py compile-world "{{WORLD}}"

# Run a deterministic replay (spec: docs/specs/sim-replay-v0.1.md); exits non-zero on golden mismatch.
#   just REPLAY=tools/sim/replays/gate_open_destroy.json sim-replay
sim-replay:
    uv run --project tools python tools/sim/kernel.py replay "{{REPLAY}}"

# Native + Wasm parity for the sim kernel (needs cargo + wasm32 target; skips without)
sim-parity:
    uv run --project tools python -m unittest discover -s tools/sim/tests -p "test_parity.py" -v

# The frozen public benchmark (ADR 0018 M4): reference agent against the frozen
# brief set, SUMMARY.md regenerated (CI diffs it).
briefbench:
    uv run --project tools python benchmarks/brief-to-asset/bench.py --summary --agent "python3 benchmarks/brief-to-asset/agents/scripted_recipe.py"

# The world-level benchmark (ADR 0018 M4): reference agent against the frozen
# battle brief, SUMMARY.md regenerated (CI diffs it).
battlebench:
    uv run --project tools python benchmarks/brief-to-battle/bench.py --summary --agent "python3 benchmarks/brief-to-battle/agents/scripted_world.py"

# Compile the fortress world + wasm kernel, write the viewer config, serve
# the repo at :8077 — open http://localhost:8077/tools/sim-viewer/
sim-viewer:
    uv run --project tools python tools/worldc/worldc.py compile-world tools/worldc/examples/fortress_world.json
    cd services && cargo build -p sim-kernel --release --target wasm32-unknown-unknown
    uv run --project tools python tools/sim-viewer/serve_config.py
    uv run --project tools python -m http.server 8077

# The engine-neutral presentation contract (ADR 0020), with no engine installed.
# This is the suite that fails first when the contract itself is wrong.
runtime-contract:
    node tests/runtime/scene_binding_test.mjs

# Cross-engine conformance: the same kernel replay drives three.js, Babylon and
# PlayCanvas, and all three must place every joint identically. Headless, no GPU.
runtime-conformance:
    cd tests/runtime && {{NPM}} ci
    node tests/runtime/cross_engine.mjs

# The host-independence gate (ADR 0019): the kernel must import nothing, so any
# runtime -- including a Godot web export that already owns the main-module slot
# -- can instantiate it. Build the wasm first (`just sim-parity`).
sim-host-abi:
    uv run --project tools python tools/sim/host_abi.py services/target/wasm32-unknown-unknown/release/sim_kernel.wasm

# The fourth parity host: replay the conformance corpus through a REAL browser,
# via the same host script a Godot web export injects. Needs Chrome/Edge.
sim-browser-host:
    cd tests/browser && {{NPM}} ci
    node tests/browser/sim-kernel-host.mjs

# The renderer-observes-only adapter test (node, no DOM, no GPU)
sim-viewer-test:
    node tools/sim-viewer/adapter_test.mjs services/target/wasm32-unknown-unknown/release/sim_kernel.wasm tools/worldc/examples/fortress_battle.json tools/worldc/examples/fortress_gate.json

# ------------------------------------------------------------------ exports

# WebGL2 Compatibility export — works with official installed templates
export-browser-webgl:
    {{PY}} tools/godot/export_game.py --game "{{GAME}}" --preset web-webgl

# WebGPU export — requires patched templates built via `just engine-build`
export-browser-webgpu:
    {{PY}} tools/godot/export_game.py --game "{{GAME}}" --preset web-webgpu

export-android:
    {{PY}} tools/godot/export_game.py --game "{{GAME}}" --preset android

export-ios:
    {{PY}} tools/godot/export_game.py --game "{{GAME}}" --preset ios

# Serve the latest web export at http://127.0.0.1:8060 with COOP/COEP headers
serve-web:
    {{PY}} tools/godot/serve_web.py --game "{{GAME}}"

# Playwright smoke: open web export(s) in installed Chrome/Edge, fail on fatal console errors
run-browser-smoke *ARGS:
    {{PY}} tools/godot/run_browser_smoke.py {{ARGS}}

# Godot headless client -> control-api -> PostgreSQL round trip (needs services-up)
demo-connectivity:
    {{PY}} tools/godot/demo_connectivity.py --game "{{GAME}}"

# ------------------------------------------------------------------ screenshots / visual regression

# Headless scene capture to PNG (SCENE is a res:// path; SIZE like 1280x720).
# Only works with a real renderer attached — headless dummy renderer cannot rasterize.
capture-scene SCENE SIZE="1280x720":
    {{PY}} tools/screenshots/capture_scene.py --game "{{GAME}}" --scene "{{SCENE}}" --size "{{SIZE}}"

# Real-GPU web screenshot via Playwright + system Chrome (works on CI agents)
capture-web *ARGS:
    {{PY}} tools/screenshots/capture_web.py {{ARGS}}

# Visual regression gate: compare candidate PNG against a baseline (tolerant)
compare-screenshots BASELINE CANDIDATE *ARGS:
    {{PY}} tools/screenshots/compare_screenshots.py "{{BASELINE}}" "{{CANDIDATE}}" {{ARGS}}

# ------------------------------------------------------------------ engine

engine-test:
    {{PY}} -m unittest discover -s engine/scripts/tests -p "test_*.py" -v

engine-versions:
    {{PY}} engine/scripts/engine.py versions

# Verify the WebGPU patch series against engine-lock.toml (checksums, ordering,
# nothing unlocked). Stdlib only — no Godot, Emscripten, or GPU required.
engine-verify-patches:
    {{PY}} engine/scripts/verify_patch_series.py

# Fetch pinned official Godot and apply the verified local patch series
engine-fetch:
    {{PY}} engine/scripts/engine.py fetch

# Build templates from the pin or --workspace candidate (long; requires scons+emsdk)
# Runs under the tools venv: engine.py shells out to `sys.executable -m SCons`, and
# SCons lives only in the tools venv, not the system Python that {{PY}} resolves to.
engine-build *ARGS:
    uv run --project tools python engine/scripts/engine.py build {{ARGS}}

# Accept a complete release/debug pair into engine-lock.toml after validation
engine-record-artifacts:
    {{PY}} engine/scripts/engine.py record-artifacts

# Test the patch series on another official ref (see godot-webgpu-update runbook)
engine-rebase *ARGS:
    {{PY}} engine/scripts/engine.py rebase {{ARGS}}

# Classify patch-application conflicts for manual review
engine-classify-conflicts *ARGS:
    {{PY}} engine/scripts/classify_conflicts.py {{ARGS}}

# Answer "does this build render?" end to end and write down the answer.
# Exports, serves, probes, traces bind-group and command-buffer validity, and
# emits ONE evidence file so a result from another machine is directly
# comparable to the published one. Exit: 0 rendered, 1 not, 2 inconclusive,
# 3 preconditions missing.
verify-renderer *ARGS:
    {{PY}} tools/verification/verify_renderer.py {{ARGS}}

# Regenerate the renderer-status table in the docs from render-probe results.
# PROBE is a directory of tests/browser/render-probe.mjs JSON output.
renderer-report PROBE OUT="docs/architecture/webgpu-runtime-status.md":
    {{PY}} tools/verification/render_report.py --probe "{{PROBE}}" --out "{{OUT}}"

# Fail if the published renderer status disagrees with the measurements
renderer-report-check PROBE OUT="docs/architecture/webgpu-runtime-status.md":
    {{PY}} tools/verification/render_report.py --probe "{{PROBE}}" --out "{{OUT}}" --check

# ------------------------------------------------------------------ provenance

# Print this repository's WebGPU patch-series id. Reproducible from any clone.
provenance-id:
    {{PY}} tools/provenance/provenance.py id

# Write provenance.json beside built templates (or any DEST)
provenance-stamp DEST="engine/artifacts/templates":
    {{PY}} tools/provenance/provenance.py stamp --dest "{{DEST}}"

# Identify the lineage of ANY Godot web build -- ours or a third party's.
# Reports whether it descends from this patch series and, if so, prints the
# MIT attribution that build is required to carry.
provenance-verify PATH *ARGS:
    {{PY}} tools/provenance/provenance.py verify "{{PATH}}" {{ARGS}}

# Print the attribution text a downstream build must include
provenance-attribution *ARGS:
    {{PY}} tools/provenance/provenance.py attribution {{ARGS}}

# Re-derive marker candidates from a real build vs stock Godot, and fail if any
# shipped marker has drifted out of the engine. Run when the patch series grows.
provenance-calibrate OURS CONTROL:
    {{PY}} tools/provenance/provenance.py calibrate --ours "{{OURS}}" --control "{{CONTROL}}"

# ADR 0002 gate: WebGPU export -> browser capture -> compare vs WebGL baseline.
# Cross-renderer compare uses a renderer-variance band (0.03) for AA/font/layout
# deltas between WebGPU and WebGL; same-renderer regression uses the strict
# default (0.001). Band scales with on-screen text/content.
engine-validate GAME="templates/godot-game":
    {{PY}} tools/godot/export_game.py --game "{{GAME}}" --preset web-webgpu
    {{PY}} tools/screenshots/capture_web.py --game "{{GAME}}" --preset web-webgpu --out captures/web-webgpu.png --wait 8000
    {{PY}} tools/screenshots/compare_screenshots.py "{{GAME}}/project/captures/web-webgl.png" "{{GAME}}/project/captures/web-webgpu.png" --max-diff-ratio 0.03

# ------------------------------------------------------------------ game generator

# Usage: `just NAME=my_game DISPLAY_NAME="My Game" new-game`
new-game:
    {{PY}} tools/build/new_game.py --name "{{NAME}}" --display-name "{{DISPLAY_NAME}}"

# ------------------------------------------------------------------ agents / MCP

# Run studio-mcp on stdio (this is what agent MCP configs invoke)
mcp-serve:
    uv run --project tools python tools/studio-mcp/server.py

# ------------------------------------------------------------------ quality gates

# Same checks CI runs on PRs, locally
ci-local:
    {{PY}} scripts/ci/run_all.py --stage pr

secret-scan:
    uv run --project tools python tools/ci/secret_scan.py

# Fail when prose (README counts, public claims) drifts from the pinned artifacts
check-claims:
    uv run --project tools python tools/ci/check_claims.py

sbom:
    {{PY}} tools/release/make_sbom.py

audit:
    {{PY}} tools/release/audit_deps.py

attribution:
    uv run --project tools python tools/release/attribution.py

release-validate *ARGS:
    {{PY}} tools/release/release_validate.py {{ARGS}}

# ------------------------------------------------------------------ benchmarks / visual

benchmark-scene:
    {{PY}} tools/benchmark/run_benchmark.py --game "{{GAME}}"

visual-baseline:
    {{PY}} tools/screenshots/visual_regression.py baseline --game "{{GAME}}"

visual-compare:
    {{PY}} tools/screenshots/visual_regression.py compare --game "{{GAME}}"

# ------------------------------------------------------------------ housekeeping

clean *ARGS:
    {{PY}} tools/build/clean.py {{ARGS}}
