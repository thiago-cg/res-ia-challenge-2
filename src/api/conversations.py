"""Rotas v1 de conversa (T09).

Aceitar trabalho é a operação mais delicada do sistema: ela precisa gravar a mensagem e criar a
execução **na mesma transação**, senão existe janela em que a pessoa vê "enviado" e nada será
executado (INV10).

Idempotência (INV05): repetir o mesmo client_message_id devolve a execução já criada, com 200 em
vez de 202, sem duplicar mensagem nem run. Conflito com execução ativa é 409 com o run corrente,
para o cliente acompanhar em vez de reenviar (AC14).

Emergência (INV09): risco imediato responde antes de qualquer acesso a banco. O bloco é fixo e
público — não há dado pessoal nele — então ele não depende de identidade. Isso é deliberado: em
uma queda de banco a orientação de emergência continua saindo.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import emitir_cookie, limpar_cookie, token_do_cookie
from src.api.schemas import ChatResponse
from src.safety.risk import classify_risk, emergency_answer

TAMANHO_MAXIMO_MENSAGEM = 8000


class NovaMensagem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=TAMANHO_MAXIMO_MENSAGEM)
    client_message_id: str = Field(min_length=1, max_length=128)


def criar_router(
    *,
    conectar: Callable[[], AbstractContextManager[Any]],
    retencao_dias: int = 30,
    deadline_segundos: int = 90,
    cookie_seguro: bool = True,
) -> APIRouter:
    """Monta as rotas com as dependências injetadas (testável sem serviço externo)."""

    from src.services.conversations import apagar, autenticar, criar_conversa, obter
    from src.services.runs import criar_run, obter_por_client_message

    router = APIRouter()

    @router.post("/conversations", status_code=201)
    def criar_conversa_rota(response: Response) -> dict[str, str]:
        with conectar() as conn:
            conversation_id, token = criar_conversa(conn, retencao_dias=retencao_dias)
            conn.commit()
        emitir_cookie(
            response,
            token,
            max_age_segundos=retencao_dias * 86400,
            seguro=cookie_seguro,
        )
        return {"conversation_id": str(conversation_id)}

    @router.post("/conversations/{conversation_id}/messages", status_code=202)
    def aceitar_mensagem(
        conversation_id: uuid.UUID,
        payload: NovaMensagem,
        request: Request,
        response: Response,
    ) -> Any:
        # 1. Emergência antes de qualquer I/O (INV09/AC06).
        if classify_risk(payload.message).immediate:
            resposta = ChatResponse.from_answer(
                emergency_answer(), emergencia=True, data_atualizacao_base=None
            )
            response.status_code = 200
            return resposta.model_dump()

        # 2. Autorização: o id não autoriza nada (INV01/INV02).
        token = token_do_cookie(request, status_code=401, detail="Sessão inválida ou expirada.")
        with conectar() as conn:
            autenticada = autenticar(conn, token)
            if autenticada is None:
                raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")
            # 404 em vez de 403: não confirma que a conversa existe
            if autenticada != conversation_id or obter(conn, autenticada) is None:
                raise HTTPException(status_code=404, detail="Conversa não encontrada.")

            # 3. Idempotência: mesma mensagem devolve a mesma execução.
            existente = obter_por_client_message(conn, autenticada, payload.client_message_id)
            if existente is not None:
                response.status_code = 200
                return {"run_id": str(existente["id"]), "status": existente["status"]}

            # 4. Aceitação durável: mensagem + execução na mesma transação.
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO messages
                        (id, conversation_id, turn_id, client_message_id, role, content)
                    VALUES (%s, %s, %s, %s, 'user', %s)
                    ON CONFLICT (conversation_id, client_message_id) DO NOTHING
                    """,
                    (
                        uuid.uuid4(),
                        autenticada,
                        payload.client_message_id,
                        payload.client_message_id,
                        payload.message,
                    ),
                )
            try:
                run_id = criar_run(
                    conn,
                    conversation_id=autenticada,
                    thread_id=f"{autenticada}:{payload.client_message_id}",
                    deadline_segundos=deadline_segundos,
                    client_message_id=payload.client_message_id,
                )
                conn.commit()
            except Exception as exc:
                conn.rollback()
                if type(exc).__name__ != "UniqueViolation":
                    raise
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, status FROM runs
                        WHERE conversation_id = %s
                          AND status IN ('queued', 'running', 'cancel_requested')
                        ORDER BY created_at DESC, id DESC
                        LIMIT 1
                        """,
                        (autenticada,),
                    )
                    ativo = cur.fetchone()
                if ativo is None:
                    raise HTTPException(status_code=409, detail="Execução em andamento.") from None
                return JSONResponse(
                    status_code=409,
                    content={"run_id": str(ativo[0]), "status": ativo[1]},
                )

        return {"run_id": str(run_id), "status": "queued"}

    @router.get("/conversations/current")
    def conversa_atual(request: Request) -> dict[str, Any]:
        """Retoma a conversa do cookie: mensagens e último resultado publicado.

        É o que permite abrir a aplicação depois de fechar a aba e ver a resposta sem reenviar
        nada. Sem o cookie, 404 — não confirma existência.
        """

        token = token_do_cookie(request, status_code=404, detail="Conversa não encontrada.")
        with conectar() as conn:
            autenticada = autenticar(conn, token)
            if autenticada is None:
                raise HTTPException(status_code=404, detail="Conversa não encontrada.")
            conversa = obter(conn, autenticada)
            if conversa is None:
                raise HTTPException(status_code=404, detail="Conversa não encontrada.")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role, content, turn_id, created_at FROM messages
                    WHERE conversation_id = %s ORDER BY created_at, id
                    """,
                    (autenticada,),
                )
                mensagens = [
                    {
                        "role": linha[0],
                        "content": linha[1],
                        "turn_id": linha[2],
                        "created_at": linha[3].isoformat() if linha[3] else None,
                    }
                    for linha in cur.fetchall()
                ]
                cur.execute(
                    """
                    SELECT result_json FROM runs
                    WHERE conversation_id = %s AND status = 'succeeded'
                    ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT 1
                    """,
                    (autenticada,),
                )
                linha_run = cur.fetchone()

        return {
            "id": str(autenticada),
            "created_at": conversa["created_at"].isoformat() if conversa["created_at"] else None,
            "expires_at": conversa["expires_at"].isoformat() if conversa["expires_at"] else None,
            "messages": mensagens,
            "last_result": linha_run[0] if linha_run else None,
        }

    @router.delete("/conversations/{conversation_id}", status_code=204)
    def excluir_conversa(conversation_id: uuid.UUID, request: Request) -> Response:
        """Tombstone + cancelamento das execuções + revogação da credencial (INV12)."""

        from src.services.runs import cancelar_ativos

        token = token_do_cookie(request, status_code=401, detail="Sessão inválida ou expirada.")
        with conectar() as conn:
            autenticada = autenticar(conn, token)
            if autenticada is None:
                raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")
            if autenticada != conversation_id:
                raise HTTPException(status_code=404, detail="Conversa não encontrada.")
            apagar(conn, autenticada)
            cancelar_ativos(conn, autenticada)
            conn.commit()

        resposta = Response(status_code=204)
        limpar_cookie(resposta, seguro=cookie_seguro)
        return resposta

    return router
