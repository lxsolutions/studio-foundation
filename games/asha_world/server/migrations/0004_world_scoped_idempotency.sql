-- Idempotency belongs to one world. Keep UUID keys reusable across isolated
-- test worlds and future shards while preserving uniqueness within each world.
-- This follows 0003 rather than editing an already-applied migration.

ALTER TABLE game_asha_world.world_event_ledger
    DROP CONSTRAINT world_event_ledger_pkey;

ALTER TABLE game_asha_world.world_event_ledger
    ADD PRIMARY KEY (world_id, idempotency_key);
