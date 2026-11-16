-- 004: idempotência de aceitação (T09). A execução guarda o client_message_id que a originou,
-- para que repetir o envio devolva a MESMA execução em vez de criar outra (INV05).

ALTER TABLE runs ADD COLUMN IF NOT EXISTS client_message_id text;

CREATE UNIQUE INDEX IF NOT EXISTS runs_client_message
    ON runs (conversation_id, client_message_id)
    WHERE client_message_id IS NOT NULL;
