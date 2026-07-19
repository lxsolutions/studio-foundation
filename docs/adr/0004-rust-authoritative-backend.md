# ADR 0004: Rust authoritative backend foundation

- Status: Accepted
- Date: 2026-07-19

## Context

MMO/combined-arms games need server-authoritative simulation, long-lived processes,
predictable latency, and memory safety. The team is small; the backend must be one
workspace, not microservices (GOAL.md principle 15).

## Decision

A single Cargo workspace in `services/` with crates:

| Crate | Role |
|---|---|
| `shared-protocol` | Wire types, envelope/versioning, golden-fixture tests shared with GDScript |
| `control-api` | Axum HTTP API: health, status, accounts/session stubs, PG read/write proof |
| `dedicated-server` | Real-time server: transport abstraction (WebSocket baseline), session loop |
| `admin-cli` | Operator commands: migrate, seed, health, kv |
| `integration-tests` | Client↔server loopback + DB integration tests |

Foundations: **Tokio, Axum, Serde, SQLx (checked migrations), Tracing, thiserror,
clap**. OpenTelemetry export is structured-in (tracing spans + JSON logs) but the OTLP
exporter is added only when the observability profile is exercised (principle 15).

### Toolchain constraint (Windows dev machines)

Pinned Rust `1.97.1`. On Windows we standardize on **`x86_64-pc-windows-gnu`**
(rustup's self-contained MinGW linker) so contributors and agents don't need MSVC
Build Tools. Consequence: **the default workspace must stay pure-Rust** — no crates
that compile C (`ring`, `openssl`, `aws-lc`, `zstd-sys`…). Therefore:

- SQLx runs **without TLS features**; dev/test Postgres is localhost-only plaintext.
  Production TLS terminates in front of the service (documented in
  `docs/security/`), or an opt-in `tls` feature (rustls) can be enabled on hosts
  with a C toolchain.
- WebSocket transport uses `tokio-tungstenite` without TLS features (same rationale).

CI additionally builds on Linux (gnu, the deployment target), which keeps us honest.

## Consequences

- One `cargo test` covers the whole backend; no service mesh, no queues, no Redis.
- Per-game servers are new binaries in the same workspace (or a game repo workspace
  that depends on these crates by version), reusing `shared-protocol` + transport.
- `sqlx::migrate!` embeds versioned migrations at compile time; runtime DB access uses
  runtime-checked queries so the workspace builds offline without a live database.

## Revisit when

- A profiled bottleneck demands specialized infrastructure (then: ADR with evidence), or
- MSVC becomes available fleet-wide and a C-dependent crate is genuinely needed.
