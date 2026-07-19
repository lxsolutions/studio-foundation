-- Runs once on first container start (docker-entrypoint-initdb.d).
-- Provisions least-privilege roles. Actual tables come from versioned migrations
-- (services/control-api/migrations), never from init scripts.

-- Application role used by services (dev password matches .env.example default).
DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'studio_app') THEN
      CREATE ROLE studio_app LOGIN PASSWORD 'studio_dev_password';
   END IF;
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'studio_ro') THEN
      CREATE ROLE studio_ro LOGIN PASSWORD 'studio_dev_readonly';
   END IF;
END
$$;

-- Shared platform schema (owned by the main dev user; migrations manage contents).
CREATE SCHEMA IF NOT EXISTS platform;

GRANT USAGE, CREATE ON SCHEMA platform TO studio_app;
GRANT USAGE ON SCHEMA platform TO studio_ro;

-- Read-only role: future tables in platform become SELECT-able automatically.
ALTER DEFAULT PRIVILEGES IN SCHEMA platform GRANT SELECT ON TABLES TO studio_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA platform GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO studio_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA platform GRANT USAGE, SELECT ON SEQUENCES TO studio_app;

-- Per-game schemas (game_<id>) are created by each game's own migrations.
