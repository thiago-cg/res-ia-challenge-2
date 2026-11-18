"""Demonstração reproduzível do fluxo durável (T18).

Mostra, sem LLM e sem navegador, o que a arquitetura promete:

    aceitar -> executar no servidor -> acompanhar por revisão -> recuperar o resultado

O processador aqui é um stub: esta demonstração prova o **mecanismo** (aceitação durável,
idempotência, publicação, recuperação), não a qualidade da resposta jurídica. Para a resposta real
use o pipeline com base ingerida e `python -m src.worker`.

Uso:
    python scripts/demo_duravel.py
"""

from __future__ import annotations

import os
import sys
import uuid
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _conectar_factory(dsn: str):
    import psycopg

    @contextmanager
    def _abrir():
        conn = psycopg.connect(dsn, connect_timeout=3)
        try:
            yield conn
        finally:
            conn.close()

    return _abrir


def main() -> int:
    # Console do Windows usa cp1252 por padrão e transforma acento em mojibake.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL não definido", file=sys.stderr)
        return 1

    from src.api.conversations import criar_router
    from src.api.runs import criar_router_runs
    from src.worker import processar_pendentes

    conectar = _conectar_factory(dsn)
    app = FastAPI()
    app.include_router(
        criar_router(conectar=conectar, retencao_dias=1, deadline_segundos=90, cookie_seguro=False),
        prefix="/api/v1",
    )
    app.include_router(criar_router_runs(conectar=conectar), prefix="/api/v1")
    cliente = TestClient(app)

    print("1. criando conversa")
    criada = cliente.post("/api/v1/conversations")
    conversation_id = criada.json()["conversation_id"]
    print(f"   conversa: {conversation_id}")

    print("2. enviando pergunta (aceitação durável)")
    envio = cliente.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": "Qual o prazo para representar?", "client_message_id": "demo-1"},
    )
    run_id = envio.json()["run_id"]
    print(f"   status HTTP: {envio.status_code} · run: {run_id}")

    print("3. repetindo o mesmo envio (idempotência)")
    repetido = cliente.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": "Qual o prazo para representar?", "client_message_id": "demo-1"},
    )
    print(
        f"   status HTTP: {repetido.status_code} · mesmo run: {repetido.json()['run_id'] == run_id}"
    )

    print("4. executando no servidor, sem cliente conectado")

    def processar(run):
        return {
            "resposta": "Resposta de demonstração: o mecanismo funcionou.",
            "citacoes": [],
            "proximos_passos": [],
            "encaminhamentos": [],
            "premissas": [],
            "nivel_confianca": "baixo",
            "abstencao": True,
            "motivo_abstencao": "demonstracao",
            "emergencia": False,
            "data_atualizacao_base": None,
            "aviso_legal": "Demonstração de mecanismo, não de conteúdo jurídico.",
        }

    processados = processar_pendentes(conectar=conectar, processar=processar, lease_segundos=60)
    print(f"   execuções processadas: {processados}")

    print("5. acompanhando por revisão")
    estado = cliente.get(f"/api/v1/conversations/{conversation_id}/runs/{run_id}").json()
    print(f"   status: {estado['status']} · revisão: {estado['revision']}")
    print(f"   eventos: {[e['type'] for e in estado['events']]}")

    print("6. recuperando o resultado")
    resultado = cliente.get(f"/api/v1/conversations/{conversation_id}/runs/{run_id}/result")
    print(
        f"   status HTTP: {resultado.status_code} · resposta: {resultado.json()['resposta'][:48]}…"
    )

    print("7. limpando a conversa de demonstração")
    print(
        f"   status HTTP: {cliente.delete(f'/api/v1/conversations/{conversation_id}').status_code}"
    )
    with conectar() as conn:
        conn.execute("DELETE FROM conversations WHERE id = %s", (uuid.UUID(conversation_id),))
        conn.commit()

    print("\ndemonstração concluída.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
