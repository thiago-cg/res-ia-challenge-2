"""T08 — identidade e autorização por cookie de capacidade (integração).

A regra central: o id da conversa NÃO autoriza nada (INV01/INV02). Só o token emitido na criação,
guardado como hash, permite ler. Estes testes existem antes de src/services/conversations.py.
"""

from __future__ import annotations

import os
import uuid

import pytest

OWNER_MARCADOR = "teste-t08-"


@pytest.fixture
def conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Postgres not reachable; set TEST_DATABASE_URL")
    import psycopg

    conexao = psycopg.connect(url, connect_timeout=3, autocommit=False)
    try:
        yield conexao
    finally:
        conexao.rollback()
        conexao.close()


def _limpar_ids(conn, ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM conversations WHERE id = ANY(%s)", (ids,))
    conn.commit()


@pytest.mark.integration
def test_criar_devolve_token_que_autentica(conn) -> None:
    from src.services.conversations import autenticar, criar_conversa

    cid, token = criar_conversa(conn)
    conn.commit()
    try:
        assert len(token) >= 32
        assert autenticar(conn, token) == cid
    finally:
        _limpar_ids(conn, [cid])


@pytest.mark.integration
def test_token_nao_e_gravado_em_claro(conn) -> None:
    from src.services.conversations import criar_conversa

    cid, token = criar_conversa(conn)
    conn.commit()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT owner_hash FROM conversations WHERE id = %s", (cid,))
            guardado = cur.fetchone()[0]
        assert isinstance(guardado, bytes)
        assert len(guardado) == 32
        import hashlib

        assert guardado == hashlib.sha256(token.encode("utf-8")).digest()
        assert guardado != token.encode("utf-8")
    finally:
        _limpar_ids(conn, [cid])


@pytest.mark.integration
def test_token_de_um_nao_autentica_outro(conn) -> None:
    """AC07: saber que a conversa A existe não dá acesso a ela."""
    from src.services.conversations import autenticar, criar_conversa

    cid_a, token_a = criar_conversa(conn)
    cid_b, token_b = criar_conversa(conn)
    conn.commit()
    try:
        assert autenticar(conn, token_a) == cid_a
        assert autenticar(conn, token_b) == cid_b
        assert autenticar(conn, token_a) != cid_b
    finally:
        _limpar_ids(conn, [cid_a, cid_b])


@pytest.mark.integration
@pytest.mark.parametrize("token", ["", "x", "0" * 43, "token-inventado"])
def test_token_invalido_nao_autentica(conn, token: str) -> None:
    from src.services.conversations import autenticar

    assert autenticar(conn, token) is None


@pytest.mark.integration
def test_conversa_apagada_nao_autentica(conn) -> None:
    from src.services.conversations import apagar, autenticar, criar_conversa

    cid, token = criar_conversa(conn)
    conn.commit()
    try:
        assert apagar(conn, cid) is True
        conn.commit()
        assert autenticar(conn, token) is None
    finally:
        _limpar_ids(conn, [cid])


@pytest.mark.integration
def test_conversa_expirada_nao_autentica(conn) -> None:
    from src.services.conversations import autenticar, criar_conversa

    cid, token = criar_conversa(conn, retencao_dias=1)
    conn.commit()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET expires_at = now() - interval '1 second' WHERE id = %s",
                (cid,),
            )
        conn.commit()
        assert autenticar(conn, token) is None
    finally:
        _limpar_ids(conn, [cid])


@pytest.mark.integration
def test_apagar_e_idempotente(conn) -> None:
    from src.services.conversations import apagar, criar_conversa

    cid, _ = criar_conversa(conn)
    conn.commit()
    try:
        assert apagar(conn, cid) is True
        assert apagar(conn, cid) is False
    finally:
        _limpar_ids(conn, [cid])


@pytest.mark.integration
def test_apagar_nao_reencontra_conversa(conn) -> None:
    from src.services.conversations import apagar, criar_conversa, obter

    cid, token = criar_conversa(conn)
    conn.commit()
    try:
        apagar(conn, cid)
        conn.commit()
        assert obter(conn, cid) is None
        assert obter(conn, cid, incluir_apagadas=True)["deleted_at"] is not None
    finally:
        _limpar_ids(conn, [cid])


@pytest.mark.integration
def test_obter_nao_expoe_owner_hash(conn) -> None:
    """Achado 3 da revisão do T08: a projeção não devolve o material de autenticação."""
    from src.services.conversations import criar_conversa, obter

    cid, _ = criar_conversa(conn)
    conn.commit()
    try:
        linha = obter(conn, cid)
        assert linha is not None
        assert "owner_hash" not in linha
        assert set(linha) == {
            "id",
            "created_at",
            "last_seen_at",
            "expires_at",
            "deleted_at",
            "purged_at",
        }
    finally:
        _limpar_ids(conn, [cid])


@pytest.mark.integration
def test_purgar_remove_tombstone_antigo_e_preserva_recente(conn) -> None:
    """Achado 1/4 da revisão: a purga não tinha prova nenhuma."""
    from src.services.conversations import apagar, criar_conversa, obter, purgar

    antiga, _ = criar_conversa(conn)
    recente, _ = criar_conversa(conn)
    conn.commit()
    try:
        apagar(conn, antiga)
        apagar(conn, recente)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET deleted_at = now() - interval '200 days' WHERE id = %s",
                (antiga,),
            )
        conn.commit()

        assert purgar(conn, dias_tombstone=90, dias_expirada=90) == 1
        conn.commit()
        assert obter(conn, antiga, incluir_apagadas=True) is None
        assert obter(conn, recente, incluir_apagadas=True) is not None
    finally:
        _limpar_ids(conn, [antiga, recente])


@pytest.mark.integration
def test_purgar_remove_conversa_expirada(conn) -> None:
    """A retenção de §21.9 tem de ser aplicada a quem nunca foi apagada."""
    from src.services.conversations import criar_conversa, obter, purgar

    cid, _ = criar_conversa(conn)
    conn.commit()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET expires_at = now() - interval '100 days' WHERE id = %s",
                (cid,),
            )
        conn.commit()

        assert purgar(conn, dias_tombstone=90, dias_expirada=30) == 1
        conn.commit()
        assert obter(conn, cid, incluir_apagadas=True) is None
    finally:
        _limpar_ids(conn, [cid])


@pytest.mark.integration
@pytest.mark.parametrize("janela", [-1, -100])
def test_purgar_rejeita_janela_negativa(conn, janela: int) -> None:
    """purgar(dias=0) apagava tudo; o guarda espelha o de criar_conversa."""
    from src.services.conversations import purgar

    with pytest.raises(ValueError):
        purgar(conn, dias_tombstone=janela)
