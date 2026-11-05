import json
import logging
from datetime import date

import pytest

from src.contracts import QueryFacts
from src.retrieve.query import QUERY_UNDERSTANDING_PROMPT_V1, understand_query

VALID_PAYLOAD = {
    "fatos": {
        "relacao": "ex-companheiro",
        "tipo_violencia": ["fisica", "psicologica"],
        "urgencia": "recente",
        "data_fato": "2026-01-02",
        "uf": "SP",
    },
    "consulta_juridica": "Quais medidas protetivas cabem?",
    "subperguntas": ["medidas protetivas", "prazo para denunciar", "registro de ocorrência"],
}


def make_facts(**overrides: object) -> QueryFacts:
    data = {
        "relacao": "companheiro",
        "tipo_violencia": ["fisica"],
        "urgencia": "imediata",
        "data_fato": date(2025, 5, 4),
        "uf": "RJ",
    }
    data.update(overrides)
    return QueryFacts(**data)


def test_prompt_is_versioned_and_contains_schema() -> None:
    assert "query_understanding_v1" in QUERY_UNDERSTANDING_PROMPT_V1
    for key in (
        "fatos",
        "relacao",
        "tipo_violencia",
        "urgencia",
        "data_fato",
        "uf",
        "consulta_juridica",
        "subperguntas",
    ):
        assert key in QUERY_UNDERSTANDING_PROMPT_V1


def test_deterministic_fallback_without_llm() -> None:
    plan = understand_query("Meu ex-marido me ameaçou")
    assert plan.consulta_juridica == "Meu ex-marido me ameaçou"
    assert plan.subperguntas == ["Meu ex-marido me ameaçou"]
    assert plan.fatos.relacao == "desconhecido"
    assert plan.fatos.tipo_violencia == []
    assert plan.fatos.urgencia == "desconhecida"
    assert plan.fatos.data_fato is None
    assert plan.fatos.uf is None


def test_llm_valid_json_is_parsed() -> None:
    prompts: list[str] = []

    def fake_llm(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(VALID_PAYLOAD)

    plan = understand_query("Ele me empurrou", llm_call=fake_llm)

    assert "Ele me empurrou" in prompts[0]
    assert "query_understanding_v1" in prompts[0]
    assert plan.fatos.relacao == "ex-companheiro"
    assert plan.fatos.tipo_violencia == ["fisica", "psicologica"]
    assert plan.fatos.urgencia == "recente"
    assert plan.fatos.data_fato == date(2026, 1, 2)
    assert plan.fatos.uf == "SP"
    assert plan.consulta_juridica == "Quais medidas protetivas cabem?"
    assert plan.subperguntas == [
        "medidas protetivas",
        "prazo para denunciar",
        "registro de ocorrência",
    ]


def test_invalid_json_falls_back_to_raw_question(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        plan = understand_query("Preciso de ajuda", llm_call=lambda _: "isto não é json")

    assert plan.consulta_juridica == "Preciso de ajuda"
    assert plan.subperguntas == ["Preciso de ajuda"]
    assert plan.fatos.relacao == "desconhecido"
    assert plan.fatos.data_fato is None
    assert "invalid" in caplog.text.lower() or "fallback" in caplog.text.lower()


def test_schema_failure_falls_back() -> None:
    payload = json.loads(json.dumps(VALID_PAYLOAD))
    payload["fatos"]["relacao"] = "amigo"
    plan = understand_query("Pergunta", llm_call=lambda _: json.dumps(payload))
    assert plan.subperguntas == ["Pergunta"]
    assert plan.fatos.relacao == "desconhecido"


def test_llm_exception_falls_back() -> None:
    def failing(_: str) -> str:
        raise TimeoutError("llm timed out")

    plan = understand_query("Pergunta original", llm_call=failing)
    assert plan.consulta_juridica == "Pergunta original"
    assert plan.subperguntas == ["Pergunta original"]
    assert plan.fatos.data_fato is None


def test_subquestions_are_truncated() -> None:
    payload = json.loads(json.dumps(VALID_PAYLOAD))
    payload["subperguntas"] = ["a", "b", "c", "d", "e"]

    plan = understand_query("Pergunta", llm_call=lambda _: json.dumps(payload))
    assert plan.subperguntas == ["a", "b", "c"]


def test_max_subquestions_parameter_is_respected() -> None:
    payload = json.loads(json.dumps(VALID_PAYLOAD))
    payload["subperguntas"] = ["a", "b", "c"]

    plan = understand_query("Pergunta", llm_call=lambda _: json.dumps(payload), max_subquestions=2)
    assert plan.subperguntas == ["a", "b"]


def test_empty_subquestions_fall_back_to_original_question() -> None:
    payload = json.loads(json.dumps(VALID_PAYLOAD))
    payload["subperguntas"] = []

    plan = understand_query("Pergunta original", llm_call=lambda _: json.dumps(payload))
    assert plan.subperguntas == ["Pergunta original"]


def test_caller_facts_are_preserved() -> None:
    provided = make_facts()

    def fake_llm(_: str) -> str:
        payload = json.loads(json.dumps(VALID_PAYLOAD))
        payload["fatos"]["data_fato"] = "2020-01-01"
        payload["fatos"]["uf"] = "AM"
        return json.dumps(payload)

    plan = understand_query("Pergunta", facts=provided, llm_call=fake_llm)
    assert plan.fatos == provided


def test_date_is_never_invented() -> None:
    payload = json.loads(json.dumps(VALID_PAYLOAD))
    payload["fatos"]["data_fato"] = None
    plan = understand_query("Pergunta", llm_call=lambda _: json.dumps(payload))
    assert plan.fatos.data_fato is None

    payload_without_date = json.loads(json.dumps(VALID_PAYLOAD))
    del payload_without_date["fatos"]["data_fato"]
    plan = understand_query("Pergunta", llm_call=lambda _: json.dumps(payload_without_date))
    assert plan.fatos.data_fato is None


def test_invalid_date_falls_back_without_inventing() -> None:
    payload = json.loads(json.dumps(VALID_PAYLOAD))
    payload["fatos"]["data_fato"] = "2026-13-40"

    plan = understand_query("Pergunta", llm_call=lambda _: json.dumps(payload))
    assert plan.subperguntas == ["Pergunta"]
    assert plan.fatos.data_fato is None


def test_fenced_json_is_accepted() -> None:
    fenced = "```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"
    plan = understand_query("Pergunta", llm_call=lambda _: fenced)
    assert plan.fatos.relacao == "ex-companheiro"
    assert len(plan.subperguntas) == 3
