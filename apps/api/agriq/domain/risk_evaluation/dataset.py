"""Reference-event dataset loading with provenance (Phase 5 §8, §9, §18).

Reference events are **real, documented occurrences** supplied by an operator
from an official source (meteorological department records, agriculture
department reports, official price series). This module loads them, validates
them strictly and carries their provenance into the evaluation report. It never
synthesises, samples, interpolates or imputes an event.

Expected file shape (JSON)::

    {
      "dataset": {
        "name": "…", "provider": "…", "url": "…",
        "collection_period": "…", "geographic_coverage": "…",
        "license": "…", "retrieved_at": "…", "units": "…"
      },
      "events": [
        {
          "risk_type": "heavy_rain_flooding",
          "event_at": "2026-07-14T00:00:00+00:00",
          "district": "Cuttack",
          "crop": "rice",
          "growth_stage": "vegetative",
          "source": "IMD daily district rainfall",
          "source_reference": "…",
          "detail": "…"
        }
      ]
    }

If this file does not exist, evaluation reports ``insufficient_data`` with the
reason ``reference_events_unavailable``. The absence of real data is stated,
never hidden behind a placeholder dataset.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from ..risk_engine.base import RISK_TYPES

#: Operator-supplied path to the real reference-event dataset.
REFERENCE_EVENTS_ENV = "AGRIQ_RISK_REFERENCE_EVENTS"

#: Provenance fields that must be present for a dataset to be usable. Anything
#: missing is reported in the evaluation output (§8 requires recorded provenance).
REQUIRED_PROVENANCE = ("name", "provider", "url", "collection_period", "geographic_coverage")

#: Recommended but not blocking (licences are sometimes genuinely unavailable).
RECOMMENDED_PROVENANCE = ("license", "units", "retrieved_at")


class ReferenceDatasetError(ValueError):
    """Raised when a reference dataset is missing, malformed or unprovenanced."""


@dataclass
class ReferenceEvent:
    """One documented real-world occurrence."""

    risk_type: str
    event_at: datetime
    district: str
    source: str
    crop: str | None = None
    growth_stage: str | None = None
    source_reference: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_type": self.risk_type,
            "event_at": self.event_at.isoformat(),
            "district": self.district,
            "crop": self.crop,
            "growth_stage": self.growth_stage,
            "source": self.source,
            "source_reference": self.source_reference,
            "detail": self.detail,
        }


@dataclass
class ReferenceDataset:
    """Validated reference events plus their recorded provenance."""

    provenance: dict[str, Any]
    events: list[ReferenceEvent] = field(default_factory=list)
    path: str | None = None
    missing_provenance: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """A dataset is usable only when it is properly provanced and non-empty."""
        return bool(self.events) and not self.missing_provenance

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "provenance": dict(self.provenance),
            "missing_provenance": list(self.missing_provenance),
            "usable": self.usable,
            "event_count": len(self.events),
        }


def default_path() -> str | None:
    """The configured reference-event dataset path, if any."""
    value = os.environ.get(REFERENCE_EVENTS_ENV, "").strip()
    return value or None


def _parse_timestamp(value: Any, index: int) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ReferenceDatasetError(f"event[{index}]: 'event_at' must be an ISO-8601 string")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReferenceDatasetError(
            f"event[{index}]: 'event_at' is not a valid ISO-8601 timestamp: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise ReferenceDatasetError(
            f"event[{index}]: 'event_at' must carry a timezone offset (e.g. +00:00) so window "
            "arithmetic is unambiguous"
        )
    return parsed


def _parse_event(raw: Mapping[str, Any], index: int) -> ReferenceEvent:
    if not isinstance(raw, Mapping):
        raise ReferenceDatasetError(f"event[{index}]: expected an object")

    risk_type = str(raw.get("risk_type") or "").strip()
    if risk_type not in RISK_TYPES:
        raise ReferenceDatasetError(
            f"event[{index}]: unknown risk_type {risk_type!r} (expected one of {', '.join(RISK_TYPES)})"
        )
    district = str(raw.get("district") or "").strip()
    if not district:
        raise ReferenceDatasetError(f"event[{index}]: 'district' is required for district-level matching")
    source = str(raw.get("source") or "").strip()
    if not source:
        raise ReferenceDatasetError(
            f"event[{index}]: 'source' is required — an unsourced event cannot be verified"
        )

    def _optional(key: str) -> str | None:
        value = raw.get(key)
        text = str(value).strip() if value is not None else ""
        return text or None

    return ReferenceEvent(
        risk_type=risk_type,
        event_at=_parse_timestamp(raw.get("event_at"), index),
        district=district,
        source=source,
        crop=_optional("crop"),
        growth_stage=_optional("growth_stage"),
        source_reference=_optional("source_reference"),
        detail=_optional("detail"),
    )


def load_reference_events(path: str | Path) -> ReferenceDataset:
    """Load and validate a real reference-event dataset.

    Raises :class:`ReferenceDatasetError` for a missing file, malformed JSON,
    or missing required provenance — a malformed input must fail loudly rather
    than quietly produce a wrong evaluation.
    """
    resolved = Path(path)
    if not resolved.exists() or not resolved.is_file():
        raise ReferenceDatasetError(f"reference-event dataset not found: {resolved}")

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReferenceDatasetError(f"could not read reference-event dataset {resolved}: {exc}") from exc

    if not isinstance(payload, Mapping):
        raise ReferenceDatasetError("dataset file must contain a JSON object")

    provenance_raw = payload.get("dataset")
    if not isinstance(provenance_raw, Mapping):
        raise ReferenceDatasetError("dataset file must contain a 'dataset' provenance object")

    provenance = {str(k): ("" if v is None else str(v)) for k, v in provenance_raw.items()}
    missing = [key for key in REQUIRED_PROVENANCE if not provenance.get(key, "").strip()]
    missing_recommended = [key for key in RECOMMENDED_PROVENANCE if not provenance.get(key, "").strip()]

    events_raw = payload.get("events")
    if not isinstance(events_raw, list):
        raise ReferenceDatasetError("dataset file must contain an 'events' array")
    events = [_parse_event(item, index) for index, item in enumerate(events_raw)]

    provenance["missing_recommended"] = ", ".join(missing_recommended)
    return ReferenceDataset(
        provenance=provenance,
        events=events,
        path=str(resolved),
        missing_provenance=missing,
    )


def unavailable(reason: str) -> ReferenceDataset:
    """Explicit empty dataset for the honest 'no real data yet' state."""
    return ReferenceDataset(provenance={"reason": reason}, events=[], path=None, missing_provenance=[reason])


__all__ = [
    "REFERENCE_EVENTS_ENV",
    "REQUIRED_PROVENANCE",
    "RECOMMENDED_PROVENANCE",
    "ReferenceDatasetError",
    "ReferenceEvent",
    "ReferenceDataset",
    "default_path",
    "load_reference_events",
    "unavailable",
]
