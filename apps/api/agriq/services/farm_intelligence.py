"""Farm Intelligence service (ARC-07): full farmer analysis orchestration.

Phase 1 real-data policy:
- Weather comes only from the live Open-Meteo call. When the provider is
  unavailable the analysis is still produced from crop/stage/field/LeafScan
  evidence, with the weather-driven components honestly omitted and the
  console showing "Verified data is currently unavailable."
- Market figures: Phase 7 removed the curated price bands entirely (they
  recorded no source, and an invented fallback band was applied to unlisted
  crops). Live mandi records come only from the AGMARKNET integration via
  services/market_service and are reported as unavailable when they cannot be
  fetched — this module now emits an explicit unavailable state instead of a
  rupee range.
- Rule-based indicators (risk score, crop health, yield protection, indicative
  loss band, screening confidence) are heuristics, not measurements. They ship
  with ``heuristic_status`` / ``confidence_status`` / ``yield_loss_status`` and
  a documented basis string; the formulas are reproduced verbatim in
  ``docs/dashboard-heuristics.md``.
- District map markers: the selected analysis district carries the actual
  score; every other district shows "Awaiting verified analysis." — no
  offline-model risk values are generated for unanalysed districts.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..core.config import BaseConfig
from ..core.constants import (
    AWAITING_ANALYSIS_MESSAGE,
    BASIS_RULE_HEURISTIC,
    BASIS_UNCALIBRATED_SCREENING,
    NO_VERIFIED_IMPACT_MESSAGE,
    NO_VERIFIED_MARKET_MESSAGE,
    TOKEN_DATA_UNAVAILABLE,
    TOKEN_YIELD_IMPACT_NOT_MEASURED,
)
from ..domain.catalogs.crops import resolve_crop
from ..domain.catalogs.districts import DISTRICTS
from ..domain.risk.explanations import english_advisory, explain_reasons, odia_advisory
from ..domain.risk.recommendations import (
    action_plan,
    before_after,
    build_treatment_console,
    digital_farm_twin,
)
from ..domain.risk.scoring import (
    clamp,
    component_scores,
    confidence_score,
    confidence_status,
    crop_health,
    heuristic_status,
    productivity_score,
    risk_color,
    risk_status,
    urgency,
    yield_loss_band,
    yield_loss_status,
)
from . import leaf_analysis
from .weather_advisory import build_weather_console, forecast_for


def market_advisory(crop_key: str, district: str, score: float, productivity: int) -> dict[str, Any]:
    """Market context block — honest unavailable state (Phase 7 §2/§53).

    This block used to render a hand-curated ₹/quintal band, including an
    invented fallback band for crops missing from that table. No sourced price
    series exists for advisory context, and a plausible-looking number is not a
    source, so AGRIQ now states the limitation instead of showing one. Live
    mandi prices come only from the AGMARKNET provider through
    ``services.market_service``; the market panel and the Copilot are the real
    market surfaces.

    The behavioural advice is retained: it is generic selling guidance, not a
    data claim, and it makes no numerical assertion.
    """
    return {
        "available": False,
        "status": TOKEN_DATA_UNAVAILABLE,
        "range": None,
        "pressure": None,
        "message": NO_VERIFIED_MARKET_MESSAGE,
        "advice": (
            "Do not rush selling only due to crop risk. Compare local mandi rate, crop "
            "quality, storage condition and urgent cash need before decision."
        ),
    }


def profit_impact(score: float, crop_key: str) -> str:
    """Rupee impact is NOT estimated (Phase 7 §2/§53).

    The previous implementation multiplied a curated price band by the risk
    score to print "₹X - ₹Y / acre if untreated". Three unsourced inputs were
    chained into a currency figure, so it was removed rather than labelled: a
    rupee amount a farmer might act on cannot be produced from data AGRIQ does
    not have.
    """
    return NO_VERIFIED_IMPACT_MESSAGE


def make_map_data(
    crop: Mapping[str, Any],
    selected_district: str | None = None,
    selected_score: int | None = None,
    growth_stage: str = "Vegetative",
    field_condition: str = "Normal field",
) -> list[dict[str, Any]]:
    """District map markers with the awaiting-analysis policy.

    Only the analysed (selected) district carries a real computed score.
    Every other district is marked ``analysed=False`` and the UI shows
    "Awaiting verified analysis." — no offline-model values are generated.
    """
    rows: list[dict[str, Any]] = []
    for name, (lat, lon) in DISTRICTS.items():
        analysed = selected_district == name and selected_score is not None
        rows.append({
            "district": name,
            "lat": lat,
            "lon": lon,
            "risk": int(selected_score) if analysed else None,
            "status": risk_status(int(selected_score)) if analysed else "PENDING",
            "color": risk_color(int(selected_score)) if analysed else "green",
            "selected": analysed,
            "analysed": analysed,
            "awaiting": AWAITING_ANALYSIS_MESSAGE,
        })

    rows.sort(key=lambda row: (row["risk"] is None, -(row["risk"] or 0)))
    return rows


def analyze_farm(
    crop_name: str,
    district: str,
    growth_stage: str,
    field_condition: str,
    leaf_file: Any,
    config: BaseConfig | None = None,
) -> dict[str, Any]:
    """Produce the full Farmer dashboard analysis payload."""
    from ..integrations.weather import open_meteo

    crop, crop_key = resolve_crop(crop_name)
    weather = open_meteo.get_weather(district)
    leafscan = leaf_analysis.safe_analyze(leaf_file)
    components = component_scores(crop, weather, leafscan, district, growth_stage, field_condition)
    score = int(clamp(sum(components.values()), 0, 96))
    health = crop_health(score, leafscan)
    productivity = productivity_score(score, weather, growth_stage)
    weather_console = build_weather_console(district, crop, weather, open_meteo.forecast_weather(weather))
    treatment = build_treatment_console(crop, score, leafscan, field_condition, weather)
    map_data = make_map_data(crop, district, score, growth_stage, field_condition)
    rank = next((idx + 1 for idx, row in enumerate(map_data) if row["district"] == district), 1)

    forecast = forecast_for(crop, district, weather, growth_stage, field_condition) if weather.get("available") else []

    result: dict[str, Any] = {
        "district": district,
        "crop": crop,
        "crop_key": crop_key,
        "growth_stage": growth_stage,
        "field_condition": field_condition,
        "weather": weather,
        "weather_available": bool(weather.get("available")),
        "leafscan": leafscan,
        "components": components,
        "risk": score,
        "status": risk_status(score),
        "color": risk_color(score),
        "urgency": urgency(score),
        "health": health,
        "productivity": productivity,
        "yield_loss": yield_loss_band(score),
        "profit_impact": profit_impact(score, crop_key),
        "confidence": confidence_score(score, weather, leafscan, components),
        # Phase 7 §3: every rule-based number ships with its own honest status
        # and basis, so no consumer can present a heuristic as a measurement or
        # a screening band as calibrated confidence.
        "heuristic_status": heuristic_status(),
        "heuristic_basis": BASIS_RULE_HEURISTIC,
        "confidence_status": confidence_status(),
        "confidence_basis": BASIS_UNCALIBRATED_SCREENING,
        "yield_loss_status": yield_loss_status(),
        "yield_loss_basis": BASIS_RULE_HEURISTIC,
        "impact_status": TOKEN_YIELD_IMPACT_NOT_MEASURED,
        "reasons": explain_reasons(crop, weather, components, leafscan, growth_stage, field_condition),
        "farm_twin": digital_farm_twin(crop, district, weather, score, growth_stage, field_condition),
        "before_after": before_after(score),
        "action_plan": action_plan(score, crop, growth_stage, field_condition),
        "english_advisory": english_advisory(score, crop),
        "odia_advisory": odia_advisory(score),
        "market": market_advisory(crop_key, district, score, productivity),
        "weather_console": weather_console,
        "treatment": treatment,
        "forecast": forecast,
        "top_hotspots": [],
        "district_rank": rank,
        "map_data": map_data,
    }
    result["dropdown_sections"] = build_farmer_dropdown_sections(result)
    return result


def build_farmer_dropdown_sections(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Ordered dropdown cards for the Farmer dashboard."""
    treatment = analysis["treatment"]
    leafscan = analysis["leafscan"]
    weather = analysis["weather"]
    weather_line = (
        f"{weather.get('temp')}°C • {weather.get('humidity')}% humidity • {weather.get('rain')} mm rain"
        if weather.get("temp") is not None
        else "Verified data is currently unavailable."
    )
    forecast = analysis.get("forecast", [])
    return [
        {
            "anchor": "intelligence",
            "title": "🧠 1. Why This Risk?",
            "badge": analysis["status"] + " • " + analysis["urgency"],
            "paragraphs": [analysis["reasons"]["en"], analysis["reasons"].get("od", "")],
            "rows": [
                {"left": "Crop", "right": analysis["crop"]["name"]},
                {"left": "District", "right": analysis["district"]},
                {"left": "Growth stage", "right": analysis["growth_stage"]},
                {"left": "Field condition", "right": analysis["field_condition"]},
                {"left": "Weather", "right": weather_line},
            ],
        },
        {
            "anchor": "riskBreakdown",
            "title": "📊 2. Risk Breakdown",
            "badge": str(analysis["risk"]) + "% risk • rule estimate",
            "rows": [{"left": name, "right": str(value) + "%"} for name, value in analysis["components"].items()],
        },
        {
            "anchor": "farmTwin",
            "title": "🌱 3. Digital Farm Twin",
            "badge": analysis["district"],
            "rows": [{"left": k.replace("_", " ").title(), "right": v} for k, v in analysis["farm_twin"].items()],
        },
        {
            "anchor": "leafScanHub",
            "title": "📸 4. LeafScan Symptom Intelligence",
            "badge": "Image-based support" if leafscan.get("available") else "No image uploaded",
            "paragraphs": [leafscan.get("symptom", ""), leafscan.get("explanation", ""), leafscan.get("recommendation", "")],
            "rows": [
                {"left": "Green %", "right": str(leafscan.get("green_pct", 0))},
                {"left": "Yellow %", "right": str(leafscan.get("yellow_pct", 0))},
                {"left": "Brown %", "right": str(leafscan.get("brown_pct", 0))},
                {"left": "Dark %", "right": str(leafscan.get("dark_pct", 0))},
            ],
            "image": leafscan.get("preview"),
        },
        {
            "anchor": "yieldHub",
            "title": "💰 5. Yield, Profit & Before/After Impact",
            # Phase 7 §2/§53: the badge used to print the yield-loss band as if
            # it were measured. The band is still shown below, labelled.
            "badge": "Indicative bands — not measured",
            "paragraphs": [
                analysis["before_after"].get("message", ""),
                analysis["market"].get("advice", ""),
                analysis["market"].get("message", ""),
                "Basis: " + str(analysis.get("yield_loss_basis", BASIS_RULE_HEURISTIC)),
            ],
            "rows": [
                {"left": "Crop health (rule estimate, not measured)",
                 "right": str(analysis["health"]) + "%"},
                {"left": "Yield protection (rule estimate, not measured)",
                 "right": str(analysis["productivity"]) + "%"},
                {"left": "If untreated (indicative band, not a measurement)",
                 "right": analysis["before_after"].get("untreated", "")},
                {"left": "Early-action scenario (illustrative, not a forecast)",
                 "right": analysis["before_after"].get("after_action_risk", "")},
                {"left": "Protection potential (qualitative)",
                 "right": analysis["before_after"].get("protection", "")},
                {"left": "Profit impact", "right": analysis.get("profit_impact", "")},
                {"left": "Mandi price",
                 "right": "Not available — no verified source"},
            ],
        },
        {
            "anchor": "actionPlanHub",
            "title": "🗓️ 6. 7-Day Farmer Action Plan",
            "badge": "Step-by-step",
            "items": analysis.get("action_plan", []),
        },
        {
            "anchor": "treatmentConsole",
            "title": "🛡️ 7. Protection & Treatment Console",
            "badge": treatment.get("possible_disease", "") + " / " + treatment.get("possible_pest", ""),
            "paragraphs": ["Decision rule: " + treatment.get("decision_rule", ""), treatment.get("disclaimer_en", ""), treatment.get("disclaimer_od", "")],
            "items": (
                ["Prevention: " + x for x in treatment.get("prevention", [])]
                + ["Natural: " + x for x in treatment.get("natural", [])]
                + ["Chemical safety: " + x for x in treatment.get("chemical", [])]
            ),
            "rows": [
                {"left": "Possible disease", "right": treatment.get("possible_disease", "")},
                {"left": "Possible pest", "right": treatment.get("possible_pest", "")},
                {"left": "Symptom basis", "right": treatment.get("symptom_basis", "")},
            ],
        },
        {
            "anchor": "forecastHub",
            "title": "🌦️ 8. 7-Day Risk Outlook",
            "badge": "Weather-linked" if forecast else "Awaiting weather",
            "rows": [
                {"left": f["day"], "right": f"{f['risk']}% • {f['status']} • {f['temp']}°C • {f['humidity']}% humidity • {f['rain']} mm rain"}
                for f in forecast
            ] if forecast else [
                {"left": "—", "right": "Forecast requires live weather; verified data is currently unavailable."}
            ],
        },
        {
            "anchor": "hotspotHub",
            "title": "📍 9. Odisha Hotspot Priority",
            "badge": "Verified analysis only",
            "rows": [
                {"left": "—" if not analysis.get("top_hotspots") else f"1. {analysis['district']}",
                 "right": AWAITING_ANALYSIS_MESSAGE if not analysis.get("top_hotspots")
                 else f"{analysis['risk']}% • {analysis['status']}"},
            ],
        },
        {
            "anchor": "advisoryHub",
            "title": "🌐 10. English + Odia Advisory",
            "badge": "Farmer-ready",
            "paragraphs": [analysis.get("english_advisory", ""), analysis.get("odia_advisory", "")],
        },
    ]


__all__ = ["analyze_farm", "make_map_data", "market_advisory", "profit_impact", "build_farmer_dropdown_sections"]
