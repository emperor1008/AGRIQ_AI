"""Market data freshness and provenance (Phase 6 §17, §18).

Freshness thresholds are **not** redefined here: the single classifier is
``domain.risk_engine.freshness.classify`` (Phase 5), which already owns the
documented windows for the ``market`` input kind (fresh ≤ 24 h, aging ≤ 72 h,
stale ≤ 240 h, expired beyond, ``unavailable`` without a real timestamp). Two
competing freshness tables in one product would be a bug waiting to happen.

What this module adds is the provenance block every Phase 6 output carries:

* ``source`` — the provider actually used
* ``observed_at`` — the provider's own date (provisional arrival date)
* ``retrieved_at`` — when AGRIQ fetched it
* ``age_minutes`` — derived from the real timestamps
* ``freshness_status`` — fresh | aging | stale | expired | unavailable
* ``price_date`` — the provisional arrival date the price belongs to

AGMARKNET publishes *daily provisional* prices, so nothing here is ever labelled
"live". ``is_live`` is always ``False`` and the wording used downstream says
"latest official record", not "live price".
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from ..risk_engine.freshness import classify, confidence_factor

#: AGMARKNET publishes provisional daily prices — never real-time. This flag is
#: part of the contract so no caller can imply a live feed.
IS_LIVE_FEED = False

#: Wording used wherever a price is described to a farmer.
RECORD_DESCRIPTION = "latest official AGMARKNET record"


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _age_minutes(*candidates: Any) -> Optional[int]:
    """Age of the newest usable real timestamp, in whole minutes."""
    best: Optional[float] = None
    now = datetime.now(timezone.utc)
    for value in candidates:
        if value is None:
            continue
        moment: Optional[datetime] = None
        raw = str(value).strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw.replace("Z", "+0000"), fmt)
                moment = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        if moment is None:
            continue
        seconds = (now - moment).total_seconds()
        if best is None or seconds < best:
            best = seconds
    if best is None:
        return None
    return max(0, int(best // 60))


def provenance(
    *,
    source: str,
    retrieved_at: Any = None,
    observed_at: Any = None,
    price_date: Any = None,
    record_count: int = 0,
    detail: str | None = None,
) -> dict[str, Any]:
    """Build the provenance block attached to every market output.

    ``observed_at`` is the provider timestamp when one exists; otherwise the
    provisional price date stands in for it and that substitution is stated in
    ``timestamp_basis`` so nobody mistakes a price date for a fetch time.
    """
    status = classify("market", observed_at or retrieved_at, retrieved_at)
    if observed_at is None and retrieved_at is None:
        status = "unavailable"
    return {
        "source": source,
        "observed_at": str(observed_at) if observed_at else None,
        "retrieved_at": str(retrieved_at) if retrieved_at else None,
        "price_date": _as_date(price_date).isoformat() if _as_date(price_date) else None,
        "age_minutes": _age_minutes(retrieved_at, observed_at),
        "freshness_status": status,
        "confidence_factor": confidence_factor(status),
        "is_live": IS_LIVE_FEED,
        "timestamp_basis": (
            "provider observation timestamp" if observed_at else
            ("fetch timestamp" if retrieved_at else "no usable timestamp")
        ),
        "record_count": record_count,
        "record_description": RECORD_DESCRIPTION,
        "detail": detail,
    }


def unavailable_provenance(reason: str) -> dict[str, Any]:
    """Provenance block for the honest 'no verified data' state."""
    return {
        "source": None,
        "observed_at": None,
        "retrieved_at": None,
        "price_date": None,
        "age_minutes": None,
        "freshness_status": "unavailable",
        "confidence_factor": 0.0,
        "is_live": IS_LIVE_FEED,
        "timestamp_basis": "no data retrieved",
        "record_count": 0,
        "record_description": RECORD_DESCRIPTION,
        "detail": reason,
        "reason": reason,
    }


__all__ = [
    "IS_LIVE_FEED",
    "RECORD_DESCRIPTION",
    "provenance",
    "unavailable_provenance",
]
