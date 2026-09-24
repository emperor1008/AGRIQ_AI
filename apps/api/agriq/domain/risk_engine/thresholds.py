"""Versioned threshold registry for the rule-based risk engine (Phase 5 §19).

Every numeric threshold is documented with its methodology source and the
rule version that uses it. Thresholds live here — never inline in analyzers
and never in UI code — so they are auditable and testable in isolation.

Methodology notes (honest provenance):
- Weather thresholds are generic agrometeorology reference points used as a
  transparent screening baseline, NOT validated Odisha-specific agronomy.
  Sources: standard crop-protection guidance (warm-humid conditions favour
  fungal disease; heavy rain definitions from WMO/IMD convention; heat-stress
  screening points commonly used for rice/tomato). They are screening
  heuristics pending local field validation — never presented as diagnosis.
- Market-volatility thresholds are descriptive statistics, not price advice.
- Rule version ``agriq-risk-rules-v1`` governs the entire registry.
"""
from __future__ import annotations

from typing import Any, Mapping

RULES_VERSION = "agriq-risk-rules-v1"

# Screening baseline for disease-conducive weather (rice + tomato).
DISEASE_WEATHER: Mapping[str, Any] = {
    "humidity_high": 80.0,        # RH % at/above which fungal pressure rises
    "humidity_hours_min": 6,      # consecutive-ish high-RH hours considered sustained
    "temp_favourable_min": 20.0,  # °C — fungal disease window (screening)
    "temp_favourable_max": 30.0,  # °C
    "recent_rain_mm_24h": 10.0,   # mm/24h — meaningful wetting event
}

# Heavy rain / flooding screening (WMO/IMD convention: heavy ≥ 64.5 mm/day).
HEAVY_RAIN: Mapping[str, Any] = {
    "moderate_mm_per_day": 35.0,
    "heavy_mm_per_day": 64.5,
    "very_heavy_mm_per_day": 115.0,
    "extreme_mm_per_day": 204.5,
    "forecast_window_days": 3,
}

# Heat-stress screening (°C, crop-stage aware modifiers applied in analyzer).
HEAT_STRESS: Mapping[str, Any] = {
    "rice_flowering_max": 35.0,   # rice flowering is heat-sensitive above ~35 °C
    "rice_vegetative_max": 37.0,
    "tomato_flowering_max": 32.0,
    "tomato_vegetative_max": 35.0,
    "hot_night_min": 25.0,        # warm nights add respiratory stress
}

# Water-stress screening; irrigation access modifies the interpretation.
WATER_STRESS: Mapping[str, Any] = {
    "no_rain_days_alert": 7,      # days without meaningful rain
    "meaningful_rain_mm": 5.0,    # daily rain below this does not reset the counter
    "hot_temp_c": 32.0,           # sustained heat raises evapo-transpiration
}

# Market-volatility bands (descriptive only; Phase 6 owns market guidance).
MARKET_VOLATILITY: Mapping[str, Any] = {
    "swing_high_pct": 15.0,       # modal-price swing vs recent records
    "swing_medium_pct": 8.0,
    "min_records": 3,             # fewer records → INSUFFICIENT_DATA
    "max_record_age_days": 30,    # older records cannot describe current volatility
}

STATUS_BANDS: Mapping[str, tuple[float, float]] = {
    # probability band -> status
    "inactive": (0.0, 0.24),
    "monitor": (0.25, 0.44),
    "elevated": (0.45, 0.64),
    "high": (0.65, 0.79),
    "critical": (0.80, 1.0),
}


def status_for_probability(probability: float | None) -> str:
    """Map a rule-derived probability to the documented status model (§9)."""
    if probability is None:
        return "insufficient_data"
    for status, (low, high) in STATUS_BANDS.items():
        if low <= probability <= high:
            return status
    return "insufficient_data"


def severity_for_probability(probability: float | None) -> str | None:
    if probability is None:
        return None
    if probability >= 0.80:
        return "severe"
    if probability >= 0.65:
        return "high"
    if probability >= 0.45:
        return "moderate"
    if probability >= 0.25:
        return "low"
    return "negligible"


def urgency_for(status: str, lead_hours: int) -> str:
    """Urgency token derived from status + warning lead time."""
    if status == "critical":
        return "act_now"
    if status == "high":
        return f"inspect_within_{lead_hours}_hours"
    if status == "elevated":
        return f"inspect_within_{lead_hours * 2}_hours"
    if status == "monitor":
        return "monitor_daily"
    return "no_action_needed"


__all__ = [
    "RULES_VERSION",
    "DISEASE_WEATHER",
    "HEAVY_RAIN",
    "HEAT_STRESS",
    "WATER_STRESS",
    "MARKET_VOLATILITY",
    "STATUS_BANDS",
    "status_for_probability",
    "severity_for_probability",
    "urgency_for",
]
