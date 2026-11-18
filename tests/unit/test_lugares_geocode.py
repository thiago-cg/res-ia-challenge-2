"""Busca de delegacias por qualquer lugar: regiões do DF, municípios e geocodificador opcional."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from src.services import geo, lugares
from src.services.geo import ServicePoint
from src.services.geocode import criar_nominatim


def _p(i: int, nome: str, uf: str, mun: str, lat: float, lon: float) -> ServicePoint:
    return ServicePoint(
        id=i, nome=nome, tipo="deam", uf=uf, municipio=mun, endereco=None, telefone=None,
        horario=None, latitude=lat, longitude=lon, fonte_url="https://x",
        atualizado_em="2026-01-01", coordenada_verificada=False,
    )  # fmt: skip


class Fonte:
    def __init__(self, pts: Sequence[ServicePoint]) -> None:
        self.pts = list(pts)

    def candidates(self, lat_min, lat_max, lon_min, lon_max, tipo=None):  # noqa: ANN001, ANN201
        return [
            p
            for p in self.pts
            if lat_min <= p.latitude <= lat_max and lon_min <= p.longitude <= lon_max
        ]

    def by_municipio(self, uf, municipio):  # noqa: ANN001, ANN201
        return [p for p in self.pts if p.uf == uf and p.municipio == municipio]

    def by_uf(self, uf):  # noqa: ANN001, ANN201
        return [p for p in self.pts if p.uf == uf]


GAMA = _p(1, "DEAM Gama", "DF", "Brasília", -16.02, -48.06)
PLANO = _p(2, "DEAM Plano", "DF", "Brasília", -15.79, -47.88)
RECIFE = _p(3, "DEAM Recife", "PE", "Recife", -8.05, -34.90)


def test_gama_e_regiao_do_df_e_acha_a_delegacia_mais_perto_dela() -> None:
    assert lugares.buscar("DF", "gama") is not None
    r = geo.find_nearby(Fonte([PLANO, GAMA, RECIFE]), uf="DF", municipio="Gama", limit=2)
    assert r.servicos[0][0] is GAMA  # a do Gama, não a do Plano Piloto
    assert r.referencia and "Gama" in r.referencia.rotulo and r.aviso is None


def test_lugar_de_outra_uf_nao_vaza_para_o_estado_errado() -> None:
    assert lugares.buscar("PE", "Gama") is None


def test_geocodificador_so_e_usado_quando_o_lugar_nao_e_conhecido() -> None:
    chamadas: list[tuple[str, str]] = []

    def geocodificar(uf: str, texto: str):  # noqa: ANN202
        chamadas.append((uf, texto))
        return lugares.Lugar(uf=uf, nome=texto, latitude=-8.06, longitude=-34.88)

    fonte = Fonte([PLANO, RECIFE])
    geo.find_nearby(fonte, uf="DF", municipio="Gama", geocodificar=geocodificar)
    assert chamadas == []  # conhecido localmente: nenhuma chamada a terceiro
    r = geo.find_nearby(fonte, uf="PE", municipio="Rua do Bom Jesus", geocodificar=geocodificar)
    assert chamadas == [("PE", "Rua do Bom Jesus")]
    assert r.servicos[0][0] is RECIFE and r.referencia is not None


def test_sem_geocodificador_lugar_desconhecido_cai_no_aviso_do_estado() -> None:
    r = geo.find_nearby(Fonte([PLANO]), uf="DF", municipio="Rua Inventada 123")
    assert r.aviso == geo.AVISO_CIDADE_NAO_ENCONTRADA and r.referencia is None


def _cliente(resposta: object, status: int = 200) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(status, json=resposta))
    )


def test_nominatim_devolve_ponto_do_brasil() -> None:
    geocodificar = criar_nominatim(client=_cliente([{"lat": "-8.06", "lon": "-34.88"}]))
    lugar = geocodificar("PE", "Boa Viagem")
    assert lugar is not None and round(lugar.latitude, 2) == -8.06


def test_nominatim_descarta_resultado_fora_do_brasil_e_falhas() -> None:
    assert criar_nominatim(client=_cliente([{"lat": "48.8", "lon": "2.3"}]))("PE", "Paris") is None
    assert criar_nominatim(client=_cliente([]))("PE", "nada") is None
    assert criar_nominatim(client=_cliente({}, status=503))("PE", "x") is None
