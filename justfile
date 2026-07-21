# Studio Foundation task runner — the single front door for humans, AI agents, and CI.
# `just` (no args) lists recipes. Business logic lives in scripts/tools, never here.

set dotenv-load := true
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set shell := ["bash", "-cu"]

PY := if os() == "windows" { "python" } else { "python3" }
# Routes through tools/infra/compose.py, which runs Docker locally by default or,
# with STUDIO_INFRA_REMOTE set in .env, over SSH on a remote Docker host.
COMPOSE := PY + " tools/infra/compose.py"

# Overridable variables: `just new-game NAME=my_game DISPLAY_NAME="My Game"`
NAME := ""
DISPLAY_NAME := ""
GAME := "templates/godot-game"
PROFILE := "desktop_high"
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
test: test-rust test-python test-protocol test-godot

test-rust:
    {{PY}} tools/cargo_env.py test --manifest-path services/Cargo.toml --workspace

# Python unit tests (currently the studio-mcp suite; add top-level test_*.py under
# tools/ to grow this back into a broader discovery run)
test-python:
    uv run --project tools python -m unittest discover -s tools/studio-mcp/tests -p "test_*.py" -v

# Cross-language protocol golden-fixture checks (Rust side runs in test-rust too)
test-protocol:
    uv run --project tools python tools/asset-pipeline/check_fixtures.py

test-godot:
    {{PY}} tools/godot/run_godot.py --game "{{GAME}}" --tests

# DB-backed integration tests (requires `just services-up`)
test-db:
    {{PY}} tools/infra/db.py test-env -- cargo test --manifest-path services/Cargo.toml -p studio-integration-tests -- --ignored

test-mcp:
    uv run --project tools python -m unittest discover -s tools/studio-mcp/tests -v

# Run the generated example game's own test suite (games/sandbox)
test-generated:
    {{PY}} tools/godot/run_godot.py --game games/sandbox --tests
    {{PY}} tools/cargo_env.py test --manifest-path games/sandbox/server/Cargo.toml

# ------------------------------------------------------------------ lint / format

lint: lint-rust lint-python lint-workflows

lint-rust:
    {{PY}} tools/cargo_env.py fmt --manifest-path services/Cargo.toml --all -- --check
    {{PY}} tools/cargo_env.py clippy --manifest-path services/Cargo.toml --workspace --all-targets -- -D warnings

lint-python:
    uv run --project tools ruff check tools
    uv run --project tools ruff format --check tools

lint-workflows:
    uv run --project tools python tools/ci/validate_workflows.py

fmt:
    cargo fmt --manifest-path services/Cargo.toml --all
    uv run --project tools ruff format tools

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

asset-preview:
    uv run --project tools python tools/asset-pipeline/pipeline.py preview "{{FILE}}"

asset-report:
    uv run --project tools python tools/asset-pipeline/pipeline.py report

# ------------------------------------------------------------------ exports

# WebGL2 Compatibility export — works with official installed templates
export-browser-webgl:
    {{PY}} tools/godot/export_game.py --game "{{GAME}}" --preset web-webgl

# WebGPU export — requires fork templates built via `just engine-build`
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

engine-versions:
    {{PY}} engine/scripts/engine.py versions

# Fetch pinned official+fork sources into engine/.cache and apply patch series
engine-fetch:
    {{PY}} engine/scripts/engine.py fetch

# Build editor/export templates from pinned sources (long; requires scons+emsdk)
engine-build *ARGS:
    {{PY}} engine/scripts/engine.py build {{ARGS}}

# Start a rebase workspace for updating the fork pin (see runbook godot-fork-rebase)
engine-rebase:
    {{PY}} engine/scripts/engine.py rebase

# Triage fork merge conflicts (mechanical/base-lag/fork-touched); --apply-safe resolves safe ones
engine-classify-conflicts *ARGS:
    {{PY}} engine/scripts/classify_conflicts.py {{ARGS}}

# ADR 0002 gate: WebGPU export -> browser capture -> compare vs WebGL baseline.
# Cross-renderer compare uses a renderer-variance band (0.03) for AA/font/layout
# deltas between WebGPU and WebGL; same-renderer regression uses the strict
# default (0.001). Band scales with on-screen text/content.
engine-validate GAME="templates/godot-game":
    {{PY}} tools/godot/export_game.py --game "{{GAME}}" --preset web-webgpu
    {{PY}} tools/screenshots/capture_web.py --game "{{GAME}}" --preset web-webgpu --out captures/web-webgpu.png --wait 8000
    {{PY}} tools/screenshots/compare_screenshots.py "{{GAME}}/project/captures/web-webgl.png" "{{GAME}}/project/captures/web-webgpu.png" --max-diff-ratio 0.03

# ------------------------------------------------------------------ game generator

# Usage: just new-game NAME=my_game DISPLAY_NAME="My Game"
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

sbom:
    {{PY}} tools/release/make_sbom.py

audit:
    {{PY}} tools/release/audit_deps.py

attribution:
    uv run --project tools python tools/release/attribution.py

# ------------------------------------------------------------------ benchmarks / visual

benchmark-scene:
    {{PY}} tools/benchmark/run_benchmark.py --game "{{GAME}}"

visual-baseline:
    {{PY}} tools/screenshots/visual_regression.py baseline --game "{{GAME}}"

visual-compare:
    {{PY}} tools/screenshots/visual_regression.py compare --game "{{GAME}}"

# ------------------------------------------------------------------ housekeeping

clean:
    {{PY}} tools/build/clean.py
