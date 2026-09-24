"""Subgroup analysis (Phase 4).

Evaluation must be reported separately per cohort: controlled vs field
images, per device category, per lighting condition. This module slices a
real evaluation result set into subgroups and computes the same metric set
per slice. Cohorts are never merged into a single headline number.
"""
from __future__ import annotations

from typing import Any, Callable

from .metrics import full_report


def subgroup_report(
    records: list[dict[str, Any]],
    labels: list[str],
    slice_key: str,
    metric_fn: Callable[..., dict[str, Any]] = full_report,
) -> dict[str, dict[str, Any]]:
    """Compute the metric report independently per subgroup.

    ``records`` need: y_true, y_pred and the slice field (e.g. device,
    environment, capture cohort).
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        if slice_key not in rec:
            raise ValueError(f"Record missing slice key '{slice_key}'")
        groups.setdefault(str(rec[slice_key]), []).append(rec)

    report: dict[str, dict[str, Any]] = {}
    for value, members in sorted(groups.items()):
        report[value] = {
            "n_samples": len(members),
            **metric_fn(
                [m["y_true"] for m in members],
                [m["y_pred"] for m in members],
                labels,
            ),
        }
    return report
