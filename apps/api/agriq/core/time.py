"""Time helpers.

Database policy (Phase 1): all persisted timestamps are **UTC**. Asia/Kolkata
(IST) formatting helpers remain for user-facing weather UI labels only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST_OFFSET = timedelta(hours=5, minutes=30)
IST_TZ = timezone(IST_OFFSET)  # fixed-offset Asia/Kolkata (no DST)

_USER_FORMAT = "%d %b %Y • %I:%M %p"


def utc_now() -> datetime:
    """Current UTC time (timezone-aware, stored as UTC in the database)."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Normalise a datetime to timezone-aware UTC (naive values assumed UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    """ISO-8601 UTC string for API payloads and provenance labels."""
    return as_utc(value or utc_now()).isoformat()


def parse_provider_time(value: str | None) -> datetime | None:
    """Parse a provider timestamp into aware UTC; None when unparseable.

    Provider strings are accepted with or without an explicit offset; naive
    values from Open-Meteo carry a named timezone offset we know beforehand,
    so callers pass that offset where relevant.
    """
    if not value:
        return None
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z",
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(text[:len(text) - (1 if text.endswith("Z") else 0)] if text.endswith("Z") else text, fmt)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def now_ist() -> datetime:
    """Current Asia/Kolkata wall-clock time (naive, UTC + 5:30). UI labels only."""
    return datetime.utcnow() + IST_OFFSET


def format_weather_time(value: str | None = None) -> str:
    """Return a user-friendly Asia/Kolkata timestamp for weather cards."""
    if not value:
        return (datetime.utcnow() + IST_OFFSET).strftime(_USER_FORMAT)
    value = str(value)
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value[:19], fmt).strftime(_USER_FORMAT)
        except ValueError:
            continue
    return value.replace("T", " ")


def ist_clock() -> str:
    """Short IST clock (used for 'updated at' labels)."""
    return (datetime.utcnow() + IST_OFFSET).strftime("%I:%M %p")


def ist_hour_key() -> str:
    """Hourly cache key, e.g. ``2026-09-22-14``."""
    return (datetime.utcnow() + IST_OFFSET).strftime("%Y-%m-%d-%H")


def ist_date(offset_days: int = 0) -> str:
    """ISO date string for today (or today + offset) in IST."""
    return (datetime.utcnow() + IST_OFFSET + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def ist_day_label(offset_days: int) -> str:
    """Short day label like ``23 Sep`` for forecast cards."""
    return (datetime.utcnow() + IST_OFFSET + timedelta(days=offset_days)).strftime("%d %b")


__all__ = [
    "IST_OFFSET",
    "IST_TZ",
    "utc_now",
    "as_utc",
    "iso_utc",
    "parse_provider_time",
    "now_ist",
    "format_weather_time",
    "ist_clock",
    "ist_hour_key",
    "ist_date",
    "ist_day_label",
]
