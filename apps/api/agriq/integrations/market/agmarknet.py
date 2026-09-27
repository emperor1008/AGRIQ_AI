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

from ...core.constants import (
    DATA_GOV_IN_API_URL,
    MANDI_CREDENTIAL_MESSAGE,
    MANDI_NO_RECORD_MESSAGE,
    MANDI_SOURCE_ERROR_MESSAGE,
    PROVIDER_AGMARKNET,
    REASON_API_KEY_NOT_CONFIGURED,
    REASON_PROVIDER_HTTP_ERROR,
    REASON_PROVIDER_MALFORMED_RESPONSE,
    REASON_PROVIDER_REQUEST_FAILED,
    REASON_PROVIDER_TIMEOUT,
    STATE_CONFIGURATION_ERROR,
    STATE_DATA_SOURCE_ERROR,
    STATE_DATA_UNAVAILABLE,
    STATE_NO_OFFICIAL_RECORD,
    UNAVAILABLE_MESSAGE,
)
from ...core.logging import get_logger
from ...core.time import iso_utc

logger = get_logger("integrations.agmarknet")

API_URL = DATA_GOV_IN_API_URL
PARAM_LIMIT = 10
#: Bounded pagination: at most this many provider pages per call, so a crafted
#: or misconfigured query can never turn into an unbounded fetch loop.
MAX_PAGES = 3
REQUEST_TIMEOUT_SECONDS = 10
MAX_RETRIES = 1

_MESSAGE_FOR_STATE = {
    STATE_CONFIGURATION_ERROR: MANDI_CREDENTIAL_MESSAGE,
    STATE_DATA_SOURCE_ERROR: MANDI_SOURCE_ERROR_MESSAGE,
    STATE_NO_OFFICIAL_RECORD: MANDI_NO_RECORD_MESSAGE,
    STATE_DATA_UNAVAILABLE: UNAVAILABLE_MESSAGE,
}

#: Failure reason → machine-readable state (single mapping for the provider).
_STATE_FOR_REASON = {
    REASON_API_KEY_NOT_CONFIGURED: STATE_CONFIGURATION_ERROR,
    REASON_PROVIDER_REQUEST_FAILED: STATE_DATA_SOURCE_ERROR,
    REASON_PROVIDER_TIMEOUT: STATE_DATA_SOURCE_ERROR,
    REASON_PROVIDER_HTTP_ERROR: STATE_DATA_SOURCE_ERROR,
    REASON_PROVIDER_MALFORMED_RESPONSE: STATE_DATA_SOURCE_ERROR,
}


