"""A v1 é montada no servidor real e as flags aparecem em /health."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api import main as main_module
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
    # A flag vem do construtor, não do ambiente: com WEB_SEARCH_ENABLED=true no .env
    # local e ausente no CI, o valor esperado fixo passava aqui e falhava lá.
    resposta = TestClient(_app(web_search_enabled=False)).get("/health")
    assert resposta.status_code == 200
    capacidades = resposta.json()["capabilities"]
    assert capacidades == {"durable": False, "resumable": False, "web_search": False}


def test_capacidades_seguem_as_flags() -> None:
    app = _app(
        multiagent_enabled=True,
        resumable_conversations_enabled=True,
        web_search_enabled=True,
    )
    capacidades = TestClient(app).get("/health").json()["capabilities"]
    assert capacidades["durable"] is True
    assert capacidades["resumable"] is True
    assert capacidades["web_search"] is True


def test_rota_v1_sem_cookie_responde_sem_abrir_conexao(monkeypatch) -> None:
    # Sem cookie não há o que autenticar. Abrir conexão para descobrir isso gastava
    # uma conexão do pool por requisição anônima e, sem banco (CI), virava 500.
    def explodir(*args, **kwargs):
        raise AssertionError("a rota abriu conexão antes de exigir o cookie")

    monkeypatch.setattr(main_module, "_open_connection", explodir)
    app = _app()
    cliente = TestClient(app)

    resposta = cliente.get("/api/v1/conversations/current")
    assert resposta.status_code == 404

    run = "00000000-0000-0000-0000-000000000001"
    assert cliente.get(f"/api/v1/conversations/{run}/runs/{run}").status_code == 401
    assert cliente.get(f"/api/v1/conversations/{run}/runs/{run}/result").status_code == 401
    assert cliente.post(f"/api/v1/conversations/{run}/runs/{run}/cancel").status_code == 401
    assert cliente.delete(f"/api/v1/conversations/{run}").status_code == 401
