"""Integração do Canal Mulher–Polícia."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

import pytest

from src.api.auth import COOKIE_NOME


def _dsn() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Postgres não configurado; defina TEST_DATABASE_URL")
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
def client(conectar):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.contact_requests import criar_router as criar_router_contatos
    from src.api.conversations import criar_router as criar_router_conversas

    app = FastAPI()
    prefixo = "/api/v1"

    app.include_router(
        criar_router_conversas(
            conectar=conectar,
            retencao_dias=1,
            deadline_segundos=90,
            cookie_seguro=False,
        ),
        prefix=prefixo,
    )
    app.include_router(
        criar_router_contatos(
            conectar=conectar,
            police_username="policia_teste",
            police_password="senha-teste",
            police_secret="a" * 64,
            cookie_seguro=False,
        ),
        prefix=prefixo,
    )
    return TestClient(app)


def _conversa(client) -> tuple[str, uuid.UUID]:
    resposta = client.post("/api/v1/conversations")
    assert resposta.status_code == 201, resposta.text
    cid = resposta.json()["conversation_id"]
    return cid, uuid.UUID(cid)


def _limpar(conectar, *ids: uuid.UUID) -> None:
    if not ids:
        return
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM conversations WHERE id = ANY(%s)", (list(ids),))
        conn.commit()


@pytest.mark.integration
def test_enviar_e_consultar_solicitacao(client, conectar) -> None:
    _, cid = _conversa(client)
    try:
        enviada = client.post(
            "/api/v1/contact-requests",
            json={"message": "Preciso de orientação."},
        )
        assert enviada.status_code == 201, enviada.text
        solicitacao = enviada.json()
        assert solicitacao["message"] == "Preciso de orientação."
        assert solicitacao["status"] == "pending"

        consulta = client.get(
            f"/api/v1/contact-requests/{solicitacao['id']}"
        )
        assert consulta.status_code == 200, consulta.text
        assert consulta.json()["id"] == solicitacao["id"]
    finally:
        _limpar(conectar, cid)


@pytest.mark.integration
def test_enviar_solicitacao_sem_sessao_retorna_401(client) -> None:
    resposta = client.post(
        "/api/v1/contact-requests",
        json={"message": "Preciso de orientação."},
    )
    assert resposta.status_code == 401


@pytest.mark.integration
def test_solicitacao_so_pode_ser_consultada_pela_conversa_dona(
    client, conectar
) -> None:
    _, cid_a = _conversa(client)
    cookie_a = client.cookies.get(COOKIE_NOME)

    try:
        enviada = client.post(
            "/api/v1/contact-requests",
            json={"message": "Solicitação privada."},
        )
        assert enviada.status_code == 201, enviada.text
        request_id = enviada.json()["id"]

        _, cid_b = _conversa(client)
        cookie_b = client.cookies.get(COOKIE_NOME)

        client.cookies.clear()
        client.cookies.set(COOKIE_NOME, cookie_a)
        consulta_a = client.get(f"/api/v1/contact-requests/{request_id}")
        assert consulta_a.status_code == 200

        client.cookies.clear()
        client.cookies.set(COOKIE_NOME, cookie_b)
        consulta_b = client.get(f"/api/v1/contact-requests/{request_id}")
        assert consulta_b.status_code == 404
    finally:
        _limpar(conectar, cid_a, cid_b)


@pytest.mark.integration
def test_painel_policial_exige_login_e_permite_responder(
    client, conectar
) -> None:
    _, cid = _conversa(client)
    try:
        enviada = client.post(
            "/api/v1/contact-requests",
            json={"message": "Gostaria de receber orientação."},
        )
        assert enviada.status_code == 201, enviada.text
        request_id = enviada.json()["id"]

        bloqueada = client.get("/api/v1/police/contact-requests")
        assert bloqueada.status_code == 401

        login_invalido = client.post(
            "/api/v1/police/login",
            json={"username": "policia_teste", "password": "errada"},
        )
        assert login_invalido.status_code == 401

        login = client.post(
            "/api/v1/police/login",
            json={"username": "policia_teste", "password": "senha-teste"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["authenticated"] is True

        painel = client.get("/api/v1/police/contact-requests")
        assert painel.status_code == 200, painel.text
        assert any(item["id"] == request_id for item in painel.json())

        resposta = client.post(
            f"/api/v1/police/contact-requests/{request_id}/response",
            json={"response": "Esta é uma resposta fictícia para demonstração."},
        )
        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["status"] == "responded"

        duplicada = client.post(
            f"/api/v1/police/contact-requests/{request_id}/response",
            json={"response": "Segunda resposta."},
        )
        assert duplicada.status_code == 404
    finally:
        _limpar(conectar, cid)
