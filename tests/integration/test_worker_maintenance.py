"""Manutenção do worker: reconcilia execuções vencidas e purga o que expirou."""

from __future__ import annotations

import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest


@pytest.fixture
def conectar():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Postgres not reachable; set TEST_DATABASE_URL")
    import psycopg

    @contextmanager
    def _abrir():
        conn = psycopg.connect(url, connect_timeout=3, autocommit=False)
        try:
            yield conn
        finally:
            conn.close()

    yield _abrir


@pytest.mark.integration
def test_manutencao_expira_run_vencido_e_purga_conversa_expirada(conectar) -> None:
    from src.services.conversations import criar_conversa, obter
    from src.services.runs import criar_run
    from src.services.runs import obter as obter_run
    from src.worker import executar_manutencao

    with conectar() as conn:
        cid, _ = criar_conversa(conn, retencao_dias=1)
        rid = criar_run(conn, conversation_id=cid, thread_id=f"t-{cid}", deadline_segundos=60)
        conn.execute("UPDATE runs SET deadline = now() - interval '1 second' WHERE id = %s", (rid,))
        conn.execute(
            "UPDATE conversations SET expires_at = now() - interval '100 days' WHERE id = %s",
            (cid,),
        )
        conn.commit()

    ajustes = SimpleNamespace(tombstone_retention_days=90, conversation_retention_days=30)
    expirados, purgados = executar_manutencao(conectar=conectar, settings=ajustes)
    assert expirados >= 1
    assert purgados >= 1

    with conectar() as conn:
        assert obter(conn, cid, incluir_apagadas=True) is None
        assert obter_run(conn, rid) is None or obter_run(conn, rid)["status"] == "expired"

    with conectar() as conn:
        conn.execute("DELETE FROM conversations WHERE id = %s", (cid,))
        conn.commit()


@pytest.mark.integration
def test_manutencao_nao_apaga_conversa_viva(conectar) -> None:
    from src.services.conversations import criar_conversa, obter
    from src.worker import executar_manutencao

    with conectar() as conn:
        cid, _ = criar_conversa(conn, retencao_dias=30)
        conn.commit()

    ajustes = SimpleNamespace(tombstone_retention_days=90, conversation_retention_days=30)
    executar_manutencao(conectar=conectar, settings=ajustes)

    with conectar() as conn:
        assert obter(conn, cid) is not None
        conn.execute("DELETE FROM conversations WHERE id = %s", (cid,))
        conn.commit()
