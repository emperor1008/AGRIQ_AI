"""Market trend and volatility from real dated observations (Phase 6 §6).

A trend is only published when there are enough *distinct real observation
dates* in the window. Two records on the same day are not a trend, and a single
snapshot is not a trend — both return ``insufficient_data`` with the observed
count so the caller can explain the gap rather than guess.

Volatility deliberately reuses the Phase 5 band definition
(``risk_engine.thresholds.MARKET_VOLATILITY``: 8 % medium, 15 % high modal-price
swing). Duplicating those bands would let the risk panel and the market panel
disagree about the same price series.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Any, Iterable, Optional, Sequence

from ..risk_engine import thresholds
from .normalization import NormalizedRecord, scope_to_primary_commodity

#: Distinct observation dates required before a trend is published.
MIN_POINTS_FOR_TREND = 3

#: Percentage deadband inside which a move is reported as "stable".
STABLE_DEADBAND_PCT = 2.0

#: Default look-back window for trend/volatility.
DEFAULT_WINDOW_DAYS = 90


def _dated(records: Iterable[NormalizedRecord]) -> list[NormalizedRecord]:
    usable = [r for r in records if r.arrival_date is not None and r.modal_price is not None]
    return sorted(usable, key=lambda r: r.arrival_date)


def scoped(records: Iterable[NormalizedRecord]) -> tuple[list[NormalizedRecord], dict[str, Any]]:
    """Records restricted to one provider commodity, with the choice recorded.

    A single provider response can carry more than one commodity spelling whose
    prices are different definitions ("Rice" vs "Paddy(Dhan)(Common)"). Blending
    them into one median would invent a price, so every calculation below uses the
    dominant spelling and reports what it left out.
    """
    usable, dominant, excluded = scope_to_primary_commodity(_dated(records))
    return usable, {
        "provider_commodity": dominant,
        "excluded_provider_commodities": excluded,
        "scope_note": (
            "Calculated from a single provider commodity spelling; other spellings in the "
            "same response are reported as excluded rather than averaged in."
            if excluded else None
        ),
    }


def series_points(
    records: Iterable[NormalizedRecord],
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    today: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Chronological ``[{date, modal_price}]`` points inside the window.

    When several markets report on the same date the **median** modal price for
    that date is used, which is stated in the returned metadata rather than
    presented as a single market's price.
    """
    usable, _ = scoped(records)
    if today is not None:
        cutoff = today - timedelta(days=window_days)
        usable = [r for r in usable if r.arrival_date and r.arrival_date >= cutoff]

    by_date: dict[date, list[float]] = {}
    for record in usable:
        by_date.setdefault(record.arrival_date, []).append(float(record.modal_price))
    return [
        {
            "date": day.isoformat(),
            "modal_price": round(median(prices), 2),
            "markets_reporting": len(prices),
        }
        for day, prices in sorted(by_date.items())
    ]


