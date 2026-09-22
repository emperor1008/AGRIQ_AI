"""Crop-stage calculation service (Phase 1).

Transparent, explainable calendar-based stage estimation:

- Input: crop, optional variety, anchor date (sowing or transplanting),
  current date and the versioned reference table.
- Output: calculated stage + reason + reference version + whether farmer
  confirmation is required.

Rules:
- The calculated stage NEVER overwrites ``farmer_confirmed_stage``.
- Reference unavailable → the farmer is asked to select the stage.
- Calendar dates cannot claim exact biological stage; the result is always
  a reference estimate until the farmer confirms it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ..domain.catalogs.crop_stages import (
    CROP_STAGE_REFERENCE_VERSION,
    windows_for,
)
from ..domain.catalogs.crops import resolve_crop


@dataclass(frozen=True)
class StageResult:
    """Result of a transparent stage calculation."""

    calculated_stage: str | None
    reason: str
    reference_version: str | None
    farmer_confirmation_required: bool
    days_elapsed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "calculated_stage": self.calculated_stage,
            "reason": self.reason,
            "reference_version": self.reference_version,
            "farmer_confirmation_required": self.farmer_confirmation_required,
            "days_elapsed": self.days_elapsed,
        }


def _as_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def calculate_stage(
    crop_name: str,
    sowing_date: date | datetime | str | None,
    transplanting_date: date | datetime | str | None = None,
    variety: str | None = None,
    current_date: date | None = None,
) -> StageResult:
    """Calculate the crop stage from the versioned reference windows.

    Transplanting date wins as the anchor when both are provided (common
    rice practice); otherwise sowing date is used.
    """
    today = current_date or date.today()
    anchor = _as_date(transplanting_date) or _as_date(sowing_date)

    if anchor is None:
        return StageResult(
            calculated_stage=None,
            reason="No sowing or transplanting date recorded yet. Please select the current stage.",
            reference_version=None,
            farmer_confirmation_required=True,
        )

    crop, crop_key = resolve_crop(crop_name)
    windows = windows_for(crop_key)

    if windows is None:
        return StageResult(
            calculated_stage=None,
            reason=(
                f"Calendar reference is not available for {crop['name']}"
                + (f" (variety {variety})" if variety else "")
                + ". Please select the current stage from the field."
            ),
            reference_version=None,
            farmer_confirmation_required=True,
            days_elapsed=(today - anchor).days,
        )

    days = (today - anchor).days
    if days < 0:
        return StageResult(
            calculated_stage=None,
            reason="The anchor date is in the future. Please check the sowing/transplanting date.",
            reference_version=CROP_STAGE_REFERENCE_VERSION,
            farmer_confirmation_required=True,
            days_elapsed=days,
        )

    for stage, start, end in windows:
        if start <= days <= end:
            return StageResult(
                calculated_stage=stage,
                reason=(
                    f"Day {days} since {'transplanting' if transplanting_date else 'sowing'} falls in the "
                    f"{stage.lower()} window (day {start}-{end}) of the AGRIQ reference for {crop['name']}."
                ),
                reference_version=CROP_STAGE_REFERENCE_VERSION,
                farmer_confirmation_required=True,
                days_elapsed=days,
            )

    # Past the last window: suggest harvest as the likely stage.
    last_stage, _start, _end = windows[-1]
    return StageResult(
        calculated_stage=last_stage,
        reason=(
            f"Day {days} is beyond the published reference duration for {crop['name']}; "
            f"the crop is likely at or past {last_stage.lower()}. Please confirm."
        ),
        reference_version=CROP_STAGE_REFERENCE_VERSION,
        farmer_confirmation_required=True,
        days_elapsed=days,
    )


def needs_farmer_stage_selection(crop_name: str) -> bool:
    """True when the reference has no windows for this crop."""
    _crop, crop_key = resolve_crop(crop_name)
    return windows_for(crop_key) is None


__all__ = ["StageResult", "calculate_stage", "needs_farmer_stage_selection"]
