"""T02 — spike de durabilidade (descartável, fora do pacote).

Pergunta:
    Depois de matar o processo no meio de um nó, o LangGraph retoma o run?
    Quantas vezes um efeito externo do nó é executado?

Backends: "sqlite" (SqliteSaver) e "postgres" (PostgresSaver, o da arquitetura proposta).

Não é código de produto: não está em src/, não é importado por nada e não entra no pacote
(hatch empacota só "src"). Serve para decidir a ADR-01 com execução, não com documentação.

Uso:
    python spikes/t02_durability/spike.py run --backend postgres
    python spikes/t02_durability/spike.py worker --thread T --mode naive|idempotent
        --backend postgres
    python spikes/t02_durability/spike.py resume --thread T --mode naive|idempotent
        --backend postgres
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "spike.sqlite"
SIGNAL = HERE / "node_entered.signal"
NODE_SLEEP_SECONDS = 6.0

PG_DSN = os.environ.get("SPIKE_PG_DSN", "postgresql://app:app@localhost:5432/spike_t02")
PG_MAINTENANCE_DSN = os.environ.get(
    "SPIKE_PG_MAINTENANCE_DSN", "postgresql://app:app@localhost:5432/violencia"
)


# --------------------------------------------------------------------------- efeitos (sqlite)
def connect() -> sqlite3.Connection:
    return sqlite3.connect(DB, timeout=15)


def init_db() -> None:
    con = connect()
    with con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            "CREATE TABLE IF NOT EXISTS node_runs (id INTEGER PRIMARY KEY, thread TEXT, node TEXT)"
        )
        con.execute("CREATE TABLE IF NOT EXISTS effects (id INTEGER PRIMARY KEY, thread TEXT)")
        con.execute(
            "CREATE TABLE IF NOT EXISTS publications (id INTEGER PRIMARY KEY, thread TEXT UNIQUE)"
        )
    con.close()


def reset_effects() -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB) + suffix).unlink(missing_ok=True)
    SIGNAL.unlink(missing_ok=True)
    init_db()


def counts() -> dict[str, int]:
    con = connect()
    rows = {
        table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("node_runs", "effects", "publications")
    }
    per_node = dict(con.execute("SELECT node, count(*) FROM node_runs GROUP BY node").fetchall())
    con.close()
    rows["research_execucoes"] = per_node.get("research", 0)
    rows["publish_execucoes"] = per_node.get("publish", 0)
    return rows


# --------------------------------------------------------------------------- postgres
def ensure_database() -> None:
    import psycopg

    with psycopg.connect(PG_MAINTENANCE_DSN, autocommit=True) as conn:
        target = PG_DSN.rsplit("/", 1)[-1]
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,)).fetchone()
        if exists is None:
            conn.execute(f'CREATE DATABASE "{target}"')


def pg_checkpointer():
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    conn = psycopg.connect(PG_DSN, autocommit=True, prepare_threshold=0)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver


def pg_reset_thread(thread: str) -> None:
    import psycopg

    try:
        with psycopg.connect(PG_DSN, autocommit=True) as conn:
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                conn.execute(f"DELETE FROM {table} WHERE thread_id = %s", (thread,))
    except Exception:
        pass  # tabelas ainda não existem na primeira execução


# --------------------------------------------------------------------------- grafo
def build_graph(mode: str, backend: str):
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class State(TypedDict, total=False):
        thread: str
        nota: str

    def registrar(thread: str, node: str) -> None:
        con = connect()
        with con:
            con.execute("INSERT INTO node_runs (thread, node) VALUES (?, ?)", (thread, node))
        con.close()

    def efeito(thread: str) -> None:
        """Efeito externo simulado: exatamente o tipo de chamada que não é transacional."""
        con = connect()
        with con:
            if mode == "idempotent":
                con.execute(
                    "INSERT INTO effects (thread) SELECT ? WHERE NOT EXISTS "
                    "(SELECT 1 FROM effects WHERE thread = ?)",
                    (thread, thread),
                )
            else:
                con.execute("INSERT INTO effects (thread) VALUES (?)", (thread,))
        con.close()

    def research(state: State) -> State:
        thread = state["thread"]
        registrar(thread, "research")
        efeito(thread)
        SIGNAL.write_text("entrei no nó", encoding="utf-8")  # o orquestrador mata aqui
        time.sleep(NODE_SLEEP_SECONDS)
        return {"nota": "pesquisado"}

    def publish(state: State) -> State:
        thread = state["thread"]
        registrar(thread, "publish")
        con = connect()
        with con:
            con.execute("INSERT OR IGNORE INTO publications (thread) VALUES (?)", (thread,))
        con.close()
        return {"nota": state.get("nota", "") + " + publicado"}

    builder = StateGraph(State)
    builder.add_node("research", research)
    builder.add_node("publish", publish)
    builder.add_edge(START, "research")
    builder.add_edge("research", "publish")
    builder.add_edge("publish", END)

    if backend == "postgres":
        ensure_database()
        checkpointer = pg_checkpointer()
    else:
        from langgraph.checkpoint.sqlite import SqliteSaver

        checkpointer = SqliteSaver.from_conn_string(str(DB)).__enter__()
    return builder.compile(checkpointer=checkpointer)


# --------------------------------------------------------------------------- papéis
def run_worker(thread: str, mode: str, backend: str) -> int:
    graph = build_graph(mode, backend)
    graph.invoke({"thread": thread}, {"configurable": {"thread_id": thread}})
    return 0


def run_resume(thread: str, mode: str, backend: str) -> int:
    graph = build_graph(mode, backend)
    try:
        graph.invoke(None, {"configurable": {"thread_id": thread}})  # retomar do checkpoint
    except Exception as exc:  # noqa: BLE001 - o spike precisa reportar, não esconder
        print(f"  resume levantou {type(exc).__name__}: {exc}")
        return 1
    return 0


# --------------------------------------------------------------------------- orquestração
def _spawn(*args: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, str(Path(__file__)), *args], cwd=str(HERE))


def experimento(mode: str, backend: str) -> dict[str, int]:
    print(f"\n=== backend: {backend} | variante: {mode} ===")
    thread = f"spike-{backend}-{mode}"
    SIGNAL.unlink(missing_ok=True)
    if backend == "postgres":
        ensure_database()
        pg_reset_thread(thread)

    print("  1. iniciando worker e esperando entrar no nó 'research'...")
    proc = _spawn("worker", "--thread", thread, "--mode", mode, "--backend", backend)
    deadline = time.time() + 60
    while not SIGNAL.exists() and time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"worker terminou cedo demais (exit {proc.returncode})")
        time.sleep(0.2)
    if not SIGNAL.exists():
        proc.kill()
        raise SystemExit("worker não chegou ao nó dentro do prazo")

    print("  2. matando o processo no meio do nó (TerminateProcess, sem shutdown)...")
    proc.kill()
    proc.wait(timeout=20)
    print(f"     exit code após kill: {proc.returncode} | contagens: {counts()}")

    print("  3. retomando com invoke(None, config) em um processo novo...")
    rc = _spawn("resume", "--thread", thread, "--mode", mode, "--backend", backend).wait(
        timeout=180
    )
    print(f"     exit code do resume: {rc}")

    final = counts()
    print(f"  4. contagens finais: {final}")
    print(
        "     veredito: "
        + (
            "publicação única"
            if final["publications"] == 1
            else f"publicações={final['publications']}"
        )
        + "; efeito externo "
        + ("único" if final["effects"] == 1 else f"DUPLICADO ({final['effects']}x)")
    )
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--backend", choices=("sqlite", "postgres", "both"), default="both")
    for name in ("worker", "resume"):
        p = sub.add_parser(name)
        p.add_argument("--thread", required=True)
        p.add_argument("--mode", choices=("naive", "idempotent"), required=True)
        p.add_argument("--backend", choices=("sqlite", "postgres"), required=True)
    args = parser.parse_args()

    init_db()
    if args.cmd == "worker":
        return run_worker(args.thread, args.mode, args.backend)
    if args.cmd == "resume":
        return run_resume(args.thread, args.mode, args.backend)

    backends = ("sqlite", "postgres") if args.backend == "both" else (args.backend,)
    resultados: dict[tuple[str, str], dict[str, int]] = {}
    for backend in backends:
        for mode in ("naive", "idempotent"):
            reset_effects()
            resultados[(backend, mode)] = experimento(mode, backend)

    print("\n=== resumo ===")
    print(f"{'backend':10s} {'variante':12s} {'publicacoes':>12s} {'efeitos':>8s} {'research':>9s}")
    for (backend, mode), res in resultados.items():
        print(
            f"{backend:10s} {mode:12s} {res['publications']:12d} "
            f"{res['effects']:8d} {res['research_execucoes']:9d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
