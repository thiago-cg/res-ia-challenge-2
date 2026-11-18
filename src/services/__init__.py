"""Serviços de domínio: pipeline da API (T04) e busca de delegacias próximas."""

from src.services.geo import (
    ServicePoint,
    bounding_box,
    find_nearby,
    haversine_km,
)

__all__ = ["ServicePoint", "bounding_box", "find_nearby", "haversine_km"]
