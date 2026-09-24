"""Data freshness semantics for the risk engine (Phase 5 §16).

Every external datum is classified as fresh / aging / stale / expired /
unavailable from its REAL provider timestamps. No timestamp is ever
fabricated; classification only compares stored provider times to now.

Stale inputs may still inform an assessment, but the result carries reduced
confidence and the staleness is surfaced to the farmer (§16, §50).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

from ...core.time import as_utc, utc_now

# Age windows (hours) per input kind. Documented in docs/risk-engine.md.
_FRESH_HOURS = {"weather": 1.5, "market": 24.0}
_AGING_HOURS = {"weather": 6.0, "market": 72.0}
_STALE_HOURS = {"weather": 36.0, "market": 240.0}

STATUSES = ("fresh", "aging", "stale", "expired", "unavailable")


def classify(kind: str, observed_at: Any, retrieved_at: Any) -> str:
    """Classify one input's freshness from its real timestamps.

    ``observed_at`` (provider time) is preferred; ``retrieved_at`` is the
    fallback when the provider did not supply an observation time.
    """
    reference: Optional[datetime] = None
    for value in (observed_at, retrieved_at):
        if value is None:
            continue
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
        if isinstance(value, datetime):
            reference = as_utc(value)
            break
    if reference is None:
        return "unavailable"

    age_h = (utc_now() - reference).total_seconds() / 3600.0
    if age_h < 0:  # provider clock slightly ahead of ours
        age_h = 0.0
    kind = kind if kind in _FRESH_HOURS else "weather"
    if age_h <= _FRESH_HOURS[kind]:
        return "fresh"
    if age_h <= _AGING_HOURS[kind]:
        return "aging"
    if age_h <= _STALE_HOURS[kind]:
        return "stale"
    return "expired"


def confidence_factor(freshness: str) -> float:
    """Multiplier applied to assessment confidence by input freshness.

    Documented, versioned mapping — stale data never silently counts as
    fresh evidence.
    """
    return {
        "fresh": 1.0,
        "aging": 0.85,
        "stale": 0.6,
        "expired": 0.3,
        "unavailable": 0.0,
    }[freshness]


def freshness_summary(kind: str, observed_at: Any, retrieved_at: Any) -> dict[str, Any]:
    """Provenance block attached to every evidence item."""
    status = classify(kind, observed_at, retrieved_at)
    return {
        "kind": kind,
        "observed_at": _iso(observed_at),
        "retrieved_at": _iso(retrieved_at),
        "freshness_status": status,
    }


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return as_utc(value).isoformat()
    if isinstance(value, timedelta):
        return None
    return str(value)


__all__ = [
    "STATUSES",
    "classify",
    "confidence_factor",
    "freshness_summary",
]
