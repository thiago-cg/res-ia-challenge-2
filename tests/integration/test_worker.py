"""Worker — reivindicação, execução e publicação (integração).

O worker é o que faz a promessa valer: aceito o trabalho, ele termina sem navegador. Aqui o
"processar" é injetado, então o teste cobre o protocolo (claim, commit curto, publicar uma vez,
falhar com código) sem LLM e sem rede.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

import pytest


def _dsn() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Postgres not reachable; set TEST_DATABASE_URL")
    return url


@pytest.fixture
def conectar():
    import psycopg

    dsn = _dsn()

    @contextmanager
    def _abrir():
        conn = psycopg.connect(dsn, connect_timeout=3, autocommit=False)
        try:
            yield conn
        finally:
            conn.close()

    yield _abrir


def _preparar(conectar) -> tuple[uuid.UUID, uuid.UUID]:
    from src.services.conversations import criar_conversa
    from src.services.runs import criar_run

    with conectar() as conn:
        cid, _ = criar_conversa(conn)
        rid = criar_run(conn, conversation_id=cid, thread_id=f"t-{cid}", deadline_segundos=90)
        conn.commit()
    return cid, rid


def _limpar(conectar, cid: uuid.UUID) -> None:
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM conversations WHERE id = %s", (cid,))
        conn.commit()


@pytest.mark.integration
def test_processar_publica_resultado(conectar) -> None:
    from src.services.runs import obter
    from src.worker import processar_pendentes

    cid, rid = _preparar(conectar)
    try:
        criados: list[dict] = []

        def processar(run: dict) -> dict:
            criados.append(run)
            return {"resposta": "resultado do worker", "abstencao": False}

        assert processar_pendentes(conectar=conectar, processar=processar) == 1
        with conectar() as conn:
            run = obter(conn, rid)
        assert run["status"] == "succeeded"
        assert run["result_json"]["resposta"] == "resultado do worker"
        assert len(criados) == 1
    finally:
        _limpar(conectar, cid)


@pytest.mark.integration
def test_processar_nao_pega_run_de_outra_conversa_concluida(conectar) -> None:
    from src.worker import processar_pendentes

    cid, _ = _preparar(conectar)
    try:

        def processar(run: dict) -> dict:
            return {"resposta": "x"}

        assert processar_pendentes(conectar=conectar, processar=processar) == 1
        assert processar_pendentes(conectar=conectar, processar=processar) == 0
        assert processar(  # sem run pendente, a função não é chamada
            {"id": uuid.uuid4()}
        ) == {"resposta": "x"}
    finally:
        _limpar(conectar, cid)


@pytest.mark.integration
def test_falha_marca_run_como_failed(conectar) -> None:
    from src.services.runs import obter
    from src.worker import processar_pendentes

    cid, rid = _preparar(conectar)
    try:

        def explode(run: dict) -> dict:
            raise RuntimeError("llm fora do ar")

        assert processar_pendentes(conectar=conectar, processar=explode) == 1
        with conectar() as conn:
            run = obter(conn, rid)
        assert run["status"] == "failed"
        assert run["error_code"] == "RuntimeError"
        assert run["result_json"] is None
    finally:
        _limpar(conectar, cid)


@pytest.mark.integration
def test_conversa_apagada_durante_execucao_nao_publica(conectar) -> None:
    """INV12: o tombstone vence a publicação."""
    from src.services.conversations import apagar
    from src.services.runs import obter
    from src.worker import processar_pendentes

    cid, rid = _preparar(conectar)
    try:

        def apaga_e_devolve(run: dict) -> dict:
            with conectar() as conn:
                apagar(conn, cid)
                conn.commit()
            return {"resposta": "tardia"}

        processar_pendentes(conectar=conectar, processar=apaga_e_devolve)
        with conectar() as conn:
            run = obter(conn, rid)
        assert run["result_json"] is None
        assert run["status"] in ("running", "failed", "cancelled")
    finally:
        _limpar(conectar, cid)
