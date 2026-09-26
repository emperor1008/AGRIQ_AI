"""Market record normalization and data-quality quarantine (Phase 6 §6, §27).

Official AGMARKNET records are the only accepted price inputs. This module puts
them into one comparable shape and *quarantines* anything that cannot be
compared honestly:

* **Unit policy** — AGMARKNET publishes ₹ per quintal. That is the canonical
  unit here and is recorded on every value. No conversion is invented; a
  record whose unit cannot be established is quarantined, not converted.
* **Commodity policy** — a record is only attributed to a catalog crop when the
  provider commodity name actually resolves to it. Unresolvable commodities are
  quarantined rather than mapped by guesswork.
* **Variety policy** — varieties are never mixed in a comparison. Aggregation
  groups by ``(commodity, variety)``.
* **Quality policy** — missing, impossible, out-of-order or future-dated values
  are flagged and excluded from every calculation, and the flags are reported
  to the caller. Suspicious data is never silently "fixed".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from ..catalogs.crops import CROPS, resolve_crop

#: Canonical market price unit. AGMARKNET modal/min/max prices are ₹/quintal.
PRICE_UNIT = "INR_per_quintal"

#: Sanity ceilings used ONLY to flag implausible values for quarantine. Values
#: above these are not clamped or corrected — they are rejected and reported.
MAX_PLAUSIBLE_PRICE = 1_000_000.0   # ₹/quintal
MIN_PLAUSIBLE_PRICE = 1.0           # ₹/quintal

#: Data-quality flags. Each one blocks the record from aggregation.
QUALITY_FLAGS = (
    "missing_modal_price",
    "impossible_price",
    "price_ordering_violation",
    "invalid_arrival_date",
    "future_arrival_date",
    "commodity_not_resolved",
    "duplicate_observation",
)

#: Catalog crop keys, plus their display names, used for commodity resolution.
_CATALOG_KEYS = {key: value for key, value in CROPS.items() if isinstance(value, dict)}
_CATALOG_DISPLAY = {str(profile["name"]).strip().lower(): key for key, profile in _CATALOG_KEYS.items()}


#: Catalog aliases (``"paddy": "rice"``). They are part of the curated catalog, so
#: a provider string that matches an alias resolves to the canonical crop key.
_CATALOG_ALIASES = {
    key: value for key, value in CROPS.items()
    if isinstance(value, str) and value in _CATALOG_KEYS
}

#: Alias spellings providers publish that are not catalog keys themselves.
#: Kept explicit so resolution never has to guess at a provider name.
_PROVIDER_COMMODITY_ALIASES = {
    "paddy": "rice",                    # AGMARKNET: "Paddy(Dhan)(Common)"
    "dhan": "rice",
    "eggplant": "brinjal",
    "ladyfinger": "okra",
    "lady finger": "okra",
    "maize": "maize",
}


#: Every accepted provider spelling → canonical catalog key.
_PROVIDER_TO_KEY = {**_CATALOG_ALIASES, **_PROVIDER_COMMODITY_ALIASES}


def _alnum_tokens(text: str) -> set[str]:
    return {token for token in "".join(ch if ch.isalnum() else " " for ch in text.lower()).split() if token}


def resolve_commodity(provider_commodity: str | None) -> Optional[str]:
    """Resolve a provider commodity string to a catalog crop key.

    Handles the shapes AGMARKNET actually publishes ("Rice", "Paddy(Dhan)(Common)",
    "Tomato", "Onion") by normalising to alphanumeric tokens and matching catalog
    keys and display names. Returns ``None`` when nothing matches — the caller
    quarantines rather than guessing.
    """
    if not provider_commodity:
        return None
    lowered = str(provider_commodity).strip().lower()
    if not lowered:
        return None
    if lowered in _CATALOG_KEYS:
        return lowered
    if lowered in _CATALOG_DISPLAY:
        return _CATALOG_DISPLAY[lowered]

    tokens = _alnum_tokens(provider_commodity)

    # Catalog aliases and documented provider spellings, compared on tokens so
    # "Paddy(Dhan)(Common)" (tokens: paddy, dhan, common) resolves to rice.
    for alias, canonical in _PROVIDER_TO_KEY.items():
        alias_tokens = _alnum_tokens(alias)
        if alias_tokens and alias_tokens <= tokens:
            return canonical

    for key, profile in _CATALOG_KEYS.items():
        if key in tokens or str(profile["name"]).lower() in lowered:
            return key
    # Longest catalog key whose leading letters match a provider token, so
    # truncated provider forms still resolve instead of silently dropping.
    long_tokens = [token for token in tokens if len(token) >= 4]
    for key in sorted(_CATALOG_KEYS, key=len, reverse=True):
        if len(key) >= 4 and any(token.startswith(key[:5]) for token in long_tokens):
            return key
    return None


def provider_commodity_name(crop: str | None) -> str | None:
    """The commodity string to ask the provider for.

    The provider filters on its own commodity names ("Rice", "Tomato"), while
    AGRIQ callers may hold a catalog key ("rice"). Catalog crops are therefore
    requested under their catalog display name; anything that does not resolve to
    a catalog crop is passed through verbatim so a provider-specific name such as
    "Paddy(Dhan)(Common)" is never rewritten into a name the provider may not use.
    """
    if not crop or not str(crop).strip():
        return None
    key = resolve_commodity(crop)
    if key is None:
        return str(crop).strip()
    return crop_display_name(key)


def primary_provider_commodity(
    records: Iterable["NormalizedRecord"],
) -> tuple[Optional[str], list[str]]:
    """Dominant provider commodity in a record set, plus the ones excluded.

    One provider can return several commodity spellings for a single request
    (AGMARKNET publishes both "Rice" and "Paddy(Dhan)(Common)", which are
    different price definitions). Averaging them would fabricate a price, so
    every series/volatility/cross-market calculation is scoped to a single
    provider commodity — the one with the most observations — and the excluded
    spellings are reported instead of being blended in silently.
    """
    counts: dict[str, int] = {}
    for record in records:
        label = (record.commodity or "").strip()
        if label:
            counts[label] = counts.get(label, 0) + 1
    if not counts:
        return None, []
    dominant = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    excluded = sorted(label for label in counts if label != dominant)
    return dominant, excluded


def scope_to_primary_commodity(
    records: Sequence["NormalizedRecord"],
) -> tuple[list["NormalizedRecord"], Optional[str], list[str]]:
    """Restrict records to the dominant provider commodity for comparability."""
    dominant, excluded = primary_provider_commodity(records)
    if dominant is None:
        return list(records), None, []
    scoped = [record for record in records if (record.commodity or "").strip() == dominant]
    return scoped, dominant, excluded


def _price(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    if text in ("", "NA", "N/A", "-", "null", "None"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _arrival_date(value: Any) -> tuple[Optional[date], str | None]:
    """Parse an arrival date; returns (date, flag) where flag marks a problem."""
    if value in (None, ""):
        return None, "invalid_arrival_date"
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        text = str(value).strip().split(" ")[0]
        parsed = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                parsed = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            return None, "invalid_arrival_date"
    # A future arrival date is a provider/data error, not a forecast.
    if parsed > datetime.now(timezone.utc).date():
        return parsed, "future_arrival_date"
    return parsed, None


@dataclass
class NormalizedRecord:
    """One official market observation in canonical form."""

    commodity_key: str
    commodity: str
    market: str
    district: Optional[str]
    state: Optional[str]
    variety: Optional[str]
    arrival_date: Optional[date]
    modal_price: Optional[float]
    min_price: Optional[float]
    max_price: Optional[float]
    price_unit: str = PRICE_UNIT
    source: str = "AGMARKNET via data.gov.in"
    retrieved_at: Optional[str] = None
    record_id: Optional[int] = None

    @property
    def group_key(self) -> tuple[str, str]:
        """Comparison group: commodity + variety (never mixed)."""
        return self.commodity_key, (self.variety or "").strip().lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "commodity": self.commodity,
            "commodity_key": self.commodity_key,
            "market": self.market,
            "district": self.district,
            "state": self.state,
            "variety": self.variety,
            "arrival_date": self.arrival_date.isoformat() if self.arrival_date else None,
            "modal_price": self.modal_price,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "price_unit": self.price_unit,
            "source": self.source,
            "retrieved_at": self.retrieved_at,
            "record_id": self.record_id,
        }


@dataclass
class QuarantinedRecord:
    """A provider record excluded from aggregation, with its reason."""

    raw: Mapping[str, Any]
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "flags": list(self.flags),
            "market": self.raw.get("market"),
            "commodity": self.raw.get("commodity"),
            "variety": self.raw.get("variety"),
            "arrival_date": str(self.raw.get("arrival_date")) if self.raw.get("arrival_date") else None,
            "modal_price": self.raw.get("modal_price", self.raw.get("max_price")),
        }


@dataclass
class NormalizationResult:
    """Accepted records plus everything that was quarantined and why."""

    accepted: list[NormalizedRecord] = field(default_factory=list)
    quarantined: list[QuarantinedRecord] = field(default_factory=list)

    @property
    def quality_summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.quarantined:
            for flag in item.flags:
                counts[flag] = counts.get(flag, 0) + 1
        return {
            "accepted": len(self.accepted),
            "quarantined": len(self.quarantined),
            "flags": counts,
            "policy": (
                "Suspicious provider values are flagged and excluded from every "
                "calculation; they are never silently corrected or imputed."
            ),
        }


def _record_field(record: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in record and record[name] is not None:
            return record[name]
    return None


def normalize_records(
    records: Iterable[Mapping[str, Any]],
    *,
    expected_commodity: str | None = None,
    today: date | None = None,
) -> NormalizationResult:
    """Normalize provider records and quarantine anything not comparable.

    ``expected_commodity`` (a catalog key or provider name) filters out records
    that belong to a different commodity — a provider occasionally returns
    neighbouring commodities for a filter, and mixing them would corrupt every
    downstream average.
    """
    reference_day = today or datetime.now(timezone.utc).date()
    expected_key = resolve_commodity(expected_commodity) if expected_commodity else None

    result = NormalizationResult()
    seen: set[tuple[Any, ...]] = set()

    for record in records:
        if not isinstance(record, Mapping):
            continue
        flags: list[str] = []

        commodity_raw = _record_field(record, "commodity", "commodity_name")
        commodity_key = resolve_commodity(commodity_raw)
        if commodity_key is None:
            flags.append("commodity_not_resolved")
        elif expected_key is not None and commodity_key != expected_key:
            # Different commodity than requested: out of scope, not malformed.
            continue

        modal = _price(_record_field(record, "modal_price"))
        minimum = _price(_record_field(record, "min_price", "minimum_price"))
        maximum = _price(_record_field(record, "max_price", "maximum_price"))

        if modal is None:
            flags.append("missing_modal_price")
        else:
            if modal < MIN_PLAUSIBLE_PRICE or modal > MAX_PLAUSIBLE_PRICE:
                flags.append("impossible_price")
            if minimum is not None and maximum is not None:
                # Ordering is a hard integrity rule for official records.
                if minimum > maximum or modal < minimum or modal > maximum:
                    flags.append("price_ordering_violation")
            if minimum is not None and minimum > MAX_PLAUSIBLE_PRICE:
                flags.append("impossible_price")
            if maximum is not None and maximum > MAX_PLAUSIBLE_PRICE:
                flags.append("impossible_price")

        arrival, date_flag = _arrival_date(_record_field(record, "arrival_date"))
        if arrival is not None and arrival > reference_day:
            date_flag = "future_arrival_date"
        if date_flag:
            flags.append(date_flag)

        market = str(_record_field(record, "market") or "").strip()
        variety = _record_field(record, "variety")
        variety_text = str(variety).strip() if variety not in (None, "") else None

        dedupe_key = (
            commodity_key,
            market.lower(),
            (str(_record_field(record, "district") or "").strip().lower()),
            (variety_text or "").lower(),
            arrival.isoformat() if arrival else None,
            modal,
        )
        if dedupe_key in seen:
            flags.append("duplicate_observation")
        else:
            seen.add(dedupe_key)

        if flags:
            # One flag per distinct reason: the quality summary counts *records*
            # per reason, so a record with three above-ceiling prices is one
            # "impossible_price" quarantine, not three.
            result.quarantined.append(
                QuarantinedRecord(raw=dict(record), flags=list(dict.fromkeys(flags)))
            )
            continue

        result.accepted.append(
            NormalizedRecord(
                commodity_key=commodity_key or "",
                commodity=str(commodity_raw or ""),
                market=market or "Unnamed market",
                district=(str(_record_field(record, "district")).strip()
                          if _record_field(record, "district") else None),
                state=(str(_record_field(record, "state")).strip()
                       if _record_field(record, "state") else None),
                variety=variety_text,
                arrival_date=arrival,
                modal_price=modal,
                min_price=minimum,
                max_price=maximum,
                source=str(_record_field(record, "source") or "AGMARKNET via data.gov.in"),
                retrieved_at=(
                    str(_record_field(record, "retrieved_at"))
                    if _record_field(record, "retrieved_at") else None
                ),
                record_id=_record_field(record, "id"),
            )
        )
    return result


def group_by_variety(
    records: Sequence[NormalizedRecord],
) -> dict[tuple[str, str], list[NormalizedRecord]]:
    """Group records by (commodity, variety) so comparisons never mix them."""
    grouped: dict[tuple[str, str], list[NormalizedRecord]] = {}
    for record in records:
        grouped.setdefault(record.group_key, []).append(record)
    return grouped


def crop_display_name(commodity_key: str | None) -> str:
    """Display name for a catalog crop key (falls back to a title-cased key)."""
    profile, _ = resolve_crop(commodity_key)
    return str(profile["name"])


__all__ = [
    "PRICE_UNIT",
    "QUALITY_FLAGS",
    "MAX_PLAUSIBLE_PRICE",
    "MIN_PLAUSIBLE_PRICE",
    "NormalizedRecord",
    "QuarantinedRecord",
    "NormalizationResult",
    "normalize_records",
    "resolve_commodity",
    "provider_commodity_name",
    "primary_provider_commodity",
    "scope_to_primary_commodity",
    "group_by_variety",
    "crop_display_name",
]
