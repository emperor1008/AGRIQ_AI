"""Evaluation metrics (Phase 4).

Computes metrics **only** from real prediction records produced by an actual
evaluation run. Every function requires the ground-truth/prediction lists to
be non-empty — no synthetic defaults, no fabricated denominators.
"""
from __future__ import annotations

from typing import Any, Sequence


class EvaluationError(Exception):
    """Raised when evaluation inputs are missing or empty."""


def confusion_matrix(y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]) -> list[list[int]]:
    _require_data(y_true, y_pred)
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for truth, pred in zip(y_true, y_pred):
        matrix[index[truth]][index[pred]] += 1
    return matrix


def per_class_prf(
    y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]
) -> dict[str, dict[str, float]]:
    matrix = confusion_matrix(y_true, y_pred, labels)
    report: dict[str, dict[str, float]] = {}
    for i, label in enumerate(labels):
        tp = matrix[i][i]
        fp = sum(matrix[r][i] for r in range(len(labels))) - tp
        fn = sum(matrix[i]) - tp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        report[label] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}
    return report


def macro_f1(per_class: dict[str, dict[str, float]]) -> float:
    if not per_class:
        raise EvaluationError("No per-class results to average")
    return round(sum(v["f1"] for v in per_class.values()) / len(per_class), 4)


def balanced_accuracy(y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]) -> float:
    per_class = per_class_prf(y_true, y_pred, labels)
    return round(sum(v["recall"] for v in per_class.values()) / len(per_class), 4)


def expected_calibration_error(
    confidences: Sequence[float], correct: Sequence[bool], bins: int = 10
) -> float:
    """Standard ECE over equal-width confidence bins."""
    _require_data(confidences, correct)
    if len(confidences) != len(correct):
        raise EvaluationError("Confidence/correctness length mismatch")
    total = len(confidences)
    ece = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        bucket = [(c, ok) for c, ok in zip(confidences, correct) if lo <= c < hi or (b == bins - 1 and c == 1.0)]
        if not bucket:
            continue
        acc = sum(1 for _, ok in bucket if ok) / len(bucket)
        avg_conf = sum(c for c, _ in bucket) / len(bucket)
        ece += (len(bucket) / total) * abs(acc - avg_conf)
    return round(ece, 4)


def reliability_diagram(
    confidences: Sequence[float], correct: Sequence[bool], bins: int = 10
) -> list[dict[str, float]]:
    """Real bin data for a reliability diagram plot."""
    diagram: list[dict[str, float]] = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        bucket = [(c, ok) for c, ok in zip(confidences, correct) if lo <= c < hi or (b == bins - 1 and c == 1.0)]
        diagram.append(
            {
                "bin_lower": round(lo, 2),
                "bin_upper": round(hi, 2),
                "count": float(len(bucket)),
                "accuracy": round(sum(1 for _, ok in bucket if ok) / len(bucket), 4) if bucket else 0.0,
                "mean_confidence": round(sum(c for c, _ in bucket) / len(bucket), 4) if bucket else 0.0,
            }
        )
    return diagram


def full_report(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    labels: Sequence[str],
    confidences: Sequence[float] | None = None,
    correct_flags: Sequence[bool] | None = None,
) -> dict[str, Any]:
    per_class = per_class_prf(y_true, y_pred, labels)
    report: dict[str, Any] = {
        "per_class": per_class,
        "macro_f1": macro_f1(per_class),
        "balanced_accuracy": balanced_accuracy(y_true, y_pred, labels),
        "confusion_matrix": {
            "labels": list(labels),
            "matrix": confusion_matrix(y_true, y_pred, labels),
        },
    }
    if confidences is not None and correct_flags is not None:
        report["ece"] = expected_calibration_error(confidences, correct_flags)
        report["reliability_diagram"] = reliability_diagram(confidences, correct_flags)
    return report


def _require_data(*sequences: Sequence[Any]) -> None:
    if any(len(s) == 0 for s in sequences):
        raise EvaluationError("Evaluation requires non-empty real result data")
