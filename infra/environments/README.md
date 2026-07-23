# Environment configuration model

Four environments, one rule: **configuration comes from environment variables;
secrets never enter this repository**. Only `*.example` files are committed.

| Environment | Source of config | Notes |
|---|---|---|
| development | `.env` copied from `.env.example` | Localhost-only defaults; Docker Compose services bind to 127.0.0.1 |
| test | `test.env.example` or CI job environment | Throwaway database container per run |
| staging | Deploy-time secret store | Never in this repository |
| production | Deploy-time secret store | Never in this repository; TLS terminates in front of services |

Variable names stay consistent across environments. Promotion changes values,
not source code. `just doctor` validates the development toolchain; services
fail fast on missing or invalid configuration.

The optional development stack in `infra/compose.yaml` uses the local Docker
engine by default. If Docker runs on another host reachable over SSH, set
`STUDIO_INFRA_REMOTE`, `STUDIO_PG_BIND_HOST`, and `STUDIO_PG_HOST` in
`.env`. Bind remote development services to a private interface, never
`0.0.0.0`.

The remote wrapper copies the generic Compose/PostgreSQL files and the compiled
mechanics-neutral Nakama bridge. When enabling Nakama remotely, also set
`STUDIO_NAKAMA_BIND_HOST` to the host's private address. A consuming
deployment owns its backend URL, token, TLS, network policy, and secret
rotation.
