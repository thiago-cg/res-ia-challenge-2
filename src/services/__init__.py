"""Nearest-service lookup (delegacias) for the map."""

from src.services.geo import (
    ServicePoint,
    bounding_box,
    find_nearby,
    haversine_km,
)

__all__ = ["ServicePoint", "bounding_box", "find_nearby", "haversine_km"]
"""Serviços de domínio extraídos do pipeline da API (T04)."""
