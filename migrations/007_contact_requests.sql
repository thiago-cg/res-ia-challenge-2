CREATE TABLE IF NOT EXISTS contact_requests (
    id              uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message         text NOT NULL CHECK (
        char_length(trim(message)) BETWEEN 1 AND 4000
    ),
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'responded')),
    response        text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    responded_at    timestamptz,
    CHECK (
        (status = 'pending' AND response IS NULL AND responded_at IS NULL)
        OR
        (status = 'responded' AND response IS NOT NULL AND responded_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_contact_requests_conversation
    ON contact_requests (conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_contact_requests_status
    ON contact_requests (status, created_at DESC);
