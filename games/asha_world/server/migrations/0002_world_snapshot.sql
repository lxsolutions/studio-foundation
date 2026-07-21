-- Authoritative world snapshot (ADR 0005 + ADR 0007). The world-sim is a
-- deterministic in-memory core; its serialized WorldState is persisted here so
-- the one shared world survives server restarts. Single-row-per-world design:
-- the sim snapshots after settlement and the server upserts.

CREATE TABLE IF NOT EXISTS game_asha_world.world_snapshot (
    world_id     text PRIMARY KEY,          -- e.g. 'default' (one world per server)
    state        jsonb NOT NULL,            -- WorldSim::snapshot() payload
    version      bigint NOT NULL DEFAULT 1, -- optimistic concurrency / replay ordering
    updated_at   timestamptz NOT NULL DEFAULT now()
);
