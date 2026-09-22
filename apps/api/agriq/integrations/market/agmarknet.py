"""AGMARKNET (data.gov.in) market price integration (Phase 1).

Fetches official mandi records from the Government of India OGD platform
using the configured API key + resource id. Only provider-returned records
are emitted; the integration never estimates missing prices and never
generates records when the provider is unavailable.
"""
from __future__ import annotations

import time
from typing import Any, Mapping

import requests

from ...core.constants import DATA_GOV_IN_API_URL, PROVIDER_AGMARKNET
from ...core.logging import get_logger

logger = get_logger("integrations.agmarknet")

API_URL = DATA_GOV_IN_API_URL
PARAM_LIMIT = 10
REQUEST_TIMEOUT_SECONDS = 10
MAX_RETRIES = 1


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "provider": PROVIDER_AGMARKNET,
        "reason": reason,
        "message": "Verified data is currently unavailable.",
        "records": [],
        "retrieved_at": None,
    }


def fetch_mandi_prices(
    api_key: str | None,
    commodity: str,
    district: str | None = None,
    resource_id: str | None = None,
    state: str = "Odisha",
) -> dict[str, Any]:
    """Fetch official mandi records for a commodity (optionally by district).

    Returns either ``{"available": True, "provider": ..., "records": [...],
    "retrieved_at": ...}`` with raw provider fields, or an explicit
    unavailable payload. No synthetic records are ever produced.
    """
    key = (api_key or "").strip()
    if not key:
        return _unavailable("api_key_not_configured")
    if not (commodity or "").strip():
        return _unavailable("commodity_required")

    url = API_URL.format(resource_id=resource_id or "9ef84268-d588-465a-a308-a864a43d0070")
    params: dict[str, Any] = {
        "api-key": key,
        "format": "json",
        "limit": PARAM_LIMIT,
        "filters[commodity]": commodity.strip(),
    }
    if state:
        params["filters[state]"] = state
    if district:
        params["filters[district]"] = district.strip()

    attempts = max(0, MAX_RETRIES) + 1
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            records = payload.get("records") or []
            normalized = [_normalize_record(record) for record in records if isinstance(record, Mapping)]
            return {
                "available": True,
                "provider": PROVIDER_AGMARKNET,
                "records": normalized[:PARAM_LIMIT],
                "retrieved_at": payload.get("updated_date"),
                "raw_payload_hash": _payload_hash(payload),
            }
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            logger.warning("agmarknet_http_error status=%s attempt=%s", status, attempt + 1)
            if status is not None and 400 <= status < 500:
                return _unavailable("provider_request_failed")
        except Exception as exc:
            logger.warning("agmarknet_failed error=%s attempt=%s", type(exc).__name__, attempt + 1)
        if attempt < attempts - 1:
            time.sleep(0.5)
    return _unavailable("provider_request_failed")


def _normalize_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Keep provider field names/values verbatim; coerce prices to float."""
    def _price(key: str) -> float | None:
        value = record.get(key)
        if value in (None, "", "NA", "0"):
            return None
        try:
            return float(str(value).replace(",", "").strip())
        except ValueError:
            return None

    return {
        "state": record.get("state"),
        "district": record.get("district"),
        "market": record.get("market"),
        "commodity": record.get("commodity"),
        "variety": record.get("variety"),
        "arrival_date": record.get("arrival_date"),
        "min_price": _price(record.get("min_price") if "min_price" in record else record.get("min_price_rs")),
        "max_price": _price(record.get("max_price") if "max_price" in record else record.get("max_price_rs")),
        "modal_price": _price(record.get("modal_price") if "modal_price" in record else record.get("modal_price_rs")),
    }


def _payload_hash(payload: Mapping[str, Any]) -> str:
    import hashlib
    import json

    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["fetch_mandi_prices", "PARAM_LIMIT", "REQUEST_TIMEOUT_SECONDS"]
