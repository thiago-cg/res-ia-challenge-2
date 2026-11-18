"""T07 — persistência de execuções (integração, Postgres real).

Cobre o protocolo do worker de §21.7: criar, reivindicar com lease, concluir com *fencing*,
reconciliar e a garantia de uma execução ativa por conversa. Mock de banco não prova nada disto.

A fixture "conn" limpa as conversas criadas por estes testes (owner_hash marcado), porque o banco
é compartilhado: sem isso um run antigo em "queued" seria reivindicado no lugar do run do teste.
"""

from __future__ import annotations

import os
import uuid

import pytest

OWNER = b"\x00" * 32


@pytest.fixture
def conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Postgres not reachable; set TEST_DATABASE_URL")
    import psycopg

    conexao = psycopg.connect(url, connect_timeout=3, autocommit=False)
    _limpar(conexao)
    try:
        yield conexao
    finally:
        conexao.rollback()
        _limpar(conexao)
        conexao.close()


def _limpar(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM conversations WHERE owner_hash = %s", (OWNER,))
    conn.commit()


def _conversa(conn) -> uuid.UUID:
    cid = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO conversations (id, owner_hash, expires_at) "
            "VALUES (%s, %s, now() + interval '1 day')",
            (cid, OWNER),
        )
    conn.commit()
    return cid


def _run(conn, *, deadline: int = 90) -> tuple[uuid.UUID, uuid.UUID]:
    from src.services.runs import criar_run

    cid = _conversa(conn)
    rid = criar_run(conn, conversation_id=cid, thread_id=f"t-{cid}", deadline_segundos=deadline)
    conn.commit()
    return cid, rid


@pytest.mark.integration
def test_criar_run_nasce_queued(conn) -> None:
    from src.services.runs import obter

    _, rid = _run(conn)
    run = obter(conn, rid)
    assert run["status"] == "queued"
    assert run["attempt"] == 0
    assert run["revision"] == 1


@pytest.mark.integration
@pytest.mark.parametrize("prazo", [0, -1, -100])
def test_deadline_invalido_e_rejeitado(conn, prazo: int) -> None:
    from src.services.runs import criar_run

    cid = _conversa(conn)
    with pytest.raises(ValueError):
        criar_run(conn, conversation_id=cid, thread_id="t", deadline_segundos=prazo)


@pytest.mark.integration
def test_awaiting_input_e_encerrado_pelo_novo_turno(conn) -> None:
    """F1 da revisão delta: §21.4 prometia o encerramento e nenhum código o oferecia."""
    from src.services.runs import encerrar_pendente, obter

    _, rid = _run(conn)
    with conn.cursor() as cur:
        cur.execute("UPDATE runs SET status = 'awaiting_input' WHERE id = %s", (rid,))
    conn.commit()

    assert encerrar_pendente(conn, rid, status="succeeded") is True
    conn.commit()
    assert obter(conn, rid)["status"] == "succeeded"
    assert encerrar_pendente(conn, rid) is False


@pytest.mark.integration
def test_reivindicar_marca_running_com_lease(conn) -> None:
    from src.services.runs import reivindicar

    _, rid = _run(conn)
    run = reivindicar(conn, lease_segundos=60)
    conn.commit()
    assert run is not None
    assert run["id"] == rid
    assert run["status"] == "running"
    assert run["attempt"] == 1
    assert run["lease_until"] is not None


@pytest.mark.integration
def test_run_com_lease_valido_nao_e_reivindicado_de_novo(conn) -> None:
    """Duas abas não podem executar a mesma conversa ao mesmo tempo (AC14)."""
    from src.services.runs import reivindicar

    _run(conn)
    primeira = reivindicar(conn, lease_segundos=60)
    conn.commit()
    segunda = reivindicar(conn, lease_segundos=60)
    conn.commit()
    assert primeira is not None
    assert segunda is None


@pytest.mark.integration
def test_lease_expirado_pode_ser_reivindicado(conn) -> None:
    """Recuperação após morte do worker: o lease vence e outro processo assume."""
    from src.services.runs import obter, reivindicar

    _, rid = _run(conn, deadline=600)
    reivindicar(conn, lease_segundos=60)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE runs SET lease_until = now() - interval '5 seconds' WHERE id = %s", (rid,)
        )
    conn.commit()

    retomado = reivindicar(conn, lease_segundos=60)
    conn.commit()
    assert retomado is not None
    assert retomado["id"] == rid
    assert retomado["attempt"] == 2
    assert obter(conn, rid)["status"] == "running"


