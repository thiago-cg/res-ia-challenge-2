"""Rotas v1 de execução (T10) e cancelamento (T13).

Acompanhamento por revisão (ADR-06): o cliente guarda a última revisão vista e pede o delta. Se
nada mudou, a resposta é 304 sem corpo — não há replay de eventos, e o resultado final continua
recuperável mesmo quando os eventos já não interessam.

O que sai daqui é projeção pública: status, revisão e eventos genéricos. Nunca estado do grafo,
prompt, resultado bruto de ferramenta ou texto jurídico não validado (INV15).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from src.api.auth import token_do_cookie

TERMINAIS = frozenset({"succeeded", "failed", "cancelled", "expired"})


def _iso(valor: Any) -> str | None:
    return valor.isoformat() if isinstance(valor, datetime) else None


def _eventos(run: dict[str, Any]) -> list[dict[str, str | None]]:
    """Projeta os eventos a partir do próprio registro — sem tabela de eventos."""

    eventos: list[dict[str, str | None]] = [
        {"type": "run.accepted", "at": _iso(run.get("created_at"))}
    ]
    if run.get("started_at"):
        eventos.append({"type": "run.started", "at": _iso(run.get("started_at"))})

    status = run.get("status")
    if status == "succeeded":
        eventos.append({"type": "run.completed", "at": _iso(run.get("finished_at"))})
    elif status == "failed":
        eventos.append({"type": "run.failed", "at": _iso(run.get("finished_at"))})
    elif status == "cancelled":
        eventos.append({"type": "run.cancelled", "at": _iso(run.get("finished_at"))})
    elif status == "expired":
        eventos.append({"type": "run.expired", "at": _iso(run.get("finished_at"))})
    elif status == "awaiting_input":
        eventos.append({"type": "run.awaiting_input", "at": _iso(run.get("started_at"))})
    return eventos


def criar_router_runs(
    *,
    conectar: Callable[[], AbstractContextManager[Any]],
) -> APIRouter:
    from src.services.conversations import autenticar
    from src.services.runs import obter, solicitar_cancelamento

    router = APIRouter()

    def _autorizar(conn: Any, token: str, conversation_id: uuid.UUID) -> uuid.UUID:
        autenticada = autenticar(conn, token)
        if autenticada is None:
            raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")
        if autenticada != conversation_id:
            raise HTTPException(status_code=404, detail="Execução não encontrada.")
        return autenticada

    @router.get("/conversations/{conversation_id}/runs/{run_id}")
    def estado(
        conversation_id: uuid.UUID,
        run_id: uuid.UUID,
        request: Request,
        since: int | None = None,
    ) -> Any:
        token = token_do_cookie(request, status_code=401, detail="Sessão inválida ou expirada.")
        with conectar() as conn:
            _autorizar(conn, token, conversation_id)
            run = obter(conn, run_id)
            if run is None or run["conversation_id"] != conversation_id:
                raise HTTPException(status_code=404, detail="Execução não encontrada.")
            if since is not None and since == run["revision"]:
                return Response(status_code=304)
            return {
                "run_id": str(run["id"]),
                "status": run["status"],
                "revision": run["revision"],
                "events": _eventos(run),
            }

    @router.get("/conversations/{conversation_id}/runs/{run_id}/result")
    def resultado(conversation_id: uuid.UUID, run_id: uuid.UUID, request: Request) -> Any:
        token = token_do_cookie(request, status_code=401, detail="Sessão inválida ou expirada.")
        with conectar() as conn:
            _autorizar(conn, token, conversation_id)
            run = obter(conn, run_id)
            if run is None or run["conversation_id"] != conversation_id:
                raise HTTPException(status_code=404, detail="Execução não encontrada.")
            if run["status"] != "succeeded" or run["result_json"] is None:
                raise HTTPException(status_code=409, detail="Execução ainda não concluída.")
            return run["result_json"]

    @router.post("/conversations/{conversation_id}/runs/{run_id}/cancel", status_code=202)
    def cancelar_execucao(
        conversation_id: uuid.UUID, run_id: uuid.UUID, request: Request
    ) -> dict[str, str]:
        token = token_do_cookie(request, status_code=401, detail="Sessão inválida ou expirada.")
        with conectar() as conn:
            _autorizar(conn, token, conversation_id)
            run = obter(conn, run_id)
            if run is None or run["conversation_id"] != conversation_id:
                raise HTTPException(status_code=404, detail="Execução não encontrada.")
            if run["status"] in TERMINAIS:
                return {"run_id": str(run_id), "status": run["status"]}
            solicitar_cancelamento(conn, run_id)
            conn.commit()
            return {"run_id": str(run_id), "status": "cancel_requested"}

    return router
