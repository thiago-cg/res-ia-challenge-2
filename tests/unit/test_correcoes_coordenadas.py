"""Correções de coordenadas do DF (verificador de 23/11/2026)."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "aplicar_correcoes_coordenadas", ROOT / "scripts" / "aplicar_correcoes_coordenadas.py"
)
modulo = importlib.util.module_from_spec(spec)
sys.modules["aplicar_correcoes_coordenadas"] = modulo
spec.loader.exec_module(modulo)

DF_LAT = (-16.1, -15.4)
DF_LON = (-48.3, -47.3)


def test_correcoes_estao_dentro_do_df_e_so_alta_vem_verificada():
    correcoes = modulo.ler_correcoes()
    assert correcoes
    for nome, linha in correcoes.items():
        assert DF_LAT[0] < float(linha["latitude"]) < DF_LAT[1], nome
        assert DF_LON[0] < float(linha["longitude"]) < DF_LON[1], nome
        assert linha["coordenada_verificada"] in {"true", "false"}
        if linha["coordenada_verificada"] == "true":
            assert "+" in linha["fontes"], f"{nome}: verificada precisa de 2+ fontes"
        else:
            assert linha["fontes"] in {"osm_mapeada", "provisorio_centro_da_regiao"}, nome


def test_aplicar_troca_so_a_linha_certa_e_e_idempotente(tmp_path):
    campos = ["uf", "nome", "latitude", "longitude", "coordenada_verificada"]
    seed = tmp_path / "seed.csv"
    with seed.open("w", newline="", encoding="utf-8") as handle:
        escritor = csv.DictWriter(handle, fieldnames=campos, lineterminator="\n")
        escritor.writeheader()
        escritor.writerow(dict(zip(campos, ["DF", "A", "-15.0", "-48.0", "false"], strict=True)))
        escritor.writerow(dict(zip(campos, ["DF", "B", "-15.1", "-48.1", "false"], strict=True)))
    correcoes = {
        "A": {
            "nome": "A",
            "latitude": "-15.5",
            "longitude": "-47.5",
            "coordenada_verificada": "true",
            "fontes": "x+y",
        }
    }
    assert len(modulo.aplicar(seed, correcoes, gravar=True)) == 1
    assert modulo.aplicar(seed, correcoes, gravar=True) == []
    linhas = list(csv.DictReader(seed.open(encoding="utf-8")))
    assert (linhas[0]["latitude"], linhas[0]["coordenada_verificada"]) == ("-15.5", "true")
    assert linhas[1]["latitude"] == "-15.1"
