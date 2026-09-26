"""Risk-evaluation metric maths (Phase 5 §14–17).

Pure functions over counted outcomes. Every function returns a
``{"value": ..., "status": ...}`` mapping and returns ``value=None`` with
``status="insufficient_data"`` whenever the sample is too small to support the
figure. Nothing here invents a denominator or fills a gap with a plausible
number.

Probabilities produced by the rule engine are **rule scores**, not calibrated
probabilities (§5, §17). The calibration helpers therefore describe the numbers
that actually exist; the label ``not_validated`` is applied by the report layer
and must not be dropped.
"""
from __future__ import annotations

from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence

#: Fixed lead-time buckets (hours) for the distribution report (§16).
LEAD_TIME_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<6h", 0.0, 6.0),
    ("6-12h", 6.0, 12.0),
    ("12-24h", 12.0, 24.0),
    ("24-48h", 24.0, 48.0),
    ("48-72h", 48.0, 72.0),
    (">=72h", 72.0, float("inf")),
)


def _metric(value: float | None, status: str, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"value": value, "status": status}
    result.update(extra)
    return result


def insufficient(reason: str, **extra: Any) -> dict[str, Any]:
    """Explicit ``insufficient_data`` marker carrying the observed counts."""
    return _metric(None, "insufficient_data", reason=reason, **extra)


def precision(warned_with_event: int, warned_without_event: int, *, min_warning_windows: int) -> dict[str, Any]:
    """Precision over falsifiable warning windows: TP / (TP + FP).

    A window is *falsifiable* only once the risk type's false-alert window has
    closed, so open windows are excluded upstream and never counted as correct.
    """
    windows = warned_with_event + warned_without_event
    if windows < min_warning_windows:
        return insufficient(
            f"{windows} falsifiable warning window(s) < {min_warning_windows} required",
            observed=windows,
            required=min_warning_windows,
        )
    return _metric(
        round(warned_with_event / windows, 4), "ok", denominators={"windows": windows}
    )


def recall(events_warned: int, events_missed: int, *, min_events: int) -> dict[str, Any]:
    """Recall over documented events: TP / (TP + FN)."""
    events = events_warned + events_missed
    if events < min_events:
        return insufficient(
            f"{events} reference event(s) < {min_events} required",
            observed=events,
            required=min_events,
        )
    return _metric(round(events_warned / events, 4), "ok", denominators={"events": events})


def f1_score(precision_result: Mapping[str, Any], recall_result: Mapping[str, Any]) -> dict[str, Any]:
    """Harmonic mean; published only when both precision and recall exist."""
    p, r = precision_result.get("value"), recall_result.get("value")
    if p is None or r is None:
        return insufficient(
            "F1 requires both precision and recall to be available",
            precision_status=precision_result.get("status"),
            recall_status=recall_result.get("status"),
        )
    if (p + r) == 0:
        return _metric(0.0, "ok")
    return _metric(round(2 * p * r / (p + r), 4), "ok")


def false_alert_rate(
    warned_with_event: int, warned_without_event: int, *, min_warning_windows: int
) -> dict[str, Any]:
    """FP / (TP + FP) — the share of closed warning windows with no event."""
    windows = warned_with_event + warned_without_event
    if windows < min_warning_windows:
        return insufficient(
            f"{windows} falsifiable warning window(s) < {min_warning_windows} required",
            observed=windows,
            required=min_warning_windows,
        )
    return _metric(round(warned_without_event / windows, 4), "ok", denominators={"windows": windows})


def missed_event_rate(events_warned: int, events_missed: int, *, min_events: int) -> dict[str, Any]:
    """FN / (TP + FN) — the share of documented events that got no warning."""
    events = events_warned + events_missed
    if events < min_events:
        return insufficient(
            f"{events} reference event(s) < {min_events} required",
            observed=events,
            required=min_events,
        )
    return _metric(round(events_missed / events, 4), "ok", denominators={"events": events})


