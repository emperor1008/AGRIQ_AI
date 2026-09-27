"""Farming Techniques dataset import CLI (Phase 7.2 §32/§33).

Usage::

    python -m agriq.cli.import_farming_knowledge --file data/farming_knowledge/dataset.json
    python -m agriq.cli.import_farming_knowledge --file <dataset> \
        --approve --reviewer "Name, role"

Without ``--approve`` every record lands as ``PENDING_REVIEW`` and is therefore
invisible to the API, to the pages and to the copilot. With ``--approve`` the
named reviewer's decision is recorded on the record and on its source row, and
the reviewed text is mirrored into retrieval chunks so the assistant can cite it.

The command never fetches anything from the network (§33): it validates the
file's provenance metadata against the approved organisation/host allow-lists
and writes rows. Downloading raw documents is the Phase 2 ingestion CLI's job.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agriq.cli.import_farming_knowledge",
        description="Import the reviewed Farming Techniques dataset (idempotent by slug).",
    )
    parser.add_argument("--file", required=True, help="Path to the dataset JSON")
    parser.add_argument("--approve", action="store_true",
                        help="Approve the imported records in this run (requires --reviewer)")
    parser.add_argument("--reviewer", default="",
                        help="Name/role of the human reviewer whose decision this is")
    parser.add_argument("--allow-test-hosts", action="store_true",
                        help="Test-only: accept the RFC 2606 documentation domains")
    args = parser.parse_args(argv)

    from .. import create_app
    from ..integrations.knowledge.farming_import import (
        DatasetError,
        dataset_summary,
        import_dataset,
    )

    app = create_app()
    with app.app_context():
        try:
            dataset, reports = import_dataset(
                args.file,
                approve=args.approve,
                reviewer=args.reviewer or None,
                allow_test_hosts=args.allow_test_hosts,
            )
        except DatasetError as exc:
            print(f"Dataset rejected: {exc}", file=sys.stderr)
            return 2

        summary = dataset_summary(dataset)
        print(f"Dataset {args.file} (version {summary['dataset_version']})")
        print(f"Review policy: {summary['review_policy']}")
        print(f"Records: {summary['techniques']} technique(s), "
              f"{summary['pesticides']} pesticide record(s)")

    for report in reports:
        line = f"  [{report.status:>7}] {report.slug}: {report.detail}"
        if report.chunks:
            line += f" (retrieval chunks: {report.chunks})"
        if report.review_status:
            line += f" review={report.review_status}"
        print(line)
        for error in report.errors:
            print(f"      - {error}")

    failed = [report for report in reports if report.status == "failed"]
    imported = [report for report in reports if report.status in ("created", "updated")]
    print(f"Done. {len(imported)} imported, {len(failed)} rejected.")
    if not args.approve:
        print("All imported rows are PENDING_REVIEW. Approve them with "
              "python -m agriq.cli.review_knowledge --approve <kind> <slug> --reviewer <name>.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
