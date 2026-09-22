"""Versioned crop-stage reference table (Phase 1).

Generic agronomic day-window reference used by the transparent crop-stage
calculator. This is REFERENCE data (clearly labelled), not an observation
and not a farm-specific measurement: calendar windows cannot claim an exact
biological stage, so the farmer can always confirm or correct the result.

Only crops listed here are auto-calculated; anything else returns
"reference unavailable" and the farmer selects the stage manually.
"""
from __future__ import annotations

from typing import Mapping

#: Bump when agronomic windows are revised; stored on each crop cycle.
CROP_STAGE_REFERENCE_VERSION = "agriq-crop-stage-2026.09-r1"

#: Stage labels match the dashboard GROWTH_STAGES options so farmer
#: confirmation and calculation stay comparable.
STAGE_SEEDLING = "Seedling"
STAGE_VEGETATIVE = "Vegetative"
STAGE_FLOWERING = "Flowering"
STAGE_FRUITING = "Fruiting / Grain Filling"
STAGE_HARVEST = "Harvest Stage"

#: crop → ordered list of (stage, start_day, end_day) counted from the
#: sowing/transplanting anchor date (inclusive windows, in days).
CROP_STAGE_WINDOWS: Mapping[str, tuple[tuple[str, int, int], ...]] = {
    "rice": (
        (STAGE_SEEDLING, 0, 20),
        (STAGE_VEGETATIVE, 21, 50),
        (STAGE_FLOWERING, 51, 75),
        (STAGE_FRUITING, 76, 100),
        (STAGE_HARVEST, 101, 135),
    ),
    "wheat": (
        (STAGE_SEEDLING, 0, 20),
        (STAGE_VEGETATIVE, 21, 60),
        (STAGE_FLOWERING, 61, 80),
        (STAGE_FRUITING, 81, 100),
        (STAGE_HARVEST, 101, 125),
    ),
    "maize": (
        (STAGE_SEEDLING, 0, 15),
        (STAGE_VEGETATIVE, 16, 45),
        (STAGE_FLOWERING, 46, 60),
        (STAGE_FRUITING, 61, 85),
        (STAGE_HARVEST, 86, 115),
    ),
    "tomato": (
        (STAGE_SEEDLING, 0, 25),
        (STAGE_VEGETATIVE, 26, 50),
        (STAGE_FLOWERING, 51, 65),
        (STAGE_FRUITING, 66, 90),
        (STAGE_HARVEST, 91, 125),
    ),
    "brinjal": (
        (STAGE_SEEDLING, 0, 25),
        (STAGE_VEGETATIVE, 26, 55),
        (STAGE_FLOWERING, 56, 70),
        (STAGE_FRUITING, 71, 100),
        (STAGE_HARVEST, 101, 140),
    ),
    "onion": (
        (STAGE_SEEDLING, 0, 25),
        (STAGE_VEGETATIVE, 26, 90),
        (STAGE_FRUITING, 91, 120),
        (STAGE_HARVEST, 121, 150),
    ),
    "potato": (
        (STAGE_SEEDLING, 0, 20),
        (STAGE_VEGETATIVE, 21, 50),
        (STAGE_FRUITING, 51, 75),
        (STAGE_HARVEST, 76, 110),
    ),
    "groundnut": (
        (STAGE_SEEDLING, 0, 20),
        (STAGE_VEGETATIVE, 21, 40),
        (STAGE_FLOWERING, 41, 60),
        (STAGE_FRUITING, 61, 95),
        (STAGE_HARVEST, 96, 120),
    ),
    "mustard": (
        (STAGE_SEEDLING, 0, 20),
        (STAGE_VEGETATIVE, 21, 45),
        (STAGE_FLOWERING, 46, 65),
        (STAGE_FRUITING, 66, 90),
        (STAGE_HARVEST, 91, 115),
    ),
    "green_gram": (
        (STAGE_SEEDLING, 0, 15),
        (STAGE_VEGETATIVE, 16, 30),
        (STAGE_FLOWERING, 31, 40),
        (STAGE_FRUITING, 41, 55),
        (STAGE_HARVEST, 56, 70),
    ),
}

#: Crops intentionally excluded from calendar calculation (perennial /
#: highly variable). The farmer selects the stage manually.
REFERENCE_EXCLUDED_CROPS = frozenset({
    "mango", "coconut", "banana", "guava", "cashew", "jackfruit",
    "papaya", "sapota", "litchi", "pomegranate",
})


def windows_for(crop_key: str) -> tuple[tuple[str, int, int], ...] | None:
    """Return the stage windows for a crop key, or None when unavailable."""
    key = (crop_key or "").strip().lower().replace(" ", "_")
    if key in REFERENCE_EXCLUDED_CROPS:
        return None
    return CROP_STAGE_WINDOWS.get(key)


__all__ = [
    "CROP_STAGE_REFERENCE_VERSION",
    "CROP_STAGE_WINDOWS",
    "REFERENCE_EXCLUDED_CROPS",
    "windows_for",
    "STAGE_SEEDLING",
    "STAGE_VEGETATIVE",
    "STAGE_FLOWERING",
    "STAGE_FRUITING",
    "STAGE_HARVEST",
]
