"""Risk-evaluation engine (Phase 5 §13–17).

Joins persisted AGRIQ warnings (every assessment ever issued, superseded rows
included) with real reference events and reports the documented metrics overall
and by crop, growth stage and district.

Design rules that must not be relaxed:

* Nothing is fabricated. Missing inputs produce ``status="insufficient_data"``
  with the observed counts and a reason, never an estimated figure.
* Warnings whose evaluation window has not closed are *pending*: excluded from
  precision and false-alert rates.
* Rule-engine numbers are **rule scores**, not calibrated probabilities. The
  report always states the calibration status it can justify (§5, §17).
* This module is pure: it takes plain dictionaries in and returns a plain
  report. It performs no I/O and touches no database, so it is testable and can
  never be reached from the farmer-facing request path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from ..risk_engine.base import RISK_TYPES
from . import definitions, metrics
from .dataset import ReferenceDataset, ReferenceEvent

#: Bound on the per-event detail rows embedded in a report (no farmer data).
MAX_EVENT_OUTCOMES = 500


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _as_utc(value: Any) -> datetime | None:
    """Parse an ISO timestamp (or datetime) into aware UTC; None when unusable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _norm(value: Any) -> str | None:
    text = str(value).strip().lower() if value is not None else ""
    return text or None


def _crop_agrees(warning_crop: str | None, event_crop: str | None) -> bool:
    """Crop agreement rule: conflicting crops never match; absent crop never blocks."""
    if not warning_crop or not event_crop:
        return True
    return warning_crop == event_crop


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _qualifying(warning: Mapping[str, Any], risk_type: str) -> bool:
    window = definitions.window_for(risk_type)
    if window is None:
        return False
    return str(warning.get("status") or "") in window["warning_statuses"]


