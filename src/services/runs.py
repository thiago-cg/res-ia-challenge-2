"""Persistência das execuções (T07).

Protocolo do worker (§21.7): reivindicar com lease, executar, publicar uma vez. As garantias que
dependem de banco moram aqui, não no grafo:

- uma execução ativa por conversa (índice parcial único, migração 003);
- reivindicação sem dois workers pegando o mesmo run (FOR UPDATE SKIP LOCKED);
- lease vencido devolve o run para a fila (recuperação após morte do worker);
- publicação idempotente: concluir só vale a partir de "running" e só grava uma vez;
- cancelamento prévio não é sobrescrito por publicação tardia (INV12).

Nenhuma função aqui faz commit: a transação é do chamador, para que aceitar mensagem e criar a
execução possam acontecer atomicamente (T09).
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

TERMINAIS = frozenset({"succeeded", "failed", "cancelled", "expired"})


def criar_run(
    conn: Any,
    *,
    conversation_id: uuid.UUID,
    thread_id: str,
    deadline_segundos: int,
    graph_version: str = "graph.v1",
    budget: dict[str, Any] | None = None,
    client_message_id: str | None = None,
) -> uuid.UUID:
    """Cria a execução em "queued". Violar o índice de execução única é erro do chamador."""

    if deadline_segundos <= 0:
        raise ValueError("deadline_segundos precisa ser positivo")

    run_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO runs (
                id, conversation_id, thread_id, status, graph_version,
                deadline, revision, budget_json, client_message_id
            ) VALUES (%s, %s, %s, 'queued', %s,
                      now() + make_interval(secs => %s), 1, %s, %s)
            """,
            (
                run_id,
                conversation_id,
                thread_id,
                graph_version,
                deadline_segundos,
                Jsonb(budget or {}),
                client_message_id,
            ),
        )
    return run_id


def reivindicar(conn: Any, *, lease_segundos: int = 60) -> dict[str, Any] | None:
    """Pega o run mais antigo disponível e marca "running" com lease."""

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            WITH candidato AS (
                SELECT id FROM runs
                WHERE deadline > now()
                  AND (
                        status = 'queued'
                     OR (status = 'running' AND lease_until IS NOT NULL AND lease_until < now())
                  )
                ORDER BY created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE runs SET
                status = 'running',
                started_at = COALESCE(started_at, now()),
                lease_until = now() + make_interval(secs => %s),
                attempt = attempt + 1,
                revision = revision + 1
            WHERE id = (SELECT id FROM candidato)
            RETURNING *
            """,
            (lease_segundos,),
        )
        return cur.fetchone()


def concluir(
    conn: Any,
    run_id: uuid.UUID,
    *,
    attempt: int,
    resultado: dict[str, Any],
) -> bool:
    """Publica o resultado uma única vez.

    Três guardas, todas necessárias (achados M2/M3 da revisão do T07):
    - "status = 'running'": cancelamento não é sobrescrito (INV12);
    - "result_json IS NULL": publicação idempotente;
    - "attempt" e tombstone: o worker que perdeu o lease não publica por cima do vigente, e
      conversa apagada não publica nada.
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE runs SET
                status = 'succeeded',
                result_json = %s,
                finished_at = now(),
                lease_until = NULL,
                revision = revision + 1
            WHERE id = %s
              AND status = 'running'
              AND result_json IS NULL
              AND attempt = %s
              AND EXISTS (
                  SELECT 1 FROM conversations c
                  WHERE c.id = runs.conversation_id AND c.deleted_at IS NULL
              )
            """,
            (Jsonb(resultado), run_id, attempt),
        )
        return cur.rowcount == 1


def falhar(conn: Any, run_id: uuid.UUID, *, attempt: int, error_code: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE runs SET
                status = 'failed',
                error_code = %s,
                finished_at = now(),
                lease_until = NULL,
                revision = revision + 1
            WHERE id = %s AND status IN ('queued', 'running') AND attempt = %s
            """,
            (error_code, run_id, attempt),
        )
        return cur.rowcount == 1


def cancelar(conn: Any, run_id: uuid.UUID) -> bool:
    """Cancela o que ainda não terminou. Idempotente."""

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE runs SET
                status = 'cancelled',
                finished_at = now(),
                lease_until = NULL,
                revision = revision + 1
            WHERE id = %s AND status IN ('queued', 'running', 'cancel_requested')
            """,
            (run_id,),
        )
        return cur.rowcount == 1


def solicitar_cancelamento(conn: Any, run_id: uuid.UUID) -> bool:
    """Marca a intenção sem matar o processo: o worker decide no próximo passo."""

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE runs SET status = 'cancel_requested', revision = revision + 1
            WHERE id = %s AND status IN ('queued', 'running')
            """,
            (run_id,),
        )
        return cur.rowcount == 1


def encerrar_pendente(conn: Any, run_id: uuid.UUID, *, status: str = "succeeded") -> bool:
    """Fecha um run que estava aguardando resposta.

    §21.4 (emenda M4): quando chega novo turno, o run em "awaiting_input" é encerrado — não
    volta para "queued" nem fica imortal. "concluir" não serve porque exige "running".
    """

    if status not in ("succeeded", "cancelled"):
        raise ValueError("status final de encerramento deve ser succeeded ou cancelled")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE runs SET
                status = %s,
                finished_at = now(),
                lease_until = NULL,
                revision = revision + 1
            WHERE id = %s AND status = 'awaiting_input'
            """,
            (status, run_id),
        )
        return cur.rowcount == 1


def cancelar_ativos(conn: Any, conversation_id: uuid.UUID) -> int:
    """Marca para cancelamento tudo que ainda pode publicar (usado na exclusão)."""

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE runs SET status = 'cancel_requested', revision = revision + 1
            WHERE conversation_id = %s AND status IN ('queued', 'running')
            """,
            (conversation_id,),
        )
        return cur.rowcount


def reconciliar_expirados(conn: Any) -> int:
    """Fecha execuções cujo prazo passou e que ninguém reivindicou a tempo."""

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE runs SET
                status = 'expired',
                finished_at = now(),
                lease_until = NULL,
                revision = revision + 1
            WHERE status <> ALL(%s)
              AND deadline < now()
            """,
            (sorted(TERMINAIS),),
        )
        return cur.rowcount


def obter_por_client_message(
    conn: Any, conversation_id: uuid.UUID, client_message_id: str
) -> dict[str, Any] | None:
    """Recupera a execução criada para uma mensagem (idempotência da aceitação)."""

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM runs WHERE conversation_id = %s AND client_message_id = %s",
            (conversation_id, client_message_id),
        )
        return cur.fetchone()


def obter(conn: Any, run_id: uuid.UUID) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM runs WHERE id = %s", (run_id,))
        return cur.fetchone()


def obter_por_conversa(conn: Any, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM runs WHERE conversation_id = %s ORDER BY created_at DESC, id DESC",
            (conversation_id,),
        )
        return list(cur.fetchall())
