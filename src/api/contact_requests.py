"""Canal Mulher–Polícia: solicitações e painel policial."""

from __future__ import annotations

import hashlib
import logging
import hmac
import time
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import token_do_cookie

COOKIE_POLICIA = "zelia_police"
SESSAO_POLICIA_SEGUNDOS = 8 * 60 * 60

logger = logging.getLogger(__name__)


class SolicitarContato(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)


class LoginPolicia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class RespostaPolicia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response: str = Field(min_length=1, max_length=4000)


def _assinatura(username: str, issued_at: str, secret: str) -> str:
    mensagem = f"{username}:{issued_at}".encode()
    return hmac.new(secret.encode(), mensagem, hashlib.sha256).hexdigest()


def _policia_autenticada(request: Request, username: str, secret: str) -> bool:
    cookie = request.cookies.get(COOKIE_POLICIA)
    if not cookie or not username or len(secret) < 32:
        return False

    try:
        issued_at, assinatura = cookie.split(".", 1)
        instante = int(issued_at)
    except (ValueError, TypeError):
        return False

    agora = int(time.time())
    if instante > agora or agora - instante > SESSAO_POLICIA_SEGUNDOS:
        return False

    esperada = _assinatura(username, issued_at, secret)
    return hmac.compare_digest(assinatura, esperada)


def criar_router(
    *,
    conectar: Callable[[], Any],
    police_username: str,
    police_password: str,
    police_secret: str,
    cookie_seguro: bool = True,
) -> APIRouter:
    from src.services import contact_requests
    from src.services.conversations import autenticar

    router = APIRouter(tags=["contact-requests"])

    def exigir_policia(request: Request) -> None:
        if not _policia_autenticada(
            request, police_username, police_secret
        ):
            raise HTTPException(
                status_code=401,
                detail="Autenticação policial necessária.",
            )

    @router.post("/contact-requests", status_code=201)
    def criar_solicitacao(
        dados: SolicitarContato,
        request: Request,
    ) -> dict:
        token = token_do_cookie(
            request,
            status_code=401,
            detail="Sessão inválida ou expirada.",
        )

        with conectar() as conn:
            conversation_id = autenticar(conn, token)
            if conversation_id is None:
                raise HTTPException(
                    status_code=401,
                    detail="Sessão inválida ou expirada.",
                )

            solicitacao = contact_requests.criar(
                conn, conversation_id, dados.message
            )
            conn.commit()

        # Notificação simulada; nenhuma unidade policial real é contatada.
        logger.info(
            "Notificação simulada: nova solicitação registrada (id=%s)",
            solicitacao["id"],
        )
        return solicitacao

    @router.get("/contact-requests/{request_id}")
    def consultar_solicitacao(
        request_id: uuid.UUID,
        request: Request,
    ) -> dict:
        token = token_do_cookie(
            request,
            status_code=401,
            detail="Sessão inválida ou expirada.",
        )

        with conectar() as conn:
            conversation_id = autenticar(conn, token)
            if conversation_id is None:
                raise HTTPException(
                    status_code=401,
                    detail="Sessão inválida ou expirada.",
                )

            solicitacao = contact_requests.obter(
                conn, request_id, conversation_id
            )

        if solicitacao is None:
            raise HTTPException(
                status_code=404,
                detail="Solicitação não encontrada.",
            )

        return solicitacao

    @router.post("/police/login")
    def login_policia(
        dados: LoginPolicia,
        response: Response,
    ) -> dict:
        if (
            not police_username
            or not police_password
            or len(police_secret) < 32
        ):
            raise HTTPException(
                status_code=503,
                detail="Painel policial não configurado.",
            )

        usuario_valido = hmac.compare_digest(
            dados.username, police_username
        )
        senha_valida = hmac.compare_digest(
            dados.password, police_password
        )

        if not (usuario_valido and senha_valida):
            raise HTTPException(
                status_code=401,
                detail="Usuário ou senha inválidos.",
            )

        issued_at = str(int(time.time()))
        assinatura = _assinatura(
            police_username, issued_at, police_secret
        )

        response.set_cookie(
            key=COOKIE_POLICIA,
            value=f"{issued_at}.{assinatura}",
            max_age=SESSAO_POLICIA_SEGUNDOS,
            httponly=True,
            samesite="strict",
            secure=cookie_seguro,
            path="/",
        )
        return {"authenticated": True}

    @router.post("/police/logout")
    def logout_policia(response: Response) -> dict:
        response.delete_cookie(
            COOKIE_POLICIA,
            path="/",
            httponly=True,
            samesite="strict",
            secure=cookie_seguro,
        )
        return {"authenticated": False}

    @router.get("/police/contact-requests")
    def listar_solicitacoes(
        request: Request,
        status: str | None = Query(
            default=None, pattern="^(pending|responded)$"
        ),
    ) -> list[dict]:
        exigir_policia(request)

        with conectar() as conn:
            return contact_requests.listar_policia(conn, status)

    @router.post("/police/contact-requests/{request_id}/response")
    def responder_solicitacao(
        request_id: uuid.UUID,
        dados: RespostaPolicia,
        request: Request,
    ) -> dict:
        exigir_policia(request)

        with conectar() as conn:
            solicitacao = contact_requests.responder(
                conn, request_id, dados.response
            )

            if solicitacao is None:
                raise HTTPException(
                    status_code=404,
                    detail="Solicitação não encontrada ou já respondida.",
                )

            conn.commit()

        return solicitacao

    return router
