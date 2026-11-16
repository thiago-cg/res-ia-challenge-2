"""Shared vocabulary of the multi-agent layer.

Every agent has ONE responsibility and talks to the others only through
``AgentMessage`` objects handed over by the orchestrator.  Every hand-over is
recorded in a ``Trace`` so the collaboration can be shown (API ``trace`` field,
demo script) without ever storing the user's text.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol
from uuid import uuid4

ORCHESTRATOR = "orquestrador"


class Agent(Protocol):
    """What every agent exposes besides its own task method."""

    name: str
    responsibility: str


@dataclass(frozen=True)
class AgentMessage:
    """A hand-over between two agents.

    ``kind`` names what is being delivered (``risco``, ``evidencia``,
    ``rascunho``, ``veredito``...).  ``payload`` carries the typed objects the
    receiver needs; ``decision`` is the short, text-free summary that is shown
    in the trace.
    """

    sender: str
    recipient: str
    kind: str
    decision: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    trace_id: str = ""


@dataclass(frozen=True)
class TraceStep:
    """One line of the execution trail (never contains the user's text)."""

    agent: str
    to: str
    kind: str
    decision: str
    elapsed_ms: float


@dataclass
class Trace:
    trace_id: str = field(default_factory=lambda: uuid4().hex[:12])
    steps: list[TraceStep] = field(default_factory=list)
    _mark: float = field(default_factory=time.perf_counter, repr=False)

    def start(self) -> None:
        """Restart the stopwatch; the next ``record`` measures from here."""

        self._mark = time.perf_counter()

    def record(self, message: AgentMessage) -> None:
        now = time.perf_counter()
        self.steps.append(
            TraceStep(
                agent=message.sender,
                to=message.recipient,
                kind=message.kind,
                decision=message.decision,
                elapsed_ms=round((now - self._mark) * 1000.0, 2),
            )
        )
        self._mark = now

    def to_list(self) -> list[dict[str, Any]]:
        return [asdict(step) for step in self.steps]
