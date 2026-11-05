from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

WEB_APP_PATH = Path(__file__).resolve().parents[2] / "web" / "app.py"


def load_web_module():
    spec = importlib.util.spec_from_file_location("web_app_under_test", WEB_APP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.gets: list[str] = []
        self.closed = False

    def post(self, url: str, json: dict[str, Any]) -> FakeResponse:
        self.posts.append((url, json))
        return FakeResponse(self.payload)

    def get(self, url: str) -> FakeResponse:
        self.gets.append(url)
        return FakeResponse(self.payload)

    def close(self) -> None:
        self.closed = True


class FakeTarget:
    def __init__(self, *, sidebar: bool = False) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._sidebar = sidebar
        self._is_sidebar = False

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def __getattr__(self, name: str):
        def method(*args: Any, **kwargs: Any) -> bool:
            self._record(name, *args, **kwargs)
            if name == "button":
                return False
            return False

        return method

    def __enter__(self) -> FakeTarget:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    @property
    def sidebar(self) -> FakeTarget:
        return self

    def names(self) -> list[str]:
        return [name for name, _, _ in self.calls]


def test_web_module_imports_and_compiles() -> None:
    module = load_web_module()

    assert callable(module.main)
    assert module.EMERGENCY_BLOCK
    assert module.LEGAL_NOTICE_PREFIX


def test_emergency_and_legal_notice_strings() -> None:
    module = load_web_module()

    for number in ("190", "180", "100", "197"):
        assert number in module.EMERGENCY_BLOCK

    notice = module.legal_notice("2026-11-05")
    assert module.LEGAL_NOTICE_PREFIX in notice
    assert "Esta é uma orientação informativa" in notice
    assert "2026-11-05" in notice
    assert "190" in notice


def test_call_chat_api_posts_payload() -> None:
    module = load_web_module()
    client = FakeClient({"resposta": "ok"})

    result = module.call_chat_api(
        "Como pedir medida protetiva?",
        "session-1",
        {"data_fato": "2026-10-01"},
        base_url="http://api.test",
        client=client,
    )

    assert result == {"resposta": "ok"}
    assert client.posts == [
        (
            "http://api.test/chat",
            {
                "session_id": "session-1",
                "message": "Como pedir medida protetiva?",
                "facts": {"data_fato": "2026-10-01"},
            },
        )
    ]
    assert client.closed is False


def test_fetch_health_uses_get() -> None:
    module = load_web_module()
    client = FakeClient({"status": "degraded"})

    result = module.fetch_health(base_url="http://api.test", client=client)

    assert result == {"status": "degraded"}
    assert client.gets == ["http://api.test/health"]


def test_render_response_puts_emergency_before_answer_text() -> None:
    module = load_web_module()
    target = FakeTarget()

    module.render_response(
        {
            "resposta": "Orientação.",
            "emergencia": True,
            "citacoes": [],
            "proximos_passos": [],
            "encaminhamentos": [],
            "premissas": [],
            "abstencao": False,
            "motivo_abstencao": None,
            "data_atualizacao_base": "2026-11-05",
        },
        target,
    )

    assert target.calls[0][0] == "error"
    assert target.calls[0][1][0] == module.EMERGENCY_BLOCK
    assert target.names()[1] == "markdown"


def test_render_response_renders_citation_cards_from_response() -> None:
    module = load_web_module()
    target = FakeTarget()
    citation = {
        "device_id": "lmp/art22",
        "norm_version_id": 7,
        "citacao": "Lei nº 11.340/2006, art. 22",
        "texto": "Texto literal do dispositivo.",
        "contexto": "Contexto.",
        "vigencia": "alterado",
        "fonte_url": "https://example.test/lmp",
    }

    module.render_response(
        {
            "resposta": "Orientação.",
            "emergencia": False,
            "citacoes": [citation],
            "proximos_passos": ["Procurar a Defensoria Pública."],
            "encaminhamentos": [],
            "premissas": [],
            "abstencao": False,
            "motivo_abstencao": None,
            "data_atualizacao_base": "2026-11-05",
        },
        target,
    )

    written = [args[0] for name, args, _ in target.calls if name == "write"]
    captions = [args[0] for name, args, _ in target.calls if name == "caption"]
    links = [(args[0], args[1]) for name, args, _ in target.calls if name == "link_button"]
    assert "Texto literal do dispositivo." in written
    assert "Vigência: alterado" in captions
    assert ("Abrir a fonte oficial", "https://example.test/lmp") in links
    assert any("não substitui atendimento jurídico individual" in item for item in captions)
    assert any("2026-11-05" in item for item in captions)


def test_render_sidebar_shows_legal_notice_examples_and_clear_button() -> None:
    module = load_web_module()
    target = FakeTarget(sidebar=True)

    module.render_sidebar(
        {
            "status": "degraded",
            "data_atualizacao_base": "2026-11-05",
        },
        target,
    )

    captions = [args[0] for name, args, _ in target.calls if name == "caption"]
    buttons = [args[0] for name, args, _ in target.calls if name == "button"]
    warnings = [args[0] for name, args, _ in target.calls if name == "warning"]
    assert module.LEGAL_NOTICE_PREFIX in captions
    assert "Não informe nome, CPF, endereço, telefone ou documentos." in captions
    assert "Limpar conversa" in buttons
    assert all(question in buttons for question in module.EXAMPLE_QUESTIONS)
    assert warnings
