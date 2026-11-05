from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.main import (
    LazyChatPipeline,
    LegalRAGPipeline,
    PipelineResult,
    SettingsHealthProbe,
    create_app,
    health_status,
)
from src.config import Settings
from src.contracts import Answer, Citation, RetrievedDevice
from src.safety.risk import emergency_answer


def make_row(
    device_id: str = "lmp/art22",
    version: int = 7,
    vigencia: str = "vigente",
    citacao: str = "Lei nº 11.340/2006, art. 22",
    texto: str = "Texto literal oficial do dispositivo.",
    contexto: str = "Contexto oficial do artigo.",
    fonte_url: str = "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm",
) -> dict[str, Any]:
    return {
        "device_id": device_id,
        "norm_version_id": version,
        "norm_id": device_id.split("/")[0],
        "artigo_id": device_id,
        "texto_literal": texto,
        "contexto": contexto,
        "citacao": citacao,
        "vigencia_status": vigencia,
        "vigencia_inicio": date(2006, 8, 7),
        "vigencia_fim": None,
        "fonte_url": fonte_url,
    }


def make_citation(device_id: str = "lmp/art22", version: int = 7) -> Citation:
    return Citation(
        device_id=device_id,
        norm_version_id=version,
        citacao="Lei nº 11.340/2006, art. 22",
        texto="Texto literal oficial do dispositivo.",
        contexto="Contexto oficial do artigo.",
        vigencia="vigente",
        fonte_url="https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm",
    )


def make_answer(**overrides) -> Answer:
    data = {
        "resposta": "Resposta de teste.",
        "citacoes": [],
        "proximos_passos": ["Procurar a Defensoria Pública."],
        "encaminhamentos": [],
        "premissas": [],
        "nivel_confianca": "medio",
        "abstencao": False,
        "motivo_abstencao": None,
    }
    data.update(overrides)
    return Answer(**data)


def llm_json(
    device_ids: list[str],
    *,
    resposta: str = "Resposta baseada nos dispositivos recuperados.",
    abstencao: bool = False,
    motivo: str | None = None,
) -> str:
    return json.dumps(
        {
            "resposta": resposta,
            "citacoes": [
                {"device_id": device_id, "afirmacao": "O dispositivo sustenta a afirmação."}
                for device_id in device_ids
            ],
            "proximos_passos": ["Procurar a Defensoria Pública."],
            "encaminhamentos": [],
            "premissas": [],
            "nivel_confianca": "medio",
            "abstencao": abstencao,
            "motivo_abstencao": motivo,
        }
    )


class FakeRepo:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        *,
        current_version: int = 7,
        on_date_row: dict[str, Any] | None = None,
    ) -> None:
        self.rows = {(row["device_id"], row["norm_version_id"]): row for row in (rows or [])}
        self.current_version = current_version
        self.on_date_row = on_date_row
        self.catalog: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[tuple[Any, ...]] = []

    def get_device_version(self, device_id: str, norm_version_id: int) -> Any | None:
        self.calls.append(("get_device_version", device_id, norm_version_id))
        return self.rows.get((device_id, norm_version_id))

    def get_device_version_on(self, device_id: str, on_date: date) -> Any | None:
        self.calls.append(("get_device_version_on", device_id, on_date))
        return self.on_date_row

    def get_current_version_id(self, device_id: str, data_fato: date | None = None) -> int | None:
        self.calls.append(("get_current_version_id", device_id, data_fato))
        return self.current_version

    def find(self, norm_id: str, artigo_id: str) -> Any | None:
        self.calls.append(("find", norm_id, artigo_id))
        return self.catalog.get((norm_id, artigo_id))

    def lookup(self, artigo_id: str, norm_version_id: int) -> Any | None:
        self.calls.append(("lookup", artigo_id, norm_version_id))
        return self.rows.get((artigo_id, norm_version_id))

    def get_data_atualizacao_base(self) -> str | None:
        return "2026-11-05"


