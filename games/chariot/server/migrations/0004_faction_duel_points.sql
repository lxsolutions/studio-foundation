-- Ghost-duel faction points ("beat my lap" settles): one row per scored duel.
-- The result is always derived server-side from the two stored ghost runs
-- (migration 0003): the lower total_ms wins, a dead heat scores nobody, and a
-- duel the server cannot verify — either run missing — is refused outright.
-- The ledger only holds what the server can prove. UNIQUE (ghost_id, run_id)
-- makes a resent record idempotent, and the public ids are stored as text, the
-- same shape the client speaks. The season tally sums this table together
-- with faction_race_point (application.rs standings).

CREATE TABLE game_chariot.faction_duel_point (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    season      text NOT NULL,
    ghost_id    text NOT NULL,
    run_id      text NOT NULL,
    faction     text NOT NULL CHECK (faction IN ('blue', 'green', 'red', 'white')),
    points      integer NOT NULL CHECK (points >= 0),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ghost_id, run_id)
);

CREATE INDEX faction_duel_point_season ON game_chariot.faction_duel_point (season);
