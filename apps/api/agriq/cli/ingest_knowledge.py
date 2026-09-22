"""Explicit knowledge ingestion CLI.

Usage::

    python -m agriq.cli.ingest_knowledge --manifest data/source_manifest.json

The command validates the manifest allowlist, downloads each source with
timeout/retry rules, stores checksums, extracts and sections text, and
persists rows as ``pending_review``. It never auto-approves and never runs
from a browser route. Output is a plain per-source report (no secrets).
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agriq.cli.ingest_knowledge",
        description="Ingest allowlisted agricultural knowledge sources for review.",
    )
    parser.add_argument("--manifest", required=True,
                        help="Path to the source manifest JSON (e.g. data/source_manifest.json)")
    parser.add_argument("--storage",
                        default=None,
                        help="Override KNOWLEDGE_STORAGE_PATH for raw document storage")
    args = parser.parse_args(argv)

    # App context gives us the configured database and settings.
    from .. import create_app
    from ..core.config import Config
    from ..integrations.knowledge.ingestion import ingest_manifest
    from ..integrations.knowledge.source_registry import ManifestError

    app = create_app()
    storage = args.storage or app.config.get("KNOWLEDGE_STORAGE_PATH", "data/knowledge")

    try:
        reports = ingest_manifest(args.manifest, storage)
    except ManifestError as exc:
        print(f"Manifest rejected: {exc}", file=sys.stderr)
        return 2

    print(f"Ingested manifest: {args.manifest}")
    for report in reports:
        print(f"  [{report.status:>8}] {report.source_key}: {report.detail} "
              f"(chunks={report.chunks}, checksum={report.checksum[:12]}…)")
    failures = [r for r in reports if r.status == "failed"]
    print(f"Done. {len(reports)} source(s), {len(failures)} failure(s). "
          f"All rows are pending_review until approved by a reviewer.")
    return 1 if failures and not [r for r in reports if r.status in ("ingested", "updated")] else 0


if __name__ == "__main__":
    raise SystemExit(main())
