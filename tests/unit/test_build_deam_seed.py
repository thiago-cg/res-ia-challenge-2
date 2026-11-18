"""Extrator da lista de DEAMs do CNJ: só entra o que o IBGE confirma."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "build_deam_seed", ROOT / "scripts/build_deam_seed.py"
)
assert _spec and _spec.loader
build = importlib.util.module_from_spec(_spec)
sys.modules["build_deam_seed"] = build
_spec.loader.exec_module(build)

TEXTO = """\
        Estado              Telefone      E-mail        Endereço
Acre             (68) 3322-7440     a@b.gov.br     Avenida 25 de Agosto, nº 1923 – Bairro: 25 de Agosto
                                                    Cruzeiro do Sul/AC. Cep.: 69980-000.
Amapá            (96)2101-2953                      Avenida José de Anchieta, nº 797 – Bairro: Central
                                                    Cep: 68925-000 Município: Santana
Espírito Santo   (27)3177-7121      x@pc.es.gov.br  Rua Benjamim Costa, nº 110 – Bairro: Marista – Colatina/SE.
Mato Grosso do Sul (67) 3461-5182                   Rua Irineu Bonicontro nº 74 – Bairro Jardim Progresso
                 (67) 3461-5115                     Naviraí – MS – CEP: 79.950-000
Distrito Federal (61)3207-6195      d@pcdf.df.gov.br  EQS 204/205 – Bairro: Asa Sul
                                                    Município: Brasília
São Paulo        (11)2071-3488      l@x.sp.gov.br   Rua Sábado D
                                                    Município: São Paulo/SP Cep: 08210-790
"""  # noqa: E501


def _por_municipio(linhas):
    return {x["municipio"]: x for x in linhas}


def test_resolve_municipio_e_uf_pelo_ibge() -> None:
    linhas, _ = build.construir(TEXTO)
    por = _por_municipio(linhas)
    assert por["Cruzeiro do Sul"]["uf"] == "AC"
    assert por["Santana"]["uf"] == "AP"  # homônimo de Santana/BA: vale o rótulo/DDD
    assert por["Colatina"]["uf"] == "ES"  # o PDF escreve "Colatina/SE" por engano


def test_cidade_numa_linha_de_telefone_propria_vira_um_registro() -> None:
    linhas, _ = build.construir(TEXTO)
    nav = _por_municipio(linhas)["Naviraí"]
    assert nav["telefone"] == "(67) 3461-5182 / (67) 3461-5115"
    assert nav["endereco"] == "Rua Irineu Bonicontro nº 74 – Bairro Jardim Progresso - Naviraí/MS"


def test_endereco_nao_carrega_email_nem_cep_nem_cidade_repetida() -> None:
    linhas, _ = build.construir(TEXTO)
    end = _por_municipio(linhas)["Cruzeiro do Sul"]["endereco"]
    assert "@" not in end and "Cep" not in end and end.count("Cruzeiro do Sul") == 1


def test_endereco_incompleto_vai_para_revisao_e_nao_para_o_seed() -> None:
    linhas, revisao = build.construir(TEXTO)
    assert "São Paulo" not in _por_municipio(linhas)
    assert any("incompleto" in item for item in revisao)


def test_df_nao_entra_no_seed_do_cnj_porque_vem_da_pcdf() -> None:
    linhas, _ = build.construir(TEXTO)
    assert "Brasília" not in _por_municipio(linhas)
    assert all(x["uf"] != "DF" for x in linhas)


def test_coordenada_e_aproximada_e_marcada_como_nao_verificada() -> None:
    linhas, _ = build.construir(TEXTO)
    assert all(x["coordenada_verificada"] == "false" for x in linhas)
    assert all(x["origem"] == "cnj_2023" for x in linhas)
