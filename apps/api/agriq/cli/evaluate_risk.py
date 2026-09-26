"""Offline risk-engine evaluation CLI (Phase 5 §14–17).

Usage (from ``apps/api``)::

    python -m agriq.cli.evaluate_risk --events /path/to/reference_events.json
    python -m agriq.cli.evaluate_risk --events events.json --since 2026-01-01 --out report.json
    python -m agriq.cli.evaluate_risk            # honest insufficient_data report

Reads every warning ever ISSUED from the configured database (superseded rows
included), matches them against the real reference-event dataset, and prints the
documented metrics overall and per crop / growth stage / district.

This is an operator tool. It is not a route, requires no session, exposes no
farmer identifiers, and writes only where ``--out`` says. When no real
reference-event dataset exists, the command reports ``insufficient_data`` with
the observed counts — it never substitutes placeholder data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _parse_day(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if end_of_day and fmt == "%Y-%m-%d":
            parsed = parsed.replace(hour=23, minute=59, second=59)
        return parsed.replace(tzinfo=timezone.utc)
    raise SystemExit(f"--since/--until must be ISO dates (got {value!r})")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agriq.cli.evaluate_risk",
        description="Evaluate the Crop Risk Intelligence engine against real reference events.",
    )
    parser.add_argument(
        "--events",
        default=None,
        help=(
            "Path to the real reference-event dataset (JSON). Defaults to "
            "AGRIQ_RISK_REFERENCE_EVENTS; when neither is set the report states "
            "insufficient_data instead of inventing events."
        ),
    )
    parser.add_argument("--since", default=None, help="Only evaluate warnings generated on/after this date")
    parser.add_argument("--until", default=None, help="Only evaluate warnings generated on/before this date")
    parser.add_argument("--limit", type=int, default=50000, help="Maximum assessment rows to read")
    parser.add_argument("--out", default=None, help="Write the JSON report to this path")
    parser.add_argument("--quiet", action="store_true", help="Print only the status line")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # Local imports keep CLI startup cheap and avoid import cycles.
    from .. import create_app
    from ..domain.risk_evaluation import dataset as dataset_module
    from ..domain.risk_evaluation.evaluate import evaluate
    from ..repositories.risk_repository import RiskAssessmentRepository

    app = create_app()

    events_path = (
        args.events or os.environ.get(dataset_module.REFERENCE_EVENTS_ENV, "").strip() or None
    )
    if events_path:
        try:
            reference = dataset_module.load_reference_events(events_path)
        except dataset_module.ReferenceDatasetError as exc:
            print(f"Reference dataset rejected: {exc}", file=sys.stderr)
            return 2
    else:
        reference = dataset_module.unavailable("reference_events_unavailable")

    with app.app_context():
        assessments = RiskAssessmentRepository.issued_for_evaluation(
            since=_parse_day(args.since),
            until=_parse_day(args.until, end_of_day=True),
            limit=max(1, args.limit),
        )

    report = evaluate(assessments, reference)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    overall = report["overall"]
    counts = overall["counts"]
    print(
        f"Risk evaluation status: {report['status']} "
        f"(protocol {report['protocol_version']}, calibration {report['calibration_status']})"
    )
    if args.quiet:
        return 0

    print(
        "  assessments read: {assessments} | warnings issued: {warnings_issued} "
        "(pending {warnings_pending}, falsifiable {warnings_falsifiable})".format(
            assessments=len(assessments), **counts
        )
    )
    print(
        f"  reference events: {counts['reference_events']} "
        f"(warned {counts['events_warned']}, missed {counts['events_missed']})"
    )
    for name in (
        "precision", "recall", "f1", "false_alert_rate",
        "missed_event_rate", "brier_score", "warning_lead_time_hours",
    ):
        metric = overall["metrics"][name]
        value = metric["value"]
        rendered = "insufficient data" if metric["status"] != "ok" else value
        reason = f" — {metric.get('reason')}" if metric.get("reason") else ""
        print(f"  {name:>24}: {rendered}{reason}")
    if report.get("reason"):
        print(f"  reason: {report['reason']}")
    print(f"  groups: crop={len(report['subgroups']['by_crop']['groups'])}, "
          f"stage={len(report['subgroups']['by_stage']['groups'])}, "
          f"district={len(report['subgroups']['by_district']['groups'])}")
    for note in report["limitations"]:
        print(f"  ! {note}")
    if args.out:
        print(f"Report written to {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
