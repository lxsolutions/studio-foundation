-- Session records for account/session interface stubs.

CREATE TABLE platform.session (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id uuid NOT NULL REFERENCES platform.account (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now() + interval '7 days'
);

CREATE INDEX session_account_idx ON platform.session (account_id);
