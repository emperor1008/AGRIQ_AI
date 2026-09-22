"""OpenStreetMap integration helpers.

The browser renders Leaflet tiles directly from OpenStreetMap; this module
only supplies district coordinates and tile configuration constants so no
other layer hard-codes provider URLs.
"""
from __future__ import annotations

from ...domain.catalogs.districts import DISTRICTS

TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_ATTRIBUTION = "&copy; OpenStreetMap"
MAX_ZOOM = 11


def district_coordinates(district: str) -> tuple[float, float]:
    """Return (lat, lon) for a district, defaulting to Cuttack."""
    return DISTRICTS.get(district, DISTRICTS["Cuttack"])


__all__ = ["TILE_URL", "TILE_ATTRIBUTION", "MAX_ZOOM", "district_coordinates"]
