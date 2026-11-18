"""T08 — cookie de capacidade e dependência de autorização (unidade, sem banco)."""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.api.auth import (
    COOKIE_NOME,
    ConversaAutenticada,
    dependencia_conversa,
    emitir_cookie,
    limpar_cookie,
)


def _app(autenticador):
    app = FastAPI()
    dependencia = dependencia_conversa(autenticador)

    @app.get("/privado")
    def privado(ctx: ConversaAutenticada = Depends(dependencia)):  # noqa: B008 - idiom do FastAPI
        return {"conversation_id": str(ctx.conversation_id)}

    return app


def test_cookie_tem_atributos_de_seguranca() -> None:
    from fastapi.responses import JSONResponse

    resposta = JSONResponse({"ok": True})
    emitir_cookie(resposta, "token-secreto", max_age_segundos=3600)
    cabecalho = resposta.headers["set-cookie"].lower()

    assert f"{COOKIE_NOME}=token-secreto" in cabecalho
    assert "httponly" in cabecalho
    assert "samesite=lax" in cabecalho
    assert "secure" in cabecalho
    assert "path=/" in cabecalho
    assert "max-age=3600" in cabecalho
    assert "token" not in resposta.headers["set-cookie"].split("=")[0].lower()


def test_cookie_pode_ser_removido() -> None:
    from fastapi.responses import JSONResponse

    resposta = JSONResponse({"ok": True})
    limpar_cookie(resposta)
    assert "max-age=0" in resposta.headers["set-cookie"].lower()


def test_sem_cookie_e_401() -> None:
    client = TestClient(_app(lambda token: None))
    resposta = client.get("/privado")
    assert resposta.status_code == 401
    assert resposta.json()["detail"] == "Sessão inválida ou expirada."


def test_token_invalido_e_401() -> None:
    client = TestClient(_app(lambda token: None))
    client.cookies.set(COOKIE_NOME, "token-inventado")
    assert client.get("/privado").status_code == 401


def test_token_valido_autoriza_a_propria_conversa() -> None:
    cid = uuid.uuid4()
    client = TestClient(_app(lambda token: cid if token == "bom" else None))
    client.cookies.set(COOKIE_NOME, "bom")
    corpo = client.get("/privado").json()
    assert corpo["conversation_id"] == str(cid)


def test_token_de_outra_conversa_nao_autoriza() -> None:
    """AC07/AC08: conhecer o id de A não dá acesso a A."""
    alvo = uuid.uuid4()
    outra = uuid.uuid4()
    client = TestClient(_app(lambda token: alvo if token == "token-a" else None))
    client.cookies.set(COOKIE_NOME, "token-b-de-outra-conversa")
    resposta = client.get("/privado")
    assert resposta.status_code == 401
    assert str(outra) not in resposta.text


def test_cookie_nao_vai_para_url_nem_parametro() -> None:
    """O token não pode viajar em query string (evita histórico e log de proxy)."""
    cid = uuid.uuid4()
    client = TestClient(_app(lambda token: cid if token == "bom" else None))
    resposta = client.get("/privado", params={"token": "bom"})
    assert resposta.status_code == 401


def test_api_v1_nao_entra_em_cache() -> None:
    """Achado 12 da revisão: o no-store cobria só /chat."""
    from src.api.middleware import SecurityHeadersMiddleware

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/v1/conversations/current")
    def conversa():
        return {"ok": True}

    @app.get("/health")
    def saude():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/api/v1/conversations/current").headers["cache-control"] == "no-store"
    assert "cache-control" not in client.get("/health").headers