class SpySearcher:
    def __init__(self, hits: list[RetrievedDevice] | None = None) -> None:
        self.hits = list(hits or [])
        self.calls: list[tuple[str, int, date | None]] = []

    def search(
        self, query: str, limit: int, data_fato: date | None = None
    ) -> list[RetrievedDevice]:
        self.calls.append((query, limit, data_fato))
        return list(self.hits)


class FakeLLM:
    model_name = "fake"
    version = "v1"

    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs = list(outputs or [])
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, timeout: float = 30) -> str:
        self.calls.append((system, user))
        if not self.outputs:
            raise RuntimeError("no fake output configured")
        return self.outputs.pop(0)


class FailingLLM:
    model_name = "failing"
    version = "v1"

    def complete(self, system: str, user: str, *, timeout: float = 30) -> str:
        raise RuntimeError("llm down")


class StubPipeline:
    def __init__(self, result: PipelineResult) -> None:
        self.result = result
        self.calls: list[tuple[str, Any]] = []

    def answer(self, message: str, facts: Any = None) -> PipelineResult:
        self.calls.append((message, facts))
        return self.result


class StaticProbe:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def snapshot(self) -> dict[str, Any]:
        self.calls += 1
        return dict(self.payload)


def make_pipeline(
    repo: FakeRepo,
    *,
    dense: SpySearcher | None = None,
    fts: SpySearcher | None = None,
    llm: Any | None = None,
    **kwargs: Any,
) -> tuple[LegalRAGPipeline, SpySearcher, SpySearcher]:
    dense_spy = dense or SpySearcher()
    fts_spy = fts or SpySearcher()
    pipeline = LegalRAGPipeline(
        repo=repo,
        dense=dense_spy,
        fts=fts_spy,
        llm=llm,
        data_atualizacao_base=kwargs.pop("data", "2026-11-05"),
        **kwargs,
    )
    return pipeline, dense_spy, fts_spy


def make_client(
    *,
    pipeline: Any = None,
    repo: FakeRepo | None = None,
    probe: StaticProbe | None = None,
    data_atualizacao_base: str = "2026-11-05",
) -> TestClient:
    active_repo = repo or FakeRepo()
    active_probe = probe or StaticProbe(
        health_status(
            database="ok",
            qdrant="ok",
            data_atualizacao_base=data_atualizacao_base,
        )
    )
    app = create_app(
        pipeline=pipeline,
        source_repo=active_repo,
        health_probe=active_probe,
        data_atualizacao_base=data_atualizacao_base,
    )
    return TestClient(app)


def test_emergency_blocks_before_any_retrieval() -> None:
    repo = FakeRepo([make_row()])
    pipeline, dense, fts = make_pipeline(repo, llm=FakeLLM([llm_json(["lmp/art22"])]))

    result = pipeline.answer("Ele está me batendo agora.")

    assert result.emergencia is True
    assert "190" in result.answer.resposta
    assert "180" in result.answer.resposta
    assert "100" in result.answer.resposta
    assert "197" in result.answer.resposta
    assert repo.calls == []
    assert dense.calls == []
    assert fts.calls == []
    assert pipeline._llm is not None
    assert pipeline._llm.calls == []  # type: ignore[attr-defined]


def test_emergency_does_not_read_base_date_from_repo() -> None:
    repo = FakeRepo([make_row()])

    def explode() -> str | None:
        raise AssertionError("base date must not be read for emergency answers")

    repo.get_data_atualizacao_base = explode  # type: ignore[method-assign]
    pipeline = LegalRAGPipeline(
        repo=repo,
        dense=SpySearcher(),
        fts=SpySearcher(),
        llm=FakeLLM([]),
    )

    result = pipeline.answer("Ele está me batendo agora.")

    assert result.emergencia is True
    assert "190" in result.answer.resposta
    assert repo.calls == []


