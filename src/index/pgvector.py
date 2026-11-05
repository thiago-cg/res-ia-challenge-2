"""pgvector dense search, PostgreSQL FTS and embedding upserts.

These functions operate on an existing psycopg connection; they never commit.
SQL shape is part of the contract: dense search uses cosine distance
(``1 - (embedding <=> %s)``) and FTS uses ``websearch_to_tsquery('portuguese')``
with ``ts_rank_cd``.  The vigência filter defaults to the current versions and
switches to the fact-date range when ``data_fato`` is supplied.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

DenseSource = Literal["dense", "bm25"]


class SearchHit(BaseModel):
    device_id: str
    norm_version_id: int
    score: float
    source: DenseSource


def update_embedding(
    conn: Any,
    device_id: str,
    norm_version_id: int,
    embedding: list[float],
    model: str,
    revision: str,
    text_hash: str,
) -> None:
    sql = """
        UPDATE device_versions
        SET embedding = %s,
            embedding_model = %s,
            embedding_model_revision = %s,
            embedding_text_hash = %s,
            indexed_at = now()
        WHERE device_id = %s
          AND norm_version_id = %s
    """
    params = (
        _vector_literal(embedding),
        model,
        revision,
        text_hash,
        device_id,
        norm_version_id,
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)


def dense_search(
    conn: Any,
    query_vector: list[float],
    *,
    limit: int = 50,
    data_fato: date | None = None,
) -> list[SearchHit]:
    _validate_limit(limit)
    clause, filter_params = _vigencia_clause(data_fato)
    vector = _vector_literal(query_vector)
    sql = f"""
        SELECT dv.device_id,
               dv.norm_version_id,
               1 - (dv.embedding <=> %s) AS score
        FROM device_versions dv
        WHERE dv.embedding IS NOT NULL
          AND {clause}
        ORDER BY dv.embedding <=> %s
        LIMIT %s
    """
    params = [vector, *filter_params, vector, limit]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        SearchHit(
            device_id=row[0],
            norm_version_id=row[1],
            score=float(row[2]),
            source="dense",
        )
        for row in rows
    ]


def fts_search(
    conn: Any,
    query: str,
    *,
    limit: int = 50,
    data_fato: date | None = None,
) -> list[SearchHit]:
    _validate_limit(limit)
    clause, filter_params = _vigencia_clause(data_fato)
    sql = f"""
        SELECT dv.device_id,
               dv.norm_version_id,
               ts_rank_cd(dv.search_vector,
                          websearch_to_tsquery('portuguese', %s)) AS score
        FROM device_versions dv
        WHERE dv.search_vector @@ websearch_to_tsquery('portuguese', %s)
          AND {clause}
        ORDER BY score DESC
        LIMIT %s
    """
    params = [query, query, *filter_params, limit]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        SearchHit(
            device_id=row[0],
            norm_version_id=row[1],
            score=float(row[2]),
            source="bm25",
        )
        for row in rows
    ]


def _vigencia_clause(data_fato: date | None) -> tuple[str, list[date]]:
    if data_fato is None:
        return "dv.vigencia_status IN ('vigente', 'alterado')", []
    return (
        "dv.vigencia_inicio <= %s AND (dv.vigencia_fim IS NULL OR dv.vigencia_fim >= %s)",
        [data_fato, data_fato],
    )


def _validate_limit(limit: int) -> None:
    if limit <= 0:
        raise ValueError("limit must be positive")


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"
