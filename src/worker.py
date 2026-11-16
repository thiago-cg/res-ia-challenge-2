"""Worker: reivindica, executa e publica (T07/T09/T14).

Contrato com o banco — todas as decisões de durabilidade estão aqui, não no grafo:

1. "reivindicar" abre uma transação curta e commita (achado H2 da revisão do T07): a linha não
   fica travada durante a execução do modelo.
2. A execução acontece **fora** de transação.
3. A publicação abre outra transação e usa `concluir` com `attempt` — o worker que perdeu o
   lease não publica por cima do vigente.
4. Exceção vira `failed` com código tipado, nunca resultado parcial.

Uso:
    python -m src.worker            # laço contínuo
    python -m src.worker --once     # uma passada (bom para teste e para cron)
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from src.obs.logging import configure_logging, log_event

logger = logging.getLogger(__name__)

Processar = Callable[[dict[str, Any]], dict[str, Any]]


def processar_pendentes(
    *,
    conectar: Callable[[], AbstractContextManager[Any]],
    processar: Processar,
    lease_segundos: int = 60,
    max_iteracoes: int | None = None,
) -> int:
    """Processa o que estiver na fila. Devolve quantas execuções tratou."""

    from src.services.runs import concluir, falhar, reivindicar

    processados = 0
    while max_iteracoes is None or processados < max_iteracoes:
        with conectar() as conn:
            run = reivindicar(conn, lease_segundos=lease_segundos)
            conn.commit()  # transação curta: não segurar a linha durante o modelo

        if run is None:
            break

        processados += 1
        log_event(
            "run.started",
            run_id=str(run["id"]),
            attempt=run["attempt"],
            revisao=run["revision"],
        )

        try:
            resultado = processar(run)
        except Exception as exc:  # noqa: BLE001 - falha do processamento vira estado, não traceback
            logger.warning("run_failed run_id=%s error=%s", run["id"], type(exc).__name__)
            with conectar() as conn:
                falhar(
                    conn,
                    run["id"],
                    attempt=run["attempt"],
                    error_code=type(exc).__name__,
                )
                conn.commit()
            continue

        with conectar() as conn:
            publicado = concluir(conn, run["id"], attempt=run["attempt"], resultado=resultado)
            conn.commit()

        log_event(
            "run.completed" if publicado else "run.completion_rejected",
            run_id=str(run["id"]),
            attempt=run["attempt"],
        )

    return processados


def executar_manutencao(
    *, conectar: Callable[[], AbstractContextManager[Any]], settings: Any
) -> tuple[int, int]:
    """Reconcilia execucoes vencidas e purga o que passou da retencao.

    Sem este passo as funcoes existiam e nunca rodavam: conversa expirada ficava para sempre e
    execucao com prazo vencido continuava 'queued'. Devolve (expirados, purgados).
    """

    from src.services.conversations import purgar
    from src.services.runs import reconciliar_expirados

    with conectar() as conn:
        expirados = reconciliar_expirados(conn)
        conn.commit()

    with conectar() as conn:
        purgados = purgar(
            conn,
            dias_tombstone=getattr(settings, "tombstone_retention_days", 90),
            dias_expirada=getattr(settings, "conversation_retention_days", 30),
        )
        conn.commit()

    if expirados or purgados:
        log_event("manutencao", expirados=expirados, purgados=purgados)
    return expirados, purgados


def construir_processar(conectar: Callable[[], AbstractContextManager[Any]]) -> Processar:
    """Processador de produção: grafo dos dois agentes sobre o pipeline existente."""

    from src.agents.graph import build_graph
    from src.api.main import build_default_pipeline
    from src.config import get_settings
    from src.services.orchestration import construir_agentes, novo_estado, projetar

    pipeline = build_default_pipeline(get_settings(), None)
    decidir, pesquisar, sintetizar = construir_agentes(pipeline)
    grafo = build_graph(
        decidir=decidir, pesquisar=pesquisar, sintetizar=sintetizar, max_tentativas=2
    )

    def _pergunta(conn: Any, run: dict[str, Any]) -> str:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content FROM messages
                WHERE conversation_id = %s AND client_message_id = %s AND role = 'user'
                ORDER BY created_at DESC LIMIT 1
                """,
                (run["conversation_id"], run["client_message_id"]),
            )
            row = cur.fetchone()
        return row[0] if row else ""

    def _processar(run: dict[str, Any]) -> dict[str, Any]:
        with conectar() as conn:
            pergunta = _pergunta(conn, run)
        estado = novo_estado(
            conversation_id=run["conversation_id"],
            run_id=run["id"],
            pergunta=pergunta,
        )
        final = grafo.invoke(estado)
        return projetar(final)

    return _processar


def _conectar_factory():
    import psycopg

    from src.config import get_settings

    settings = get_settings()

    def _conectar():
        return psycopg.connect(settings.database_url, connect_timeout=3)

    return _conectar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Executa trabalhos aceitos pela API.")
    parser.add_argument("--once", action="store_true", help="uma passada e sai")
    parser.add_argument("--interval", type=float, default=2.0, help="segundos entre passadas")
    args = parser.parse_args(argv)

    settings_configure = configure_logging
    settings_configure("INFO")

    from src.config import get_settings

    ajustes = get_settings()
    conectar = _conectar_factory()
    processar = construir_processar(conectar)

    if args.once:
        total = processar_pendentes(
            conectar=conectar, processar=processar, lease_segundos=ajustes.run_lease_seconds
        )
        expirados, purgados = executar_manutencao(conectar=conectar, settings=ajustes)
        print(f"processados: {total} · expirados: {expirados} · purgados: {purgados}")
        return 0

    intervalo = args.interval or ajustes.worker_poll_seconds
    ciclos = 0
    while True:
        try:
            processar_pendentes(
                conectar=conectar, processar=processar, lease_segundos=ajustes.run_lease_seconds
            )
            ciclos += 1
            if ciclos % 15 == 0:
                executar_manutencao(conectar=conectar, settings=ajustes)
        except Exception:  # noqa: BLE001 - o laço não pode morrer por erro transitório
            logger.exception("worker_cycle_failed")
        time.sleep(intervalo)


if __name__ == "__main__":
    raise SystemExit(main())