def test_emergency_never_builds_lazy_pipeline() -> None:
    factory_calls: list[str] = []

    def failing_factory() -> LegalRAGPipeline:
        factory_calls.append("called")
        raise ValueError("no encoder revision")

    app = create_app(
        settings=Settings(),
        pipeline=LazyChatPipeline(failing_factory),
        source_repo=FakeRepo(),
        health_probe=StaticProbe(
            health_status(
                database="unavailable",
                qdrant="unavailable",
                data_atualizacao_base="2026-11-05",
            )
        ),
        data_atualizacao_base="2026-11-05",
    )
    client = TestClient(app)

    body = client.post(
        "/chat",
        json={"session_id": "session-emergency", "message": "Ele está me batendo agora."},
    ).json()

    assert body["emergencia"] is True
    assert "190" in body["resposta"]
    assert "180" in body["resposta"]
    assert "100" in body["resposta"]
    assert "197" in body["resposta"]
    assert factory_calls == []


def test_lazy_pipeline_emergency_skips_factory() -> None:
    factory_calls: list[str] = []

    def failing_factory() -> LegalRAGPipeline:
        factory_calls.append("called")
        raise ValueError("no encoder revision")

    lazy = LazyChatPipeline(failing_factory)

    result = lazy.answer("Ele está me batendo agora.")

    assert result.emergencia is True
    assert "190" in result.answer.resposta
    assert factory_calls == []


