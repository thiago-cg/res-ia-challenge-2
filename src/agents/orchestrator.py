"""Orchestrator: sequences the agents, applies the review loop, keeps the trace.

Flow (see docs/12-arquitetura-multiagente.md):

    Segurança ──emergência──▶ resposta de emergência (fim)
        │ liberado
        ▼
    Recuperação ──sem base──▶ abstenção (fim)
        │ evidência
        ▼
    Resposta ◀──feedback── Verificador     (no máximo 2 tentativas)
        │ rascunho ──────────▶ │ aprovado ▶ resposta final
                               │ reprovado ▶ abstenção segura

The control flow mirrors ``LegalRAGPipeline._generate`` so answers are
identical; what changes is that each step is owned by one agent and every
hand-over is recorded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.agents.answer import AnswerAgent, Draft
from src.agents.base import ORCHESTRATOR, AgentMessage, Trace
from src.agents.retrieval import RetrievalAgent
from src.agents.safety import SafetyAgent
from src.agents.verifier import Verdict, VerifierAgent
from src.contracts import QueryFacts
from src.retrieve.query import default_facts

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class TracedResult:
    result: Any  # PipelineResult
    trace: Trace


class MultiAgentPipeline:
    """Drop-in replacement for ``LegalRAGPipeline`` with visible collaboration."""

    def __init__(self, pipeline: Any) -> None:
        self.pipeline = pipeline
        self.safety = SafetyAgent()
        self.retrieval = RetrievalAgent(pipeline)
        self.answerer = AnswerAgent(pipeline)
        self.verifier = VerifierAgent(pipeline)

    @property
    def agents(self) -> list[Any]:
        return [self.safety, self.retrieval, self.answerer, self.verifier]

    # ChatPipeline protocol -------------------------------------------------
    def answer(self, message: str, facts: QueryFacts | None = None) -> Any:
        return self.answer_traced(message, facts).result

    def answer_traced(self, message: str, facts: QueryFacts | None = None) -> TracedResult:
        trace = Trace()
        trace.start()
        pipeline = self.pipeline

        # 1. Safety --------------------------------------------------------
        risk = self.safety.assess(message, trace_id=trace.trace_id)
        trace.record(risk)
        if risk.kind == "emergencia":
            result = pipeline._result(risk.payload["answer"], emergencia=True)
            return TracedResult(result, trace)

        # 2. Retrieval -----------------------------------------------------
        found = self.retrieval.search(message, facts, trace_id=trace.trace_id)
        trace.record(found)
        evidence = found.payload["evidence"]
        if found.kind == "sem_evidencia":
            self._final(trace, f"abstenção: {evidence.abstain_reason}")
            return TracedResult(pipeline._abstain(evidence.abstain_reason), trace)

        # 3-4. Answer <-> Verifier loop ------------------------------------
        result = self._write_and_verify(message, evidence, trace)
        return TracedResult(result, trace)

    # Internals -------------------------------------------------------------
    def _write_and_verify(self, message: str, evidence: Any, trace: Trace) -> Any:
        pipeline = self.pipeline
        devices = list(evidence.devices)
        retrieved_ids = tuple(item.device_id for item in devices)
        prompt = self.answerer.build_prompt(
            message, evidence.facts or default_facts(), evidence.subquestions, devices
        )

        for attempt in range(1, MAX_ATTEMPTS + 1):
            drafted = self.answerer.draft(prompt, devices, attempt=attempt, trace_id=trace.trace_id)
            trace.record(drafted)
            draft: Draft = drafted.payload["draft"]

            if draft.status == "llm_indisponivel":
                return self._end(trace, pipeline._safe_answer(devices, "llm_indisponivel"))
            if draft.status in ("saida_invalida", "citacao_invalida"):
                if attempt == 1:
                    prompt = self.answerer.with_feedback(prompt, draft.feedback or "")
                    continue
                return self._end(trace, pipeline._safe_answer(devices, draft.status))
            if draft.status == "erro":
                return self._end(
                    trace, pipeline._abstain("erro_recuperacao", retrieved_ids=retrieved_ids)
                )
            if draft.status == "abstencao":
                return self._end(
                    trace,
                    pipeline._result(draft.answer, emergencia=False, retrieved_ids=retrieved_ids),
                )

            checked = self.verifier.check(
                draft.answer, devices, attempt=attempt, trace_id=trace.trace_id
            )
            trace.record(checked)
            verdict: Verdict = checked.payload["verdict"]

            if verdict.action == "error":
                return self._end(
                    trace, pipeline._abstain("erro_recuperacao", retrieved_ids=retrieved_ids)
                )
            if verdict.action == "accept":
                return self._end(
                    trace,
                    pipeline._result(
                        draft.answer,
                        emergencia=False,
                        retrieved_ids=retrieved_ids,
                        claims_supported=verdict.claims_supported,
                    ),
                )
            if verdict.action == "regenerate" and attempt == 1:
                prompt = self.answerer.with_feedback(prompt, "; ".join(verdict.issues))
                continue
            return self._end(
                trace, pipeline._abstain("verificacao_falhou", retrieved_ids=retrieved_ids)
            )

        return self._end(trace, pipeline._safe_answer(devices, "nao_foi_possivel_gerar"))

    def _end(self, trace: Trace, result: Any) -> Any:
        answer = result.answer
        if answer.abstencao:
            self._final(trace, f"abstenção: {answer.motivo_abstencao}")
        else:
            self._final(trace, f"resposta entregue com {len(answer.citacoes)} citação(ões)")
        return result

    def _final(self, trace: Trace, decision: str) -> None:
        trace.record(
            AgentMessage(
                sender=ORCHESTRATOR,
                recipient="usuaria",
                kind="resposta_final",
                decision=decision,
                trace_id=trace.trace_id,
            )
        )
