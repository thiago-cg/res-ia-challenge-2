"""Verifier agent: independent check of every citation and claim in a draft."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.agents.base import ORCHESTRATOR, AgentMessage
from src.contracts import Answer, RetrievedDevice
from src.generate.verify import verify

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Verdict:
    action: str  # accept | regenerate | abstain | error
    issues: tuple[str, ...] = ()
    claims_supported: tuple[bool, ...] = field(default_factory=tuple)


class VerifierAgent:
    name = "verificador"
    responsibility = (
        "Conferir se cada citação existe no contexto recuperado, se a versão é a "
        "vigente e se as afirmações são sustentadas. Decide: aceitar, pedir nova "
        "tentativa (com feedback) ou abster."
    )

    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline

    def check(
        self,
        answer: Answer,
        devices: Sequence[RetrievedDevice],
        *,
        attempt: int,
        trace_id: str = "",
    ) -> AgentMessage:
        pipeline = self._pipeline
        try:
            result = verify(
                answer,
                devices,
                repo=pipeline.repo,
                judge=pipeline.judge,
                attempt=attempt,
                max_attempts=2,
            )
        except Exception as exc:
            logger.warning("verification_failed error=%s", type(exc).__name__)
            return AgentMessage(
                sender=self.name,
                recipient=ORCHESTRATOR,
                kind="veredito",
                decision="falha na verificação: abstenção segura",
                payload={"verdict": Verdict("error")},
                trace_id=trace_id,
            )

        verdict = Verdict(
            action=result.action,
            issues=tuple(result.issues),
            claims_supported=tuple(result.claims_supported),
        )
        if verdict.action == "accept":
            ok = sum(verdict.claims_supported)
            decision = f"aprovado ({ok}/{len(verdict.claims_supported)} afirmações sustentadas)"
            recipient = ORCHESTRATOR
        elif verdict.action == "regenerate" and attempt == 1:
            decision = f"reprovado ({len(verdict.issues)} problema(s)): pede nova tentativa"
            recipient = "resposta"
        else:
            decision = "reprovado: abstenção"
            recipient = ORCHESTRATOR
        return AgentMessage(
            sender=self.name,
            recipient=recipient,
            kind="veredito",
            decision=decision,
            payload={"verdict": verdict},
            trace_id=trace_id,
        )
