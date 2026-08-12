-- The four circus factions (ADR 0005: game-owned schema). Membership is one
-- row per stable/member key; race points append one row per scoring finisher.
-- The season tally is a SUM over faction_race_point — no derived tables.

CREATE TABLE game_chariot.faction_membership (
    member_key  text PRIMARY KEY,
    faction     text NOT NULL CHECK (faction IN ('blue', 'green', 'red', 'white')),
    joined_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE game_chariot.faction_race_point (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    season      text NOT NULL,
    race_id     text NOT NULL,
    faction     text NOT NULL CHECK (faction IN ('blue', 'green', 'red', 'white')),
    place       integer NOT NULL CHECK (place >= 1),
    points      integer NOT NULL CHECK (points >= 0),
    recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX faction_race_point_season ON game_chariot.faction_race_point (season);
