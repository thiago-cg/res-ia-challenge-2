"""pgvector dense search, PostgreSQL FTS and embedding upserts.

These functions operate on an existing psycopg connection; they never commit.
SQL shape is part of the contract: dense search uses cosine distance
(``1 - (embedding <=> %s)``) and FTS uses ``websearch_to_tsquery('portuguese')``
with ``ts_rank_cd``.  The vigência filter defaults to the current versions and
switches to the fact-date range when ``data_fato`` is supplied.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from src.textnorm import build_fts_query

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
    return [_search_hit(row, "dense") for row in rows]


def fts_search(
    conn: Any,
    query: str,
    *,
    limit: int = 50,
    data_fato: date | None = None,
) -> list[SearchHit]:
    _validate_limit(limit)
    # An empty lexical query is a normal "no lexical evidence" outcome, not an
    # error: the caller still has the dense list.  Running an empty tsquery
    # would raise, so short-circuit.
    lexical = build_fts_query(query)
    if not lexical:
        return []
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
    params = [lexical, lexical, *filter_params, limit]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_search_hit(row, "bm25") for row in rows]


def _search_hit(row: Any, source: DenseSource) -> SearchHit:
    """Adapt psycopg rows from both ``dict_row`` and the default tuple factory."""

    if isinstance(row, Mapping):
        device_id = row.get("device_id")
        norm_version_id = row.get("norm_version_id")
        score = row.get("score")
    else:
        try:
            device_id, norm_version_id, score = row[0], row[1], row[2]
        except (IndexError, KeyError, TypeError) as exc:
            raise ValueError(f"unsupported search row: {row!r}") from exc

    if device_id is None or norm_version_id is None or score is None:
        raise ValueError(f"search row is missing required fields: {row!r}")

    return SearchHit(
        device_id=str(device_id),
        norm_version_id=int(norm_version_id),
        score=float(score),
        source=source,
    )


def _vigencia_clause(data_fato: date | None) -> tuple[str, list[date]]:
    if data_fato is None:
        return (
            "dv.vigencia_status IN ('vigente', 'alterado') "
            "AND dv.vigencia_inicio <= CURRENT_DATE "
            "AND (dv.vigencia_fim IS NULL OR dv.vigencia_fim >= CURRENT_DATE)",
            [],
        )
    return (
        "dv.vigencia_inicio <= %s AND (dv.vigencia_fim IS NULL OR dv.vigencia_fim >= %s)",
        [data_fato, data_fato],
    )


def _validate_limit(limit: int) -> None:
    if limit <= 0:
        raise ValueError("limit must be positive")


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"
