"""Nearest-delegacia lookup: distance math, radius widening, API contract, privacy."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.load_services import UPSERT, read_services_csv, upsert
from src.api.main import create_app
from src.config import Settings
from src.services.geo import (
    NEAR_KM,
    ServicePoint,
    bounding_box,
    find_nearby,
    haversine_km,
)

# Real reference points (approximate city centres)
BRASILIA = (-15.7939, -47.8828)
CEILANDIA = (-15.8190, -48.1068)
GOIANIA = (-16.6869, -49.2648)
SAO_PAULO = (-23.5505, -46.6333)
RIO = (-22.9068, -43.1729)


def point(
    id: int,
    nome: str,
    tipo: str,
    lat: float,
    lon: float,
    *,
    municipio: str = "Brasília",
    verificada: bool = True,
) -> ServicePoint:
    return ServicePoint(
        id=id,
        nome=nome,
        tipo=tipo,
        uf="DF",
        municipio=municipio,
        endereco="Rua X",
        telefone="(61) 0000-0000",
        horario="24 horas",
        latitude=lat,
        longitude=lon,
        fonte_url="https://exemplo.gov.br/fonte",
        atualizado_em=date(2026, 9, 8),
        coordenada_verificada=verificada,
    )


class FakeServices:
    def __init__(self, points: Sequence[ServicePoint]) -> None:
        self.points = list(points)
        self.calls = 0

    def candidates(
        self,
        lat_min: float,
        lat_max: float,
        lon_min: float,
        lon_max: float,
        tipo: str | None = None,
    ) -> Sequence[ServicePoint]:
        self.calls += 1
        return [
            p
            for p in self.points
            if lat_min <= p.latitude <= lat_max
            and lon_min <= p.longitude <= lon_max
            and (tipo is None or p.tipo == tipo)
        ]

    def by_municipio(self, uf: str, municipio: str) -> Sequence[ServicePoint]:
        return [p for p in self.points if p.uf == uf and p.municipio.lower() == municipio.lower()]

    def by_uf(self, uf: str) -> Sequence[ServicePoint]:
        return [p for p in self.points if p.uf == uf]


DEAM_I = point(1, "DEAM I", "deam", -15.8215, -47.9095)
DEAM_II = point(2, "DEAM II", "deam", -15.8145, -48.1120, verificada=False)
DP_6 = point(3, "6ª DP", "delegacia_comum", -15.7800, -47.7800)
SAO_PAULO_DP = point(9, "DP SP", "delegacia_comum", *SAO_PAULO, municipio="São Paulo")


# --- distance math ---------------------------------------------------------------
def test_haversine_known_distance_sao_paulo_rio() -> None:
    assert haversine_km(*SAO_PAULO, *RIO) == pytest.approx(357, abs=4)


def test_haversine_zero_and_symmetric() -> None:
    assert haversine_km(*BRASILIA, *BRASILIA) == 0
    assert haversine_km(*BRASILIA, *GOIANIA) == pytest.approx(haversine_km(*GOIANIA, *BRASILIA))


def test_bounding_box_contains_every_point_inside_the_radius() -> None:
    lat_min, lat_max, lon_min, lon_max = bounding_box(*BRASILIA, 25)
    assert lat_min <= CEILANDIA[0] <= lat_max
    assert lon_min <= CEILANDIA[1] <= lon_max
    assert not (lat_min <= GOIANIA[0] <= lat_max and lon_min <= GOIANIA[1] <= lon_max)


# --- search ------------------------------------------------------------------------
def test_returns_nearest_first_with_distance() -> None:
    source = FakeServices([DEAM_II, DP_6, DEAM_I])

    result = find_nearby(source, lat=BRASILIA[0], lon=BRASILIA[1])

    names = [p.nome for p, _ in result.servicos]
    distances = [d for _, d in result.servicos]
    assert names[0] == "DEAM I"  # ~3.9 km, the closest of the three
    assert distances == sorted(distances)
    assert result.aviso is None


def test_nearest_deam_is_reported_even_when_a_common_station_is_closer() -> None:
    close_dp = point(4, "DP perto", "delegacia_comum", -15.7945, -47.8830)
    source = FakeServices([close_dp, DEAM_I])

    result = find_nearby(source, lat=BRASILIA[0], lon=BRASILIA[1], limit=1)

    assert result.servicos[0][0].nome == "DP perto"
    assert result.deam_mais_proxima is not None
    assert result.deam_mais_proxima[0].nome == "DEAM I"


def test_radius_widens_until_something_is_found() -> None:
    source = FakeServices([DEAM_I])

    result = find_nearby(source, lat=GOIANIA[0], lon=GOIANIA[1])  # ~170 km away

    assert [p.nome for p, _ in result.servicos] == ["DEAM I"]
    assert result.servicos[0][1] > NEAR_KM
    assert result.aviso is not None and "190" in result.aviso and "180" in result.aviso
    assert source.calls > 1


def test_nothing_registered_returns_a_safe_notice() -> None:
    result = find_nearby(FakeServices([]), lat=BRASILIA[0], lon=BRASILIA[1])

    assert result.servicos == []
    assert result.aviso is not None and "180" in result.aviso


def test_filter_by_type() -> None:
    source = FakeServices([DEAM_I, DP_6])

    result = find_nearby(source, lat=BRASILIA[0], lon=BRASILIA[1], tipo="delegacia_comum")

    assert [p.tipo for p, _ in result.servicos] == ["delegacia_comum"]


def test_city_search_measures_from_the_city_centre() -> None:
    source = FakeServices([DP_6, DEAM_I, SAO_PAULO_DP])

    result = find_nearby(source, uf="df", municipio="brasilia")  # sem acento, minúsculas

    assert result.referencia is not None
    assert result.referencia.rotulo == "centro de Brasília/DF"
    assert [p.nome for p, _ in result.servicos][:2] == ["DEAM I", "6ª DP"]
    assert all(d is not None for _, d in result.servicos)
    assert result.deam_mais_proxima is not None and result.deam_mais_proxima[0].nome == "DEAM I"


def test_city_search_in_another_city_changes_the_results() -> None:
    # Regressão: a busca por cidade não pode devolver sempre as mesmas delegacias.
    source = FakeServices([DEAM_I, DEAM_II, SAO_PAULO_DP])

    sp = find_nearby(source, uf="SP", municipio="São Paulo")
    df = find_nearby(source, uf="DF", municipio="Brasília")

    assert sp.servicos[0][0].nome == "DP SP"
    assert df.servicos[0][0].nome == "DEAM I"
    assert sp.referencia != df.referencia


def test_city_without_nearby_service_shows_the_closest_with_a_warning() -> None:
    result = find_nearby(FakeServices([DEAM_I]), uf="GO", municipio="Goiânia")

    assert result.servicos and result.servicos[0][1] > 50  # type: ignore[operator]
    assert result.aviso is not None and "perto de você" in result.aviso


def test_unknown_municipality_falls_back_to_the_state_with_a_warning() -> None:
    # Lugar que nenhuma lista conhece: não pode virar beco sem saída.
    de_outro_estado = replace(SAO_PAULO_DP, uf="SP")
    source = FakeServices([DP_6, DEAM_I, de_outro_estado])

    result = find_nearby(source, uf="DF", municipio="Rua Inventada 123")

    assert [p.nome for p, _ in result.servicos] == ["DEAM I", "6ª DP"]
    assert result.aviso is not None and "Não encontramos essa cidade" in result.aviso
    assert result.deam_mais_proxima is not None


def test_unknown_state_has_no_results_and_says_so() -> None:
    result = find_nearby(FakeServices([DEAM_I]), uf="AM", municipio="Manaus")

    assert result.servicos == []
    assert result.aviso is not None and "Ainda não temos" in result.aviso


def test_needs_a_location_or_a_municipality() -> None:
    with pytest.raises(ValueError):
        find_nearby(FakeServices([]))


# --- API -----------------------------------------------------------------------------
def make_client(points: Sequence[ServicePoint]) -> TestClient:
    app = create_app(
        settings=Settings(),
        pipeline=object(),  # type: ignore[arg-type]
        source_repo=object(),  # type: ignore[arg-type]
        health_probe=object(),  # type: ignore[arg-type]
        services_repo=FakeServices(points),
    )
    return TestClient(app)


def test_api_returns_nearby_services_and_emergency_numbers() -> None:
    client = make_client([DEAM_I, DEAM_II, DP_6])

    response = client.post("/services/nearby", json={"lat": -15.7939, "lon": -47.8828})

    assert response.status_code == 200
    body = response.json()
    assert body["servicos"][0]["nome"] == "DEAM I"
    assert body["servicos"][0]["distancia_km"] > 0
    assert body["servicos"][0]["fonte_url"]
    assert body["deam_mais_proxima"]["nome"] == "DEAM I"
    assert body["emergencia"] == {"policia_militar": "190", "central_mulher": "180"}
    assert "Confirme" in body["aviso_legal"]


def test_api_exposes_whether_the_coordinate_is_verified() -> None:
    client = make_client([DEAM_II])

    body = client.post("/services/nearby", json={"lat": -15.8, "lon": -48.1}).json()

    assert body["servicos"][0]["coordenada_verificada"] is False


def test_api_by_municipality_returns_distances_and_reference() -> None:
    client = make_client([DEAM_I, DP_6])

    body = client.post("/services/nearby", json={"uf": "DF", "municipio": "Brasília"}).json()

    assert [s["nome"] for s in body["servicos"]] == ["DEAM I", "6ª DP"]
    assert body["servicos"][0]["distancia_km"] is not None
    assert body["referencia"]["rotulo"] == "centro de Brasília/DF"
    assert body["referencia"]["latitude"] == pytest.approx(-15.7795, abs=0.01)


def test_api_by_point_has_no_reference() -> None:
    body = make_client([DEAM_I]).post("/services/nearby", json={"lat": -15.8, "lon": -47.9}).json()

    assert body["referencia"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"lat": -15.8},  # longitude missing
        {"lat": 200, "lon": -47.8},
        {"uf": "DF"},  # municipality missing
        {"lat": -15.8, "lon": -47.8, "limit": 0},
        {"lat": -15.8, "lon": -47.8, "tipo": "outro"},
        {"lat": -15.8, "lon": -47.8, "extra": 1},
    ],
)
def test_api_rejects_invalid_requests(payload: dict) -> None:
    assert make_client([DEAM_I]).post("/services/nearby", json=payload).status_code == 422


def test_api_never_puts_the_location_in_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    client = make_client([DEAM_I])

    with caplog.at_level(logging.DEBUG):
        client.post("/services/nearby", json={"lat": -15.79391, "lon": -47.88282})

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "15.79" not in logged
    assert "47.88" not in logged


def test_api_failure_points_to_the_emergency_lines() -> None:
    class Broken(FakeServices):
        def candidates(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("db down")

    app = create_app(
        settings=Settings(),
        pipeline=object(),  # type: ignore[arg-type]
        source_repo=object(),  # type: ignore[arg-type]
        health_probe=object(),  # type: ignore[arg-type]
        services_repo=Broken([]),
    )

    response = TestClient(app).post("/services/nearby", json={"lat": -15.8, "lon": -47.8})

    assert response.status_code == 503
    assert "190" in response.json()["detail"]


# --- CSV loader ----------------------------------------------------------------------
HEADER = (
    "uf,municipio,nome,tipo,endereco,telefone,horario,latitude,longitude,"
    "coordenada_verificada,origem,fonte_url,atualizado_em\n"
)


def write_csv(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / "services.csv"
    path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_loader_accepts_good_rows_and_skips_bad_ones(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path,
        "DF,Brasília,Boa,deam,Rua A,(61) 1,24 horas,-15.8,-47.9,true,curado,https://f.gov.br,2026-09-08",
        "DF,Brasília,Sem coordenada,deam,,,,,,false,curado,https://f.gov.br,2026-09-08",
        "DF,Brasília,Tipo errado,posto,,,,-15.8,-47.9,false,curado,https://f.gov.br,2026-09-08",
        "DF,Brasília,Fora do Brasil,deam,,,,48.8,2.3,false,curado,https://f.gov.br,2026-09-08",
        "DF,Brasília,Data ruim,deam,,,,-15.8,-47.9,false,curado,https://f.gov.br,08/09/2026",
        "DF,Brasília,Sem fonte,deam,,,,-15.8,-47.9,false,curado,,2026-09-08",
    )

    report = read_services_csv(path)

    assert [r["nome"] for r in report.valid] == ["Boa"]
    reasons = dict(report.skipped)
    assert "sem latitude" in reasons["Sem coordenada"]
    assert "tipo inválido" in reasons["Tipo errado"]
    assert "fora do Brasil" in reasons["Fora do Brasil"]
    assert "data inválida" in reasons["Data ruim"]
    assert "fonte_url" in reasons["Sem fonte"]


def test_loader_upsert_is_idempotent_by_construction(tmp_path: Path) -> None:
    class Cursor:
        def __init__(self, log: list) -> None:
            self.log = log

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, sql: str, params: dict) -> None:
            self.log.append((sql, params))

    class Conn:
        def __init__(self) -> None:
            self.log: list = []
            self.committed = False

        def cursor(self) -> Cursor:
            return Cursor(self.log)

        def commit(self) -> None:
            self.committed = True

    path = write_csv(
        tmp_path,
        "DF,Brasília,Boa,deam,Rua A,(61) 1,24 horas,-15.8,-47.9,true,curado,https://f.gov.br,2026-09-08",
    )
    rows = read_services_csv(path).valid
    conn = Conn()

    assert upsert(conn, rows) == 1
    assert conn.committed
    sql, params = conn.log[0]
    assert sql is UPSERT and "ON CONFLICT" in sql and "DO UPDATE" in sql
    assert params["latitude"] == -15.8 and params["coordenada_verificada"] is True


def test_seed_csv_for_the_df_is_valid() -> None:
    report = read_services_csv(Path("data/seed/services_df.csv"))

    assert {r["nome"].split(" - ")[0] for r in report.valid} >= {"DEAM I", "DEAM II"}
    assert all(r["fonte_url"].startswith("https://") for r in report.valid)
