"""Seed das DPs do DF (PCDF) e refinamento de coordenadas por geocodificação."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

from src.services.lugares import Lugar

ROOT = Path(__file__).resolve().parents[2]


def _carregar(nome: str):  # noqa: ANN202
    spec = importlib.util.spec_from_file_location(nome, ROOT / f"scripts/{nome}.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo
    spec.loader.exec_module(modulo)
    return modulo


pcdf = _carregar("build_pcdf_seed")
geocodificar_csv = _carregar("geocode_services")


def _entrada() -> list[dict[str, str]]:
    with (ROOT / "data/seed/pcdf_delegacias_dataset.csv").open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_seed_do_df_tem_as_dps_reais_e_nao_as_deam() -> None:
    linhas, _ = pcdf.construir(_entrada())
    nomes = [x["nome"] for x in linhas]
    assert len(nomes) == 31 and "14ª DP – Gama" in nomes and "20ª DP – Gama" in nomes
    assert not any(n.startswith("DEAM") for n in nomes)
    assert all(x["tipo"] == "delegacia_comum" and x["origem"] == "pcdf" for x in linhas)
    assert all(x["coordenada_verificada"] == "false" for x in linhas)


def test_dp_sem_endereco_so_entra_com_endereco_do_cnj_e_avisa() -> None:
    linhas, revisao = pcdf.construir(_entrada())
    lago_norte = next(x for x in linhas if "Lago Norte" in x["nome"])
    assert "SHIN 3/5" in lago_norte["endereco"] and lago_norte["telefone"] == "(61) 3207-6943"
    assert any("09ª DP" in r and "CNJ" in r for r in revisao)


def test_dps_do_gama_usam_a_coordenada_do_arquivo_e_ficam_distintas() -> None:
    linhas, _ = pcdf.construir(_entrada())
    gama = [x for x in linhas if "Gama" in x["nome"]]
    assert {x["latitude"] for x in gama} == {"-16.01675", "-16.00934"}


def test_telefone_vinculado_por_inferencia_aparece_na_revisao() -> None:
    _, revisao = pcdf.construir(_entrada())
    assert any("14ª DP" in r and "confirmar" in r for r in revisao)
    assert any("15ª DP" in r and "sem telefone" in r for r in revisao)


LINHA = {
    "uf": "DF", "nome": "X", "latitude": "-15.80000", "longitude": "-48.10000",
    "endereco": "QNM 02, Conjunto G/H – Ceilândia, Brasília/DF – CEP 72210-020",
}  # fmt: skip


def test_geocodificacao_aceita_perto_e_descarta_longe() -> None:
    perto = lambda uf, texto: Lugar(uf, texto, -15.8201, -48.1085)  # noqa: E731
    novas, rel = geocodificar_csv.refinar([LINHA], perto, pausa=lambda s: None)
    assert novas[0]["latitude"] == "-15.82010" and rel[0].startswith("OK")

    longe = lambda uf, texto: Lugar(uf, texto, -8.05, -34.9)  # noqa: E731
    novas, rel = geocodificar_csv.refinar([LINHA], longe, pausa=lambda s: None)
    assert novas[0]["latitude"] == "-15.80000" and rel[0].startswith("MANTEVE")


def test_geocodificacao_tenta_o_cep_quando_o_endereco_nao_acha() -> None:
    pedidos: list[str] = []

    def so_cep(uf: str, texto: str):  # noqa: ANN202
        pedidos.append(texto)
        return Lugar(uf, texto, -15.8201, -48.1085) if texto == "72210-020" else None

    novas, _ = geocodificar_csv.refinar([LINHA], so_cep, pausa=lambda s: None)
    assert pedidos[-1] == "72210-020" and novas[0]["latitude"] == "-15.82010"
