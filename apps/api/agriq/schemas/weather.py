"""Live-weather request schema (query-string parameters)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.catalogs.crops import FIELD_CONDITIONS, GROWTH_STAGES


@dataclass(frozen=True)
class WeatherQuery:
    district: str
    crop: str
    growth_stage: str
    field_condition: str


def parse_weather_query(args: Any) -> WeatherQuery:
    district = str(args.get("district", "Cuttack") or "Cuttack").strip()
    crop = str(args.get("crop", "Rice") or "Rice").strip()[:60] or "Rice"
    stage = str(args.get("growth_stage", "Vegetative") or "Vegetative").strip()
    condition = str(args.get("field_condition", "Normal field") or "Normal field").strip()
    if stage not in GROWTH_STAGES:
        stage = "Vegetative"
    if condition not in FIELD_CONDITIONS:
        condition = "Normal field"
    return WeatherQuery(district=district, crop=crop, growth_stage=stage, field_condition=condition)


__all__ = ["WeatherQuery", "parse_weather_query"]
