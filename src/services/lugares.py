from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.services.municipios import normalizar

DEFAULT_CSV = Path(__file__).resolve().parents[2] / "data" / "seed" / "localidades_br.csv"


@dataclass(frozen=True)
class Lugar:
    uf: str
    nome: str
    latitude: float
    longitude: float


@lru_cache(maxsize=4)
def carregar(caminho: Path = DEFAULT_CSV) -> tuple[Lugar, ...]:
    with caminho.open(encoding="utf-8", newline="") as handle:
        return tuple(
            Lugar(
                uf=linha["uf"].upper(),
                nome=linha["nome"],
                latitude=float(linha["latitude"]),
                longitude=float(linha["longitude"]),
            )
            for linha in csv.DictReader(handle)
        )


def _procurar(doestado: list[Lugar], alvo: str) -> Lugar | None:
    for lugar in doestado:
        if normalizar(lugar.nome) == alvo:
            return lugar
    if len(alvo) >= 4:
        prefixo = [lugar for lugar in doestado if normalizar(lugar.nome).startswith(alvo)]
        if len(prefixo) == 1:
            return prefixo[0]
    return None


def buscar(uf: str, texto: str, caminho: Path = DEFAULT_CSV) -> Lugar | None:
    """Lugar da ``uf`` com esse nome (sem acento/caixa).

    Aceita prefixo único e, se não achar, tira palavras do fim do texto
    ("Taguatinga Sul" -> "Taguatinga", "Sobradinho II" -> "Sobradinho").
    """

    alvo = normalizar(texto)
    if not alvo:
        return None
    doestado = [lugar for lugar in carregar(caminho) if lugar.uf == uf.upper()]
    achado = _procurar(doestado, alvo)
    if achado:
        return achado
    palavras = alvo.split()
    for n in range(len(palavras) - 1, 0, -1):
        achado = _procurar(doestado, " ".join(palavras[:n]))
        if achado:
            return achado
    return None
