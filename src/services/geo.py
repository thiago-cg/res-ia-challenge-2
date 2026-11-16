"""Distance math and the nearest-service search.

Pure Python on purpose: the table holds a few thousand rows at most, so a bounding-box
prefilter in SQL plus Haversine here is simple, testable and needs no PostGIS.

Privacy: this module never logs or stores the coordinates it receives.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

EARTH_RADIUS_KM = 6371.0088

#: Search radii in km, tried in order until something is found.
RADII_KM: tuple[float, ...] = (25.0, 100.0, 400.0, 1500.0)
#: Beyond this distance the answer says "nothing registered near you".
NEAR_KM = 50.0

TIPOS = ("deam", "nucleo_atendimento_mulher", "delegacia_comum")


@dataclass(frozen=True)
class ServicePoint:
    id: int
    nome: str
    tipo: str
    uf: str
    municipio: str
    endereco: str | None
    telefone: str | None
    horario: str | None
    latitude: float
    longitude: float
    fonte_url: str
    atualizado_em: date
    coordenada_verificada: bool = False


class ServicesSource(Protocol):
    def candidates(
        self,
        lat_min: float,
        lat_max: float,
        lon_min: float,
        lon_max: float,
        tipo: str | None = None,
    ) -> Sequence[ServicePoint]: ...

    def by_municipio(self, uf: str, municipio: str) -> Sequence[ServicePoint]: ...


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""

    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = p2 - p1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bounding_box(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """(lat_min, lat_max, lon_min, lon_max) that fully contains the circle."""

    d_lat = math.degrees(radius_km / EARTH_RADIUS_KM)
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    d_lon = min(180.0, math.degrees(radius_km / (EARTH_RADIUS_KM * cos_lat)))
    return lat - d_lat, lat + d_lat, lon - d_lon, lon + d_lon


def _within(
    source: ServicesSource, lat: float, lon: float, radius_km: float, tipo: str | None
) -> list[tuple[ServicePoint, float]]:
    lat_min, lat_max, lon_min, lon_max = bounding_box(lat, lon, radius_km)
    scored = [
        (point, haversine_km(lat, lon, point.latitude, point.longitude))
        for point in source.candidates(lat_min, lat_max, lon_min, lon_max, tipo)
    ]
    return sorted(
        (item for item in scored if item[1] <= radius_km),
        key=lambda item: item[1],
    )


def nearest(
    source: ServicesSource,
    lat: float,
    lon: float,
    *,
    tipo: str | None = None,
    limit: int = 5,
) -> list[tuple[ServicePoint, float]]:
    """Closest services, widening the radius until at least one is found."""

    for radius in RADII_KM:
        found = _within(source, lat, lon, radius, tipo)
        if found:
            return found[:limit]
    return []


@dataclass(frozen=True)
class NearbyResult:
    servicos: list[tuple[ServicePoint, float | None]]
    deam_mais_proxima: tuple[ServicePoint, float] | None
    aviso: str | None


AVISO_DISTANTE = (
    "Não encontramos serviços cadastrados perto de você. "
    "Ligue 190 (emergência) ou 180 (Central de Atendimento à Mulher)."
)
AVISO_SEM_RESULTADO = (
    "Ainda não temos serviços cadastrados para essa região. "
    "Ligue 190 (emergência) ou 180 (Central de Atendimento à Mulher)."
)


def find_nearby(
    source: ServicesSource,
    *,
    lat: float | None = None,
    lon: float | None = None,
    uf: str | None = None,
    municipio: str | None = None,
    tipo: str | None = None,
    limit: int = 5,
) -> NearbyResult:
    """Services by coordinates (nearest first) or, without a location, by municipality."""

    if lat is not None and lon is not None:
        found = nearest(source, lat, lon, tipo=tipo, limit=limit)
        deam: tuple[ServicePoint, float] | None = None
        if found and tipo in (None, "deam"):
            deam = next(((p, d) for p, d in found if p.tipo == "deam"), None)
        if deam is None and tipo in (None, "deam"):
            closest_deam = nearest(source, lat, lon, tipo="deam", limit=1)
            deam = closest_deam[0] if closest_deam else None
        aviso = None
        if not found:
            aviso = AVISO_SEM_RESULTADO
        elif found[0][1] > NEAR_KM:
            aviso = AVISO_DISTANTE
        return NearbyResult(
            servicos=[(p, round(d, 2)) for p, d in found],
            deam_mais_proxima=(deam[0], round(deam[1], 2)) if deam else None,
            aviso=aviso,
        )

    if uf and municipio:
        rows = [p for p in source.by_municipio(uf.upper(), municipio) if tipo in (None, p.tipo)]
        rows.sort(key=lambda p: (TIPOS.index(p.tipo) if p.tipo in TIPOS else len(TIPOS), p.nome))
        rows = rows[:limit]
        deam_row = next((p for p in rows if p.tipo == "deam"), None)
        return NearbyResult(
            servicos=[(p, None) for p in rows],
            deam_mais_proxima=(deam_row, 0.0) if deam_row else None,
            aviso=None if rows else AVISO_SEM_RESULTADO,
        )

    raise ValueError("informe lat/lon ou uf/municipio")
