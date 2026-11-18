"""T10/T13 — acompanhamento, resultado, cancelamento e exclusão (integração).

- estado com revision monotônica e 304 quando nada mudou (ADR-06);
- resultado final idempotente, 409 enquanto não concluído;
- cancelamento sem publicação tardia (INV12);
- exclusão com tombstone, revogação e cancelamento das execuções ativas.
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
def client(conectar):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.conversations import criar_router
    from src.api.runs import criar_router_runs

    app = FastAPI()
    prefixo = "/api/v1"
    app.include_router(
        criar_router(conectar=conectar, retencao_dias=1, deadline_segundos=90, cookie_seguro=False),
        prefix=prefixo,
    )
    app.include_router(criar_router_runs(conectar=conectar), prefix=prefixo)
    return TestClient(app)


def _conversa(client) -> tuple[str, uuid.UUID]:
    r = client.post("/api/v1/conversations")
    assert r.status_code == 201, r.text
    cid = r.json()["conversation_id"]
    return cid, uuid.UUID(cid)


def _enviar(client, cid: str, msg: str = "Qual o prazo?") -> str:
    r = client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"message": msg, "client_message_id": f"m-{uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


def _limpar(conectar, cid: uuid.UUID) -> None:
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM conversations WHERE id = %s", (cid,))
        conn.commit()


@pytest.mark.integration
def test_estado_de_execucao_queued(client, conectar) -> None:
    cid, cid_u = _conversa(client)
    try:
        run_id = _enviar(client, cid)
        r = client.get(f"/api/v1/conversations/{cid}/runs/{run_id}")
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["status"] == "queued"
        assert corpo["revision"] >= 1
        tipos = [e["type"] for e in corpo["events"]]
        assert "run.accepted" in tipos
    finally:
        _limpar(conectar, cid_u)


@pytest.mark.integration
def test_since_igual_a_revision_devolve_304(client, conectar) -> None:
    """ADR-06: polling por revisão, sem replay de eventos."""
    cid, cid_u = _conversa(client)
    try:
        run_id = _enviar(client, cid)
        primeira = client.get(f"/api/v1/conversations/{cid}/runs/{run_id}")
        revisao = primeira.json()["revision"]
        segunda = client.get(
            f"/api/v1/conversations/{cid}/runs/{run_id}", params={"since": revisao}
        )
        assert segunda.status_code == 304
        assert segunda.content == b""
    finally:
        _limpar(conectar, cid_u)


@pytest.mark.integration
def test_resultado_de_execucao_incompleta_e_409(client, conectar) -> None:
    cid, cid_u = _conversa(client)
    try:
        run_id = _enviar(client, cid)
        r = client.get(f"/api/v1/conversations/{cid}/runs/{run_id}/result")
        assert r.status_code == 409
    finally:
        _limpar(conectar, cid_u)


@pytest.mark.integration
def test_resultado_concluido_devolve_o_payload_publicado(client, conectar) -> None:
    from src.services.runs import concluir, reivindicar

    cid, cid_u = _conversa(client)
    try:
        run_id = _enviar(client, cid)
        with conectar() as conn:
            run = reivindicar(conn, lease_segundos=60)
            conn.commit()
            concluir(
                conn,
                uuid.UUID(run_id),
                attempt=run["attempt"],
                resultado={"resposta": "ok", "abstencao": False, "emergencia": False},
            )
            conn.commit()

        r = client.get(f"/api/v1/conversations/{cid}/runs/{run_id}/result")
        assert r.status_code == 200, r.text
        assert r.json()["resposta"] == "ok"

        repetido = client.get(f"/api/v1/conversations/{cid}/runs/{run_id}/result")
        assert repetido.status_code == 200
        assert repetido.json()["resposta"] == "ok"
    finally:
        _limpar(conectar, cid_u)


@pytest.mark.integration
def test_cancelar_execucao_ativa(client, conectar) -> None:
    cid, cid_u = _conversa(client)
    try:
        run_id = _enviar(client, cid)
        r = client.post(f"/api/v1/conversations/{cid}/runs/{run_id}/cancel")
        assert r.status_code == 202, r.text
        estado = client.get(f"/api/v1/conversations/{cid}/runs/{run_id}").json()
        assert estado["status"] in ("cancel_requested", "cancelled")
    finally:
        _limpar(conectar, cid_u)


@pytest.mark.integration
def test_cancelar_e_idempotente(client, conectar) -> None:
    cid, cid_u = _conversa(client)
    try:
        run_id = _enviar(client, cid)
        client.post(f"/api/v1/conversations/{cid}/runs/{run_id}/cancel")
        segunda = client.post(f"/api/v1/conversations/{cid}/runs/{run_id}/cancel")
        assert segunda.status_code == 202
    finally:
        _limpar(conectar, cid_u)


@pytest.mark.integration
def test_excluir_conversa_revoga_e_cancela(client, conectar) -> None:
    """T13: tombstone, cancelamento das execuções e credencial inválida."""
    cid, cid_u = _conversa(client)
    run_id = _enviar(client, cid)

    r = client.delete(f"/api/v1/conversations/{cid}")
    assert r.status_code == 204, r.text

    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT deleted_at FROM conversations WHERE id = %s", (cid_u,))
        assert cur.fetchone()[0] is not None
        cur.execute("SELECT status FROM runs WHERE id = %s", (uuid.UUID(run_id),))
        assert cur.fetchone()[0] in ("cancel_requested", "cancelled")

    depois = client.get(f"/api/v1/conversations/{cid}/runs/{run_id}")
    assert depois.status_code == 401
    _limpar(conectar, cid_u)


@pytest.mark.integration
def test_acesso_a_execucao_de_outra_conversa_e_404(client, conectar) -> None:
    """401 é só para credencial inválida; conversa alheia é 404, sem confirmar existência."""
    from fastapi.testclient import TestClient

    cid_a, cid_u = _conversa(client)
    run_id = _enviar(client, cid_a)
    outro = TestClient(client.app)
    outro.post("/api/v1/conversations")
    try:
        r = outro.get(f"/api/v1/conversations/{cid_a}/runs/{run_id}")
        assert r.status_code == 404
        assert str(cid_a) not in r.text
    finally:
        _limpar(conectar, cid_u)


@pytest.mark.integration
def test_execucao_inexistente_e_404(client, conectar) -> None:
    cid, cid_u = _conversa(client)
    try:
        r = client.get(f"/api/v1/conversations/{cid}/runs/{uuid.uuid4()}")
        assert r.status_code == 404
    finally:
        _limpar(conectar, cid_u)