def test_emergency_response_is_marked_at_api_level() -> None:
    repo = FakeRepo([make_row()])
    pipeline, dense, fts = make_pipeline(repo)
    client = make_client(pipeline=pipeline, repo=repo)

    response = client.post(
        "/chat",
        json={"session_id": "session-emergency", "message": "Ele está com arma aqui."},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["emergencia"] is True
    assert "190" in body["resposta"]
    assert dense.calls == []
    assert fts.calls == []


def test_explicit_citation_not_found_abstains_without_hybrid_fallback() -> None:
    repo = FakeRepo([make_row()])
    pipeline, dense, fts = make_pipeline(repo)

    result = pipeline.answer("O que diz o art. 99 da Lei Maria da Penha?")

    assert result.answer.abstencao is True
    assert result.answer.motivo_abstencao == "citacao_explicita_nao_encontrada"
    assert result.answer.citacoes == []
    assert dense.calls == []
    assert fts.calls == []
    assert not any(call[0] == "get_current_version_id" for call in repo.calls)


def test_ambiguous_citation_abstains_without_hybrid_fallback() -> None:
    repo = FakeRepo([make_row()])
    pipeline, dense, fts = make_pipeline(repo)

    result = pipeline.answer("O que diz o art. 22?")

    assert result.answer.abstencao is True
    assert result.answer.motivo_abstencao == "citacao_explicita_nao_encontrada"
    assert dense.calls == []
    assert fts.calls == []
    assert not any(call[0] == "find" for call in repo.calls)


def test_resolved_explicit_citation_hydrates_pair_and_skips_hybrid() -> None:
    row = make_row(device_id="lmp/art7", version=3)
    repo = FakeRepo([row], current_version=3)
    repo.catalog[("lmp", "lmp/art7")] = {
        "device_id": "lmp/art7",
        "norm_id": "lmp",
        "artigo_id": "lmp/art7",
    }
    llm = FakeLLM([llm_json(["lmp/art7"])])
    pipeline, dense, fts = make_pipeline(repo, llm=llm)

    result = pipeline.answer("O que diz o art. 7º da Lei Maria da Penha?")

    assert result.answer.abstencao is False
    assert len(result.answer.citacoes) == 1
    citation = result.answer.citacoes[0]
    assert citation.device_id == "lmp/art7"
    assert citation.norm_version_id == 3
    assert citation.texto == row["texto_literal"]
    assert citation.citacao == row["citacao"]
    assert dense.calls == []
    assert fts.calls == []
    assert ("get_current_version_id", "lmp/art7", None) in repo.calls
    assert ("get_device_version", "lmp/art7", 3) in repo.calls
    assert 'id="lmp/art7"' in llm.calls[0][1]


def test_citations_come_only_from_hydrated_metadata() -> None:
    row = make_row(device_id="lmp/art7", version=3)
    repo = FakeRepo([row], current_version=3)
    repo.catalog[("lmp", "lmp/art7")] = {
        "device_id": "lmp/art7",
        "norm_id": "lmp",
        "artigo_id": "lmp/art7",
    }
    llm = FakeLLM(
        [
            llm_json(
                ["lmp/art7"],
                resposta="A Súmula 999 inventada não existe; veja o art. 7º.",
            )
        ]
    )
    pipeline, _, _ = make_pipeline(repo, llm=llm)

    result = pipeline.answer("O que diz o art. 7º da Lei Maria da Penha?")

    citation = result.answer.citacoes[0]
    assert citation.citacao == row["citacao"]
    assert citation.texto == row["texto_literal"]
    assert "Súmula 999" in result.answer.resposta
    assert "Súmula 999" not in citation.citacao


def test_llm_output_ids_are_restricted_to_retrieved_ids() -> None:
    row = make_row(device_id="lmp/art7", version=3)
    repo = FakeRepo([row], current_version=3)
    repo.catalog[("lmp", "lmp/art7")] = {
        "device_id": "lmp/art7",
        "norm_id": "lmp",
        "artigo_id": "lmp/art7",
    }
    llm = FakeLLM(
        [
            llm_json(["lmp/art999"]),
            llm_json(["lmp/art999"]),
        ]
    )
    pipeline, _, _ = make_pipeline(repo, llm=llm)

    result = pipeline.answer("O que diz o art. 7º da Lei Maria da Penha?")

    assert len(llm.calls) == 2
    assert result.answer.abstencao is True
    assert result.answer.motivo_abstencao == "saida_invalida"
    assert "lmp/art999" not in {citation.device_id for citation in result.answer.citacoes}


def test_llm_abstention_uses_fallback_abstain() -> None:
    row = make_row(device_id="lmp/art7", version=3)
    repo = FakeRepo([row], current_version=3)
    repo.catalog[("lmp", "lmp/art7")] = {
        "device_id": "lmp/art7",
        "norm_id": "lmp",
        "artigo_id": "lmp/art7",
    }
    llm = FakeLLM([llm_json([], abstencao=True, motivo="sem base suficiente")])
    pipeline, _, _ = make_pipeline(repo, llm=llm)

    result = pipeline.answer("O que diz o art. 7º da Lei Maria da Penha?")

    assert result.answer.abstencao is True
    assert result.answer.motivo_abstencao == "sem base suficiente"
    assert result.answer.citacoes == []


def test_explicit_resolution_error_abstains_safely() -> None:
    class RaisingFindRepo(FakeRepo):
        def find(self, norm_id: str, artigo_id: str) -> Any | None:
            raise RuntimeError("database down")

    repo = RaisingFindRepo([make_row()])
    pipeline, dense, fts = make_pipeline(repo)

    result = pipeline.answer("O que diz o art. 7º da Lei Maria da Penha?")

    assert result.answer.abstencao is True
    assert result.answer.motivo_abstencao == "erro_recuperacao"
    assert result.answer.citacoes == []
    assert dense.calls == []
    assert fts.calls == []


def test_explicit_hydration_error_abstains_safely() -> None:
    class RaisingHydrateRepo(FakeRepo):
        def get_device_version(self, device_id: str, norm_version_id: int) -> Any | None:
            raise RuntimeError("database down")

    row = make_row(device_id="lmp/art7", version=3)
    repo = RaisingHydrateRepo([row], current_version=3)
    repo.catalog[("lmp", "lmp/art7")] = {
        "device_id": "lmp/art7",
        "norm_id": "lmp",
        "artigo_id": "lmp/art7",
    }
    pipeline, dense, fts = make_pipeline(repo)

    result = pipeline.answer("O que diz o art. 7º da Lei Maria da Penha?")

    assert result.answer.abstencao is True
    assert result.answer.motivo_abstencao == "erro_recuperacao"
    assert result.answer.citacoes == []
    assert dense.calls == []
    assert fts.calls == []


def test_normal_hydration_error_abstains_safely() -> None:
    class RaisingHydrateRepo(FakeRepo):
        def get_device_version(self, device_id: str, norm_version_id: int) -> Any | None:
            raise RuntimeError("database down")

    repo = RaisingHydrateRepo([])
    hit = RetrievedDevice(
        device_id="lmp/art22",
        norm_version_id=7,
        score=0.9,
        source="dense",
        texto_literal="",
        citacao="",
    )
    pipeline, _, _ = make_pipeline(
        repo,
        dense=SpySearcher([hit]),
        fts=SpySearcher([hit.model_copy(update={"source": "bm25", "score": 0.4})]),
        llm=FakeLLM([]),
    )

    result = pipeline.answer("Como pedir medida protetiva de urgência?")

    assert result.answer.abstencao is True
    assert result.answer.motivo_abstencao == "erro_recuperacao"
    assert result.answer.citacoes == []


def test_verification_error_abstains_safely() -> None:
    row = make_row(device_id="lmp/art7", version=3)
    repo = FakeRepo([row], current_version=3)
    repo.catalog[("lmp", "lmp/art7")] = {
        "device_id": "lmp/art7",
        "norm_id": "lmp",
        "artigo_id": "lmp/art7",
    }

    def judge(resposta: str, retrieved: list[RetrievedDevice]) -> list[str]:
        raise RuntimeError("judge down")

    pipeline, _, _ = make_pipeline(
        repo,
        llm=FakeLLM([llm_json(["lmp/art7"])]),
        judge=judge,
    )

    result = pipeline.answer("O que diz o art. 7º da Lei Maria da Penha?")

    assert result.answer.abstencao is True
    assert result.answer.motivo_abstencao == "erro_recuperacao"
    assert result.answer.citacoes == []


def test_llm_failure_falls_back_to_retrieved_devices() -> None:
    row = make_row(device_id="lmp/art7", version=3)
    repo = FakeRepo([row], current_version=3)
    repo.catalog[("lmp", "lmp/art7")] = {
        "device_id": "lmp/art7",
        "norm_id": "lmp",
        "artigo_id": "lmp/art7",
    }
    pipeline, _, _ = make_pipeline(repo, llm=FailingLLM())

    result = pipeline.answer("O que diz o art. 7º da Lei Maria da Penha?")

    assert result.answer.abstencao is True
    assert result.answer.motivo_abstencao == "llm_indisponivel"
    assert [citation.device_id for citation in result.answer.citacoes] == ["lmp/art7"]
    assert result.answer.citacoes[0].fonte_url == row["fonte_url"]


def test_verifier_abstention_regenerates_once_then_uses_fallback_abstain() -> None:
    row = make_row(device_id="lmp/art7", version=3)
    repo = FakeRepo([row], current_version=3)
    repo.catalog[("lmp", "lmp/art7")] = {
        "device_id": "lmp/art7",
        "norm_id": "lmp",
        "artigo_id": "lmp/art7",
    }
    llm = FakeLLM([llm_json(["lmp/art7"]), llm_json(["lmp/art7"])])

    def judge(resposta: str, retrieved: list[RetrievedDevice]) -> list[str]:
        return ["unsupported claim"]

    pipeline, _, _ = make_pipeline(repo, llm=llm, judge=judge)

    result = pipeline.answer("O que diz o art. 7º da Lei Maria da Penha?")

    assert len(llm.calls) == 2
    assert result.answer.abstencao is True
    assert result.answer.motivo_abstencao == "verificacao_falhou"
    assert result.answer.citacoes == []
    assert "Não encontrei base suficiente" in result.answer.resposta


def test_retrieved_device_vigencia_is_respected() -> None:
    row = make_row(device_id="lmp/art22", version=7, vigencia="alterado")
    repo = FakeRepo([row], current_version=7)
    hit = RetrievedDevice(
        device_id="lmp/art22",
        norm_version_id=7,
        score=0.9,
        source="dense",
        texto_literal="",
        citacao="",
    )
    dense = SpySearcher([hit])
    fts = SpySearcher([hit.model_copy(update={"source": "bm25", "score": 0.4})])
    llm = FakeLLM([llm_json(["lmp/art22"])])
    pipeline, _, _ = make_pipeline(repo, dense=dense, fts=fts, llm=llm)

    result = pipeline.answer("Como pedir medida protetiva de urgência?")

    assert result.answer.citacoes[0].vigencia == "alterado"
    assert 'vigencia="alterado"' in llm.calls[0][1]
    assert any(call[0] == "lookup" for call in repo.calls)


def test_normal_retrieval_runs_dense_and_fts_and_hydrates() -> None:
    row = make_row(device_id="lmp/art22", version=7)
    repo = FakeRepo([row], current_version=7)
    hit = RetrievedDevice(
        device_id="lmp/art22",
        norm_version_id=7,
        score=0.9,
        source="dense",
        texto_literal="",
        citacao="",
    )
    dense = SpySearcher([hit])
    fts = SpySearcher([hit.model_copy(update={"source": "bm25", "score": 0.3})])
    llm = FakeLLM([llm_json(["lmp/art22"])])
    pipeline, _, _ = make_pipeline(repo, dense=dense, fts=fts, llm=llm)

    result = pipeline.answer("Como pedir medida protetiva de urgência?")

    assert result.answer.abstencao is False
    assert result.answer.citacoes[0].texto == row["texto_literal"]
    assert dense.calls and fts.calls
    assert ("get_device_version", "lmp/art22", 7) in repo.calls


def test_no_retrieval_abstains() -> None:
    repo = FakeRepo([])
    pipeline, _, _ = make_pipeline(repo, llm=FakeLLM([]))

    result = pipeline.answer("Como pedir medida protetiva de urgência?")

    assert result.answer.abstencao is True
    assert result.answer.motivo_abstencao == "nenhum_dispositivo_recuperado"


def test_health_reports_degraded_when_dependencies_are_down() -> None:
    probe = StaticProbe(
        health_status(
            database="unavailable",
            qdrant="unavailable",
            data_atualizacao_base="2026-11-05",
        )
    )
    client = make_client(probe=probe)

    response = client.get("/health")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
    assert body["qdrant"] == "unavailable"
    assert body["data_atualizacao_base"] == "2026-11-05"
    assert probe.calls == 1


def test_health_reports_ok_when_both_dependencies_are_up() -> None:
    client = make_client(
        probe=StaticProbe(
            health_status(
                database="ok",
                qdrant="ok",
                index_version="42",
                last_ingest="2026-11-05T10:00:00+00:00",
                data_atualizacao_base="2026-11-05",
            )
        )
    )

    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["index_version"] == "42"
    assert body["last_ingest"] == "2026-11-05T10:00:00+00:00"


def test_health_status_never_fakes_ok() -> None:
    assert health_status(database="ok", qdrant="unavailable")["status"] == "degraded"
    assert health_status(database="unavailable", qdrant="ok")["status"] == "degraded"
    assert health_status(database="ok", qdrant="ok")["status"] == "ok"


def test_settings_health_probe_degrades_honestly() -> None:
    probe = SettingsHealthProbe(
        Settings(),
        data_atualizacao_base="2026-11-05",
        database_check=lambda: ("unavailable", None, None),
        qdrant_check=lambda: "unavailable",
    )

    snapshot = probe.snapshot()

    assert snapshot["status"] == "degraded"
    assert snapshot["database"] == "unavailable"
    assert snapshot["qdrant"] == "unavailable"


def test_settings_health_probe_derives_base_date_from_last_ingest() -> None:
    probe = SettingsHealthProbe(
        Settings(),
        data_atualizacao_base=None,
        database_check=lambda: ("ok", "42", "2026-11-05T10:00:00+00:00"),
        qdrant_check=lambda: "ok",
    )

    snapshot = probe.snapshot()

    assert snapshot["status"] == "ok"
    assert snapshot["data_atualizacao_base"] == "2026-11-05"


def test_source_returns_metadata_and_date_resolution() -> None:
    row = make_row(device_id="lmp/art22", version=7, vigencia="alterado")
    repo = FakeRepo([row], on_date_row=row)
    client = make_client(repo=repo)

    response = client.get("/sources/lmp/art22", params={"date": "2020-01-01"})

    body = response.json()
    assert response.status_code == 200
    assert body["device_id"] == "lmp/art22"
    assert body["norm_version_id"] == 7
    assert body["vigencia"] == "alterado"
    assert body["texto_literal"] == row["texto_literal"]
    assert body["fonte_url"] == row["fonte_url"]
    assert ("get_device_version_on", "lmp/art22", date(2020, 1, 1)) in repo.calls


def test_source_returns_requested_version() -> None:
    row = make_row(device_id="lmp/art22", version=7)
    repo = FakeRepo([row])
    client = make_client(repo=repo)

    response = client.get("/sources/lmp/art22", params={"version": 7})

    assert response.status_code == 200
    assert ("get_device_version", "lmp/art22", 7) in repo.calls


def test_source_missing_returns_404() -> None:
    client = make_client(repo=FakeRepo([]))

    response = client.get("/sources/lmp/art999", params={"version": 1})

    assert response.status_code == 404
    assert "lmp/art999" in response.json()["detail"]


def test_chat_returns_schema_and_legal_notice() -> None:
    answer = make_answer(citacoes=[make_citation()])
    pipeline = StubPipeline(PipelineResult(answer, False, "2026-11-05"))
    client = make_client(pipeline=pipeline)

    response = client.post(
        "/chat",
        json={
            "session_id": "session-1",
            "message": "Como pedir medida protetiva?",
            "facts": {"data_fato": "2026-10-01", "uf": "SP"},
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["resposta"] == answer.resposta
    assert body["citacoes"][0]["device_id"] == "lmp/art22"
    assert body["emergencia"] is False
    assert body["data_atualizacao_base"] == "2026-11-05"
    assert body["aviso_legal"].startswith(
        "Esta é uma orientação informativa e não substitui atendimento jurídico individual."
    )
    assert "2026-11-05" in body["aviso_legal"]
    assert pipeline.calls
    facts = pipeline.calls[0][1]
    assert facts.data_fato == date(2026, 10, 1)
    assert facts.uf == "SP"


def test_chat_emergency_uses_emergency_answer() -> None:
    pipeline = StubPipeline(PipelineResult(emergency_answer(), True, "2026-11-05"))
    client = make_client(pipeline=pipeline)

    body = client.post(
        "/chat",
        json={"session_id": "session-emergency", "message": "Socorro"},
    ).json()

    assert body["emergencia"] is True
    assert "190" in body["resposta"]
    assert body["citacoes"] == []


def test_chat_request_rejects_norm_version_id() -> None:
    client = make_client()

    response = client.post(
        "/chat",
        json={
            "session_id": "session-1",
            "message": "Pergunta",
            "norm_version_id": 7,
        },
    )

    assert response.status_code == 422


def test_chat_logs_do_not_contain_pii(caplog: pytest.LogCaptureFixture) -> None:
    pipeline = StubPipeline(PipelineResult(make_answer(), False, "2026-11-05"))
    client = make_client(pipeline=pipeline)
    cpf = "123.456.789-00"

    with caplog.at_level(logging.INFO, logger="src.api.main"):
        response = client.post(
            "/chat",
            json={
                "session_id": "session-pii",
                "message": f"Meu CPF é {cpf} e ele me ameaça.",
            },
        )

    assert response.status_code == 200
    assert cpf not in caplog.text
    assert "session-pii" in caplog.text
    assert "chat_request" in caplog.text


def test_chat_uses_app_base_date_when_pipeline_has_none() -> None:
    pipeline = StubPipeline(PipelineResult(make_answer(), False, None))
    client = make_client(pipeline=pipeline, data_atualizacao_base="2026-11-05")

    body = client.post(
        "/chat",
        json={"session_id": "session-1", "message": "Pergunta"},
    ).json()

    assert body["data_atualizacao_base"] == "2026-11-05"


def test_chat_pipeline_failure_returns_safe_500() -> None:
    class ExplodingPipeline:
        def answer(self, message: str, facts: Any = None) -> PipelineResult:
            raise RuntimeError("boom with CPF 123.456.789-00")

    client = make_client(pipeline=ExplodingPipeline())

    response = client.post(
        "/chat",
        json={"session_id": "session-1", "message": "Pergunta"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Não foi possível processar a solicitação agora."
    assert "boom" not in response.text
