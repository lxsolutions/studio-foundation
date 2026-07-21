-- Game-owned schema (ADR 0005): this game's server owns game_asha_world
-- and nothing else. Platform data stays in the platform schema, accessed
-- through the control API — never by direct cross-schema writes.

CREATE SCHEMA IF NOT EXISTS game_asha_world;

-- Example of a game-owned table shape; replace with real game state tables.
CREATE TABLE game_asha_world.world_flag (
    k          text PRIMARY KEY,
    v          jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
