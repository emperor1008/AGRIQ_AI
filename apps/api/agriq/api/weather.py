"""Live weather API blueprint (GET /api/live-weather).

Phase 1 real-data policy: the response carries either live Open-Meteo data
(labelled) or an explicit unavailable state — the offline seasonal model is
no longer executed in production. The risk-linked forecast rows are only
produced when verified weather is available.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..domain.catalogs.crops import resolve_crop
from ..integrations.weather import open_meteo
from ..schemas.weather import parse_weather_query
from ..services.weather_advisory import build_weather_console, forecast_for

weather_bp = Blueprint("weather", __name__)


@weather_bp.get("/api/live-weather")
def live_weather_api():
    query = parse_weather_query(request.args)
    crop, _ = resolve_crop(query.crop)
    weather = open_meteo.get_weather(query.district)

    console = build_weather_console(
        query.district, crop, weather, open_meteo.forecast_weather(weather)
    )
    if not weather.get("available"):
        return jsonify({
            "weather_console": console,
            "risk_forecast": [],
            "message": weather.get("message", "Verified data is currently unavailable."),
        })

    risk_forecast = forecast_for(crop, query.district, weather, query.growth_stage, query.field_condition)
    return jsonify({"weather_console": console, "risk_forecast": risk_forecast})
