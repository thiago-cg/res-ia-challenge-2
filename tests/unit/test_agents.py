"""Multi-agent layer: same answers as the pipeline, plus a visible collaboration."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from src.agents import MultiAgentPipeline
from src.api.main import LazyChatPipeline, LegalRAGPipeline
from src.contracts import RetrievedDevice
from tests.unit.test_api import (
    FailingLLM,
    FakeLLM,
    FakeRepo,
    llm_json,
    make_client,
    make_pipeline,
    make_row,
)

ART7_QUESTION = "O que diz o art. 7º da Lei Maria da Penha?"
NORMAL_QUESTION = "Como pedir medida protetiva de urgência?"
EMERGENCY = "Ele está me batendo agora."


def art7_pipeline(
    llm: Any, *, judge: Callable[..., Any] | None = None, repo: FakeRepo | None = None
) -> LegalRAGPipeline:
    repo = repo or FakeRepo([make_row(device_id="lmp/art7", version=3)], current_version=3)
    repo.catalog[("lmp", "lmp/art7")] = {
        "device_id": "lmp/art7",
        "norm_id": "lmp",
        "artigo_id": "lmp/art7",
    }
    pipeline, _, _ = make_pipeline(repo, llm=llm, judge=judge)
    return pipeline


def _flag_claims(resposta: str, retrieved: list[RetrievedDevice]) -> list[str]:
    return ["unsupported claim"]


# (name, question, factory) — each factory builds a FRESH pipeline so the legacy
# pipeline and the multi-agent one start from identical state.
SCENARIOS: list[tuple[str, str, Callable[[], LegalRAGPipeline]]] = [
    ("aceita_de_primeira", ART7_QUESTION, lambda: art7_pipeline(FakeLLM([llm_json(["lmp/art7"])]))),
    (
        "abstencao_do_modelo",
        ART7_QUESTION,
        lambda: art7_pipeline(
            FakeLLM([llm_json([], abstencao=True, motivo="sem base suficiente")])
        ),
    ),
    (
        "json_invalido_e_refaz",
        ART7_QUESTION,
        lambda: art7_pipeline(FakeLLM(["isto não é json", llm_json(["lmp/art7"])])),
    ),
    (
        "json_invalido_duas_vezes",
        ART7_QUESTION,
        lambda: art7_pipeline(FakeLLM(["lixo", "lixo"])),
    ),
    (
        "citacao_fora_do_contexto_duas_vezes",
        ART7_QUESTION,
        lambda: art7_pipeline(FakeLLM([llm_json(["cp/art999"]), llm_json(["cp/art999"])])),
    ),
    ("llm_fora_do_ar", ART7_QUESTION, lambda: art7_pipeline(FailingLLM())),
    (
        "verificador_reprova_duas_vezes",
        ART7_QUESTION,
        lambda: art7_pipeline(
            FakeLLM([llm_json(["lmp/art7"]), llm_json(["lmp/art7"])]), judge=_flag_claims
        ),
    ),
    (
        "sem_recuperacao",
        NORMAL_QUESTION,
        lambda: make_pipeline(FakeRepo([]), llm=FakeLLM([]))[0],
    ),
    (
        "emergencia",
        EMERGENCY,
        lambda: art7_pipeline(FakeLLM([llm_json(["lmp/art7"])])),
    ),
]


@pytest.mark.parametrize(("name", "question", "factory"), SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_multiagent_answers_exactly_like_the_pipeline(
    name: str, question: str, factory: Callable[[], LegalRAGPipeline]
) -> None:
    legacy = factory().answer(question)
    multi = MultiAgentPipeline(factory()).answer(question)

    assert multi.answer.model_dump() == legacy.answer.model_dump()
    assert multi.emergencia == legacy.emergencia
    assert multi.retrieved_ids == legacy.retrieved_ids
    assert multi.claims_supported == legacy.claims_supported
    assert multi.data_atualizacao_base == legacy.data_atualizacao_base


def _route(trace: Any) -> list[tuple[str, str]]:
    return [(step.agent, step.to) for step in trace.steps]


def test_trace_shows_the_four_agents_collaborating() -> None:
    multi = MultiAgentPipeline(art7_pipeline(FakeLLM([llm_json(["lmp/art7"])])))

    outcome = multi.answer_traced(ART7_QUESTION)

    assert _route(outcome.trace) == [
        ("seguranca", "recuperacao"),
        ("recuperacao", "resposta"),
        ("resposta", "verificador"),
        ("verificador", "orquestrador"),
        ("orquestrador", "usuaria"),
    ]
    assert [step.kind for step in outcome.trace.steps] == [
        "risco",
        "evidencia",
        "rascunho",
        "veredito",
        "resposta_final",
    ]
    assert outcome.result.answer.abstencao is False


def test_emergency_stops_after_the_safety_agent() -> None:
    llm = FakeLLM([llm_json(["lmp/art7"])])
    repo = FakeRepo([make_row(device_id="lmp/art7", version=3)], current_version=3)
    multi = MultiAgentPipeline(art7_pipeline(llm, repo=repo))

    outcome = multi.answer_traced(EMERGENCY)

    assert outcome.result.emergencia is True
    assert _route(outcome.trace) == [("seguranca", "orquestrador")]
    assert llm.calls == []
    assert repo.calls == []


def test_review_loop_asks_the_answer_agent_to_try_again() -> None:
    llm = FakeLLM(["isto não é json", llm_json(["lmp/art7"])])
    multi = MultiAgentPipeline(art7_pipeline(llm))

    outcome = multi.answer_traced(ART7_QUESTION)

    kinds = [step.kind for step in outcome.trace.steps]
    assert kinds.count("rascunho_rejeitado") == 1
    assert kinds.count("rascunho") == 1
    assert len(llm.calls) == 2  # never more than 2 attempts
    assert outcome.result.answer.abstencao is False


def test_verifier_rejection_sends_feedback_back_to_the_answer_agent() -> None:
    llm = FakeLLM([llm_json(["lmp/art7"]), llm_json(["lmp/art7"])])
    multi = MultiAgentPipeline(art7_pipeline(llm, judge=_flag_claims))

    outcome = multi.answer_traced(ART7_QUESTION)

    verdicts = [step for step in outcome.trace.steps if step.kind == "veredito"]
    assert [step.to for step in verdicts] == ["resposta", "orquestrador"]
    assert len(llm.calls) == 2
    assert "[FEEDBACK DA VERIFICAÇÃO]" in llm.calls[1][1]
    assert outcome.result.answer.motivo_abstencao == "verificacao_falhou"


def test_trace_never_contains_the_user_text() -> None:
    multi = MultiAgentPipeline(art7_pipeline(FakeLLM([llm_json(["lmp/art7"])])))
    outcome = multi.answer_traced(ART7_QUESTION)

    dumped = json.dumps(outcome.trace.to_list(), ensure_ascii=False)

    assert "Maria da Penha" not in dumped
    assert "art. 7" not in dumped


def test_each_agent_declares_a_single_responsibility() -> None:
    multi = MultiAgentPipeline(art7_pipeline(FakeLLM([])))

    names = [agent.name for agent in multi.agents]

    assert names == ["seguranca", "recuperacao", "resposta", "verificador"]
    assert all(agent.responsibility for agent in multi.agents)


def test_chat_returns_trace_only_when_asked() -> None:
    pipeline = MultiAgentPipeline(art7_pipeline(FakeLLM([llm_json(["lmp/art7"])])))
    client = make_client(pipeline=pipeline)

    plain = client.post("/chat", json={"session_id": "s1", "message": ART7_QUESTION})
    assert plain.status_code == 200
    assert plain.json()["trace"] is None

    pipeline = MultiAgentPipeline(art7_pipeline(FakeLLM([llm_json(["lmp/art7"])])))
    client = make_client(pipeline=pipeline)
    traced = client.post(
        "/chat", json={"session_id": "s1", "message": ART7_QUESTION, "trace": True}
    )
    body = traced.json()
    assert [step["agent"] for step in body["trace"]] == [
        "seguranca",
        "recuperacao",
        "resposta",
        "verificador",
        "orquestrador",
    ]


def test_chat_emergency_trace_has_only_the_safety_step() -> None:
    client = make_client(pipeline=MultiAgentPipeline(art7_pipeline(FakeLLM([]))))

    response = client.post("/chat", json={"session_id": "s1", "message": EMERGENCY, "trace": True})

    body = response.json()
    assert body["emergencia"] is True
    assert [step["agent"] for step in body["trace"]] == ["seguranca"]


def test_lazy_pipeline_emergency_trace_never_builds_the_pipeline() -> None:
    built: list[int] = []

    def factory() -> Any:
        built.append(1)
        raise AssertionError("must not be built for an emergency")

    outcome = LazyChatPipeline(factory).answer_traced(EMERGENCY)

    assert outcome.result.emergencia is True
    assert built == []
    assert _route(outcome.trace) == [("seguranca", "orquestrador")]
