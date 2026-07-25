-- Game-owned schema (ADR 0005): this game's server owns game_chariot
-- and nothing else. Platform data stays in the platform schema, accessed
-- through the control API — never by direct cross-schema writes.

CREATE SCHEMA IF NOT EXISTS game_chariot;

-- Example of a game-owned table shape; replace with real game state tables.
CREATE TABLE game_chariot.world_flag (
    k          text PRIMARY KEY,
    v          jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
