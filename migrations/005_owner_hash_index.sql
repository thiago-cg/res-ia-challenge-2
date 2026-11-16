-- 005: o hash da credencial identifica a conversa (ADR-02). Sem índice, cada requisição
-- autenticada fazia Seq Scan em conversations (achado 9 da revisão do T08).

CREATE UNIQUE INDEX IF NOT EXISTS conversations_owner_hash
    ON conversations (owner_hash);
