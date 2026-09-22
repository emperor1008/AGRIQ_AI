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
from ..core.time import utc_now
from ..extensions import db
from ..integrations.market import agmarknet
from ..models.farmer import MarketPriceRecord

logger = get_logger("services.market_service")


def _unavailable(reason: str) -> dict[str, Any]:
    from ..core.constants import PROVIDER_AGMARKNET

    return {
        "available": False,
        "provider": PROVIDER_AGMARKNET,
        "reason": reason,
        "message": "Verified data is currently unavailable.",
        "records": [],
        "retrieved_at": None,
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
        return _unavailable(result.get("reason", "provider_request_failed"))

    stored: list[dict[str, Any]] = []
    for record in result.get("records", []):
        persisted = _persist_record(record, state)
        if persisted is not None:
            stored.append(_record_to_dict(persisted))
    return {
        "available": True,
        "provider": PROVIDER_AGMARKNET,
        "records": stored,
        "retrieved_at": iso_or_none(result.get("retrieved_at")) or utc_now().isoformat(),
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


__all__ = ["get_mandi_prices"]