def brier_score(
    pairs: Sequence[tuple[float, bool]], *, min_samples: int
) -> dict[str, Any]:
    """Mean squared error between issued probability and binary outcome.

    ``pairs`` are ``(probability, event_occurred)`` for closed windows only.
    """
    cleaned = [(float(p), bool(o)) for p, o in pairs if p is not None]
    if len(cleaned) < min_samples:
        return insufficient(
            f"{len(cleaned)} paired sample(s) < {min_samples} required",
            observed=len(cleaned),
            required=min_samples,
        )
    score = sum((p - (1.0 if o else 0.0)) ** 2 for p, o in cleaned) / len(cleaned)
    return _metric(round(score, 4), "ok", denominators={"samples": len(cleaned)})


def reliability_curve(
    pairs: Sequence[tuple[float, bool]], *, min_samples: int, bins: int = 5
) -> dict[str, Any]:
    """Observed event frequency vs mean issued probability, per fixed bin."""
    cleaned = [(float(p), bool(o)) for p, o in pairs if p is not None]
    if len(cleaned) < min_samples:
        return insufficient(
            f"{len(cleaned)} paired sample(s) < {min_samples} required",
            observed=len(cleaned),
            required=min_samples,
        )
    total = len(cleaned)
    curve: list[dict[str, Any]] = []
    max_gap = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        bucket = [
            (p, o)
            for p, o in cleaned
            if (low <= p < high) or (index == bins - 1 and p >= high)
        ]
        if not bucket:
            curve.append(
                {
                    "bin_lower": round(low, 2),
                    "bin_upper": round(high, 2),
                    "count": 0,
                    "observed_frequency": None,
                    "mean_probability": None,
                }
            )
            continue
        observed = sum(1 for _, o in bucket if o) / len(bucket)
        mean_probability = sum(p for p, _ in bucket) / len(bucket)
        max_gap = max(max_gap, abs(observed - mean_probability))
        curve.append(
            {
                "bin_lower": round(low, 2),
                "bin_upper": round(high, 2),
                "count": len(bucket),
                "observed_frequency": round(observed, 4),
                "mean_probability": round(mean_probability, 4),
            }
        )
    return _metric(None, "ok", denominators={"samples": total}, curve=curve, max_gap=round(max_gap, 4))


def lead_time_stats(hours: Iterable[float], *, min_samples: int) -> dict[str, Any]:
    """Warning lead time summary + distribution (§16).

    Negative values (a warning issued after the event) are dropped: they are not
    warning lead time. Including them would overstate performance.
    """
    values = sorted(float(h) for h in hours if h is not None and float(h) >= 0)
    if len(values) < min_samples:
        return insufficient(
            f"{len(values)} matched event(s) < {min_samples} required",
            observed=len(values),
            required=min_samples,
        )
    distribution = []
    for label, low, high in LEAD_TIME_BUCKETS:
        count = sum(1 for v in values if low <= v < high)
        distribution.append({"bucket": label, "count": count})
    return _metric(
        round(mean(values), 2),
        "ok",
        denominators={"matched_events": len(values)},
        mean_hours=round(mean(values), 2),
        median_hours=round(median(values), 2),
        min_hours=round(values[0], 2),
        max_hours=round(values[-1], 2),
        distribution=distribution,
    )


def combine_status(metrics: Mapping[str, Mapping[str, Any]]) -> str:
    """Aggregate status: ``ok`` only when at least one metric is available."""
    available = [m.get("status") for m in metrics.values() if isinstance(m, Mapping)]
    if not available:
        return "insufficient_data"
    return "ok" if "ok" in available else "insufficient_data"


__all__ = [
    "LEAD_TIME_BUCKETS",
    "insufficient",
    "precision",
    "recall",
    "f1_score",
    "false_alert_rate",
    "missed_event_rate",
    "brier_score",
    "reliability_curve",
    "lead_time_stats",
    "combine_status",
]
