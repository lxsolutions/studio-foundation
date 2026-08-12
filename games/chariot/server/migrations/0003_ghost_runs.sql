-- Ghost time-trial runs ("beat my lap"): one row per stored run. The tick
-- stream lives in the payload; total_ms is projected out so bounds checks
-- and future leaderboards never unpack JSON. The server stores and returns
-- runs verbatim — validation is the shape bounds in src/ghosts.rs, applied
-- before a row is ever written.

CREATE TABLE game_chariot.ghost_runs (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_key  text NOT NULL,
    faction     text NOT NULL CHECK (faction IN ('blue', 'green', 'red', 'white')),
    handle      text NOT NULL CHECK (char_length(handle) BETWEEN 1 AND 24),
    total_ms    integer NOT NULL CHECK (total_ms BETWEEN 30000 AND 1200000),
    payload     jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ghost_runs_faction ON game_chariot.ghost_runs (faction);
