import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load_compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_compose_db_contract() -> None:
    compose = _load_compose()
    db = compose["services"]["db"]
    assert db["image"] == "pgvector/pgvector:pg17"
    assert db["environment"]["POSTGRES_USER"] == "app"
    assert db["environment"]["POSTGRES_PASSWORD"] == "app"
    assert db["environment"]["POSTGRES_DB"] == "violencia"
    assert "5432:5432" in db["ports"]
    assert any("pgdata" in volume for volume in db["volumes"])
    assert "pg_isready" in " ".join(db["healthcheck"]["test"])


def test_compose_qdrant_contract() -> None:
    compose = _load_compose()
    qdrant = compose["services"]["qdrant"]
    assert qdrant["image"] == "qdrant/qdrant:v1.15.3"
    assert {"6333:6333", "6334:6334"} <= set(qdrant["ports"])
    assert any("qdrant_data" in volume for volume in qdrant["volumes"])
    assert "target" in qdrant["profiles"]
    assert {"pgdata", "qdrant_data"} <= set(compose["volumes"])


def test_wait_for_db_help() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "wait_for_db.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "DATABASE_URL" in result.stdout


@pytest.mark.integration
def test_postgres_reachable() -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Postgres not reachable; set TEST_DATABASE_URL")

    try:
        import psycopg
    except ImportError:  # pragma: no cover - dependency is declared
        pytest.skip("psycopg not installed")

    try:
        with psycopg.connect(url, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
    except Exception as exc:
        pytest.skip(f"Postgres not reachable at TEST_DATABASE_URL: {exc}")
