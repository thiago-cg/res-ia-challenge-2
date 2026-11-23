"""Taguatinga Norte e Sul são lugares próprios: a busca não cai no centro de Taguatinga."""

from __future__ import annotations

from src.services.lugares import buscar
from src.services.municipios import normalizar


def test_norte_e_sul_tem_ponto_de_partida_proprio():
    geral = buscar("DF", "Taguatinga")
    norte = buscar("DF", "Taguatinga Norte")
    sul = buscar("DF", "taguatinga sul")
    assert geral and norte and sul
    assert normalizar(norte.nome) == "taguatinga norte"
    assert normalizar(sul.nome) == "taguatinga sul"
    assert norte.latitude > geral.latitude > sul.latitude  # Norte fica ao norte (lat maior)


def test_busca_sem_sufixo_continua_no_centro_da_regiao():
    assert buscar("DF", "Taguatinga").nome == "Taguatinga"
    assert buscar("DF", "Taguatinga Centro").nome == "Taguatinga"  # tira a palavra do fim
