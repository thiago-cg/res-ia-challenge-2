"""Municípios do Brasil (IBGE) com latitude/longitude, para buscar "pela cidade".

Quem escolhe uma cidade em vez de compartilhar a localização recebe as delegacias
mais próximas do centro dela, com distância. Dados: ``data/seed/municipios_br.csv``
(5.570 linhas; ver ``municipios_br.LICENCA.txt``). A comparação ignora acento,
caixa e pontuação ("Sao Paulo" acha "São Paulo").
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.services.geo import haversine_km

DEFAULT_CSV = Path(__file__).resolve().parents[2] / "data" / "seed" / "municipios_br.csv"


@dataclass(frozen=True)
class Municipio:
    uf: str
    nome: str
    latitude: float
    longitude: float


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem pontuação, com espaços simples."""

    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sem_acento.casefold()).strip()


@lru_cache(maxsize=4)
def carregar(caminho: Path = DEFAULT_CSV) -> dict[str, tuple[Municipio, ...]]:
    por_uf: dict[str, list[Municipio]] = {}
    with caminho.open(encoding="utf-8", newline="") as handle:
        for linha in csv.DictReader(handle):
            item = Municipio(
                uf=linha["uf"].upper(),
                nome=linha["nome"],
                latitude=float(linha["latitude"]),
                longitude=float(linha["longitude"]),
            )
            por_uf.setdefault(item.uf, []).append(item)
    return {uf: tuple(itens) for uf, itens in por_uf.items()}


def buscar(uf: str, nome: str, caminho: Path = DEFAULT_CSV) -> Municipio | None:
    """Município do ``uf`` com esse nome. Aceita prefixo único ("Novo Gam" -> Novo Gama)."""

    candidatos = carregar(caminho).get(uf.upper(), ())
    alvo = normalizar(nome)
    if not alvo:
        return None
    exatos = [m for m in candidatos if normalizar(m.nome) == alvo]
    if exatos:
        return exatos[0]
    if len(alvo) >= 4:
        prefixo = [m for m in candidatos if normalizar(m.nome).startswith(alvo)]
        if len(prefixo) == 1:
            return prefixo[0]
    return None


def mais_proximo(
    uf: str, latitude: float, longitude: float, caminho: Path = DEFAULT_CSV
) -> Municipio | None:
    """Município do ``uf`` cujo ponto de referência está mais perto da coordenada."""

    candidatos = carregar(caminho).get(uf.upper(), ())
    if not candidatos:
        return None
    return min(candidatos, key=lambda m: haversine_km(latitude, longitude, m.latitude, m.longitude))
