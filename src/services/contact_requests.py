import uuid
from typing import Any

from psycopg.rows import dict_row


def criar(conn: Any, conversation_id: uuid.UUID, message: str) -> dict | None:
    request_id = uuid.uuid4()

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO contact_requests (id, conversation_id, message)
            VALUES (%s, %s, %s)
            RETURNING id, conversation_id, message, status,
                      response, created_at, updated_at, responded_at
            """,
            (request_id, conversation_id, message.strip()),
        )
        return cur.fetchone()


def obter(
    conn: Any,
    request_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, conversation_id, message, status,
                   response, created_at, updated_at, responded_at
            FROM contact_requests
            WHERE id = %s AND conversation_id = %s
            """,
            (request_id, conversation_id),
        )
        return cur.fetchone()


def listar_policia(conn: Any, status: str | None = None) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        if status:
            cur.execute(
                """
                SELECT id, conversation_id, message, status,
                       response, created_at, updated_at, responded_at
                FROM contact_requests
                WHERE status = %s
                ORDER BY created_at DESC
                """,
                (status,),
            )
        else:
            cur.execute(
                """
                SELECT id, conversation_id, message, status,
                       response, created_at, updated_at, responded_at
                FROM contact_requests
                ORDER BY created_at DESC
                """
            )
        return cur.fetchall()


def responder(
    conn: Any,
    request_id: uuid.UUID,
    response: str,
) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE contact_requests
            SET status = 'responded',
                response = %s,
                updated_at = now(),
                responded_at = now()
            WHERE id = %s AND status = 'pending'
            RETURNING id, conversation_id, message, status,
                      response, created_at, updated_at, responded_at
            """,
            (response.strip(), request_id),
        )
        return cur.fetchone()
