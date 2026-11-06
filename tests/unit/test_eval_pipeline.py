from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from src.api.main import PipelineResult as ApiPipelineResult
from src.api.main import build_eval_pipeline
from src.config import Settings
from src.contracts import Answer, Citation, QueryFacts
from src.eval.pipeline import make_eval_pipeline


def _citation(device_id: str = "lmp/art1") -> Citation:
    return Citation(
        device_id=device_id,
        norm_version_id=1,
        citacao="Lei nº 11.340/2006, art. 1º",
        texto="Texto literal.",
        contexto="Contexto.",
        vigencia="vigente",
        fonte_url="https://example.test/lmp.htm",
    )


def _answer(citations: Sequence[Citation] = (), *, abstencao: bool = False) -> Answer:
    return Answer(
        resposta="Resposta de teste." if not abstencao else "Não encontrei base suficiente.",
        citacoes=list(citations),
        proximos_passos=[],
        encaminhamentos=[],
        premissas=[],
        nivel_confianca="medio" if not abstencao else "baixo",
        abstencao=abstencao,
        motivo_abstencao=None if not abstencao else "verificacao_falhou",
    )


class FakeChatPipeline:
    def __init__(self, result: ApiPipelineResult) -> None:
        self.result = result
        self.calls: list[tuple[str, QueryFacts | None]] = []

    def answer(self, message: str, facts: QueryFacts | None = None) -> ApiPipelineResult:
        self.calls.append((message, facts))
        return self.result


class FakeRepo:
    def health_snapshot(self) -> tuple[str, str | None, str | None]:
        return "ok", None, None


class FakeEncoder:
    model_name = "fake"
    dimension = 3

    def __init__(self, *, revision: str = "abc123", fail: bool = False) -> None:
        self.revision = revision
        self.fail = fail
        self.probes: list[str] = []

    def encode_query(self, text: str) -> list[float]:
        self.probes.append(text)
        if self.fail:
            raise RuntimeError("model files missing")
        return [0.1, 0.2, 0.3]


class FakeDefaultPipeline:
    def __init__(self, encoder: FakeEncoder | None = None) -> None:
        self.repo = FakeRepo()
        self.encoder = encoder or FakeEncoder()

    def answer(self, message: str, facts: QueryFacts | None = None) -> ApiPipelineResult:
        return ApiPipelineResult(
            answer=_answer([_citation()]),
            emergencia=False,
            data_atualizacao_base=None,
            retrieved_ids=("lmp/art1",),
        )


def test_adapter_maps_question_answer_and_retrieved_ids() -> None:
    chat = FakeChatPipeline(
        ApiPipelineResult(
            answer=_answer([_citation()]),
            emergencia=False,
            data_atualizacao_base=None,
            retrieved_ids=("lmp/art1",),
        )
    )
    adapter = make_eval_pipeline(chat)

    result = adapter({"pergunta": "Qual o prazo?", "data_fato": "2024-01-02"})

    assert chat.calls[0][0] == "Qual o prazo?"
    facts = chat.calls[0][1]
    assert facts is not None
    assert facts.data_fato == date(2024, 1, 2)
    assert result.retrieved_ids == ("lmp/art1",)
    assert result.citations == ["lmp/art1"]
    assert result.answer == "Resposta de teste."
    assert result.emergency is False
    assert result.abstained is False
    assert result.claims_supported == [True]
    assert result.latency_ms >= 0.0


def test_adapter_accepts_missing_data_fato() -> None:
    chat = FakeChatPipeline(
        ApiPipelineResult(answer=_answer([_citation()]), retrieved_ids=("lmp/art1",))
    )
    adapter = make_eval_pipeline(chat)

    adapter({"pergunta": "Qual o prazo?"})

    facts = chat.calls[0][1]
    assert facts is not None
    assert facts.data_fato is None


def test_adapter_clears_claims_when_pipeline_abstains() -> None:
    chat = FakeChatPipeline(
        ApiPipelineResult(
            answer=_answer([_citation()], abstencao=True),
            retrieved_ids=("lmp/art1",),
        )
    )

    result = make_eval_pipeline(chat)({"pergunta": "Pergunta"})

    assert result.abstained is True
    assert result.citations == ["lmp/art1"]
    assert result.claims_supported == []


def test_adapter_clears_claims_for_emergency() -> None:
    chat = FakeChatPipeline(
        ApiPipelineResult(
            answer=_answer([_citation()]),
            emergencia=True,
            retrieved_ids=(),
        )
    )

    result = make_eval_pipeline(chat)({"pergunta": "Ele está me batendo agora."})

    assert result.emergency is True
    assert result.retrieved_ids == ()
    assert result.claims_supported == []


def test_build_eval_pipeline_wraps_the_default_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoder = FakeEncoder()
    monkeypatch.setattr(
        "src.api.main.get_settings",
        lambda: Settings(embedding_model_revision="abc123"),
    )
    monkeypatch.setattr(
        "src.api.main.build_default_pipeline",
        lambda settings, data_atualizacao_base: FakeDefaultPipeline(encoder),
    )

    adapter = build_eval_pipeline()
    result = adapter({"pergunta": "Qual o prazo?", "data_fato": None})

    assert encoder.probes == ["probe"]
    assert result.retrieved_ids == ("lmp/art1",)
    assert result.claims_supported == [True]


def test_build_eval_pipeline_fails_clearly_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(settings: Any, data_atualizacao_base: Any) -> Any:
        raise RuntimeError("connection refused")

    monkeypatch.setattr("src.api.main.build_default_pipeline", unavailable)

    with pytest.raises(RuntimeError, match="pipeline real de avaliação indisponível"):
        build_eval_pipeline()


def test_build_eval_pipeline_fails_when_encoder_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.api.main.get_settings",
        lambda: Settings(embedding_model_revision="abc123"),
    )
    monkeypatch.setattr(
        "src.api.main.build_default_pipeline",
        lambda settings, data_atualizacao_base: FakeDefaultPipeline(FakeEncoder(fail=True)),
    )

    with pytest.raises(RuntimeError, match="embedding de teste") as excinfo:
        build_eval_pipeline()

    assert "safetensors" in str(excinfo.value)
    assert "GGUF" in str(excinfo.value)


def test_build_eval_pipeline_fails_when_model_path_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing-model"
    monkeypatch.setattr(
        "src.api.main.get_settings",
        lambda: Settings(
            embedding_model_revision="abc123",
            harrier_model_path=str(missing),
        ),
    )
    monkeypatch.setattr(
        "src.api.main.build_default_pipeline",
        lambda settings, data_atualizacao_base: FakeDefaultPipeline(),
    )

    with pytest.raises(RuntimeError, match="caminho do modelo não existe"):
        build_eval_pipeline()


def test_build_eval_pipeline_fails_with_unpinned_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.api.main.get_settings",
        lambda: Settings(embedding_model_revision=""),
    )
    monkeypatch.setattr(
        "src.api.main.build_default_pipeline",
        lambda settings, data_atualizacao_base: FakeDefaultPipeline(FakeEncoder(revision="")),
    )

    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL_REVISION"):
        build_eval_pipeline()
