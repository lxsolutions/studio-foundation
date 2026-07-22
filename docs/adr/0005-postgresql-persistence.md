# ADR 0005: PostgreSQL as the source of truth

- Status: Accepted
- Date: 2026-07-19

## Context

Accounts, identities, entitlements, characters, progression, inventory, match history,
persistent world data, and audit records need a durable, transactional, self-hostable
store with a permissive-enough license.

## Decision

**PostgreSQL** (PostgreSQL License, permissive), pinned image `postgres:17-alpine` in
`infra/compose.yaml` for development; any Postgres ≥ 15 self-hosted or managed for
production. No ORM — SQLx with SQL migrations.

### Schema ownership model (no universal schema)

- `platform` schema — shared identity/platform data only: accounts, sessions,
  entitlements, audit. Owned by `control-api`, migrations in
  `services/control-api/migrations/`.
- `game_<id>` schema per game — owned by that game's server crate, migrations in the
  game's own `server/migrations/` namespace (created by the new-game generator).
  Cross-schema access goes through `platform` views/functions, never direct table
  writes from another owner.
- Migrations are versioned, forward-only files (`NNNN_description.sql`); naming is
  enforced by the pre-commit hook. Never edit an applied migration — add a new one.
- Each owner keeps its SQLx history in its own schema (`platform._sqlx_migrations`,
  `game_<id>._sqlx_migrations`). A game runner creates its schema, sets that schema
  as the migration connection's exclusive `search_path`, then runs its embedded
  migrator. Unrelated owners may therefore each have a `0001` without collision.
- Dev seed data: `infra/postgres/seed.sql` via `just db-seed`; reset via `just
  db-reset`; logical backup/restore via `just db-backup` / `just db-restore`.

### Access rules

- Services connect with least-privilege roles (`infra/postgres/init/` provisions
  `studio_app`, read-only `studio_ro`).
- Tooling/MCP may query **read-only, dev/test databases only** (ADR 0009).
- Kubernetes/HA/replication: out of scope until a demonstrated requirement (ADR 15
  principle); backups are `pg_dump`-based at this stage.

## Consequences

- Every stateful feature has exactly one owner and one migration path; game data can
  be dumped/restored per schema.
- Local + CI databases are throwaway containers; production is any vanilla Postgres —
  no proprietary cloud dependency.
