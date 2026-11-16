"""Cookie de capacidade e dependência de autorização (T08, ADR-02).

O cookie é o único portador de identidade. Ele é opaco, HttpOnly, SameSite=Lax e Secure quando
houver TLS; o servidor guarda apenas o hash (src/services/conversations.py).

Nada aqui assume que "session_id", "conversation_id" ou "thread_id" autorizam alguma coisa.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

COOKIE_NOME = "zelia_owner"

__all__ = [
    "COOKIE_NOME",
    "ConversaAutenticada",
    "dependencia_conversa",
    "emitir_cookie",
    "limpar_cookie",
]


@dataclass(frozen=True)
class ConversaAutenticada:
    """Contexto de autorização resolvido. Só existe depois de validar o token."""

    conversation_id: uuid.UUID


def emitir_cookie(
    resposta: Response,
    token: str,
    *,
    max_age_segundos: int,
    seguro: bool = True,
) -> None:
    resposta.set_cookie(
        key=COOKIE_NOME,
        value=token,
        max_age=max_age_segundos,
        httponly=True,
        samesite="lax",
        secure=seguro,
        path="/",
    )


def limpar_cookie(resposta: Response) -> None:
    resposta.delete_cookie(
        COOKIE_NOME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=True,
    )


def dependencia_conversa(
    autenticador: Callable[[str | None], uuid.UUID | None],
) -> Callable[[Request], ConversaAutenticada]:
    """Monta a dependência a partir de um autenticador injetado (testável sem banco)."""

    def _dependencia(request: Request) -> ConversaAutenticada:
        conversation_id = autenticador(request.cookies.get(COOKIE_NOME))
        if conversation_id is None:
            # 401 sem detalhe: não confirma se a conversa existe ou se o token só expirou
            raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")
        return ConversaAutenticada(conversation_id)

    return _dependencia
