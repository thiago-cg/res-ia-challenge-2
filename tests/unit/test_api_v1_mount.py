"""A v1 é montada no servidor real e as flags aparecem em /health."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import create_app
from src.config import Settings


def _app(**over):
    settings = Settings(**over)
    return create_app(settings=settings, source_repo=object())


def test_rotas_v1_estao_montadas() -> None:
    caminhos = set(_app().openapi()["paths"])
    esperados = {
        "/api/v1/conversations",
        "/api/v1/conversations/{conversation_id}",
        "/api/v1/conversations/{conversation_id}/messages",
        "/api/v1/conversations/{conversation_id}/runs/{run_id}",
        "/api/v1/conversations/{conversation_id}/runs/{run_id}/result",
        "/api/v1/conversations/{conversation_id}/runs/{run_id}/cancel",
    }
    assert esperados <= caminhos


def test_health_publica_capacidades() -> None:
    resposta = TestClient(_app()).get("/health")
    assert resposta.status_code == 200
    capacidades = resposta.json()["capabilities"]
    assert capacidades == {"durable": False, "resumable": False, "web_search": True}


def test_capacidades_seguem_as_flags() -> None:
    app = _app(
        multiagent_enabled=True,
        resumable_conversations_enabled=True,
        web_search_enabled=False,
    )
    capacidades = TestClient(app).get("/health").json()["capabilities"]
    assert capacidades["durable"] is True
    assert capacidades["resumable"] is True
    assert capacidades["web_search"] is False


def test_rota_v1_sem_cookie_e_401() -> None:
    resposta = TestClient(_app()).get("/api/v1/conversations/current")
    assert resposta.status_code in (401, 404)
