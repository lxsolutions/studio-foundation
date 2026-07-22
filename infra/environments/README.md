# Environment configuration model

Four environments, one rule: **configuration comes from environment variables; secrets
never enter this repository** (only `*.example` files are committed).

| Environment | Source of config | Notes |
|---|---|---|
| development | `.env` (copied from `.env.example`) | Localhost-only defaults; Docker Compose services bound to 127.0.0.1 |
| test | `test.env.example` → CI job env | Throwaway DB container per run; ports shifted to avoid collisions |
| staging | Deploy-time secret store (host env / systemd env file) | Never in repo. Same variable names as development |
| production | Deploy-time secret store | Never in repo. TLS terminates in front of services (ADR 0004) |

Variable names are identical across environments — promotion is a values change, not a
code change. `just doctor` validates the development set; services fail fast on
missing/invalid values at boot (see `services/*/src/config.rs`).

Development's Docker Compose stack (`infra/compose.yaml`) defaults to the local
Docker engine, loopback-bound. If the local machine can't run Docker itself (e.g.
no virtualization support) but a Docker host is reachable over SSH, set
`STUDIO_INFRA_REMOTE` (+ `STUDIO_PG_BIND_HOST`/`STUDIO_PG_HOST`) in `.env` — see
the commented example there — to run it on that host instead. This is still a
development-only config knob: it changes *where* the loopback-equivalent binding
lives (that host's own private/Tailscale interface, never `0.0.0.0`), not the
one-rule-above-the-line that secrets/config stay out of the repo.
The remote wrapper syncs the committed Nakama runtime bundle and local config with
the Postgres bootstrap files. When enabling that profile remotely, also set
`STUDIO_NAKAMA_BIND_HOST` to the host's private mesh address.
