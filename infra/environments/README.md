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
