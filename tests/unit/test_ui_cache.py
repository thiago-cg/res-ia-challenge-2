"""A interface não pode ficar presa a arquivos antigos no cache do navegador."""

from fastapi.testclient import TestClient

from src.api.main import app


def test_arquivos_da_interface_pedem_revalidacao() -> None:
    cliente = TestClient(app)
    for caminho in ("/app/", "/app/scripts/app.js", "/app/styles/app.css"):
        resposta = cliente.get(caminho)
        assert resposta.status_code == 200, caminho
        assert resposta.headers["cache-control"] == "no-cache", caminho


def test_revalidacao_devolve_304_quando_nada_mudou() -> None:
    cliente = TestClient(app)
    primeira = cliente.get("/app/scripts/app.js")
    etag = primeira.headers.get("etag")
    assert etag
    segunda = cliente.get("/app/scripts/app.js", headers={"If-None-Match": etag})
    assert segunda.status_code == 304
