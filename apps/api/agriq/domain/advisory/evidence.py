"""Evidence builder: assembles freshness-labelled evidence from verified
sources (weather service, farmer records, soil tests, knowledge retrieval,
market records). No item is ever created without a real source and timestamp.
"""
from __future__ import annotations

from typing import Any, Optional

from ..safety.chemical_rules import ChemicalSafetyResult
from .recommendation import EvidenceItem


def weather_evidence(weather: Optional[dict[str, Any]]) -> Optional[EvidenceItem]:
    """Evidence item from the weather service result (or None if unavailable).

    The weather service exposes ``temp``/``wind`` keys and freshness via
    live/cached/stale flags — both are normalised here.
    """
    if not weather or not weather.get("available"):
        return None
    if weather.get("stale"):
        freshness = "stale"
    elif weather.get("cached"):
        freshness = "cached"
    elif weather.get("live"):
        freshness = "live"
    else:
        freshness = "unavailable"
    return EvidenceItem(
        type="weather_forecast" if weather.get("is_forecast") else "weather_observation",
        source=str(weather.get("provider", "Open-Meteo")),
        observed_or_retrieved_at=weather.get("provider_observed_at") or weather.get("retrieved_at"),
        detail=(
            f"temperature {weather.get('temp')}°C, humidity {weather.get('humidity')}%, "
            f"precipitation {weather.get('precipitation')} mm"
        ),
        freshness=freshness,
    )


def crop_cycle_evidence(cycle: dict[str, Any]) -> EvidenceItem:
    """Evidence from the farmer's own crop-cycle record."""
    parts = [f"crop {cycle.get('crop')}"]
    if cycle.get("stage"):
        parts.append(f"stage {cycle.get('stage')}")
    if cycle.get("sowing_date"):
        parts.append(f"sown {cycle.get('sowing_date')}")
    return EvidenceItem(
        type="farmer_record",
        source=f"Crop cycle {cycle.get('id')}",
        observed_or_retrieved_at=cycle.get("updated_at"),
        detail=", ".join(parts),
        freshness="n/a",
    )


def observation_evidence(observation: dict[str, Any]) -> EvidenceItem:
    """Evidence from a farmer-recorded field observation."""
    return EvidenceItem(
        type="farmer_record",
        source=f"Observation {observation.get('id')}",
        observed_or_retrieved_at=observation.get("observed_at"),
        detail=observation.get("notes") or observation.get("field_condition") or "field observation",
        freshness="n/a",
    )


def soil_test_evidence(soil: Optional[dict[str, Any]]) -> Optional[EvidenceItem]:
    """Evidence from the most recent soil test, with source type."""
    if not soil:
        return None
    return EvidenceItem(
        type="soil_test",
        source=soil.get("source_type", "unknown"),
        observed_or_retrieved_at=soil.get("tested_at"),
        detail=soil.get("summary") or "soil test on record",
        freshness="n/a",
    )


def knowledge_evidence(chunk: dict[str, Any]) -> EvidenceItem:
    """Evidence from an approved knowledge chunk."""
    return EvidenceItem(
        type="knowledge",
        source=f"{chunk.get('organisation')} — {chunk.get('title')}",
        observed_or_retrieved_at=chunk.get("retrieved_at") or chunk.get("publication_date"),
        detail=(chunk.get("section_reference") or "")[:200] or "approved advisory section",
        freshness="n/a",
    )


def market_evidence(record: dict[str, Any]) -> EvidenceItem:
    """Evidence from an official AGMARKNET record."""
    return EvidenceItem(
        type="market_record",
        source=str(record.get("source", "AGMARKNET via data.gov.in")),
        observed_or_retrieved_at=record.get("retrieved_at"),
        detail=(
            f"{record.get('commodity')} modal price {record.get('modal_price')} "
            f"at {record.get('market')} on {record.get('arrival_date')}"
        ),
        freshness="live",
    )


def guardrail_evidence(result: ChemicalSafetyResult) -> Optional[EvidenceItem]:
    """Evidence note when a safety rule fired (why something was blocked)."""
    if not result.blocked or not result.reason:
        return None
    return EvidenceItem(
        type="safety_rule",
        source="AGRIQ safety guardrails",
        detail=result.reason,
        freshness="n/a",
    )


__all__ = [
    "weather_evidence", "crop_cycle_evidence", "observation_evidence",
    "soil_test_evidence", "knowledge_evidence", "market_evidence",
    "guardrail_evidence",
]