@pytest.mark.integration
def test_concluir_grava_resultado_e_estado_terminal(conn) -> None:
    from src.services.runs import concluir, obter, reivindicar

    _, rid = _run(conn)
    run = reivindicar(conn, lease_segundos=60)
    conn.commit()

    assert concluir(conn, rid, attempt=run["attempt"], resultado={"resposta": "ok"}) is True
    conn.commit()
    final = obter(conn, rid)
    assert final["status"] == "succeeded"
    assert final["finished_at"] is not None
    assert final["result_json"]["resposta"] == "ok"
    assert final["lease_until"] is None


@pytest.mark.integration
def test_concluir_duas_vezes_nao_sobrescreve_publicacao(conn) -> None:
    """A publicação é idempotente: o segundo concluir não muda o resultado."""
    from src.services.runs import concluir, obter, reivindicar

    _, rid = _run(conn)
    run = reivindicar(conn, lease_segundos=60)
    conn.commit()

    assert concluir(conn, rid, attempt=run["attempt"], resultado={"resposta": "primeira"}) is True
    conn.commit()
    assert concluir(conn, rid, attempt=run["attempt"], resultado={"resposta": "segunda"}) is False
    conn.commit()
    assert obter(conn, rid)["result_json"]["resposta"] == "primeira"


@pytest.mark.integration
def test_worker_superado_nao_publica(conn) -> None:
    """M2 da revisão: sem fencing, o worker que perdeu o lease publicava por cima do vigente."""
    from src.services.runs import concluir, obter, reivindicar

    _, rid = _run(conn, deadline=600)
    antigo = reivindicar(conn, lease_segundos=60)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE runs SET lease_until = now() - interval '5 seconds' WHERE id = %s", (rid,)
        )
    conn.commit()

    novo = reivindicar(conn, lease_segundos=60)
    conn.commit()
    assert novo is not None and novo["attempt"] == antigo["attempt"] + 1

    assert concluir(conn, rid, attempt=antigo["attempt"], resultado={"quem": "antigo"}) is False
    conn.commit()
    assert obter(conn, rid)["result_json"] is None

    assert concluir(conn, rid, attempt=novo["attempt"], resultado={"quem": "novo"}) is True
    conn.commit()
    assert obter(conn, rid)["result_json"]["quem"] == "novo"


@pytest.mark.integration
def test_conversa_apagada_nao_publica(conn) -> None:
    """M3/INV12: tombstone impede publicação tardia."""
    from src.services.runs import concluir, obter, reivindicar

    cid, rid = _run(conn)
    run = reivindicar(conn, lease_segundos=60)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("UPDATE conversations SET deleted_at = now() WHERE id = %s", (cid,))
    conn.commit()

    assert concluir(conn, rid, attempt=run["attempt"], resultado={"resposta": "tardia"}) is False
    conn.commit()
    assert obter(conn, rid)["result_json"] is None


@pytest.mark.integration
def test_uma_execucao_ativa_por_conversa_no_servico(conn) -> None:
    import psycopg

    from src.services.runs import criar_run

    cid, _ = _run(conn)
    with pytest.raises(psycopg.errors.IntegrityError):
        criar_run(conn, conversation_id=cid, thread_id=f"t2-{cid}", deadline_segundos=90)
    conn.rollback()


@pytest.mark.integration
def test_reconciliar_marca_expirados(conn) -> None:
    from src.services.runs import obter, reconciliar_expirados

    _, rid = _run(conn, deadline=1)
    with conn.cursor() as cur:
        cur.execute("UPDATE runs SET deadline = now() - interval '1 second' WHERE id = %s", (rid,))
    conn.commit()

    assert reconciliar_expirados(conn) == 1
    conn.commit()
    assert obter(conn, rid)["status"] == "expired"


@pytest.mark.integration
def test_awaiting_input_tambem_expira(conn) -> None:
    """M1 da revisão: awaiting_input não é terminal e antes ficava imortal."""
    from src.services.runs import obter, reconciliar_expirados

    _, rid = _run(conn, deadline=1)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE runs SET status = 'awaiting_input', deadline = now() - interval '1 second' "
            "WHERE id = %s",
            (rid,),
        )
    conn.commit()

    assert reconciliar_expirados(conn) == 1
    conn.commit()
    assert obter(conn, rid)["status"] == "expired"


@pytest.mark.integration
def test_cancelamento_impede_conclusao(conn) -> None:
    """INV12: cancelamento não pode ser sobrescrito por publicação tardia."""
    from src.services.runs import cancelar, concluir, obter, reivindicar

    _, rid = _run(conn)
    run = reivindicar(conn, lease_segundos=60)
    conn.commit()

    assert cancelar(conn, rid) is True
    conn.commit()
    assert concluir(conn, rid, attempt=run["attempt"], resultado={"resposta": "tardia"}) is False
    conn.commit()
    final = obter(conn, rid)
    assert final["status"] == "cancelled"
    assert final["result_json"] is None
