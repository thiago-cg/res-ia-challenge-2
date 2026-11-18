"""Retrieval agent: finds the legal devices that must ground the answer."""

from __future__ import annotations

from typing import Any

from src.agents.base import ORCHESTRATOR, AgentMessage
from src.contracts import QueryFacts


class RetrievalAgent:
    name = "recuperacao"
    responsibility = (
        "Entender a pergunta, buscar os dispositivos legais (densa/híbrida), "
        "ranquear, deduplicar por artigo e hidratar o texto oficial. "
        "Se não houver base, devolve o motivo da abstenção."
    )

    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline

    def search(
        self, message: str, facts: QueryFacts | None = None, *, trace_id: str = ""
    ) -> AgentMessage:
        evidence = self._pipeline.retrieve(message, facts)
        if evidence.abstain_reason is not None:
            return AgentMessage(
                sender=self.name,
                recipient=ORCHESTRATOR,
                kind="sem_evidencia",
                decision=f"sem base suficiente: {evidence.abstain_reason}",
                payload={"evidence": evidence},
                trace_id=trace_id,
            )
        origin = "citação explícita" if evidence.explicit else "busca"
        return AgentMessage(
            sender=self.name,
            recipient="resposta",
            kind="evidencia",
            decision=f"{len(evidence.devices)} dispositivo(s) por {origin}",
            payload={"evidence": evidence},
            trace_id=trace_id,
        )