def trend(
    records: Iterable[NormalizedRecord],
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Direction and size of price movement over the window.

    Returns ``status="insufficient_data"`` with the observed point count when
    fewer than :data:`MIN_POINTS_FOR_TREND` distinct real dates exist.
    """
    points = series_points(records, window_days=window_days, today=today)
    _, scope = scoped(records)
    if len(points) < MIN_POINTS_FOR_TREND:
        return {
            "status": "insufficient_data",
            "reason": (
                f"{len(points)} distinct official observation date(s) in the last "
                f"{window_days} days; {MIN_POINTS_FOR_TREND} are required to describe a trend"
            ),
            "points": len(points),
            "required_points": MIN_POINTS_FOR_TREND,
            "series": points,
            **scope,
        }

    first, last = points[0], points[-1]
    change = round(last["modal_price"] - first["modal_price"], 2)
    base = first["modal_price"] or 0.0
    change_pct = round((change / base) * 100.0, 2) if base else None

    if change_pct is None:
        direction = "unknown"
    elif change_pct > STABLE_DEADBAND_PCT:
        direction = "rising"
    elif change_pct < -STABLE_DEADBAND_PCT:
        direction = "falling"
    else:
        direction = "stable"

    return {
        "status": "ok",
        "direction": direction,
        "change_absolute": change,
        "change_percent": change_pct,
        "first": first,
        "last": last,
        "points": len(points),
        "window_days": window_days,
        "stable_deadband_percent": STABLE_DEADBAND_PCT,
        "series": points,
        **scope,
        "basis": (
            "Median modal price per observation date from official records; "
            "direction uses a ±2 % deadband."
        ),
    }


def volatility(records: Iterable[NormalizedRecord]) -> dict[str, Any]:
    """Modal-price spread across official records, using the Phase 5 bands."""
    usable, scope = scoped(records)
    prices = sorted(float(r.modal_price) for r in usable if r.modal_price is not None)
    if len(prices) < 2:
        return {
            "status": "insufficient_data",
            "reason": f"{len(prices)} usable official observation(s); 2 are required",
            "records": len(prices),
        }
    low, high = prices[0], prices[-1]
    middle = median(prices)
    if middle <= 0:
        return {"status": "insufficient_data", "reason": "median price is not usable"}
    swing_pct = round((high - low) / middle * 100.0, 2)

    bands = thresholds.MARKET_VOLATILITY
    if swing_pct >= bands["swing_high_pct"]:
        band = "high"
    elif swing_pct >= bands["swing_medium_pct"]:
        band = "medium"
    else:
        band = "low"

    return {
        "status": "ok",
        "band": band,
        "swing_percent": swing_pct,
        "low": low,
        "high": high,
        "median": round(middle, 2),
        "records": len(prices),
        "bands": {"medium_percent": bands["swing_medium_pct"], "high_percent": bands["swing_high_pct"]},
        "basis": "Modal-price spread vs median across official records (Phase 5 volatility bands).",
        **scope,
    }


def latest_by_market(records: Iterable[NormalizedRecord]) -> list[NormalizedRecord]:
    """Newest official record per (market, variety), price-dated."""
    usable, _ = scoped(records)
    newest: dict[tuple[str, str], NormalizedRecord] = {}
    for record in usable:
        key = (record.market.lower(), (record.variety or "").lower())
        current = newest.get(key)
        if current is None or (record.arrival_date or date.min) >= (current.arrival_date or date.min):
            newest[key] = record
    return sorted(newest.values(), key=lambda r: (-(r.modal_price or 0.0), r.market))


def seasonal_index(records: Sequence[NormalizedRecord], *, weeks: int = 4) -> dict[str, Any]:
    """Per-week-of-observation index from real history.

    Only published with enough weeks of real data; otherwise the caller is told
    the index is unavailable rather than shown an invented seasonal curve.
    """
    points = series_points(records)
    if len(points) < MIN_POINTS_FOR_TREND * weeks:
        return {
            "status": "insufficient_data",
            "reason": (
                f"{len(points)} observation date(s); at least "
                f"{MIN_POINTS_FOR_TREND * weeks} are required for a seasonal index"
            ),
        }
    buckets: dict[int, list[float]] = {}
    for point in points:
        week = date.fromisoformat(point["date"]).isocalendar().week
        buckets.setdefault(week % weeks, []).append(point["modal_price"])
    overall = median([p["modal_price"] for p in points]) or 1.0
    return {
        "status": "ok",
        "index": {
            str(bucket): round(median(values) / overall, 3)
            for bucket, values in sorted(buckets.items())
        },
        "basis": "Median price per rotating week bucket relative to the overall median.",
    }


__all__ = [
    "scoped",
    "MIN_POINTS_FOR_TREND",
    "STABLE_DEADBAND_PCT",
    "DEFAULT_WINDOW_DAYS",
    "series_points",
    "trend",
    "volatility",
    "latest_by_market",
    "seasonal_index",
]
