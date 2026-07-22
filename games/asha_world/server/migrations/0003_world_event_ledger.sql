-- Durable canonical-event ledger (ADR 0005 + ADR 0007).
--
-- The snapshot is the fast recovery image; this append-only ledger is the
-- traceable history and database-level idempotency authority. A settlement
-- transaction writes the ledger row and updated snapshot atomically.

CREATE TABLE IF NOT EXISTS game_asha_world.world_event_ledger (
    idempotency_key uuid PRIMARY KEY,
    world_id       text NOT NULL
                   REFERENCES game_asha_world.world_snapshot(world_id)
                   ON DELETE CASCADE,
    actor_user_id  text NOT NULL CHECK (length(actor_user_id) BETWEEN 1 AND 256),
    event_type     text NOT NULL CHECK (length(event_type) BETWEEN 1 AND 64),
    event          jsonb NOT NULL,
    applied        boolean NOT NULL,
    summary        text NOT NULL,
    settled_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS world_event_ledger_world_time_idx
    ON game_asha_world.world_event_ledger (world_id, settled_at, idempotency_key);
