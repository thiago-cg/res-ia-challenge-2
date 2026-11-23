"""Qualidade dos seeds de delegacias/DEAMs (issue #22).

Lê os CSVs de ``data/seed/services_*.csv`` sem banco e sem rede. Garante que o que o
``scripts/load_services.py`` carrega não tem duplicatas, tem coordenadas dentro do Brasil,
fonte e data, e que as lacunas conhecidas (telefone, coordenada) continuam visíveis e
não crescem sem que alguém perceba.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"
SEEDS = sorted(SEED_DIR.glob("services_*.csv"))

LAT_RANGE = (-34.0, 6.0)  # mesmos limites da constraint services_coords_check
LON_RANGE = (-75.0, -32.0)
TIPOS = {"deam", "nucleo_atendimento_mulher", "delegacia_comum"}
UFS = {
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
}
# A versão ".geocodificado" é a mesma lista com coordenadas refinadas: uma ou outra é
# carregada, nunca as duas, então ela não conta como duplicata da versão original.
ALTERNATIVAS = {"services_df_pcdf.geocodificado.csv"}

# Lacunas conhecidas, em aberto até confirmar por telefone. O teste exige que esta lista
# seja exatamente a realidade: se um telefone for preenchido, remova o nome daqui.
SEM_TELEFONE_CONHECIDO = {"15ª DP – Ceilândia Centro", "16ª DP – Planaltina"}
# Linhas ainda sem coordenada (o carregador as pula e lista no final).
SEM_COORDENADA_CONHECIDA = {
    "29ª Delegacia de Polícia (Riacho Fundo II) - Núcleo Integrado de Atendimento à Mulher",
}


def _linhas(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _com_coordenada(linha: dict[str, str]) -> bool:
    return bool(linha["latitude"].strip() and linha["longitude"].strip())


def _chave(linha: dict[str, str]) -> tuple[str, str, str, str]:
    # a mesma chave do índice único services_identity_idx
    return (linha["uf"], linha["municipio"], linha["nome"], linha["endereco"] or "")


def test_ha_seeds_para_validar() -> None:
    assert len(SEEDS) >= 3, "esperava os seeds do CNJ, do DF curado e da PCDF"


@pytest.mark.parametrize("caminho", SEEDS, ids=lambda p: p.name)
def test_sem_linhas_duplicadas_no_mesmo_arquivo(caminho: Path) -> None:
    contagem = Counter(_chave(linha) for linha in _linhas(caminho))
    assert [k for k, n in contagem.items() if n > 1] == []


def test_sem_duplicatas_entre_arquivos() -> None:
    vistos: dict[tuple[str, str, str, str], str] = {}
    repetidas = []
    for caminho in SEEDS:
        if caminho.name in ALTERNATIVAS:
            continue
        for linha in _linhas(caminho):
            chave = _chave(linha)
            if chave in vistos:
                repetidas.append((chave, vistos[chave], caminho.name))
            vistos[chave] = caminho.name
    assert repetidas == []


@pytest.mark.parametrize("caminho", SEEDS, ids=lambda p: p.name)
def test_campos_basicos_validos(caminho: Path) -> None:
    for linha in _linhas(caminho):
        nome = linha["nome"]
        assert linha["uf"] in UFS, nome
        assert linha["tipo"] in TIPOS, nome
        assert linha["municipio"].strip(), nome
        assert linha["nome"].strip()
        assert linha["fonte_url"].startswith(("http://", "https://")), nome
        date.fromisoformat(linha["atualizado_em"])  # levanta se não for AAAA-MM-DD
        assert linha["coordenada_verificada"].lower() in {"true", "false"}, nome


@pytest.mark.parametrize("caminho", SEEDS, ids=lambda p: p.name)
def test_coordenadas_dentro_do_brasil(caminho: Path) -> None:
    for linha in _linhas(caminho):
        tem_lat, tem_lon = bool(linha["latitude"].strip()), bool(linha["longitude"].strip())
        assert tem_lat == tem_lon, f"só uma coordenada preenchida: {linha['nome']}"
        if tem_lat:
            assert LAT_RANGE[0] <= float(linha["latitude"]) <= LAT_RANGE[1], linha["nome"]
            assert LON_RANGE[0] <= float(linha["longitude"]) <= LON_RANGE[1], linha["nome"]


def test_telefone_presente_nas_linhas_carregaveis() -> None:
    sem_telefone: set[str] = set()
    for caminho in SEEDS:
        if caminho.name in ALTERNATIVAS:
            continue
        for linha in _linhas(caminho):
            if _com_coordenada(linha) and not linha["telefone"].strip():
                sem_telefone.add(linha["nome"])
    assert sem_telefone == SEM_TELEFONE_CONHECIDO


def test_linhas_sem_coordenada_sao_so_as_conhecidas() -> None:
    sem_coordenada: set[str] = set()
    for caminho in SEEDS:
        if caminho.name in ALTERNATIVAS:
            continue
        sem_coordenada |= {
            linha["nome"] for linha in _linhas(caminho) if not _com_coordenada(linha)
        }
    assert sem_coordenada == SEM_COORDENADA_CONHECIDA


def test_df_tem_ao_menos_90_por_cento_com_coordenada_fonte_e_data() -> None:
    """Critério de aceite da issue #22."""
    df: list[dict[str, str]] = []
    for caminho in SEEDS:
        if caminho.name in ALTERNATIVAS:
            continue
        df += [linha for linha in _linhas(caminho) if linha["uf"] == "DF"]
    completas = [
        linha
        for linha in df
        if _com_coordenada(linha) and linha["fonte_url"].strip() and linha["atualizado_em"].strip()
    ]
    assert df, "nenhum serviço do DF nos seeds"
    assert len(completas) / len(df) >= 0.9, f"{len(completas)}/{len(df)} do DF completos"


def test_o_mapa_cobre_todas_as_ufs() -> None:
    ufs = {
        linha["uf"]
        for caminho in SEEDS
        if caminho.name not in ALTERNATIVAS
        for linha in _linhas(caminho)
        if _com_coordenada(linha)
    }
    assert ufs == UFS, f"UFs sem delegacia carregável: {sorted(UFS - ufs)}"
