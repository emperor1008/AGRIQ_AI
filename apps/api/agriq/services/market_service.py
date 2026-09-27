"""Market service (Phase 1): official mandi records with persistence.

Fetches AGMARKNET records for the farmer's crop/district, stores exactly
what the provider returned (source, retrieval time, record hash) with a
unique constraint guarding against duplicate official rows. When the
provider is unavailable the service reports an explicit unavailable state —
no estimated, cached-beyond-TTL or locally generated prices are displayed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Mapping, Optional

from flask import current_app

from ..core.logging import get_logger
from ..core.time import iso_utc, utc_now
from ..extensions import db
from ..integrations.market import agmarknet
from ..models.farmer import MarketPriceRecord

logger = get_logger("services.market_service")

_SOURCE_LABEL = "AGMARKNET via data.gov.in"

#: Provider failure reason → machine-readable state (same vocabulary as weather).
_MANDI_STATE_BY_REASON = {
    "api_key_not_configured": "CONFIGURATION_ERROR",
    "provider_request_failed": "DATA_SOURCE_ERROR",
    "provider_timeout": "DATA_SOURCE_ERROR",
    "provider_http_error": "DATA_SOURCE_ERROR",
    "provider_malformed_response": "DATA_SOURCE_ERROR",
}


def _credential_configured() -> bool:
    """Whether this deployment can make a live provider request at all."""
    return bool(str(current_app.config.get("DATA_GOV_IN_API_KEY", "") or "").strip())


def _unavailable(reason: str) -> dict[str, Any]:
    """Explicit unavailable state — a cause and a next step, never a price."""
    from ..core.constants import (
        MANDI_CREDENTIAL_MESSAGE,
        MANDI_SOURCE_ERROR_MESSAGE,
        PROVIDER_AGMARKNET,
        STATE_CONFIGURATION_ERROR,
        STATE_DATA_UNAVAILABLE,
        UNAVAILABLE_MESSAGE,
    )

    state = _MANDI_STATE_BY_REASON.get(reason, STATE_DATA_UNAVAILABLE)
    message = {
        STATE_CONFIGURATION_ERROR: MANDI_CREDENTIAL_MESSAGE,
        "DATA_SOURCE_ERROR": MANDI_SOURCE_ERROR_MESSAGE,
    }.get(state, UNAVAILABLE_MESSAGE)
    return {
        "available": False,
        "provider": PROVIDER_AGMARKNET,
        "reason": reason,
        "state": state,
        "state_message": message,
        "credential_configured": _credential_configured(),
        "message": "Verified data is currently unavailable.",
        "records": [],
        "retrieved_at": None,
        "fetched_at": None,
    }


def get_mandi_prices(
    commodity: str,
    district: str | None = None,
    state: str = "Odisha",
    field_id: int | None = None,
) -> dict[str, Any]:
    """Official records for a commodity/district, persisted and de-duplicated."""
    from ..core.constants import PROVIDER_AGMARKNET

    key = current_app.config.get("DATA_GOV_IN_API_KEY", "").strip()
    resource_id = current_app.config.get("DATA_GOV_IN_MARKET_RESOURCE_ID", "").strip()
    if not key:
        return _unavailable("api_key_not_configured")

    result = agmarknet.fetch_mandi_prices(
        api_key=key,
        commodity=commodity,
        district=district,
        resource_id=resource_id or None,
        state=state,
    )
    if not result.get("available"):
        return _unavailable(result.get("reason") or "provider_request_failed")

    fetched_at = result.get("fetched_at") or iso_utc()
    stored: list[dict[str, Any]] = []
    for record in result.get("records", []):
        persisted = _persist_record(record, state)
        if persisted is not None:
            stored.append(_record_to_dict(persisted))

    from ..core.constants import (
        MANDI_NO_RECORD_MESSAGE,
        STATE_NO_OFFICIAL_RECORD,
        STATE_OK,
    )

    # The provider answered. Zero rows is a real "no official record" answer for
    # this crop/district/date — reported as such, never as an outage, and never
    # filled in with an estimate.
    empty = not stored
    return {
        "available": True,
        "provider": PROVIDER_AGMARKNET,
        "reason": "no_official_record" if empty else None,
        "state": STATE_NO_OFFICIAL_RECORD if empty else STATE_OK,
        "state_message": MANDI_NO_RECORD_MESSAGE if empty else None,
        "credential_configured": True,
        "records": stored,
        "record_count": len(stored),
        "retrieved_at": fetched_at,
        "fetched_at": fetched_at,
        "provider_updated_at": result.get("provider_updated_at"),
        "reported_total": result.get("reported_total"),
        "source": _SOURCE_LABEL,
    }


def _persist_record(record: Mapping[str, Any], default_state: str) -> Optional[MarketPriceRecord]:
    """Insert one official record; skip duplicates (integrity error safe)."""
    arrival = _parse_date(record.get("arrival_date"))
    raw_hash = hashlib.sha256(
        json.dumps(record, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    existing = db.session.execute(
        db.select(MarketPriceRecord).where(
            MarketPriceRecord.commodity == (record.get("commodity") or ""),
            MarketPriceRecord.district == record.get("district"),
            MarketPriceRecord.market == record.get("market"),
            MarketPriceRecord.arrival_date == arrival,
            MarketPriceRecord.modal_price == record.get("modal_price"),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    try:
        row = MarketPriceRecord(
            source="AGMARKNET via data.gov.in",
            state=record.get("state") or default_state,
            district=record.get("district"),
            market=record.get("market"),
            commodity=record.get("commodity") or "",
            variety=record.get("variety"),
            arrival_date=arrival,
            minimum_price=record.get("min_price"),
            maximum_price=record.get("max_price"),
            modal_price=record.get("modal_price"),
            retrieved_at=utc_now(),
            raw_record_hash=raw_hash,
        )
        db.session.add(row)
        db.session.commit()
        return row
    except Exception as exc:  # concurrent insert or constraint collision
        db.session.rollback()
        logger.warning("market_record_skipped error=%s", type(exc).__name__)
        return None


def record_status(arrival_date: Any, retrieved_at: Any = None) -> str:
    """Freshness of one official record, from the canonical classifier.

    AGMARKNET publishes *daily provisional* prices, so a record's date is its
    observation time. An old arrival date therefore reads ``stale``/``expired``
    rather than being presented as a current price.
    """
    from ..domain.risk_engine.freshness import classify

    return classify("market", arrival_date, retrieved_at)


def _record_to_dict(row: MarketPriceRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "state": row.state,
        "district": row.district,
        "market": row.market,
        "commodity": row.commodity,
        "variety": row.variety,
        "arrival_date": row.arrival_date.isoformat() if row.arrival_date else None,
        "min_price": row.minimum_price,
        "max_price": row.maximum_price,
        "modal_price": row.modal_price,
        "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
        "record_status": record_status(row.arrival_date, row.retrieved_at),
    }


def _parse_date(value: Any):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text.split(" ")[0], fmt).date()
        except ValueError:
            continue
    return None


def iso_or_none(value: Any) -> str | None:
    return str(value) if value else None


def stored_history(
    commodity: str,
    *,
    district: str | None = None,
    state: str | None = None,
    since_days: int = 180,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """Official records already persisted, as a real dated price history (Phase 6).

    This is the only price history AGRIQ has: rows actually returned by the
    provider and stored over time. Nothing is backfilled, interpolated or
    synthesised, so a thin history stays thin — trend and forecast features then
    report that they lack data instead of inventing a series.
    """
    from datetime import timedelta

    from ..core.time import utc_now

    cutoff = (utc_now() - timedelta(days=max(1, since_days))).date()
    query = (
        db.select(MarketPriceRecord)
        .where(MarketPriceRecord.commodity.isnot(None))
        .where(MarketPriceRecord.arrival_date >= cutoff)
        .order_by(MarketPriceRecord.arrival_date.asc(), MarketPriceRecord.id.asc())
        .limit(limit)
    )
    if district:
        query = query.where(MarketPriceRecord.district == district)
    if state:
        query = query.where(MarketPriceRecord.state == state)

    # Resolve through the catalog so provider names ("Paddy(Dhan)(Common)")
    # and catalog keys/names ("rice", "Rice") compare correctly.
    from ..domain.market.normalization import resolve_commodity

    rows = list(db.session.execute(query).scalars())
    target_key = (resolve_commodity(commodity) or (commodity or "").strip().lower())
    matched: list[dict[str, Any]] = []
    for row in rows:
        if target_key and (resolve_commodity(row.commodity) or "").lower() != target_key:
            continue
        matched.append(_record_to_dict(row))
    return matched


def persisted_summary(
    *,
    district: str | None = None,
    state: str | None = None,
    since_days: int = 180,
) -> dict[str, Any]:
    """Count and recency of official records AGRIQ has already persisted.

    A read-only database query: no provider call, so assembling a farmer context
    can never turn into a network fan-out. The rows are real provider records
    stored earlier; only their arrival date is reported, never a "current" claim.
    """
    from datetime import timedelta

    from sqlalchemy import func

    cutoff = (utc_now() - timedelta(days=max(1, since_days))).date()
    query = (
        db.select(func.count(MarketPriceRecord.id), func.max(MarketPriceRecord.arrival_date))
        .where(MarketPriceRecord.arrival_date.isnot(None))
        .where(MarketPriceRecord.arrival_date >= cutoff)
    )
    if district:
        query = query.where(MarketPriceRecord.district == district)
    if state:
        query = query.where(MarketPriceRecord.state == state)
    count, newest = db.session.execute(query).one()
    return {
        "record_count": int(count or 0),
        "newest_arrival_date": newest.isoformat() if newest else None,
        "window_days": since_days,
        "district": district,
        "state": state,
    }


def context_state(
    *,
    district: str | None = None,
    state: str | None = None,
    commodity: str | None = None,
) -> dict[str, Any]:
    """Real state of official price data for a farmer context (never fetches).

    Separates the cases a UI must not blur together:

    * a credential is missing → ``CONFIGURATION_ERROR`` naming the variable
    * official records are stored → reported with their arrival date and
      canonical freshness (old rows read as historical, not as today's price)
    * a credential exists but nothing is stored yet → ``DATA_UNAVAILABLE``

    ``commodity`` is accepted for callers that know it; the summary is scoped to
    the farmer's district/state because provider commodity names are normalized
    elsewhere and a false "no records" claim would be worse than a wider count.
    """
    from ..core.constants import (
        MANDI_CREDENTIAL_MESSAGE,
        PROVIDER_AGMARKNET,
        STATE_CONFIGURATION_ERROR,
        STATE_DATA_STALE,
        STATE_DATA_UNAVAILABLE,
        STATE_OK,
    )

    credential = _credential_configured()
    summary = persisted_summary(district=district, state=state)
    count = summary["record_count"]
    newest = summary["newest_arrival_date"]
    freshness = record_status(newest) if newest else "unavailable"

    if count and freshness in ("fresh", "aging"):
        state_value: str | None = STATE_OK
        message: str | None = None
    elif count:
        state_value = STATE_DATA_STALE
        message = (
            f"{count} official record(s) are stored and the newest arrival date is "
            f"{newest}. Older official records are shown as historical, not as "
            "today's price."
        )
    elif not credential:
        state_value, message = STATE_CONFIGURATION_ERROR, MANDI_CREDENTIAL_MESSAGE
    else:
        state_value = STATE_DATA_UNAVAILABLE
        message = (
            "No official record has been retrieved yet for this district. Open market "
            "intelligence to request the latest official records."
        )

    return {
        "available": bool(count),
        "provider": PROVIDER_AGMARKNET,
        "source": _SOURCE_LABEL,
        "state": state_value,
        "state_message": message,
        "reason": None if count else (
            "api_key_not_configured" if not credential else "not_retrieved_yet"
        ),
        "credential_configured": credential,
        "commodity": commodity,
        "record_count": count,
        "newest_arrival_date": newest,
        "freshness_status": freshness,
        "fetched_live": False,
        "window_days": summary["window_days"],
        "records": [],
    }


__all__ = ["get_mandi_prices", "stored_history", "persisted_summary", "context_state",
           "record_status"]
