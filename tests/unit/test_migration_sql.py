from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "migrations" / "001_init.sql").read_text(encoding="utf-8").lower()


def test_required_extensions() -> None:
    for extension in ("vector", "pg_trgm", "unaccent"):
        assert f"create extension if not exists {extension}" in SQL


def test_required_tables() -> None:
    tables = (
        "norms",
        "norm_versions",
        "devices",
        "device_versions",
        "device_explanations",
        "device_questions",
        "device_relations",
        "ingest_runs",
        "eval_questions",
        "services",
    )
    for table in tables:
        assert f"create table {table}" in SQL, f"missing table {table}"


def test_devices_current_view() -> None:
    assert "create view devices_current as" in SQL
    assert "vigencia_status in ('vigente', 'alterado')" in SQL


def test_required_indexes_and_constraints() -> None:
    for name in (
        "devices_norm_artigo_idx",
        "devices_parent_idx",
        "devices_rotulo_trgm_idx",
        "device_versions_vigencia_idx",
        "device_versions_norm_idx",
        "device_versions_search_idx",
        "device_versions_embedding_idx",
        "device_questions_version_fk",
        "device_versions_no_overlap",
    ):
        assert name in SQL, f"missing index/constraint {name}"


def test_vigencia_checks() -> None:
    assert "check (vigencia_fim is null or vigencia_fim >= vigencia_inicio)" in SQL
    assert "overlapping" in SQL


def test_embedding_dimension_and_vector_types() -> None:
    assert "vector(1024)" in SQL
    assert "hnsw (embedding vector_cosine_ops)" in SQL
    assert "to_tsvector('portuguese', search_text)" in SQL


def test_status_and_type_check_literals() -> None:
    for literal in ("vigente", "alterado", "revogado", "cancelado", "superado"):
        assert literal in SQL
    for tipo in ("artigo", "caput", "paragrafo", "inciso", "alinea", "item"):
        assert tipo in SQL