def evaluate(
    assessments: Iterable[Mapping[str, Any]],
    dataset: ReferenceDataset,
    *,
    now: datetime | None = None,
    sufficiency: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Evaluate persisted warnings against a real reference-event dataset."""
    minima = dict(definitions.SUFFICIENCY)
    if sufficiency:
        minima.update(sufficiency)
    reference_now = now or datetime.now(timezone.utc)

    warnings = _prepare_warnings(assessments, reference_now)
    events = [event for event in dataset.events if definitions.window_for(event.risk_type)]

    overall = _evaluate_scope(warnings, events, reference_now, minima)
    subgroups = {
        "by_crop": _group(warnings, events, reference_now, minima, warning_key="crop", event_key="crop"),
        "by_stage": _group(
            warnings, events, reference_now, minima, warning_key="growth_stage", event_key="growth_stage"
        ),
        "by_district": _group(
            warnings, events, reference_now, minima, warning_key="district", event_key="district"
        ),
    }

    status = "ok" if overall["status"] == "ok" else "insufficient_data"
    report: dict[str, Any] = {
        "protocol_version": definitions.PROTOCOL_VERSION,
        "status": status,
        "evaluated_at": reference_now.isoformat(),
        "dataset": dataset.to_dict(),
        "calibration_status": _calibration_status(warnings),
        "overall": overall,
        "subgroups": subgroups,
        "definitions": dict(definitions.METRIC_DEFINITIONS),
        "event_windows": {rt: dict(cfg) for rt, cfg in definitions.WINDOWS.items()},
        "event_window_notes": dict(definitions.EVENT_WINDOW_NOTES),
        "limitations": _limitations(dataset, warnings, overall),
    }
    if status != "ok":
        report["reason"] = overall.get("reason", "insufficient_data")
    return report


def _prepare_warnings(
    assessments: Iterable[Mapping[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    """Normalise assessments into evaluable warnings (warming them, never inventing)."""
    prepared: list[dict[str, Any]] = []
    for raw in assessments:
        risk_type = str(raw.get("risk_type") or "")
        window = definitions.window_for(risk_type)
        if window is None:
            continue
        generated_at = _as_utc(raw.get("generated_at"))
        if generated_at is None:
            continue  # an undated assessment cannot be placed in a window
        probability = raw.get("probability")
        try:
            probability = float(probability) if probability is not None else None
        except (TypeError, ValueError):
            probability = None
        prepared.append(
            {
                "risk_type": risk_type,
                "status": str(raw.get("status") or ""),
                "probability": probability,
                "generated_at": generated_at,
                "window_closes_at": generated_at + timedelta(hours=window["false_alert_window_hours"]),
                "lead_window_hours": window["lead_window_hours"],
                "district": _norm(raw.get("district")),
                "crop": _norm(raw.get("crop_name") or raw.get("crop")),
                "growth_stage": _norm(raw.get("growth_stage")),
                "assessment_method": raw.get("assessment_method"),
                "probability_kind": raw.get("probability_kind"),
                "rule_version": raw.get("rule_version"),
            }
        )
    return prepared


def _match_event(warning: Mapping[str, Any], events: Sequence[ReferenceEvent]) -> ReferenceEvent | None:
    """First documented event inside the warning's falsifiability window.

    District must match exactly: matching any district for a warning that has
    none would overstate performance.
    """
    for event in events:
        if event.risk_type != warning["risk_type"]:
            continue
        if _norm(event.district) != warning["district"]:
            continue
        if not _crop_agrees(warning["crop"], _norm(event.crop)):
            continue
        if warning["generated_at"] < event.event_at <= warning["window_closes_at"]:
            return event
    return None


def _warnings_for_event(iterable: Sequence[Mapping[str, Any]], event: ReferenceEvent) -> list[Mapping[str, Any]]:
    """Qualifying warnings issued inside the event's lead window."""
    start = event.event_at - timedelta(hours=definitions.window_for(event.risk_type)["lead_window_hours"])
    matches = []
    for warning in iterable:
        if warning["risk_type"] != event.risk_type:
            continue
        if _norm(event.district) != warning["district"]:
            continue
        if not _crop_agrees(warning["crop"], _norm(event.crop)):
            continue
        if start <= warning["generated_at"] <= event.event_at:
            matches.append(warning)
    return matches


def _evaluate_scope(
    warnings: Sequence[Mapping[str, Any]],
    events: Sequence[ReferenceEvent],
    now: datetime,
    minima: Mapping[str, int],
) -> dict[str, Any]:
    """Full metric set for one population slice (overall or one subgroup).

    Every outcome metric requires the scope to actually contain reference
    events: with no events recorded for a scope we cannot tell "nothing
    happened" from "nothing was recorded", so no outcome figure is published.
    Reporting precision = 0 there would manufacture a failure claim.
    """
    has_events = bool(events)
    qualifying = [w for w in warnings if _qualifying(w, w["risk_type"])]
    # A warning with no district cannot be tied to a district-level reference
    # event either way. Such warnings are excluded from outcome metrics (and
    # counted) rather than credited or blamed on a guess.
    without_district = [w for w in qualifying if not w["district"]]
    verifiable = [w for w in qualifying if w["district"]]
    closed = [w for w in verifiable if w["window_closes_at"] <= now]
    pending_count = len(verifiable) - len(closed)

    warned_with_event = 0
    warned_without_event = 0
    for warning in closed:
        if _match_event(warning, events) is not None:
            warned_with_event += 1
        else:
            warned_without_event += 1

    events_warned = 0
    events_missed = 0
    outcomes: list[dict[str, Any]] = []
    lead_hours: list[float] = []
    for event in events:
        matches = _warnings_for_event(verifiable, event)
        matched = bool(matches)
        first_valid = min((m["generated_at"] for m in matches), default=None)
        lead = round((event.event_at - first_valid).total_seconds() / 3600.0, 2) if first_valid else None
        if matched:
            events_warned += 1
            if lead is not None:
                lead_hours.append(lead)
        else:
            events_missed += 1
        outcomes.append(
            {
                "risk_type": event.risk_type,
                "district": event.district,
                "crop": event.crop,
                "event_time": event.event_at.isoformat(),
                "event_source": event.source,
                "first_valid_warning_time": first_valid.isoformat() if first_valid else None,
                "warning_lead_time_hours": lead,
                "warned": matched,
            }
        )

    no_events_reason = "no_reference_events_in_scope: outcomes are unverifiable, so no " \
        "outcome metric is published for this scope"
    if has_events:
        precision_result = metrics.precision(
            warned_with_event, warned_without_event, min_warning_windows=minima["min_warning_windows"]
        )
        recall_result = metrics.recall(events_warned, events_missed, min_events=minima["min_events"])
        false_alert_result = metrics.false_alert_rate(
            warned_with_event, warned_without_event, min_warning_windows=minima["min_warning_windows"]
        )
        missed_result = metrics.missed_event_rate(
            events_warned, events_missed, min_events=minima["min_events"]
        )
    else:
        precision_result = metrics.insufficient(no_events_reason, observed=len(closed))
        recall_result = metrics.insufficient(no_events_reason, observed=0)
        false_alert_result = metrics.insufficient(no_events_reason, observed=len(closed))
        missed_result = metrics.insufficient(no_events_reason, observed=0)

    metric_set = {
        "precision": precision_result,
        "recall": recall_result,
        "f1": metrics.f1_score(precision_result, recall_result),
        "false_alert_rate": false_alert_result,
        "missed_event_rate": missed_result,
        "warning_lead_time_hours": metrics.lead_time_stats(
            lead_hours, min_samples=minima["min_lead_time_samples"]
        ),
    }

    calibration_pairs = _calibration_pairs(warnings, events, now) if has_events else []
    metric_set["brier_score"] = metrics.brier_score(
        calibration_pairs, min_samples=minima["min_calibration_samples"]
    )
    metric_set["reliability"] = metrics.reliability_curve(
        calibration_pairs, min_samples=minima["min_calibration_samples"]
    )

    status = metrics.combine_status(metric_set)
    result: dict[str, Any] = {
        "status": status,
        "metrics": metric_set,
        "counts": {
            "warnings_issued": len(qualifying),
            "warnings_pending": pending_count,
            "warnings_without_district": len(without_district),
            "warnings_falsifiable": len(closed),
            "warnings_confirmed": warned_with_event,
            "warnings_unconfirmed": warned_without_event,
            "reference_events": len(events),
            "events_warned": events_warned,
            "events_missed": events_missed,
            "calibration_pairs": len(calibration_pairs),
        },
        "event_outcomes": outcomes[:MAX_EVENT_OUTCOMES],
        "event_outcomes_truncated": max(0, len(outcomes) - MAX_EVENT_OUTCOMES),
    }
    if status != "ok":
        result["reason"] = _scope_reason(len(closed), len(events))
    return result


def _calibration_pairs(
    warnings: Sequence[Mapping[str, Any]], events: Sequence[ReferenceEvent], now: datetime
) -> list[tuple[float, bool]]:
    """(probability, outcome) pairs for every dated assessment with a closed window.

    All assessments are used, not only warning-band ones, because a probability
    of 0.15 is just as much a claim about the window as a probability of 0.85.
    """
    pairs: list[tuple[float, bool]] = []
    for warning in warnings:
        if warning["probability"] is None or warning["window_closes_at"] > now:
            continue
        pairs.append((warning["probability"], _match_event(warning, events) is not None))
    return pairs


def _scope_reason(closed_windows: int, events: int) -> str:
    """Why a scope could not produce numbers — one of four honest causes."""
    if not events:
        return "no_reference_events_in_scope"
    if not closed_windows:
        return "no_closed_warning_windows"
    return "below_documented_sample_minimum"


def _group(
    warnings: Sequence[Mapping[str, Any]],
    events: Sequence[ReferenceEvent],
    now: datetime,
    minima: Mapping[str, int],
    *,
    warning_key: str,
    event_key: str,
) -> dict[str, Any]:
    """Per-dimension slices plus explicit unattributed counts (§13)."""
    warning_values = sorted({w[warning_key] for w in warnings if w.get(warning_key)})
    event_values = sorted({_norm(getattr(event, event_key)) for event in events if getattr(event, event_key)})
    groups: dict[str, Any] = {}

    for value in sorted(set(warning_values) | set(event_values)):
        scoped_warnings = [w for w in warnings if w.get(warning_key) == value]
        scoped_events = [e for e in events if _norm(getattr(e, event_key)) == value]
        groups[value] = _evaluate_scope(scoped_warnings, scoped_events, now, minima)

    unattributed_warnings = sum(1 for w in warnings if not w.get(warning_key))
    unattributed_events = sum(1 for e in events if not getattr(e, event_key))
    return {
        "dimension": warning_key,
        "groups": groups,
        "unattributed": {
            "warnings_without_dimension": unattributed_warnings,
            "events_without_dimension": unattributed_events,
            "note": (
                "Records without this dimension cannot be attributed to a subgroup and are "
                "excluded from the per-group figures (they remain in the overall figures)."
            ),
        },
    }


def _calibration_status(warnings: Sequence[Mapping[str, Any]]) -> str:
    """``validated`` is claimed only when the sample really is calibrated output."""
    kinds = {w.get("probability_kind") for w in warnings if w.get("probability") is not None}
    kinds.discard(None)
    if kinds and kinds == {"calibrated_probability"}:
        return "validated"
    return "not_validated"


def _limitations(
    dataset: ReferenceDataset, warnings: Sequence[Mapping[str, Any]], overall: Mapping[str, Any]
) -> list[str]:
    """Honest, non-negotiable caveats shipped with every report."""
    notes = [
        "Probabilities produced by the rule engine are rule scores, not calibrated "
        "probabilities; calibration_status reflects what the sample actually supports.",
        "Matching is performed at (risk_type, district) granularity because "
        "authoritative reference events are district-level while AGRIQ warnings are "
        "field-level. Field-level attribution is not claimed.",
        "Warnings whose evaluation window has not closed are excluded from precision "
        "and false-alert rates and reported as pending.",
        "Only validated reasoning: no metric is published below its documented "
        "minimum sample size; below it the report says insufficient_data.",
    ]
    if not dataset.events:
        notes.append("No reference-event dataset was supplied, so no outcome metric exists yet.")
    if dataset.missing_provenance:
        notes.append(
            "Reference dataset provenance is incomplete (missing: "
            + ", ".join(dataset.missing_provenance)
            + "), so results must not be published until provenance is recorded."
        )
    if overall.get("status") != "ok":
        notes.append("No metric in this report reached its documented sample minimum.")
    return notes


def risk_types_with_events(dataset: ReferenceDataset) -> list[str]:
    """Risk types that actually have reference events (used by reporting/CLI)."""
    present = {event.risk_type for event in dataset.events}
    return [risk_type for risk_type in RISK_TYPES if risk_type in present]


__all__ = ["evaluate", "risk_types_with_events", "MAX_EVENT_OUTCOMES"]
