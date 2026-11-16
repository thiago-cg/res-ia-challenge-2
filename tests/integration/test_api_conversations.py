"""T09 — aceitação durável e idempotência (integração, HTTP + Postgres real).

O que este incremento promete:
- aceitar a mensagem só depois de gravar mensagem + execução na MESMA transação (INV10);
- repetir o mesmo client_message_id devolve a mesma execução, sem duplicar (INV05);
- segunda mensagem com execução ativa é recusada com 409 (AC14);
- emergência responde na hora, sem banco e sem criar execução (INV09/AC06);
- sem cookie é 401; conversa alheia é 404 sem vazar existência (INV02/AC07).
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


@pytest.fixture
def app(conectar):
    from fastapi import FastAPI

    from src.api.conversations import criar_router

    aplicacao = FastAPI()
    aplicacao.include_router(
        criar_router(conectar=conectar, retencao_dias=1, deadline_segundos=90, cookie_seguro=False),
        prefix="/api/v1",
    )
    return aplicacao


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def _criar_conversa(client) -> tuple[str, uuid.UUID]:
    resposta = client.post("/api/v1/conversations")
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["conversation_id"], uuid.UUID(resposta.json()["conversation_id"])


def _limpar(conectar, cid: uuid.UUID) -> None:
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM conversations WHERE id = %s", (cid,))
        conn.commit()


@pytest.mark.integration
def test_criar_conversa_devolve_id_e_cookie(client, conectar) -> None:
    resposta = client.post("/api/v1/conversations")
    assert resposta.status_code == 201
    cid = uuid.UUID(resposta.json()["conversation_id"])
    assert "zelia_owner" in resposta.cookies
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM conversations WHERE id = %s", (cid,))
        assert cur.fetchone() is not None
    _limpar(conectar, cid)


@pytest.mark.integration
def test_aceitar_mensagem_grava_mensagem_e_execucao(client, conectar) -> None:
    cid, _ = _criar_conversa(client)
    try:
        resposta = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"message": "Qual o prazo para representar?", "client_message_id": "m-1"},
        )
        assert resposta.status_code == 202, resposta.text
        corpo = resposta.json()
        assert corpo["status"] == "queued"
        run_id = uuid.UUID(corpo["run_id"])

        with conectar() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM messages "
                "WHERE conversation_id = %s AND client_message_id = 'm-1'",
                (cid,),
            )
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT status FROM runs WHERE id = %s", (run_id,))
            assert cur.fetchone()[0] == "queued"
    finally:
        _limpar(conectar, cid)


@pytest.mark.integration
def test_repetir_client_message_id_devolve_a_mesma_execucao(client, conectar) -> None:
    """INV05/AC04: retry não duplica mensagem nem execução."""
    cid, _ = _criar_conversa(client)
    try:
        primeiro = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"message": "Qual o prazo?", "client_message_id": "m-repetida"},
        )
        segundo = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"message": "Qual o prazo?", "client_message_id": "m-repetida"},
        )
        assert primeiro.status_code == 202
        assert segundo.status_code == 200
        assert segundo.json()["run_id"] == primeiro.json()["run_id"]

        with conectar() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM messages "
                "WHERE conversation_id = %s AND client_message_id = 'm-repetida'",
                (cid,),
            )
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT count(*) FROM runs WHERE conversation_id = %s", (cid,))
            assert cur.fetchone()[0] == 1
    finally:
        _limpar(conectar, cid)


@pytest.mark.integration
def test_segunda_mensagem_com_execucao_ativa_e_409(client, conectar) -> None:
    """AC14: duas abas, uma execução."""
    cid, _ = _criar_conversa(client)
    try:
        primeira = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"message": "primeira", "client_message_id": "m-1"},
        )
        assert primeira.status_code == 202
        segunda = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"message": "segunda", "client_message_id": "m-2"},
        )
        assert segunda.status_code == 409
        assert segunda.json()["run_id"] == primeira.json()["run_id"]
    finally:
        _limpar(conectar, cid)


@pytest.mark.integration
def test_emergencia_responde_sem_criar_execucao(client, conectar) -> None:
    """INV09/AC06: risco imediato não espera fila, modelo nem banco."""
    cid, _ = _criar_conversa(client)
    try:
        resposta = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"message": "Ele está me batendo agora.", "client_message_id": "m-emerg"},
        )
        assert resposta.status_code == 200, resposta.text
        corpo = resposta.json()
        assert corpo["emergencia"] is True
        assert "190" in corpo["resposta"]
        with conectar() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM runs WHERE conversation_id = %s", (cid,))
            assert cur.fetchone()[0] == 0
    finally:
        _limpar(conectar, cid)


@pytest.mark.integration
def test_sem_cookie_e_401(client) -> None:
    resposta = client.post(
        f"/api/v1/conversations/{uuid.uuid4()}/messages",
        json={"message": "oi", "client_message_id": "m-1"},
    )
    assert resposta.status_code == 401


@pytest.mark.integration
def test_conversa_alheia_e_404_sem_vazar(client, conectar) -> None:
    """AC07: conhecer o UUID não dá acesso."""
    from fastapi.testclient import TestClient

    cid_a, _ = _criar_conversa(client)
    outro = TestClient(client.app)
    outro.post("/api/v1/conversations")
    try:
        resposta = outro.post(
            f"/api/v1/conversations/{cid_a}/messages",
            json={"message": "oi", "client_message_id": "m-1"},
        )
        assert resposta.status_code == 404
        assert str(cid_a) not in resposta.text
    finally:
        _limpar(conectar, cid_a)


@pytest.mark.integration
def test_conversa_apagada_revoga_a_credencial(client, conectar) -> None:
    """ADR-03: excluir revoga o acesso, e o token deixa de autenticar.

    A resposta é 401, não 404, e isso é deliberado: "conversa apagada" e "token inválido"
    recebem o mesmo tratamento, para não confirmar a existência de uma conversa a quem
    apresenta um token qualquer. A distinção só existiria à custa de uma consulta extra que
    revela mais do que o necessário.
    """
    cid, _ = _criar_conversa(client)
    from src.services.conversations import apagar

    with conectar() as conn:
        apagar(conn, cid)
        conn.commit()
    resposta = client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"message": "oi", "client_message_id": "m-1"},
    )
    assert resposta.status_code == 401
    _limpar(conectar, cid)


@pytest.mark.integration
def test_mensagem_vazia_ou_gigante_e_422(client, conectar) -> None:
    cid, _ = _criar_conversa(client)
    try:
        vazia = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"message": "", "client_message_id": "m-1"},
        )
        assert vazia.status_code == 422
        gigante = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"message": "x" * 8001, "client_message_id": "m-2"},
        )
        assert gigante.status_code == 422
    finally:
        _limpar(conectar, cid)
