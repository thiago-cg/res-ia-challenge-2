"""Delegacias a partir do OpenStreetMap (Overpass): consulta, classificação e deduplicação.

Funções puras, sem rede: o script ``scripts/import_osm_police.py`` faz a ponte com a
Overpass e o Postgres. Dados © contribuidores do OpenStreetMap, licença ODbL
(https://www.openstreetmap.org/copyright): quem exibe precisa atribuir a fonte.

O OSM não tem uma marcação própria para "delegacia da mulher": a classificação usa o
nome (heurística) e erra para os dois lados. Por isso o app sempre pede para confirmar
por telefone e deixa claro quando o dado vem do OSM.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from src.services.geo import haversine_km
from src.services.municipios import mais_proximo

UFS = ("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO").split()

_I = re.IGNORECASE
# Entra: delegacia civil ou serviço de atendimento à mulher.
_DELEGACIA = re.compile(
    r"delegacia|\bdp\b|\bdeam\b|\bdam\b|\bdem\b|distrito policial|pol[ií]cia civil|"
    r"especializada|\bdeic\b|seccional|\b\d+\s*[ªa°º]?\s*d\.?p\.?\b",
    _I,
)
# Sai: outras forças e órgãos que também são amenity=police no OSM.
_EXCLUIR = re.compile(
    r"militar|rodovi[aá]ri|federal|bombeiro|guarda|batalh|cavalaria|ambiental|penal|"
    r"prisional|t[eé]cnica|cient[ií]fica|perici|instituto|m[eé]dico.?legal|\bpmr?\b|\bppm\b|"
    r"\bcpu\b|\bbpm\b|quartel|corregedoria|detran|transito|tr[aâ]nsito",
    _I,
)
_MULHER = re.compile(r"mulher|\bdeam\b|\bdam\b|\bdem\b", _I)
_NUCLEO = re.compile(r"n[uú]cleo|nuiam", _I)


def consulta_overpass(uf: str) -> str:
    """Consulta da Overpass para todas as delegacias de um estado."""

    return (
        "[out:json][timeout:240];"
        f'area["ISO3166-2"="BR-{uf}"]["admin_level"="4"]->.a;'
        'nwr["amenity"="police"](area.a);'
        "out center tags;"
    )


def _texto(tags: dict[str, str], *chaves: str) -> str | None:
    for chave in chaves:
        valor = (tags.get(chave) or "").strip()
        if valor:
            return valor
    return None


def classificar(tags: dict[str, str]) -> str | None:
    """Tipo da delegacia ('deam', 'nucleo_atendimento_mulher', 'delegacia_comum') ou None."""

    nome = _texto(tags, "name", "official_name", "alt_name") or ""
    operador = _texto(tags, "operator") or ""
    if not nome or _EXCLUIR.search(f"{nome} {operador}"):
        return None
    if _MULHER.search(nome):
        return "nucleo_atendimento_mulher" if _NUCLEO.search(nome) else "deam"
    if _DELEGACIA.search(nome) or re.search(r"pol[ií]cia civil", operador, _I):
        return "delegacia_comum"
    return None


def _endereco(tags: dict[str, str]) -> str | None:
    rua = _texto(tags, "addr:street")
    numero = _texto(tags, "addr:housenumber")
    bairro = _texto(tags, "addr:suburb", "addr:neighbourhood")
    primeiro = ", ".join(p for p in (rua, numero) if p)
    texto = " - ".join(p for p in (primeiro, bairro) if p)
    return texto or None


def _telefone(tags: dict[str, str]) -> str | None:
    bruto = _texto(tags, "phone", "contact:phone")
    if not bruto:
        return None
    primeiro = re.split(r"[;,/]", bruto)[0].strip()
    return primeiro if len(re.sub(r"\D", "", primeiro)) >= 8 else None


def _horario(tags: dict[str, str]) -> str | None:
    bruto = _texto(tags, "opening_hours")
    return "24 horas" if bruto and bruto.replace(" ", "") in {"24/7", "Mo-Su00:00-24:00"} else None


def elemento_para_linha(
    elemento: dict[str, Any], uf: str, hoje: date | None = None
) -> dict[str, Any] | None:
    """Um elemento da Overpass vira uma linha de ``services`` (ou None se for descartado)."""

    tags = elemento.get("tags") or {}
    tipo = classificar(tags)
    if tipo is None:
        return None
    centro = elemento.get("center") or {}
    lat = elemento.get("lat", centro.get("lat"))
    lon = elemento.get("lon", centro.get("lon"))
    if lat is None or lon is None:
        return None
    nome = _texto(tags, "name", "official_name", "alt_name") or ""
    municipio = _texto(tags, "addr:city")
    if municipio is None:
        achado = mais_proximo(uf, float(lat), float(lon))
        municipio = achado.nome if achado else uf
    return {
        "uf": uf,
        "municipio": municipio,
        "nome": nome,
        "tipo": tipo,
        "endereco": _endereco(tags),
        "telefone": _telefone(tags),
        "horario": _horario(tags),
        "latitude": float(lat),
        "longitude": float(lon),
        "coordenada_verificada": True,  # ponto mapeado por pessoas, não estimado por nós
        "origem": "osm",
        "fonte_url": f"https://www.openstreetmap.org/{elemento['type']}/{elemento['id']}",
        "atualizado_em": hoje or date.today(),
    }


def _classe(tipo: str) -> str:
    return "comum" if tipo == "delegacia_comum" else "mulher"


def deduplicar(
    linhas: list[dict[str, Any]],
    existentes: list[tuple[float, float, str]] | None = None,
    raio_km: float = 0.35,
) -> list[dict[str, Any]]:
    """Remove repetidas (o mesmo posto mapeado como ponto e como prédio) e as que já existem
    nos dados curados à mão. ``existentes`` = (lat, lon, tipo) de linhas que não são do OSM."""

    mantidas: list[dict[str, Any]] = []
    for linha in sorted(linhas, key=lambda r: (r["telefone"] is None, r["nome"])):
        classe = _classe(linha["tipo"])
        repetida = any(
            _classe(m["tipo"]) == classe
            and haversine_km(linha["latitude"], linha["longitude"], m["latitude"], m["longitude"])
            <= 0.1
            for m in mantidas
        ) or any(
            _classe(tipo) == classe
            and haversine_km(linha["latitude"], linha["longitude"], lat, lon) <= raio_km
            for lat, lon, tipo in (existentes or [])
        )
        if not repetida:
            mantidas.append(linha)
    return mantidas
