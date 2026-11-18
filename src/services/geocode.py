"""Geocodificação opcional para "qualquer lugar" (bairro, rua, ponto de referência).

DESLIGADA por padrão (``GEOCODER=off``). Quando ligada, o servidor (nunca o navegador) envia
só o texto digitado e a UF ao Nominatim/OpenStreetMap e recebe um ponto. Isso é uma chamada a
terceiro: a tela precisa avisar. O texto digitado não é registrado em log, e o resultado fica
em cache de memória por processo. Falha, lentidão ou "sem resultado" viram ``None`` e a busca
segue com o aviso de estado, nunca um erro para a pessoa.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache

import httpx

from src.services.lugares import Lugar

logger = logging.getLogger(__name__)

Geocodificador = Callable[[str, str], Lugar | None]

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "zelia-delegacias/1.0 (projeto academico; contato: ver README)"
ESTADOS = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MG": "Minas Gerais", "MS": "Mato Grosso do Sul", "MT": "Mato Grosso",
    "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco", "PI": "Piauí", "PR": "Paraná",
    "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia", "RR": "Roraima",
    "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
    "TO": "Tocantins",
}  # fmt: skip


def criar_nominatim(
    *, timeout: float = 4.0, client: httpx.Client | None = None, url: str = NOMINATIM_URL
) -> Geocodificador:
    """Geocodificador Nominatim restrito ao Brasil e à UF informada."""

    @lru_cache(maxsize=512)
    def consultar(uf: str, texto: str) -> Lugar | None:
        params = {
            "q": f"{texto}, {ESTADOS.get(uf, uf)}, Brasil",
            "countrycodes": "br",
            "format": "jsonv2",
            "limit": "1",
        }
        try:
            http = client or httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
            resposta = http.get(url, params=params)
            resposta.raise_for_status()
            achados = resposta.json()
        except Exception as exc:  # rede, timeout, JSON inválido: nunca derruba a busca
            logger.warning("geocode_failed error=%s", type(exc).__name__)
            return None
        if not achados:
            return None
        try:
            lat, lon = float(achados[0]["lat"]), float(achados[0]["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (-34.0 <= lat <= 6.0 and -75.0 <= lon <= -32.0):
            return None  # fora do Brasil: descarta
        return Lugar(uf=uf, nome=texto, latitude=lat, longitude=lon)

    return lambda uf, texto: consultar(uf.upper(), " ".join(texto.split()))
