"""Refina as coordenadas de um CSV de serviços pelo endereço (Nominatim/OpenStreetMap).

Precisa de internet e deve ser rodado por uma pessoa, uma vez, com revisão do relatório:

    uv run python scripts/geocode_services.py data/seed/services_df_pcdf.csv \
        --saida data/seed/services_df_pcdf.geocodificado.csv

Para cada linha tenta (1) endereço completo e (2) só o CEP. Só aceita o resultado se ficar a
até ``--max-km`` do ponto que a linha já tinha (o centro da região), o que descarta achados em
outra cidade. Respeita 1 requisição por segundo (política do Nominatim). Toda coordenada
continua ``coordenada_verificada=false`` até alguém conferir no mapa. Dados © contribuidores
do OpenStreetMap (ODbL).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.services.geo import haversine_km  # noqa: E402
from src.services.geocode import Geocodificador, criar_nominatim  # noqa: E402


def consultas(linha: dict[str, str]) -> list[str]:
    """Textos a tentar, do mais específico ao mais geral."""

    endereco = re.sub(r"\s*–\s*CEP.*$", "", linha["endereco"])
    cep = re.search(r"CEP\s*(\d{5}-?\d{3})", linha["endereco"])
    textos = [endereco]
    if cep:
        textos.append(cep.group(1))
    return textos


def refinar(
    linhas: list[dict[str, str]],
    geocodificar: Geocodificador,
    *,
    max_km: float = 15.0,
    pausa: Callable[[float], None] = time.sleep,
) -> tuple[list[dict[str, str]], list[str]]:
    saida: list[dict[str, str]] = []
    relatorio: list[str] = []
    for linha in linhas:
        nova = dict(linha)
        antes = (float(linha["latitude"]), float(linha["longitude"]))
        motivo = "sem resultado"
        for texto in consultas(linha):
            achado = geocodificar(linha["uf"], texto)
            pausa(1.1)
            if achado is None:
                continue
            km = haversine_km(antes[0], antes[1], achado.latitude, achado.longitude)
            if km > max_km:
                motivo = f"descartado: {km:.0f} km do ponto anterior ({texto!r})"
                continue
            nova["latitude"], nova["longitude"] = (
                f"{achado.latitude:.5f}",
                f"{achado.longitude:.5f}",
            )
            relatorio.append(f"OK    {linha['nome']}: moveu {km:.1f} km (consulta {texto!r})")
            break
        else:
            relatorio.append(f"MANTEVE {linha['nome']}: {motivo}")
        saida.append(nova)
    return saida, relatorio


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("entrada", type=Path)
    ap.add_argument("--saida", type=Path, required=True)
    ap.add_argument("--max-km", type=float, default=15.0)
    args = ap.parse_args(argv)
    with args.entrada.open(encoding="utf-8", newline="") as handle:
        leitor = csv.DictReader(handle)
        campos = list(leitor.fieldnames or [])
        linhas = list(leitor)
    novas, relatorio = refinar(linhas, criar_nominatim(), max_km=args.max_km)
    with args.saida.open("w", encoding="utf-8", newline="") as handle:
        escritor = csv.DictWriter(handle, fieldnames=campos, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(novas)
    print("\n".join(relatorio))
    moveu = sum(1 for linha in relatorio if linha.startswith("OK"))
    print(f"\n{moveu}/{len(novas)} refinadas. Confira no mapa antes de marcar como verificada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
