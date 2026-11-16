-- 003: conversas, mensagens e execuções (T07; docs/12 §21.2)
-- Idempotente por necessidade: scripts/apply_migrations.py reexecuta todos os .sql (D10).

CREATE TABLE IF NOT EXISTS conversations (
    id            uuid PRIMARY KEY,
    owner_hash    bytea NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    deleted_at    timestamptz,
    purged_at     timestamptz
);

CREATE TABLE IF NOT EXISTS messages (
    id                uuid PRIMARY KEY,
    conversation_id   uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_id           text NOT NULL,
    client_message_id text NOT NULL,
    role              text NOT NULL CHECK (role IN ('user', 'assistant')),
    content           text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, client_message_id)
);

CREATE TABLE IF NOT EXISTS runs (
    id              uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    thread_id       text NOT NULL,
    status          text NOT NULL CHECK (status IN (
                        'queued', 'running', 'awaiting_input', 'succeeded', 'failed',
                        'cancel_requested', 'cancelled', 'expired'
                    )),
    graph_version   text NOT NULL,
    revision        bigint NOT NULL DEFAULT 0,
    attempt         integer NOT NULL DEFAULT 0,
    lease_until     timestamptz,
    deadline        timestamptz NOT NULL,
    budget_json     jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_json     jsonb,
    error_code      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    finished_at     timestamptz
);

-- Uma execução ativa por conversa (INV04/AC14).
CREATE UNIQUE INDEX IF NOT EXISTS one_active_run_per_conversation
    ON runs (conversation_id) WHERE status IN ('queued', 'running', 'cancel_requested');

CREATE INDEX IF NOT EXISTS runs_claimable ON runs (created_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS runs_expired   ON runs (deadline)   WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS messages_conversation ON messages (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS conversations_expiry ON conversations (expires_at)
    WHERE deleted_at IS NULL;
