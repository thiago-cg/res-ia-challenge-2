"""Safety agent: decides whether the conversation must be cut short."""

from __future__ import annotations

from src.agents.base import ORCHESTRATOR, AgentMessage
from src.safety.risk import classify_risk, emergency_answer


class SafetyAgent:
    name = "seguranca"
    responsibility = (
        "Detectar risco imediato na mensagem. Se houver, interrompe o fluxo e "
        "entrega a resposta de emergência (190/180); se não, libera para a recuperação."
    )

    def assess(self, message: str, *, trace_id: str = "") -> AgentMessage:
        risk = classify_risk(message)
        if risk.immediate:
            return AgentMessage(
                sender=self.name,
                recipient=ORCHESTRATOR,
                kind="emergencia",
                decision=f"risco imediato ({risk.kind or 'não classificado'}): fluxo interrompido",
                payload={"answer": emergency_answer(), "risk": risk},
                trace_id=trace_id,
            )
        return AgentMessage(
            sender=self.name,
            recipient="recuperacao",
            kind="risco",
            decision="sem risco imediato: segue para recuperação",
            payload={"risk": risk},
            trace_id=trace_id,
        )
