"""Postgres adapter for the ``services`` table (only rows that have coordinates)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from src.services.geo import ServicePoint

_COLUMNS = (
    "id, nome, tipo, uf, municipio, endereco, telefone, horario, latitude, longitude, "
    "fonte_url, atualizado_em, coordenada_verificada"
)


def _to_point(row: Any) -> ServicePoint:
    return ServicePoint(
        id=row["id"],
        nome=row["nome"],
        tipo=row["tipo"],
        uf=row["uf"],
        municipio=row["municipio"],
        endereco=row["endereco"],
        telefone=row["telefone"],
        horario=row["horario"],
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        fonte_url=row["fonte_url"],
        atualizado_em=row["atualizado_em"],
        coordenada_verificada=bool(row["coordenada_verificada"]),
    )


@contextmanager
def _connect(database_url: str) -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, connect_timeout=3, row_factory=dict_row) as conn:
        yield conn


class PostgresServicesRepo:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def candidates(
        self,
        lat_min: float,
        lat_max: float,
        lon_min: float,
        lon_max: float,
        tipo: str | None = None,
    ) -> Sequence[ServicePoint]:
        sql = f"""
            SELECT {_COLUMNS} FROM services
            WHERE latitude BETWEEN %s AND %s
              AND longitude BETWEEN %s AND %s
              AND (%s::text IS NULL OR tipo = %s)
        """  # noqa: S608 - column list is a constant
        with _connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (lat_min, lat_max, lon_min, lon_max, tipo, tipo))
            return [_to_point(row) for row in cur.fetchall()]

    def by_municipio(self, uf: str, municipio: str) -> Sequence[ServicePoint]:
        sql = f"""
            SELECT {_COLUMNS} FROM services
            WHERE uf = %s AND lower(municipio) = lower(%s) AND latitude IS NOT NULL
        """  # noqa: S608
        with _connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (uf, municipio))
            return [_to_point(row) for row in cur.fetchall()]
