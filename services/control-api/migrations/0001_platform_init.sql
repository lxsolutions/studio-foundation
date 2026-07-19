-- Platform schema: shared identity/platform data ONLY (ADR 0005).
-- Game data lives in game_<id> schemas owned by each game's server migrations.
-- Must succeed on a completely empty database (CI runs it that way).

CREATE SCHEMA IF NOT EXISTS platform;

CREATE TABLE platform.account (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name text NOT NULL UNIQUE,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Bootstrap read/write proof table (kept: useful as a permanent smoke probe).
CREATE TABLE platform.kv_demo (
    k          text PRIMARY KEY,
    v          jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE platform.audit_log (
    id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at     timestamptz NOT NULL DEFAULT now(),
    actor  text  NOT NULL,
    action text  NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb
);
