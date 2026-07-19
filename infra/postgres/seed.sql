-- Development seed data. Idempotent. Applied by `just db-seed` AFTER migrations.
-- Never referenced by tests that must pass on an empty database.

INSERT INTO platform.account (id, display_name)
VALUES
  ('00000000-0000-0000-0000-000000000001', 'dev_admin'),
  ('00000000-0000-0000-0000-000000000002', 'dev_player_one'),
  ('00000000-0000-0000-0000-000000000003', 'dev_player_two')
ON CONFLICT (id) DO NOTHING;

INSERT INTO platform.kv_demo (k, v)
VALUES ('seeded', '{"by": "infra/postgres/seed.sql"}')
ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v, updated_at = now();
