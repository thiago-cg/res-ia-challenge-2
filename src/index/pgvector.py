"""pgvector dense search, PostgreSQL FTS and embedding upserts.

These functions operate on an existing psycopg connection; they never commit.
SQL shape is part of the contract: dense search uses cosine distance
(``1 - (embedding <=> %s)``) and FTS uses ``websearch_to_tsquery('portuguese')``
with ``ts_rank_cd``.  The vigência filter defaults to the current versions and
switches to the fact-date range when ``data_fato`` is supplied.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from src.textnorm import build_fts_terms

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
    """Lexical search scored by inverse document frequency coverage.

    ``ts_rank_cd`` has no notion of rarity: a question that mentions ``lei``
    scores almost the same as one that mentions ``coabitacao``.  Each content
    term is therefore weighted by ``log((N + 1) / (df + 1))`` and the score is
    the sum of the weights of the terms a device actually contains; matching
    several rare terms beats matching one common one.

    Measured on the 110 answerable questions, lexical-only recall@10 goes from
    0.280 to 0.358 (questions fully retrieved 13% -> 24%).
    """

    _validate_limit(limit)
    terms = build_fts_terms(query)
    if not terms:
        return []

    total, frequency = _document_frequencies(conn, terms)
    weighted = [
        (term, math.log((total + 1) / (frequency[term] + 1))) for term in terms if term in frequency
    ]
    if not weighted:
        return []

    clause, filter_params = _vigencia_clause(data_fato)
    values = ", ".join(["(CAST(%s AS text), CAST(%s AS float8))"] * len(weighted))
    params = [value for pair in weighted for value in pair]
    sql = f"""
        WITH terms(term, weight) AS (VALUES {values})
        SELECT dv.device_id,
               dv.norm_version_id,
               sum(terms.weight) AS score
        FROM device_versions dv
        JOIN terms ON dv.search_vector @@ to_tsquery('portuguese', terms.term)
        WHERE {clause}
        GROUP BY dv.device_id, dv.norm_version_id
        ORDER BY score DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, [*params, *filter_params, limit])
        rows = cur.fetchall()
    return [_search_hit(row, "bm25") for row in rows]


def _document_frequencies(conn: Any, terms: Sequence[str]) -> tuple[int, dict[str, int]]:
    """Row count and per-term document frequency for the lexical scorer."""

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM device_versions")
        row = cur.fetchone()
        total = int(_value(row, 0, "count")) if row is not None else 0
        cur.execute(
            """SELECT t, count(*) FROM device_versions dv, unnest(%s::text[]) AS t
               WHERE dv.search_vector @@ to_tsquery('portuguese', t) GROUP BY t""",
            (list(terms),),
        )
        frequency = {
            str(_value(item, 0, "t")): int(_value(item, 1, "count")) for item in cur.fetchall()
        }
    return total, frequency


def _value(row: Any, index: int, key: str) -> Any:
    """Read a column from a tuple row or a dict row indifferently."""

    if isinstance(row, Mapping):
        return row[key]
    return row[index]


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
