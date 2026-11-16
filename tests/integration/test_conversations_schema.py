"""T07 — schema de conversas, mensagens e execuções (integração, Postgres real).

Existe antes de migrations/003_conversations.sql: o primeiro run falha porque as tabelas não
existem. Um mock de banco não provaria nada aqui — as garantias são de constraint.
"""

from __future__ import annotations

import os
import uuid

import pytest


def _connect():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Postgres not reachable; set TEST_DATABASE_URL")
    import psycopg

    return psycopg.connect(url, connect_timeout=3)


def _nova_conversa(cur) -> uuid.UUID:
    cid = uuid.uuid4()
    cur.execute(
        "INSERT INTO conversations (id, owner_hash, expires_at) "
        "VALUES (%s, %s, now() + interval '1 day')",
        (cid, b"\x00" * 32),
    )
    return cid


def _novo_run(cur, cid: uuid.UUID, status: str = "queued", thread: str | None = None) -> uuid.UUID:
    rid = uuid.uuid4()
    cur.execute(
        "INSERT INTO runs (id, conversation_id, thread_id, status, graph_version, deadline) "
        "VALUES (%s, %s, %s, %s, 'v1', now() + interval '90 seconds')",
        (rid, cid, thread or rid.hex, status),
    )
    return rid


def _violacao():
    """Violação de constraint do Postgres (integridade ou unicidade)."""

    import psycopg

    return psycopg.errors.IntegrityError


@pytest.mark.integration
def test_tabelas_de_conversa_existem() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename = ANY(%s)",
            (["conversations", "messages", "runs"],),
        )
        existentes = {row[0] for row in cur.fetchall()}
    assert existentes == {"conversations", "messages", "runs"}


@pytest.mark.integration
def test_uma_execucao_ativa_por_conversa() -> None:
    """INV04/AC14: duas abas não podem criar duas execuções ativas."""
    with _connect() as conn, conn.cursor() as cur:
        cid = _nova_conversa(cur)
        _novo_run(cur, cid, "running")
        with pytest.raises(_violacao()) as exc:
            _novo_run(cur, cid, "queued")
        assert "one_active_run_per_conversation" in str(exc.value)
        conn.rollback()


@pytest.mark.integration
def test_execucao_terminal_libera_nova_execucao() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cid = _nova_conversa(cur)
        _novo_run(cur, cid, "succeeded")
        _novo_run(cur, cid, "queued")  # não pode violar o índice parcial
        cur.execute("SELECT count(*) FROM runs WHERE conversation_id = %s", (cid,))
        assert cur.fetchone()[0] == 2
        conn.rollback()


@pytest.mark.integration
def test_client_message_id_e_unico_por_conversa() -> None:
    """INV05: repetir o envio não duplica a mensagem."""
    with _connect() as conn, conn.cursor() as cur:
        cid = _nova_conversa(cur)
        cur.execute(
            "INSERT INTO messages "
            "(id, conversation_id, turn_id, client_message_id, role, content) "
            "VALUES (%s, %s, 't1', 'm1', 'user', 'oi')",
            (uuid.uuid4(), cid),
        )
        with pytest.raises(_violacao()) as exc:
            cur.execute(
                "INSERT INTO messages "
                "(id, conversation_id, turn_id, client_message_id, role, content) "
                "VALUES (%s, %s, 't1', 'm1', 'user', 'oi')",
                (uuid.uuid4(), cid),
            )
        assert "unique" in str(exc.value).lower()
        conn.rollback()


@pytest.mark.integration
def test_status_e_role_sao_restritos() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cid = _nova_conversa(cur)
        with pytest.raises(_violacao(), match="check constraint"):
            _novo_run(cur, cid, "terminou_bem")
        conn.rollback()

    with _connect() as conn, conn.cursor() as cur:
        cid = _nova_conversa(cur)
        with pytest.raises(_violacao(), match="check constraint"):
            cur.execute(
                "INSERT INTO messages "
                "(id, conversation_id, turn_id, client_message_id, role, content) "
                "VALUES (%s, %s, 't1', 'm1', 'sistema', 'oi')",
                (uuid.uuid4(), cid),
            )
        conn.rollback()


@pytest.mark.integration
def test_exclusao_em_cascata() -> None:
    """O tombstone não pode deixar mensagens ou execuções órfãs."""
    with _connect() as conn, conn.cursor() as cur:
        cid = _nova_conversa(cur)
        _novo_run(cur, cid, "succeeded")
        cur.execute(
            "INSERT INTO messages "
            "(id, conversation_id, turn_id, client_message_id, role, content) "
            "VALUES (%s, %s, 't1', 'm1', 'user', 'oi')",
            (uuid.uuid4(), cid),
        )
        cur.execute("DELETE FROM conversations WHERE id = %s", (cid,))
        cur.execute("SELECT count(*) FROM runs WHERE conversation_id = %s", (cid,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM messages WHERE conversation_id = %s", (cid,))
        assert cur.fetchone()[0] == 0
        conn.rollback()


@pytest.mark.integration
def test_conversa_tem_marcas_de_expiracao_e_exclusao() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='conversations' AND column_name = ANY(%s)",
            (["expires_at", "deleted_at", "purged_at", "owner_hash"],),
        )
        assert {row[0] for row in cur.fetchall()} == {
            "expires_at",
            "deleted_at",
            "purged_at",
            "owner_hash",
        }
