from __future__ import annotations

import math
from datetime import date

import pytest

from src.index.pgvector import (
    SearchHit,
    dense_search,
    fts_search,
    update_embedding,
)


class FakeCursor:
    def __init__(self, rows: list[object] | None = None) -> None:
        self.rows = rows or []
        self.executions: list[tuple[str, object]] = []
        self.total = 100
        self.frequencies: list[tuple[str, int]] = [
            ("medida", 10),
            ("protetiva", 5),
            ("contato", 3),
            ("violencia", 20),
            ("domestica", 15),
        ]
        self._sql = ""

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:
        self.executions.append((sql, params))
        self._sql = sql

    def fetchone(self) -> tuple[int]:
        return (self.total,)

    def fetchall(self) -> list[object]:
        if "unnest" in self._sql:
            return list(self.frequencies)
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[object] | None = None) -> None:
        self.cursor_obj = FakeCursor(rows)

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    @property
    def last_execution(self) -> tuple[str, object]:
        return self.cursor_obj.executions[-1]


def normalized(sql: str) -> str:
    return " ".join(sql.split())


def dict_row(device_id: str = "lmp/art22", version: int = 42, score: float = 0.87) -> dict:
    return {"device_id": device_id, "norm_version_id": version, "score": score}


def test_dense_search_uses_cosine_distance_and_current_vigencia() -> None:
    conn = FakeConnection(rows=[dict_row()])

    hits = dense_search(conn, [0.5, 0.25])

    sql, params = conn.last_execution
    compact = normalized(sql)
    assert "1 - (dv.embedding <=> %s) AS score" in compact
    assert "ORDER BY dv.embedding <=> %s" in compact
    assert "dv.embedding IS NOT NULL" in compact
    assert "dv.vigencia_status IN ('vigente', 'alterado')" in compact
    assert "dv.vigencia_inicio <= CURRENT_DATE" in compact
    assert "dv.vigencia_fim IS NULL OR dv.vigencia_fim >= CURRENT_DATE" in compact
    assert params == ["[0.5,0.25]", "[0.5,0.25]", 50]
    assert hits == [
        SearchHit(device_id="lmp/art22", norm_version_id=42, score=0.87, source="dense")
    ]


def test_dense_search_accepts_default_tuple_rows() -> None:
    conn = FakeConnection(rows=[("lmp/art22", 42, 0.87)])

    hits = dense_search(conn, [0.5, 0.25])

    assert hits == [
        SearchHit(device_id="lmp/art22", norm_version_id=42, score=0.87, source="dense")
    ]


def test_dense_search_with_data_fato_uses_date_range_and_no_status_filter() -> None:
    fato = date(2010, 5, 1)
    conn = FakeConnection(rows=[dict_row()])

    dense_search(conn, [1.0], data_fato=fato, limit=10)

    compact = normalized(conn.last_execution[0])
    assert "dv.vigencia_inicio <= %s" in compact
    assert "dv.vigencia_fim IS NULL OR dv.vigencia_fim >= %s" in compact
    assert "vigencia_status" not in compact
    assert conn.last_execution[1] == ["[1.0]", fato, fato, "[1.0]", 10]


def test_fts_search_scores_by_term_rarity() -> None:
    """Rare terms must outweigh common ones: ts_rank_cd has no idf."""

    conn = FakeConnection(rows=[dict_row("lmp/art22/cpt/inc3/ali-b", 42, 0.42)])

    hits = fts_search(conn, "medida protetiva")

    sql, params = conn.cursor_obj.executions[-1]
    compact = normalized(sql)
    assert "WITH terms(term, weight) AS" in compact
    assert "sum(terms.weight) AS score" in compact
    assert "dv.search_vector @@ to_tsquery('portuguese', terms.term)" in compact
    assert "GROUP BY dv.device_id, dv.norm_version_id" in compact
    assert "ORDER BY score DESC" in compact
    assert "dv.vigencia_status IN ('vigente', 'alterado')" in compact
    assert "dv.vigencia_inicio <= CURRENT_DATE" in compact
    assert "dv.vigencia_fim IS NULL OR dv.vigencia_fim >= CURRENT_DATE" in compact
    # flat pairs: medida, log(101/11), protetiva, log(101/6)
    assert params[0] == "medida"
    assert math.isclose(params[1], math.log(101 / 11))
    assert params[2] == "protetiva"
    assert math.isclose(params[3], math.log(101 / 6))
    assert params[-1] == 50
    assert hits[0].source == "bm25"
    assert hits[0].score == 0.42


def test_fts_search_strips_accents_so_accented_questions_match() -> None:
    conn = FakeConnection(rows=[])

    fts_search(conn, "Vítima de violência doméstica")

    sql, params = conn.cursor_obj.executions[-1]
    terms = [value for value in params[:-1] if isinstance(value, str)]
    assert "violencia" in terms
    assert "domestica" in terms
    assert all("í" not in term for term in terms)


def test_fts_search_returns_empty_without_issuing_sql_for_stopwords() -> None:
    conn = FakeConnection(rows=[])

    hits = fts_search(conn, "de da do")

    assert hits == []
    assert conn.cursor_obj.executions == []


def test_fts_search_accepts_default_tuple_rows() -> None:
    conn = FakeConnection(rows=[("lmp/art22", 42, 0.42)])

    hits = fts_search(conn, "medida protetiva")

    assert hits == [SearchHit(device_id="lmp/art22", norm_version_id=42, score=0.42, source="bm25")]


def test_search_rejects_malformed_rows() -> None:
    with pytest.raises(ValueError, match="missing required fields"):
        dense_search(FakeConnection(rows=[dict_row(device_id=None)]), [1.0])


def test_fts_search_with_data_fato_uses_date_range() -> None:
    fato = date(2009, 8, 7)
    conn = FakeConnection(rows=[])

    fts_search(conn, "contato", data_fato=fato, limit=5)

    compact = normalized(conn.last_execution[0])
    assert "dv.vigencia_inicio <= %s" in compact
    assert "dv.vigencia_fim IS NULL OR dv.vigencia_fim >= %s" in compact
    assert conn.cursor_obj.executions[-1][1][-3:] == [fato, fato, 5]


def test_update_embedding_writes_model_revision_hash_and_indexed_at() -> None:
    conn = FakeConnection()

    update_embedding(
        conn,
        "lmp/art22",
        42,
        [1.0, 0.0],
        "harrier-oss-v1-0.6b",
        "rev-abc",
        "hash-123",
    )

    compact = normalized(conn.last_execution[0])
    assert compact.startswith("UPDATE device_versions SET embedding = %s")
    assert "embedding_model = %s" in compact
    assert "embedding_model_revision = %s" in compact
    assert "embedding_text_hash = %s" in compact
    assert "indexed_at = now()" in compact
    assert "WHERE device_id = %s AND norm_version_id = %s" in compact
    assert conn.last_execution[1] == (
        "[1.0,0.0]",
        "harrier-oss-v1-0.6b",
        "rev-abc",
        "hash-123",
        "lmp/art22",
        42,
    )


@pytest.mark.parametrize("limit", [0, -1])
def test_search_rejects_non_positive_limit(limit: int) -> None:
    with pytest.raises(ValueError):
        dense_search(FakeConnection(), [1.0], limit=limit)
    with pytest.raises(ValueError):
        fts_search(FakeConnection(), "texto", limit=limit)
