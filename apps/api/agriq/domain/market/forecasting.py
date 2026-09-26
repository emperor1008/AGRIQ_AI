"""Price forecasting with chronological evaluation (Phase 6 §7, §8, §21).

Methodology, stated plainly because it bounds every claim the product can make:

1. The series is a sequence of **real dated observations** (median modal price
   per observation date from official records). Nothing is interpolated: gaps in
   the calendar are gaps in the series, and models index on the observation
   sequence, which ``trend.series_points`` reports alongside the dates.
2. Evaluation is **chronological**: the oldest observations train, the next block
   validates (model *selection*), the newest block tests (reported metrics).
   Nothing from the future ever feeds a feature or a selection decision.
3. Candidates are simple and defensible: naive (last value), seasonal naive
   (lag 7), moving average (7) and a fitted linear-trend + weekday-seasonal model
   implemented in pure Python (no new dependency, fully explainable).
4. A forecast is published only when enough real history exists. Otherwise the
   result is ``insufficient_data`` with the counts required — never a number.

The prediction interval is a documented normal-approximation from residual
dispersion, grown with the square root of the horizon. It is **not** a
statistically calibrated interval, and ``interval_method`` says so.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean
from typing import Any, Optional, Sequence

#: Minimum real observations before any forecast is published.
MIN_OBSERVATIONS = 21
#: Minimum observations required for the training block specifically.
MIN_TRAIN_OBSERVATIONS = 10
#: Supported horizons (days).
SUPPORTED_HORIZONS = (7, 14)
#: Rolling window for the moving-average candidate.
MOVING_AVERAGE_WINDOW = 7
#: Weekly seasonality period (AGMARKNET observations are daily).
SEASONAL_PERIOD = 7

MODEL_VERSION = "agriq-price-forecast-v1"


def _sorted_points(series: Sequence[dict[str, Any]]) -> list[tuple[date, float]]:
    points: list[tuple[date, float]] = []
    for entry in series:
        try:
            day = date.fromisoformat(str(entry["date"]))
            value = float(entry["modal_price"])
        except (KeyError, TypeError, ValueError):
            continue
        points.append((day, value))
    points.sort(key=lambda item: item[0])
    return points


# ---------------------------------------------------------------------------
# Metric maths (only published when actually computed)
# ---------------------------------------------------------------------------

def mae(actual: Sequence[float], predicted: Sequence[float]) -> Optional[float]:
    if not actual or len(actual) != len(predicted):
        return None
    return round(sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual), 2)


def rmse(actual: Sequence[float], predicted: Sequence[float]) -> Optional[float]:
    if not actual or len(actual) != len(predicted):
        return None
    return round(math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual)), 2)


def smape(actual: Sequence[float], predicted: Sequence[float]) -> Optional[float]:
    """Symmetric MAPE (%). Safe when either value is zero (unlike MAPE)."""
    if not actual or len(actual) != len(predicted):
        return None
    terms = []
    for a, p in zip(actual, predicted):
        denominator = (abs(a) + abs(p)) / 2
        if denominator == 0:
            continue
        terms.append(abs(a - p) / denominator)
    if not terms:
        return None
    return round(sum(terms) / len(terms) * 100.0, 2)


def mape(actual: Sequence[float], predicted: Sequence[float]) -> Optional[float]:
    """MAPE (%), returned as None when any actual is zero (mathematically unsafe)."""
    if not actual or len(actual) != len(predicted):
        return None
    if any(a == 0 for a in actual):
        return None
    return round(sum(abs((a - p) / a) for a, p in zip(actual, predicted)) / len(actual) * 100.0, 2)


def _out_of_sample_dispersion(
    points: Sequence[tuple[date, float]], start: int, end: int, predictions: Sequence[float]
) -> Optional[float]:
    """Std-dev of one-step prediction errors on a block the model had not seen.

    Used for every interval width. In-sample residuals understate how wrong a
    forecast can be, and taking them from a model fitted on all data would leak the
    evaluated block into the interval that is supposed to measure it.
    """
    residuals = [
        value - predicted for (_, value), predicted in zip(points[start:end], predictions)
    ]
    if len(residuals) < 2:
        return None
    centre = mean(residuals)
    variance = sum((residual - centre) ** 2 for residual in residuals) / (len(residuals) - 1)
    return math.sqrt(max(variance, 0.0))


def interval_coverage(
    actual: Sequence[float], lower: Sequence[float], upper: Sequence[float]
) -> Optional[float]:
    if not actual or len(actual) != len(lower) or len(actual) != len(upper):
        return None
    inside = sum(1 for a, lo, hi in zip(actual, lower, upper) if lo <= a <= hi)
    return round(inside / len(actual), 4)


def error_report(actual: Sequence[float], predicted: Sequence[float]) -> dict[str, Any]:
    """Full metric block; unavailable metrics carry an explicit reason."""
    report: dict[str, Any] = {
        "n": len(actual),
        "mae": mae(actual, predicted),
        "rmse": rmse(actual, predicted),
        "smape_percent": smape(actual, predicted),
    }
    mape_value = mape(actual, predicted)
    report["mape_percent"] = mape_value
    if mape_value is None:
        report["mape_unavailable_reason"] = "undefined when an observed price is zero"
    return report


# ---------------------------------------------------------------------------
# Candidates: each is y_hat(index, history) -> float
# ---------------------------------------------------------------------------

def _naive(history: Sequence[float], index: int) -> float:
    return history[index - 1]


def _seasonal_naive(history: Sequence[float], index: int) -> float:
    lag = index - SEASONAL_PERIOD
    return history[lag] if lag >= 0 else history[index - 1]


def _moving_average(history: Sequence[float], index: int) -> float:
    window = history[max(0, index - MOVING_AVERAGE_WINDOW):index]
    return mean(window) if window else history[index - 1]


@dataclass
class TrendSeasonalModel:
    """Linear trend + weekday seasonal index, fitted by least squares.

    Explainable by construction: ``level``, ``slope_per_observation`` and a
    ``weekly_index`` map are all reported with the forecast, so a farmer-facing
    explanation can state exactly why the number moved.
    """

    level: float
    slope: float
    weekly_index: dict[int, float] = field(default_factory=dict)
    residual_std: float = 0.0
    fitted_points: int = 0

    def predict(self, index: int, weekday: int) -> float:
        return self.level + self.slope * index + self.weekly_index.get(weekday, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": round(self.level, 2),
            "slope_per_observation": round(self.slope, 4),
            "weekly_index": {str(k): round(v, 2) for k, v in sorted(self.weekly_index.items())},
            "residual_std": round(self.residual_std, 2),
            "fitted_points": self.fitted_points,
        }


def _weekday_index(day: date) -> int:
    return day.weekday()


def fit_trend_seasonal(points: Sequence[tuple[date, float]]) -> TrendSeasonalModel:
    """Fit trend + weekly seasonal index on a chronological training block."""
    n = len(points)
    if n == 0:
        return TrendSeasonalModel(level=0.0, slope=0.0)
    if n == 1:
        return TrendSeasonalModel(level=points[0][1], slope=0.0, fitted_points=1)

    mean_index = (n - 1) / 2
    mean_value = mean(value for _, value in points)
    denominator = sum((i - mean_index) ** 2 for i in range(n))
    slope = 0.0
    if denominator > 0:
        slope = sum((i - mean_index) * (value - mean_value) for i, (_, value) in enumerate(points)) / denominator
    level = mean_value - slope * mean_index

    residuals = [
        value - (level + slope * i)
        for i, (_, value) in enumerate(points)
    ]
    buckets: dict[int, list[float]] = {}
    for (day, _), residual in zip(points, residuals):
        buckets.setdefault(_weekday_index(day), []).append(residual)
    weekly_index = {key: mean(values) for key, values in buckets.items()}
    # Centre the weekly index so the level stays interpretable.
    if weekly_index:
        offset = mean(weekly_index.values())
        weekly_index = {key: value - offset for key, value in weekly_index.items()}

    final_residuals = [
        value - (level + slope * i + weekly_index.get(_weekday_index(day), 0.0))
        for i, (day, value) in enumerate(points)
    ]
    variance = sum(r * r for r in final_residuals) / max(1, len(final_residuals) - 1)
    return TrendSeasonalModel(
        level=level,
        slope=slope,
        weekly_index=weekly_index,
        residual_std=math.sqrt(max(variance, 0.0)),
        fitted_points=n,
    )


def _candidate_predictions(
    points: Sequence[tuple[date, float]], start: int, end: int
) -> dict[str, list[float]]:
    """One-step-ahead predictions for indices ``[start, end)`` from real history."""
    history = [value for _, value in points]
    indices = list(range(start, end))
    predictions: dict[str, list[float]] = {
        "naive_last_value": [],
        "seasonal_naive_7": [],
        "moving_average_7": [],
        "trend_weekly_seasonal": [],
    }

    # The fitted model is trained strictly on data BEFORE the evaluated block.
    model = fit_trend_seasonal(points[:start])
    for index in indices:
        predictions["naive_last_value"].append(_naive(history, index))
        predictions["seasonal_naive_7"].append(_seasonal_naive(history, index))
        predictions["moving_average_7"].append(_moving_average(history, index))
        day = points[index][0]
        predictions["trend_weekly_seasonal"].append(model.predict(index, _weekday_index(day)))
    return predictions


@dataclass
class ForecastOutcome:
    """Result of a forecast attempt: either a published forecast or a refusal."""

    status: str
    reason: Optional[str] = None
    horizon_days: int = 0
    observations: int = 0
    required_observations: int = MIN_OBSERVATIONS
    selected_model: Optional[str] = None
    model_parameters: dict[str, Any] = field(default_factory=dict)
    forecast: list[dict[str, Any]] = field(default_factory=list)
    prediction_interval: Optional[dict[str, Any]] = None
    metrics: dict[str, Any] = field(default_factory=dict)
    training_period: Optional[dict[str, str]] = None
    evaluation_period: Optional[dict[str, str]] = None
    model_version: str = MODEL_VERSION
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "model_version": self.model_version,
            "horizon_days": self.horizon_days,
            "observations": self.observations,
            "required_observations": self.required_observations,
            "selected_model": self.selected_model,
            "model_parameters": dict(self.model_parameters),
            "forecast": list(self.forecast),
            "prediction_interval": self.prediction_interval,
            "metrics": dict(self.metrics),
            "training_period": self.training_period,
            "evaluation_period": self.evaluation_period,
            "assumptions": list(self.assumptions),
        }


def _insufficient(series_len: int, horizon: int, reason: str) -> ForecastOutcome:
    return ForecastOutcome(
        status="insufficient_data",
        reason=reason,
        horizon_days=horizon,
        observations=series_len,
        required_observations=MIN_OBSERVATIONS,
    )


def forecast(
    series: Sequence[dict[str, Any]],
    *,
    horizon_days: int = 7,
) -> ForecastOutcome:
    """Forecast ``horizon_days`` ahead, or refuse with a documented reason."""
    if horizon_days not in SUPPORTED_HORIZONS:
        return _insufficient(len(series), horizon_days,
                             f"horizon must be one of {SUPPORTED_HORIZONS} days")

    points = _sorted_points(series)
    n = len(points)
    if n < MIN_OBSERVATIONS:
        return _insufficient(
            n,
            horizon_days,
            (
                f"{n} distinct official observation date(s) available; "
                f"at least {MIN_OBSERVATIONS} are required before a forecast is published"
            ),
        )

    test_start = n - horizon_days
    validation_start = test_start - horizon_days
    if validation_start < MIN_TRAIN_OBSERVATIONS:
        return _insufficient(
            n,
            horizon_days,
            (
                f"{n} observation(s) leave fewer than {MIN_TRAIN_OBSERVATIONS} for training "
                f"after reserving {horizon_days} validation and {horizon_days} test observations"
            ),
        )

    actual_test = [value for _, value in points[test_start:]]
    actual_validation = [value for _, value in points[validation_start:test_start]]

    validation_predictions = _candidate_predictions(points, validation_start, test_start)
    test_predictions = _candidate_predictions(points, test_start, n)

    validation_report = {
        name: error_report(actual_validation, values)
        for name, values in validation_predictions.items()
    }
    # Model selection happens on the VALIDATION block only, never the test block.
    selection_key = lambda report: (report["rmse"] if report["rmse"] is not None else math.inf)  # noqa: E731
    selected = min(validation_report, key=lambda name: selection_key(validation_report[name]))

    test_report = {
        name: error_report(actual_test, values) for name, values in test_predictions.items()
    }
    selected_test = test_report[selected]

    # Interval width comes from the selected model's error on the validation block
    # — data strictly before the test block and outside its training window.
    interval_dispersion = _out_of_sample_dispersion(
        points, validation_start, test_start, validation_predictions[selected]
    )
    if interval_dispersion is None:
        interval_dispersion = fit_trend_seasonal(points[:test_start]).residual_std

    # Final fit on every real observation, forecast forward with real dates.
    final_model = fit_trend_seasonal(points)
    last_day, last_value = points[-1]
    forward: list[dict[str, Any]] = []
    lower: list[float] = []
    upper: list[float] = []
    for step in range(1, horizon_days + 1):
        target = last_day + timedelta(days=step)
        target_index = n - 1 + step
        if selected == "naive_last_value":
            value = last_value
        elif selected == "seasonal_naive_7":
            lag = target_index - SEASONAL_PERIOD
            value = points[lag][1] if 0 <= lag < n else last_value
        elif selected == "moving_average_7":
            value = mean([v for _, v in points[-MOVING_AVERAGE_WINDOW:]])
        else:
            value = final_model.predict(target_index, _weekday_index(target))
        spread = interval_dispersion * math.sqrt(step) * 1.28  # ~80 % normal band
        forward.append({"date": target.isoformat(), "modal_price": round(value, 2)})
        lower.append(round(value - spread, 2))
        upper.append(round(value + spread, 2))

    coverage = interval_coverage(
        actual_test,
        [value - interval_dispersion * 1.28 for value in test_predictions[selected]],
        [value + interval_dispersion * 1.28 for value in test_predictions[selected]],
    )

    return ForecastOutcome(
        status="ok",
        horizon_days=horizon_days,
        observations=n,
        required_observations=MIN_OBSERVATIONS,
        selected_model=selected,
        model_parameters=final_model.to_dict(),
        forecast=forward,
        prediction_interval={
            "lower": lower,
            "upper": upper,
            "nominal_coverage": 0.8,
            "dispersion": round(interval_dispersion, 2),
            "dispersion_source": (
                "standard deviation of the selected model's one-step errors on the validation "
                "block (out-of-sample; the test block never contributes to the interval)"
            ),
            "method": (
                "normal approximation from out-of-sample validation dispersion, grown with "
                "sqrt(horizon); not a calibrated prediction interval"
            ),
            "test_coverage": coverage,
            "test_coverage_basis": (
                "share of test-block observations inside a ±1.28·dispersion one-step band; "
                "a nominal 80 % band that covers much less reports that it does"
            ),
        },
        metrics={
            "selection_block": {"kind": "validation", "n": len(actual_validation),
                                "period": _period(points, validation_start, test_start),
                                "candidates": validation_report},
            "reported_block": {"kind": "test", "n": len(actual_test),
                               "period": _period(points, test_start, n),
                               "candidates": test_report},
            "selected_model": selected,
            "beats_naive_baseline": _beats_naive(selected_test, test_report["naive_last_value"]),
        },
        training_period=_period(points, 0, test_start),
        evaluation_period=_period(points, test_start, n),
        assumptions=[
            "Evaluation is chronological: training data always precedes validation, which precedes test.",
            "Model selection uses the validation block only; test metrics are reported as computed.",
            "Prediction-interval width comes from out-of-sample validation error, never from the "
            "evaluated block.",
            "Observations are median modal prices per observation date, not a single market's quote.",
            "Gaps in the calendar remain gaps; the model indexes the observation sequence.",
            f"Selected model '{selected}' was chosen by lowest validation RMSE.",
        ],
    )


def _period(points: Sequence[tuple[date, float]], start: int, end: int) -> Optional[dict[str, str]]:
    if start >= end or not points:
        return None
    block = points[max(0, start):min(end, len(points))]
    if not block:
        return None
    return {"from": block[0][0].isoformat(), "to": block[-1][0].isoformat(), "observations": str(len(block))}


def _beats_naive(selected: dict[str, Any], naive: dict[str, Any]) -> Optional[bool]:
    """Whether the selected model's test RMSE is at least as good as naive."""
    if selected.get("rmse") is None or naive.get("rmse") is None:
        return None
    return bool(selected["rmse"] <= naive["rmse"])


def baseline_names() -> tuple[str, ...]:
    """Candidate names that are *baselines* (used in reporting honesty)."""
    return ("naive_last_value", "seasonal_naive_7", "moving_average_7")


__all__ = [
    "MIN_OBSERVATIONS",
    "MIN_TRAIN_OBSERVATIONS",
    "SUPPORTED_HORIZONS",
    "MOVING_AVERAGE_WINDOW",
    "SEASONAL_PERIOD",
    "MODEL_VERSION",
    "TrendSeasonalModel",
    "ForecastOutcome",
    "fit_trend_seasonal",
    "forecast",
    "error_report",
    "mae",
    "rmse",
    "smape",
    "mape",
    "interval_coverage",
    "baseline_names",
]
