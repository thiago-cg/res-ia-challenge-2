"""Verificador de coordenadas: consenso entre fontes, sem rede (as fontes são simuladas)."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "verificar_coordenadas", RAIZ / "scripts" / "verificar_coordenadas.py"
)
assert _spec and _spec.loader
v = importlib.util.module_from_spec(_spec)
sys.modules["verificar_coordenadas"] = v
_spec.loader.exec_module(v)

GAMA = (-16.0215, -48.0690)
LINHA = {
    "uf": "DF",
    "municipio": "Brasília",
    "nome": "14ª DP – Gama",
    "tipo": "delegacia_comum",
    "endereco": "Área Especial 01, Setor Central – Gama, Brasília/DF – CEP 72405-610",
    "latitude": "-16.0206",
    "longitude": "-48.0654",
    "coordenada_verificada": "false",
}


def test_extrai_cep_e_endereco_e_numero():
    assert v.extrair_cep(LINHA["endereco"]) == "72405610"
    assert v.extrair_cep("sem cep") is None
    assert (
        v.endereco_sem_cep(LINHA["endereco"])
        == "Área Especial 01, Setor Central – Gama, Brasília/DF"
    )
    assert v.numero_da_delegacia("014ª DP – Gama") == "14"
    assert v.numero_da_delegacia("DEAM I") is None


def test_brasilapi_le_as_coordenadas_e_recusa_fora_do_df():
    dentro = {"location": {"coordinates": {"latitude": "-16.0215", "longitude": "-48.0690"}}}
    assert v.ponto_da_brasilapi(dentro) == GAMA
    assert v.ponto_da_brasilapi({"location": {"coordinates": {}}}) is None
    fora = {"location": {"coordinates": {"latitude": "-23.55", "longitude": "-46.63"}}}
    assert v.ponto_da_brasilapi(fora) is None


def test_osm_agrupa_por_numero_da_delegacia():
    elementos = [
        {"lat": -16.0215, "lon": -48.0690, "tags": {"name": "14ª Delegacia de Polícia"}},
        {"center": {"lat": -15.83, "lon": -48.05}, "tags": {"name": "21ª DP Taguatinga Sul"}},
        {"lat": -15.8, "lon": -47.9, "tags": {"name": "Batalhão da Polícia Militar"}},
    ]
    grupos = v.pontos_osm_com_numero(elementos)
    assert grupos["14"] == [GAMA] and "21" in grupos and len(grupos) == 2


def test_duas_fontes_em_acordo_dao_confianca_alta():
    fontes = {
        "a": lambda _l: [GAMA],
        "b": lambda _l: [(-16.0214, -48.0689)],  # ~15 m de a
        "c": lambda _l: [(-15.90, -48.20)],  # longe: não conta
    }
    (r,) = v.verificar([LINHA], fontes)
    assert r.confianca == "alta" and r.fontes_em_acordo == ["a", "b"]
    assert abs(r.latitude - (-16.02145)) < 1e-4


def test_uma_fonte_ou_fontes_discordantes_nao_viram_verificadas():
    sozinha = v.verificar([LINHA], {"a": lambda _l: [GAMA]})[0]
    assert sozinha.confianca == "media"
    discordam = v.verificar([LINHA], {"a": lambda _l: [GAMA], "b": lambda _l: [(-16.0, -48.0)]})[0]
    assert discordam.confianca == "media"  # nenhum par a menos de 300 m
    nenhuma = v.verificar([LINHA], {"a": lambda _l: []})[0]
    assert nenhuma.confianca == "sem_acordo" and nenhuma.latitude is None


def test_ponto_achado_em_outra_cidade_e_descartado():
    longe = (-15.5, -47.4)  # dentro da caixa do DF, mas a ~70 km do ponto atual
    r = v.verificar([LINHA], {"a": lambda _l: [longe], "b": lambda _l: [longe]})[0]
    assert r.confianca == "sem_acordo"


def test_fonte_que_falha_nao_derruba_as_outras():
    def quebrada(_l):
        raise TimeoutError

    r = v.verificar([LINHA], {"x": quebrada, "a": lambda _l: [GAMA], "b": lambda _l: [GAMA]})[0]
    assert r.confianca == "alta"


def test_csv_so_muda_linhas_de_confianca_alta(tmp_path):
    ok = v.verificar([LINHA], {"a": lambda _l: [GAMA], "b": lambda _l: [GAMA]})[0]
    outra = dict(LINHA, nome="20ª DP – Gama")
    sem = v.verificar([outra], {"a": lambda _l: []})[0]
    saida = tmp_path / "saida.csv"
    campos = list(LINHA)
    atualizadas, verificadas = v.escrever_csv([ok, sem], campos, saida, marcar_verificada=True)
    linhas = list(csv.DictReader(saida.open(encoding="utf-8")))
    assert (atualizadas, verificadas) == (1, 1)
    assert linhas[0]["coordenada_verificada"] == "true" and linhas[0]["latitude"] == "-16.02150"
    assert linhas[1]["coordenada_verificada"] == "false" and linhas[1]["latitude"] == "-16.0206"
    # sem a opção, nunca marca como verificada
    v.escrever_csv([ok], campos, saida, marcar_verificada=False)
    assert list(csv.DictReader(saida.open(encoding="utf-8")))[0]["coordenada_verificada"] == "false"


def test_relatorio_e_mapa_sao_gerados(tmp_path):
    r = v.verificar([LINHA], {"a": lambda _l: [GAMA], "b": lambda _l: [GAMA]})
    v.escrever_relatorio(r, tmp_path / "r.csv")
    v.escrever_mapa(r, tmp_path / "m.html")
    assert "google.com/maps" in (tmp_path / "r.csv").read_text(encoding="utf-8")
    assert "14ª DP – Gama" in (tmp_path / "m.html").read_text(encoding="utf-8")
