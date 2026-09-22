"""Farmer analysis request schema (district/crop/stage/condition allowlists)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.catalogs.crops import GROWTH_STAGES, FIELD_CONDITIONS, resolve_crop

MAX_CROP_NAME = 60


@dataclass(frozen=True)
class FarmAnalysisRequest:
    crop: str
    district: str
    growth_stage: str
    field_condition: str

    @property
    def valid_district(self) -> bool:
        from ..domain.catalogs.districts import DISTRICTS
        return self.district in DISTRICTS


def parse_farm_request(form: Any) -> FarmAnalysisRequest:
    """Parse and normalise the farmer analysis form."""
    crop = str(form.get("crop", "Rice") or "Rice").strip()[:MAX_CROP_NAME] or "Rice"
    district = str(form.get("district", "Cuttack") or "Cuttack").strip()
    stage = str(form.get("growth_stage", "Vegetative") or "Vegetative").strip()
    condition = str(form.get("field_condition", "Normal field") or "Normal field").strip()

    if stage not in GROWTH_STAGES:
        stage = "Vegetative"
    if condition not in FIELD_CONDITIONS:
        condition = "Normal field"
    return FarmAnalysisRequest(crop=crop, district=district, growth_stage=stage, field_condition=condition)


__all__ = ["FarmAnalysisRequest", "parse_farm_request"]
