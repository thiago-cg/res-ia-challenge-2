"""Conversas e identidade por cookie de capacidade (T08, ADR-02).

O identificador da conversa é público no sentido de "não secreto": quem souber o UUID não consegue
nada (INV01). O direito de ler vem de um token aleatório emitido na criação, guardado apenas como
sha256 — o banco nunca vê o token em claro.

"Não autorizado" e "não existe" respondem igual ao cliente, para não confirmar existência de
conversa alheia. A distinção só existe aqui dentro, para diagnóstico.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any

from psycopg.rows import dict_row

RETENCAO_PADRAO_DIAS = 30
DIAS_PARA_PURGAR = 90


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def criar_conversa(
    conn: Any,
    *,
    retencao_dias: int = RETENCAO_PADRAO_DIAS,
) -> tuple[uuid.UUID, str]:
    """Cria a conversa e devolve (id, token). O token não é recuperável depois."""

    if retencao_dias <= 0:
        raise ValueError("retencao_dias precisa ser positivo")

    conversation_id = uuid.uuid4()
    token = secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO conversations (id, owner_hash, expires_at)
            VALUES (%s, %s, now() + make_interval(days => %s))
            """,
            (conversation_id, _hash(token), retencao_dias),
        )
    return conversation_id, token


def autenticar(conn: Any, token: str | None) -> uuid.UUID | None:
    """Resolve o token para a conversa, se estiver válida, não apagada e não expirada."""

    if not token or len(token) > 512:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM conversations
            WHERE owner_hash = %s
              AND deleted_at IS NULL
              AND expires_at > now()
            """,
            (_hash(token),),
        )
        row = cur.fetchone()
    return (row["id"] if isinstance(row, dict) else row[0]) if row else None


COLUNAS_PUBLICAS = "id, created_at, last_seen_at, expires_at, deleted_at, purged_at"


def obter(
    conn: Any, conversation_id: uuid.UUID, *, incluir_apagadas: bool = False
) -> dict[str, Any] | None:
    """Devolve a conversa **sem** owner_hash.

    O hash da credencial não sai do banco por esta função (achado 3 da revisão do T08): quem só
    precisa saber se a conversa existe não tem por que receber o material de autenticação.
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {COLUNAS_PUBLICAS} FROM conversations WHERE id = %s"
            + ("" if incluir_apagadas else " AND deleted_at IS NULL"),
            (conversation_id,),
        )
        return cur.fetchone()


def tocar(conn: Any, conversation_id: uuid.UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE conversations SET last_seen_at = now()
            WHERE id = %s AND deleted_at IS NULL AND expires_at > now()
            """,
            (conversation_id,),
        )


def apagar(conn: Any, conversation_id: uuid.UUID) -> bool:
    """Tombstone. A purga física é separada e assíncrona (ADR-03)."""

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE conversations SET deleted_at = now()
            WHERE id = %s AND deleted_at IS NULL
            """,
            (conversation_id,),
        )
        return cur.rowcount == 1


def purgar(
    conn: Any,
    *,
    dias_tombstone: int = DIAS_PARA_PURGAR,
    dias_expirada: int = DIAS_PARA_PURGAR,
) -> int:
    """Remove fisicamente conversas fora da política de retenção.

    Dois relógios, porque são duas coisas diferentes (achado 1 da revisão do T08):
    - tombstone: conversa apagada pela pessoa, removida depois da janela de exclusão;
    - expiração: conversa que ninguém abriu e cujo prazo venceu — sem esta cláusula, a
      retenção de §21.9 nunca era aplicada e a conversa vivia para sempre.
    """

    if dias_tombstone < 0 or dias_expirada < 0:
        raise ValueError("janelas de purga não podem ser negativas")

    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM conversations
            WHERE purged_at IS NULL
              AND (
                    (deleted_at IS NOT NULL
                     AND deleted_at < now() - make_interval(days => %s))
                 OR (deleted_at IS NULL
                     AND expires_at < now() - make_interval(days => %s))
              )
            """,
            (dias_tombstone, dias_expirada),
        )
        return cur.rowcount
