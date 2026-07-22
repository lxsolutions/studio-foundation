# Dependency and license inventory

Policy: ADR 0013. Permissive licenses (MIT/Apache-2.0/BSD/ISC/Zlib/PostgreSQL) are
pre-approved. GPL/AGPL requires an ADR documenting isolation. Every new dependency PR
must add a row here (purpose, license, maintenance health, alternatives considered).
Exact resolved versions live in the lockfiles (`Cargo.lock`, `uv.lock`,
`engine-lock.toml`); this table records the pin *policy* and license review.

## Engine and content tools (external, not vendored)

| Component | Pin | License | Role | Notes |
|---|---|---|---|---|
| Godot Engine | 4.7.1-stable `a13da4feb…` | MIT | Primary engine | ADR 0001 |
| Asha WebGPU backend (our fork `lxsolutions/godot-webgpu`, vendored from `dwalter/godotwebgpu`) | `webgpu-4.7.1` line (base 4.7.1; upstream tip `f329e39ce…`) | MIT | Browser WebGPU export backend | ADR 0002; beta; AI-generated; see NOTICE.md |
| Godot export templates (web) | 4.7.1.stable official | MIT | WebGL2 browser export | installed via editor |
| Blender | 5.2.0 LTS | GPL-2.0-or-later | Master asset tool (standalone process only) | ADR 0006 isolation note |
| Emscripten | 4.0.11 | MIT/UIUC | Web engine builds | pinned from fork CI |
| SCons | 4.9.1 | MIT | Godot build system | via uv-managed venv |

## Developer toolchain

| Component | Pin | License | Role |
|---|---|---|---|
| Rust toolchain | 1.97.1 (windows: gnu host) | MIT OR Apache-2.0 | Backend services |
| just | 1.57.0 | CC0-1.0 | Task runner |
| uv | ≥0.8 | MIT OR Apache-2.0 | Python env manager |
| Python | 3.11 | PSF-2.0 | Tooling/pipeline scripts |
| Node.js | 22 LTS | MIT | Nakama runtime build/test and browser test harness |
| TypeScript | 6.x (npm lockfile) | Apache-2.0 | Build the Nakama JavaScript runtime module |
| Docker Engine/Compose | any current | Apache-2.0 | Local infrastructure |
| Git | ≥2.40 | GPL-2.0 (tool) | VCS (standalone tool) |

## Rust workspace (services/) — direct dependencies

Pure-Rust policy (no C compilation) per ADR 0004. All verified permissive:

| Crate | License | Purpose |
|---|---|---|
| tokio | MIT | Async runtime |
| axum | MIT | HTTP API framework |
| hyper/tower (via axum) | MIT | HTTP stack |
| serde, serde_json | MIT OR Apache-2.0 | Serialization |
| sqlx (postgres, no TLS) | MIT OR Apache-2.0 | DB access + checked migrations |
| tracing, tracing-subscriber | MIT | Structured logging/instrumentation |
| thiserror, anyhow | MIT OR Apache-2.0 | Error handling |
| clap | MIT OR Apache-2.0 | CLI parsing |
| tokio-tungstenite (no TLS) | MIT | WebSocket transport |
| uuid (v7) | MIT OR Apache-2.0 | Identifiers |
| rand | MIT OR Apache-2.0 | Seeds/nonces (non-crypto uses documented) |

Full transitive audit: `just sbom` (cargo-sbom/cargo-license output under
`build/sbom/`), `just audit` (cargo-audit RustSec).

## Python tooling (tools/) — direct dependencies

| Package | License | Purpose |
|---|---|---|
| (stdlib only for studio-mcp and hooks) | PSF | Auditable, offline-safe |
| PyYAML (dev) | MIT | CI workflow YAML validation |
| scons (engine builds) | MIT | Godot compilation |

## Local infrastructure images

| Image | Pin | License | Profile |
|---|---|---|---|
| postgres | 17-alpine | PostgreSQL License | default |
| jaegertracing/jaeger | 2.x | Apache-2.0 | `observability` (optional) |
| registry.heroiclabs.com/heroiclabs/nakama | 3.22.0 | Apache-2.0 | `nakama` (optional identity/social/matchmaking authority); active upstream, self-hostable; custom auth/match services rejected as premature duplication |
| (object storage) | — | — | **Not included.** MinIO moved to AGPL + feature-gutted community builds; if a demonstrated need arises, SeaweedFS (Apache-2.0) is the reviewed candidate — see ADR 0013. |

## Browser testing

| Component | Pin | License | Notes |
|---|---|---|---|
| Playwright (npm, no bundled browsers) | 1.x pinned in tests/browser/package.json | Apache-2.0 | Drives installed Chrome/Edge via `channel`; Firefox download optional |

## Explicitly rejected (with reasons)

- **MinIO** — AGPL relicense + community build feature removal (2025); replaced by "no
  object storage until needed".
- **Grafana** — AGPL; Jaeger (Apache-2.0) covers dev tracing needs today.
- **ring / openssl-based crates** — C toolchain requirement conflicts with windows-gnu
  policy (ADR 0004).
