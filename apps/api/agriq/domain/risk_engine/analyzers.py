"""Deterministic risk analyzers (Phase 5 §6, §10–14).

Five analyzers, one per supported risk type. Each is a pure function of its
inputs (validated farmer context + verified weather + market context) and
returns the normalized ``Assessment`` contract. No provider calls, no DB, no
LLM, no fabricated values — insufficient inputs yield honest unavailable /
insufficient-data statuses.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from . import thresholds, weather_input

from .base import (
    Assessment,
    Evidence,
    RISK_TYPES,
    SUPPORTED_CROPS,
    confidence_from,
    insufficient,
    unavailable,
)
from .freshness import classify, confidence_factor

_LEAD_HOURS = {
    "disease_conducive_weather": 24,
    "heavy_rain_flooding": 48,
    "heat_stress": 24,
    "water_stress": 72,
    "market_volatility": 0,
}


def _validate_crop(crop: Any) -> Optional[str]:
    """Return the normalised crop name when supported, else None."""
    if not crop:
        return None
    name = str(crop).strip().lower()
    return name if name in SUPPORTED_CROPS else None


def _fresh_factor(weights: Mapping[str, Any]) -> float:
    """Worst-case freshness factor across the evidence used."""
    factors = [confidence_factor(w.get("freshness", "unavailable")) for w in weights]
    return min(factors) if factors else 0.0


# ---------------------------------------------------------------------------
# 1. Disease-conducive weather (§10)
# ---------------------------------------------------------------------------

def disease_conducive_weather(
    crop: Any, stage: Any, weather: Optional[Mapping[str, Any]]
) -> Assessment:
    crop_name = _validate_crop(crop)
    if crop_name is None:
        return unavailable(RISK_TYPES[0], "crop_not_supported")
    if weather is None:
        return unavailable(RISK_TYPES[0], "weather_unavailable")

    t = thresholds.DISEASE_WEATHER
    humidity = weather.get("humidity")
    temp = weather.get("temp")
    rain_24: Optional[float]
    if weather.get("rain") is None:
        rain_24 = None  # provider gap — never treated as dry weather
    else:
        try:
            rain_24 = float(weather.get("rain"))
        except (TypeError, ValueError):
            rain_24 = None
    reasons: list[str] = []
    signals = 0
    total = 0

    # Humidity signal (current observation). A missing value is a *gap*, not
    # a zero — it simply does not participate in the score (real-data policy).
    if humidity is not None:
        total += 1
        try:
            if float(humidity) >= t["humidity_high"]:
                signals += 1
                reasons.append(f"Relative humidity is {float(humidity):.0f}%, above the {t['humidity_high']:.0f}% screening threshold.")
        except (TypeError, ValueError):
            pass

    # Temperature window signal.
    if temp is not None:
        total += 1
        try:
            if t["temp_favourable_min"] <= float(temp) <= t["temp_favourable_max"]:
                signals += 1
                reasons.append(
                    f"Temperature {float(temp):.0f}°C falls in the {t['temp_favourable_min']:.0f}–{t['temp_favourable_max']:.0f}°C window favourable to fungal disease development."
                )
        except (TypeError, ValueError):
            pass

    # Rain / leaf-wetting signal (24h observation). Only counted when the
    # provider actually returned a value — None is a gap, not dry weather.
    rain_signal_available = rain_24 is not None
    if rain_signal_available:
        total += 1
        if float(rain_24) >= t["recent_rain_mm_24h"]:
            signals += 1
            reasons.append(f"Recent rainfall ({float(rain_24):.1f} mm) has kept the crop canopy wet.")

    # Sustained high-humidity signal from the hourly series (next 12 h forecast hours).
    humidity_hours = [h for h in weather_input.hourly_humidity(weather) if h >= t["humidity_high"]]
    if humidity_hours:
        total += 1
        if len(humidity_hours) >= t["humidity_hours_min"]:
            signals += 1
            reasons.append(
                f"High humidity ({t['humidity_high']:.0f}%+) persists across {len(humidity_hours)} forecast hours."
            )

    if total == 0 or (rain_signal_available is False and humidity is None and temp is None):
        return insufficient(RISK_TYPES[0], "no_usable_weather_values")

    probability = round(signals / total, 2)
    # Stage weighting: flowering/grain stages are more vulnerable.
    stage_l = str(stage or "").lower()
    stage_note = None
    if any(word in stage_l for word in ("flower", "grain", "fruit")):
        probability = round(min(1.0, probability + 0.1), 2)
        stage_note = f"The crop is at the {stage} stage, which is more sensitive to disease pressure."

    status = thresholds.status_for_probability(probability)
    lead = _LEAD_HOURS[RISK_TYPES[0]]
    evidence = [
        weather_input.observation_evidence(
            weather, f"temp {temp} °C, humidity {humidity} %, rain(24h) {rain_24} mm"
        )
    ]
    if humidity_hours:
        evidence.append(
            weather_input.forecast_evidence(weather, f"{len(humidity_hours)} forecast hours above {t['humidity_high']:.0f}% RH")
        )
    factors = {
        "input_freshness": confidence_factor(weather.get("freshness", "unavailable")),
        "context_completeness": 1.0 if stage else 0.6,
        "evidence_directness": 0.8 if signals else 0.5,
    }
    confidence, basis = confidence_from(factors, "rule-based screening; weather is forecast-model output, not a field sensor")
    if weather.get("freshness") in ("stale", "expired"):
        reasons.append("Using older verified weather data; assessment confidence is reduced.")

    return Assessment(
        risk_type=RISK_TYPES[0],
        status=status,
        probability=probability,
        severity=thresholds.severity_for_probability(probability),
        urgency=thresholds.urgency_for(status, lead),
        warning_lead_time_hours=lead,
        confidence=confidence,
        confidence_basis=basis,
        threat="Disease-conducive weather conditions" if probability >= 0.45 else None,
        reasons=reasons + ([stage_note] if stage_note else []),
        actions=(
            [
                "Inspect representative plants (including lower leaves) within the advisory window.",
                "Check for early lesion, spot or blight symptoms; photograph anything unusual for the record.",
                "Avoid unnecessary canopy wetting when irrigating.",
            ]
            if status in ("elevated", "high", "critical")
            else ["Continue routine monitoring; no specific disease-precaution is indicated by current conditions."]
        ),
        evidence=evidence,
        data_quality={
            "inputs_available": True,
            "weather_freshness": weather.get("freshness"),
            "signals": f"{signals}/{total}",
        },
        requires_expert_confirmation=status in ("high", "critical"),
    )


# ---------------------------------------------------------------------------
# 2. Heavy rain / flooding (§11)
# ---------------------------------------------------------------------------

def heavy_rain_flooding(
    crop: Any, stage: Any, weather: Optional[Mapping[str, Any]], field_condition: Any = None
) -> Assessment:
    crop_name = _validate_crop(crop)
    if crop_name is None:
        return unavailable(RISK_TYPES[1], "crop_not_supported")
    if weather is None:
        return unavailable(RISK_TYPES[1], "weather_unavailable")

    t = thresholds.HEAVY_RAIN
    days = t["forecast_window_days"]
    rains, forecast_days_with_data = weather_input.daily_rain(weather, days)
    if forecast_days_with_data == 0:
        return insufficient(RISK_TYPES[1], "no_forecast_rainfall_data")

    reasons: list[str] = []
    peak_day = max(rains) if rains else 0.0
    evidence = [
        weather_input.forecast_evidence(
            weather,
            (
                f"{days}-day forecast rainfall: {[round(r, 1) for r in rains]} mm/day"
                if rains
                else f"No rainfall values were returned for the next {days} days"
            ),
        )
    ]

    # Distinguish forecast rain, waterlogging potential, and confirmed flooding.
    if peak_day >= t["extreme_mm_per_day"]:
        probability = 0.9
        reasons.append(f"Extreme rainfall ({peak_day:.0f} mm/day) is forecast within {days} days.")
    elif peak_day >= t["very_heavy_mm_per_day"]:
        probability = 0.8
        reasons.append(f"Very heavy rainfall ({peak_day:.0f} mm/day) is forecast within {days} days.")
    elif peak_day >= t["heavy_mm_per_day"]:
        probability = 0.7
        reasons.append(f"Heavy rainfall ({peak_day:.0f} mm/day) is forecast within {days} days.")
    elif peak_day >= t["moderate_mm_per_day"]:
        probability = 0.5
        reasons.append(f"Moderate rainfall ({peak_day:.0f} mm/day) is forecast; waterlogging possible on poorly drained fields.")
    else:
        probability = 0.15
        reasons.append(f"No heavy rainfall is forecast in the next {days} days (max {peak_day:.0f} mm/day).")

    stage_l = str(stage or "").lower()
    condition_l = str(field_condition or "").lower()
    if "waterlogged" in condition_l or "water logged" in condition_l:
        probability = round(min(1.0, probability + 0.15), 2)
        reasons.append("The farmer has reported waterlogged field conditions.")
    if any(word in stage_l for word in ("flower", "grain", "fruit")):
        reasons.append("The crop is at a rain-sensitive reproductive stage.")

    status = thresholds.status_for_probability(probability)
    lead = _LEAD_HOURS[RISK_TYPES[1]]
    factors = {
        "input_freshness": confidence_factor(weather.get("freshness", "unavailable")),
        "context_completeness": 0.8 if stage else 0.5,
        "evidence_directness": 0.9,
    }
    confidence, basis = confidence_from(factors, "IMD-convention rainfall bands applied to Open-Meteo forecast totals")

    if probability < 0.45:
        return Assessment(
            risk_type=RISK_TYPES[1],
            status=status,
            probability=probability,
            severity=thresholds.severity_for_probability(probability),
            urgency=thresholds.urgency_for(status, lead),
            warning_lead_time_hours=lead,
            confidence=confidence,
            confidence_basis=basis,
            threat=None,
            reasons=reasons,
            actions=["No drainage action needed based on the current forecast."],
            evidence=evidence,
            data_quality={"inputs_available": True, "forecast_days": days, "weather_freshness": weather.get("freshness")},
        )

    actions = [
        "Check field drainage channels and bund outlets before the rainfall arrives.",
        "Avoid field operations and fertiliser/pesticide application immediately before the forecast rain.",
        "After rain, drain standing water within 24–48 hours where possible.",
    ]
    return Assessment(
        risk_type=RISK_TYPES[1],
        status=status,
        probability=probability,
        severity=thresholds.severity_for_probability(probability),
        urgency=thresholds.urgency_for(status, lead),
        warning_lead_time_hours=lead,
        confidence=confidence,
        confidence_basis=basis,
        threat="Heavy rainfall may cause waterlogging" if probability >= 0.65 else "Moderate rainfall — watch field drainage",
        reasons=reasons,
        actions=actions,
        evidence=evidence,
        data_quality={"inputs_available": True, "forecast_days": days, "weather_freshness": weather.get("freshness")},
        requires_expert_confirmation=probability >= 0.8,
    )


# ---------------------------------------------------------------------------
# 3. Heat stress (§12)
# ---------------------------------------------------------------------------

def heat_stress(crop: Any, stage: Any, weather: Optional[Mapping[str, Any]], irrigated: bool | None = None) -> Assessment:
    crop_name = _validate_crop(crop)
    if crop_name is None:
        return unavailable(RISK_TYPES[2], "crop_not_supported")
    if weather is None:
        return unavailable(RISK_TYPES[2], "weather_unavailable")

    t = thresholds.HEAT_STRESS
    temp_max: Optional[float] = None
    for row in (weather.get("daily") or [])[:2]:
        value = row.get("temp_max")
        try:
            temp_max = max(temp_max, float(value)) if temp_max is not None else float(value)
        except (TypeError, ValueError):
            continue
    current = weather.get("temp")
    candidates = [v for v in (temp_max, current) if v is not None]
    if not candidates:
        return insufficient(RISK_TYPES[2], "no_temperature_data")

    peak = max(candidates)
    stage_l = str(stage or "").lower()
    reproductive = any(word in stage_l for word in ("flower", "grain", "fruit"))
    if crop_name == "rice":
        limit = t["rice_flowering_max"] if reproductive else t["rice_vegetative_max"]
    else:
        limit = t["tomato_flowering_max"] if reproductive else t["tomato_vegetative_max"]

    reasons: list[str] = []
    if peak >= limit + 2:
        probability = 0.85
    elif peak >= limit:
        probability = 0.7
    elif peak >= limit - 2:
        probability = 0.45
    else:
        probability = 0.15

    if peak >= limit - 2:
        reasons.append(
            f"Temperature up to {peak:.0f}°C is expected, at or above the {limit:.0f}°C screening threshold for {crop_name}"
            + (" at the reproductive stage." if reproductive else ".")
        )
    else:
        reasons.append(f"Forecast maximum temperature ({peak:.0f}°C) is below the {limit:.0f}°C screening threshold.")

    if irrigated is False:
        probability = round(min(1.0, probability + 0.1), 2)
        reasons.append("No assured irrigation is recorded for this field, which increases heat-stress impact.")
    elif irrigated is True:
        probability = round(max(0.1, probability - 0.1), 2)
        reasons.append("Irrigation is available on this field, which reduces heat-stress impact.")

    status = thresholds.status_for_probability(probability)
    lead = _LEAD_HOURS[RISK_TYPES[2]]
    factors = {
        "input_freshness": confidence_factor(weather.get("freshness", "unavailable")),
        "context_completeness": 0.9 if stage else 0.6,
        "evidence_directness": 0.85,
    }
    confidence, basis = confidence_from(
        factors, "crop-specific screening thresholds applied to Open-Meteo daily maxima"
    )
    evidence = [weather_input.forecast_evidence(weather, f"forecast daily max {peak} °C")]

    if probability < 0.45:
        return Assessment(
            risk_type=RISK_TYPES[2],
            status=status,
            probability=probability,
            severity=thresholds.severity_for_probability(probability),
            urgency=thresholds.urgency_for(status, lead),
            warning_lead_time_hours=lead,
            confidence=confidence,
            confidence_basis=basis,
            threat=None,
            reasons=reasons,
            actions=["No heat-stress precaution needed based on the current forecast."],
            evidence=evidence,
            data_quality={"inputs_available": True, "weather_freshness": weather.get("freshness")},
        )

    return Assessment(
        risk_type=RISK_TYPES[2],
        status=status,
        probability=probability,
        severity=thresholds.severity_for_probability(probability),
        urgency=thresholds.urgency_for(status, lead),
        warning_lead_time_hours=lead,
        confidence=confidence,
        confidence_basis=basis,
        threat="Heat stress possible during sensitive stages",
        reasons=reasons,
        actions=(
            [
                "Irrigate in the early morning or evening, not at midday, if water is available.",
                "Avoid transplanting, spraying or fertiliser application during peak heat hours.",
                "Watch for leaf rolling/curling around midday and record it as an observation.",
            ]
            if crop_name == "rice"
            else [
                "Irrigate in the early morning or evening if water is available.",
                "Use shade or mulch where practical for young plants.",
                "Avoid midday field operations during the hot window.",
            ]
        ),
        evidence=evidence,
        data_quality={"inputs_available": True, "weather_freshness": weather.get("freshness")},
        requires_expert_confirmation=status == "critical",
    )


# ---------------------------------------------------------------------------
# 4. Water stress (§13)
# ---------------------------------------------------------------------------

def water_stress(
    crop: Any,
    stage: Any,
    weather: Optional[Mapping[str, Any]],
    *,
    irrigation_type: Any = None,
    soil_type: Any = None,
    field_condition: Any = None,
) -> Assessment:
    crop_name = _validate_crop(crop)
    if crop_name is None:
        return unavailable(RISK_TYPES[3], "crop_not_supported")
    if weather is None:
        return unavailable(RISK_TYPES[3], "weather_unavailable")

    t = thresholds.WATER_STRESS
    daily_rows = (weather.get("daily") or [])[:7]
    rain_values = []
    for row in daily_rows:
        try:
            rain_values.append(float(row.get("rain") or 0.0))
        except (TypeError, ValueError):
            rain_values.append(0.0)

    # Recent observed rain counts as moisture supply.
    observed_rain: Optional[float] = None
    try:
        observed_rain = float(weather.get("rain")) if weather.get("rain") is not None else None
    except (TypeError, ValueError):
        observed_rain = None

    condition_l = str(field_condition or "").lower()
    irrigation_l = str(irrigation_type or "").strip().lower()
    # §13: irrigation access changes the interpretation. "Rain-fed"/"None"
    # means no irrigation; unknown text stays unknown rather than guessed.
    has_irrigation: Optional[bool]
    if not irrigation_l:
        has_irrigation = None
    elif any(word in irrigation_l for word in ("canal", "bore", "well", "tube", "sprinkler", "drip", "pump", "lift")):
        has_irrigation = True
    elif "rain" in irrigation_l or irrigation_l in ("none", "no irrigation", "not irrigated"):
        has_irrigation = False
    else:
        has_irrigation = None

    # Dry-spell length: leading days (after today) with rain below the
    # meaningful threshold. Current observation wetness breaks the spell.
    dry_days = 0
    for value in rain_values:
        if value < t["meaningful_rain_mm"]:
            dry_days += 1
        else:
            break
    if "waterlogged" in condition_l or "wet" in condition_l:
        dry_days = 0
    elif observed_rain is not None and observed_rain >= t["meaningful_rain_mm"]:
        dry_days = 0

    reasons: list[str] = []
    if dry_days >= t["no_rain_days_alert"]:
        probability = 0.7
        reasons.append(f"No meaningful rain ({t['meaningful_rain_mm']:.0f} mm+ per day) is forecast for the next {dry_days} days.")
    elif dry_days >= 4:
        probability = 0.5
        reasons.append(f"A {dry_days}-day dry spell is forecast; soil moisture will decline.")
    elif dry_days >= 2:
        probability = 0.3
        reasons.append(f"A short dry spell ({dry_days} days) is forecast.")
    else:
        probability = 0.15
        reasons.append("Rainfall is forecast within the advisory window; water stress is unlikely in the near term.")

    # Irrigation access changes the interpretation (§13 requirement).
    if has_irrigation is True:
        probability = round(max(0.1, probability - 0.2), 2)
        reasons.append(f"Irrigation is available ({irrigation_type}), so a dry spell can be managed with timely irrigation.")
    elif has_irrigation is False:
        probability = round(min(0.95, probability + 0.2), 2)
        reasons.append("No irrigation source is recorded for this field; the crop depends on rainfall alone.")

    stage_l = str(stage or "").lower()
    if "flower" in stage_l or "grain" in stage_l:
        probability = round(min(1.0, probability + 0.05), 2)
        reasons.append("The crop is at a moisture-sensitive reproductive stage.")
    if soil_type and any(word in str(soil_type).lower() for word in ("sandy", "light")):
        probability = round(min(1.0, probability + 0.05), 2)
        reasons.append("Sandy/light soil holds less moisture, so stress develops faster.")

    status = thresholds.status_for_probability(probability)
    lead = _LEAD_HOURS[RISK_TYPES[3]]
    factors = {
        "input_freshness": confidence_factor(weather.get("freshness", "unavailable")),
        "context_completeness": (0.9 if has_irrigation is not None else 0.5) * (0.95 if stage else 0.6),
        "evidence_directness": 0.7,  # no soil-moisture sensor: inferred from rain + context
    }
    confidence, basis = confidence_from(
        factors, "rainfall deficit + irrigation context; no soil-moisture measurement is available"
    )
    evidence = [weather_input.forecast_evidence(weather, f"{len(rain_values)}-day forecast rainfall used for dry-spell estimate")]

    if probability < 0.45:
        return Assessment(
            risk_type=RISK_TYPES[3],
            status=status,
            probability=probability,
            severity=thresholds.severity_for_probability(probability),
            urgency=thresholds.urgency_for(status, lead),
            warning_lead_time_hours=lead,
            confidence=confidence,
            confidence_basis=basis,
            threat=None,
            reasons=reasons,
            actions=["No irrigation action is indicated by the current forecast."],
            evidence=evidence,
            data_quality={
                "inputs_available": True,
                "soil_moisture_measured": False,
                "weather_freshness": weather.get("freshness"),
            },
        )

    return Assessment(
        risk_type=RISK_TYPES[3],
        status=status,
        probability=probability,
        severity=thresholds.severity_for_probability(probability),
        urgency=thresholds.urgency_for(status, lead),
        warning_lead_time_hours=lead,
        confidence=confidence,
        confidence_basis=basis,
        threat="Water stress possible without timely irrigation",
        reasons=reasons,
        actions=[
            "Check soil moisture at root depth before deciding to irrigate.",
            "Irrigate during cool hours to reduce evaporation losses if stress signs appear.",
            "Record the field condition after irrigation so the next assessment improves.",
        ],
        evidence=evidence,
        data_quality={
            "inputs_available": True,
            "soil_moisture_measured": False,
            "weather_freshness": weather.get("freshness"),
        },
    )


# ---------------------------------------------------------------------------
# 5. Market volatility (§14) — real AGMARKNET records only
# ---------------------------------------------------------------------------

def market_volatility(
    commodity: Any, market_context: Optional[Mapping[str, Any]]
) -> Assessment:
    """Volatility screening from OFFICIAL records already fetched and stored.

    Descriptive statistics only — never price advice, never forecasting.
    Requires >= min_records recent records within the max age window;
    otherwise returns DATA_UNAVAILABLE / INSUFFICIENT_DATA honestly.
    """
    risk_type = RISK_TYPES[4]
    if not market_context or not market_context.get("available"):
        return unavailable(risk_type, str(market_context.get("reason") if market_context else "market_data_not_requested"))

    records = market_context.get("records") or []
    t = thresholds.MARKET_VOLATILITY
    usable: list[dict[str, Any]] = []
    now = datetime.now()
    for record in records:
        modal = record.get("modal_price")
        arrival = record.get("arrival_date")
        if modal is None or arrival is None:
            continue
        try:
            arrival_dt = datetime.fromisoformat(str(arrival)[:10])
        except ValueError:
            continue
        age_days = abs((now - arrival_dt).days)
        if age_days <= t["max_record_age_days"]:
            usable.append({"modal": float(modal), "arrival": arrival, "age_days": age_days})

    if len(usable) < t["min_records"]:
        return insufficient(risk_type, "fewer_than_three_recent_official_records")

    prices = sorted(u["modal"] for u in usable)
    low, high = prices[0], prices[-1]
    median = prices[len(prices) // 2]
    if median <= 0:
        return insufficient(risk_type, "invalid_price_values")

    swing_pct = round((high - low) / median * 100.0, 1)
    reasons = [
        f"Modal price ranged {low:.0f}–{high:.0f} ({swing_pct:.1f}% of median) across {len(usable)} official records.",
    ]
    if swing_pct >= t["swing_high_pct"]:
        probability = 0.7
        reasons.append("The price swing exceeds the high-volatility screening band.")
    elif swing_pct >= t["swing_medium_pct"]:
        probability = 0.5
        reasons.append("The price swing is in the medium-volatility screening band.")
    else:
        probability = 0.2
        reasons.append("Official records show a stable price range.")

    newest_age = min(u["age_days"] for u in usable)
    data_freshness = "fresh" if newest_age <= 2 else ("aging" if newest_age <= 7 else "stale")

    evidence = [
        {
            "type": "market_record",
            "source": market_context.get("provider", "AGMARKNET (data.gov.in)"),
            "observed_at": usable[-1]["arrival"],
            "retrieved_at": market_context.get("retrieved_at"),
            "freshness": data_freshness,
            "detail": f"{len(usable)} official records for {commodity}, newest {newest_age} day(s) old",
        }
    ]
    factors = {
        "input_freshness": {"fresh": 1.0, "aging": 0.85, "stale": 0.6}.get(data_freshness, 0.3),
        "context_completeness": 1.0,
        "evidence_directness": 0.6,  # price ≠ farm-gate realisation
    }
    confidence, basis = confidence_from(
        factors, "descriptive spread of official AGMARKNET modal prices; not a forecast"
    )
    status = thresholds.status_for_probability(probability)

    if probability < 0.45:
        return Assessment(
            risk_type=risk_type,
            status=status,
            probability=probability,
            severity=thresholds.severity_for_probability(probability),
            urgency=thresholds.urgency_for(status, _LEAD_HOURS[risk_type]),
            warning_lead_time_hours=_LEAD_HOURS[risk_type] or None,
            confidence=confidence,
            confidence_basis=basis,
            threat=None,
            reasons=reasons,
            actions=["No market action is indicated; keep selling decisions independent of this screening."],
            evidence=evidence,
            data_quality={"inputs_available": True, "records_used": len(usable)},
        )

    return Assessment(
        risk_type=risk_type,
        status=status,
        probability=probability,
        severity=thresholds.severity_for_probability(probability),
        urgency=thresholds.urgency_for(status, _LEAD_HOURS[risk_type]),
        warning_lead_time_hours=_LEAD_HOURS[risk_type] or None,
        confidence=confidence,
        confidence_basis=basis,
        threat="Notable price movement in official mandi records",
        reasons=reasons,
        actions=[
            "Compare current official mandi prices before finalising any sale.",
            "Treat this as information, not advice — discuss timing with a trader or agriculture officer.",
        ],
        evidence=evidence,
        data_quality={"inputs_available": True, "records_used": len(usable)},
        requires_expert_confirmation=True,
    )


ANALYZERS = {
    RISK_TYPES[0]: disease_conducive_weather,
    RISK_TYPES[1]: heavy_rain_flooding,
    RISK_TYPES[2]: heat_stress,
    RISK_TYPES[3]: water_stress,
    RISK_TYPES[4]: market_volatility,
}

__all__ = ["ANALYZERS", "disease_conducive_weather", "heavy_rain_flooding", "heat_stress", "water_stress", "market_volatility"]
