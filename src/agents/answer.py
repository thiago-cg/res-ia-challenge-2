"""Answer agent: writes the plain-language answer from the retrieved devices only."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src.agents.base import ORCHESTRATOR, AgentMessage
from src.contracts import Answer, InvalidCitation, QueryFacts, RetrievedDevice
from src.generate.fallback import abstain as fallback_abstain
from src.generate.prompt import build_user_prompt
from src.generate.schemas import LLMOutputError, parse_llm_output

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Draft:
    """Outcome of one drafting attempt."""

    status: str  # ok | abstencao | llm_indisponivel | saida_invalida | citacao_invalida | erro
    answer: Answer | None = None
    reason: str | None = None
    feedback: str | None = None


class AnswerAgent:
    name = "resposta"
    responsibility = (
        "Redigir a resposta em linguagem simples usando SOMENTE os dispositivos "
        "recuperados, com citações. Aceita o feedback do Verificador para refazer."
    )

    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline

    def build_prompt(
        self,
        message: str,
        facts: QueryFacts,
        subquestions: Sequence[str],
        devices: Sequence[RetrievedDevice],
    ) -> str:
        settings = self._pipeline.settings
        return build_user_prompt(
            message,
            facts,
            list(subquestions),
            devices,
            max_devices=settings.max_devices,
            max_context_tokens=settings.max_context_tokens,
        )

    def with_feedback(self, prompt: str, feedback: str) -> str:
        return self._pipeline._feedback_prompt(prompt, feedback)

    def draft(
        self,
        prompt: str,
        devices: Sequence[RetrievedDevice],
        *,
        attempt: int,
        trace_id: str = "",
    ) -> AgentMessage:
        draft = self._draft(prompt, devices)
        if draft.status == "ok" and draft.answer is not None:
            return AgentMessage(
                sender=self.name,
                recipient="verificador",
                kind="rascunho",
                decision=f"rascunho {attempt} com {len(draft.answer.citacoes)} citação(ões)",
                payload={"draft": draft},
                trace_id=trace_id,
            )
        return AgentMessage(
            sender=self.name,
            recipient=ORCHESTRATOR,
            kind="rascunho_rejeitado",
            decision=f"tentativa {attempt}: {draft.status}",
            payload={"draft": draft},
            trace_id=trace_id,
        )

    def _draft(self, prompt: str, devices: Sequence[RetrievedDevice]) -> Draft:
        pipeline = self._pipeline
        try:
            raw = pipeline._complete(prompt, devices)
        except Exception as exc:
            logger.warning("llm_unavailable error=%s", type(exc).__name__)
            return Draft("llm_indisponivel")

        try:
            output = parse_llm_output(raw, allowed_ids={item.device_id for item in devices})
        except LLMOutputError as exc:
            return Draft("saida_invalida", feedback=str(exc))

        if output.abstencao:
            return Draft(
                "abstencao",
                answer=fallback_abstain(
                    output.motivo_abstencao or "abstencao_do_modelo",
                    retrieved=devices,
                    data_atualizacao=pipeline.data_atualizacao_base,
                ),
                reason=output.motivo_abstencao or "abstencao_do_modelo",
            )

        try:
            return Draft("ok", answer=pipeline._render_answer(output, devices))
        except InvalidCitation as exc:
            return Draft("citacao_invalida", feedback=str(exc))
        except Exception as exc:
            logger.warning("citation_render_failed error=%s", type(exc).__name__)
            return Draft("erro")
