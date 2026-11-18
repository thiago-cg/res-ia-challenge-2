from __future__ import annotations

import pytest

from src.services.municipios import buscar, carregar, mais_proximo, normalizar


def test_normaliza_acento_caixa_e_pontuacao() -> None:
    assert normalizar("  São  Paulo ") == "sao paulo"
    assert normalizar("Brasília") == "brasilia"
    assert normalizar("Sant'Ana do Livramento") == "sant ana do livramento"


def test_base_tem_todos_os_municipios_com_coordenadas_no_brasil() -> None:
    tabela = carregar()
    total = sum(len(v) for v in tabela.values())
    assert total >= 5500 and len(tabela) == 27
    for itens in tabela.values():
        for m in itens:
            assert -34 <= m.latitude <= 6 and -75 <= m.longitude <= -32


@pytest.mark.parametrize(
    ("uf", "nome", "esperado"),
    [
        ("DF", "Brasilia", "Brasília"),
        ("sp", "sao paulo", "São Paulo"),
        ("GO", "GOIÂNIA", "Goiânia"),
        ("GO", "Novo Gam", "Novo Gama"),  # prefixo único é aceito
    ],
)
def test_buscar_ignora_acento_e_caixa(uf: str, nome: str, esperado: str) -> None:
    achado = buscar(uf, nome)
    assert achado is not None and achado.nome == esperado


def test_regiao_administrativa_do_df_nao_e_municipio() -> None:
    assert buscar("DF", "Gama") is None
    assert buscar("DF", "Ceilândia") is None


def test_buscar_com_nome_curto_ou_ambiguo_nao_chuta() -> None:
    assert buscar("SP", "") is None
    assert buscar("SP", "Sa") is None  # curto demais para prefixo
    assert buscar("XX", "Brasília") is None


def test_mais_proximo_acha_o_municipio_pela_coordenada() -> None:
    achado = mais_proximo("SP", -23.55, -46.63)
    assert achado is not None and achado.nome == "São Paulo"