def _unavailable(reason: str) -> dict[str, Any]:
    """Explicit unavailable payload: a state, a cause, and never a price."""
    state = _STATE_FOR_REASON.get(reason, STATE_DATA_UNAVAILABLE)
    return {
        "available": False,
        "provider": PROVIDER_AGMARKNET,
        "reason": reason,
        "state": state,
        "state_message": _MESSAGE_FOR_STATE.get(state, UNAVAILABLE_MESSAGE),
        "message": "Verified data is currently unavailable.",
        "records": [],
        "retrieved_at": None,
        "fetched_at": None,
        "provider_updated_at": None,
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
    base_params: dict[str, Any] = {
        "api-key": key,
        "format": "json",
        "limit": PARAM_LIMIT,
        "filters[commodity]": commodity.strip(),
    }
    if state:
        base_params["filters[state]"] = state
    if district:
        base_params["filters[district]"] = district.strip()

    started = time.perf_counter()
    collected: list[dict[str, Any]] = []
    offset = 0
    provider_updated_at: Any = None
    total_available: int | None = None
    for _page in range(MAX_PAGES):
        params = dict(base_params)
        params["offset"] = offset
        payload, reason = _request_page(url, params)
        if payload is None:
            if not collected:
                logger.warning(
                    "mandi_request_failed source=%s reason=%s latency_ms=%d",
                    PROVIDER_AGMARKNET, reason, int((time.perf_counter() - started) * 1000),
                )
                return _unavailable(reason)
            # A later page failed: keep the real records already retrieved.
            logger.warning(
                "mandi_page_incomplete source=%s reason=%s records=%d",
                PROVIDER_AGMARKNET, reason, len(collected),
            )
            break

        records = payload.get("records")
        if not isinstance(records, list):
            logger.warning("mandi_malformed_records source=%s", PROVIDER_AGMARKNET)
            if not collected:
                return _unavailable(REASON_PROVIDER_MALFORMED_RESPONSE)
            break

        provider_updated_at = payload.get("updated_date", provider_updated_at)
        if payload.get("total") is not None:
            try:
                total_available = int(payload["total"])
            except (TypeError, ValueError):
                pass

        page_rows = [_normalize_record(r) for r in records if isinstance(r, Mapping)]
        collected.extend(page_rows)
        if len(records) < PARAM_LIMIT or not records:
            break
        offset += PARAM_LIMIT

    fetched_at = iso_utc()
    logger.info(
        "mandi_retrieved source=%s records=%d latency_ms=%d state=%s",
        PROVIDER_AGMARKNET, len(collected), int((time.perf_counter() - started) * 1000),
        "OK" if collected else STATE_NO_OFFICIAL_RECORD,
    )
    return {
        "available": True,
        "provider": PROVIDER_AGMARKNET,
        "reason": None if collected else "no_official_record",
        # The provider answered; an empty result is a real, distinct state and is
        # never rendered as "no data source".
        "state": "OK" if collected else STATE_NO_OFFICIAL_RECORD,
        "state_message": None if collected else MANDI_NO_RECORD_MESSAGE,
        "records": collected,
        "retrieved_at": fetched_at,
        "fetched_at": fetched_at,
        "provider_updated_at": str(provider_updated_at) if provider_updated_at else None,
        "reported_total": total_available,
        "raw_payload_hash": _payload_hash(collected),
    }


def _request_page(url: str, params: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """One provider page with the safe retry policy; returns (payload, reason)."""
    reason = REASON_PROVIDER_REQUEST_FAILED
    attempts = max(0, MAX_RETRIES) + 1
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                reason = REASON_PROVIDER_MALFORMED_RESPONSE
                logger.warning("agmarknet_malformed_json attempt=%s", attempt + 1)
                payload = None
            if isinstance(payload, Mapping):
                return dict(payload), reason
            reason = REASON_PROVIDER_MALFORMED_RESPONSE
        except requests.Timeout:
            reason = REASON_PROVIDER_TIMEOUT
            logger.warning("agmarknet_timeout attempt=%s", attempt + 1)
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            reason = REASON_PROVIDER_HTTP_ERROR
            logger.warning("agmarknet_http_error status=%s attempt=%s", status, attempt + 1)
            if status is not None and 400 <= status < 500:
                # The OGD platform refuses a missing or invalid key with a 4xx.
                # That is a configuration problem, not a transient outage, so it
                # is classified as one instead of being retried.
                if status in (401, 403) or _is_credential_error(exc):
                    reason = REASON_API_KEY_NOT_CONFIGURED
                break
        except Exception as exc:
            logger.warning("agmarknet_failed error=%s attempt=%s", type(exc).__name__, attempt + 1)
        if attempt < attempts - 1:
            time.sleep(0.5)
    return None, reason


def _is_credential_error(exc: requests.HTTPError) -> bool:
    """True when a 4xx body names an authorisation/api-key problem.

    data.gov.in answers a keyless request with ``400 {"error":
    "Authorization field missing"}``, so the status code alone is not enough to
    tell a credential problem from a bad query.
    """
    body = ""
    try:
        body = str(getattr(exc.response, "text", "") or "")[:400].lower()
    except Exception:  # response without readable text
        return False
    return "authorization" in body or "api key" in body or "api-key" in body


#: Provider spellings for "this price was not reported". A zero price is NOT a
#: price, so those fields stay ``None`` instead of becoming ``0``.
_ABSENT_PRICE = {None, "", "NA", "N/A", "na", "-0", "-", "0", "0.0", "0.00"}


def _first(record: Mapping[str, Any], *names: str) -> Any:
    """First non-empty value among the provider's alternative field names."""
    for name in names:
        value = record.get(name)
        if value not in (None, ""):
            return value
    return None


def _price(value: Any) -> float | None:
    """Provider price text → float.

    NOTE (Phase 7.3): the previous implementation looked the *value* up as a key
    (``record.get(record.get('modal_price'))``), so every price silently became
    ``None`` even when the provider returned a real one. Prices are converted
    from the value itself now, and an absent price stays ``None``.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value else None
    if value in _ABSENT_PRICE:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _normalize_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Keep provider field names/values verbatim; coerce prices to float."""
    return {
        "state": record.get("state"),
        "district": record.get("district"),
        "market": record.get("market"),
        "commodity": record.get("commodity"),
        "variety": record.get("variety"),
        "grade": _first(record, "grade"),
        "arrival_date": _first(record, "arrival_date", "arrival_Date"),
        "min_price": _price(_first(record, "min_price", "min_price_rs", "minimum_price")),
        "max_price": _price(_first(record, "max_price", "max_price_rs", "maximum_price")),
        "modal_price": _price(_first(record, "modal_price", "modal_price_rs")),
    }


def _payload_hash(payload: Any) -> str:
    import hashlib
    import json

    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "fetch_mandi_prices",
    "PARAM_LIMIT",
    "MAX_PAGES",
    "REQUEST_TIMEOUT_SECONDS",
    "MAX_RETRIES",
]
