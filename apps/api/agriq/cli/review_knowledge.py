"""Knowledge review CLI (Phase 7.2 §32).

The only way a Farming Techniques record becomes production knowledge. There is
deliberately no HTTP route for this: approval is a human decision with a name
attached.

Usage::

    python -m agriq.cli.review_knowledge --list
    python -m agriq.cli.review_knowledge --approve technique mulching --reviewer "Dr A, OUAT"
    python -m agriq.cli.review_knowledge --reject  technique mulching --reviewer "Dr A" --note "source unclear"
    python -m agriq.cli.review_knowledge --expire  pesticide <slug> --reviewer "Dr A"
    python -m agriq.cli.review_knowledge --translation technique mulching \
        --language hi --field overview --text "..." --reviewed-by "Dr A"

Approving a record also approves its provenance row and mirrors the reviewed
text into retrieval chunks, which is what lets the copilot cite it.
"""
from __future__ import annotations

import argparse
import sys

from ..extensions import db
from ..integrations.knowledge.farming_import import mirror_record_to_retrieval
from ..models.farming_knowledge import (
    REVIEW_EXPIRED,
    REVIEW_REJECTED,
    REVIEW_VERIFIED,
    TRANSLATION_REVIEWED,
    FarmingTechnique,
    PesticideInformation,
)
from ..models.knowledge import KnowledgeSource
from ..repositories.farming_knowledge_repository import FarmingKnowledgeRepository as Repo


def _load(kind: str, slug: str):
    model = PesticideInformation if kind == "pesticide" else FarmingTechnique
    return db.session.execute(db.select(model).where(model.slug == slug)).scalar_one_or_none()


def set_review_status(kind: str, slug: str, *, status: str, reviewer: str,
                      note: str | None = None) -> tuple[bool, int]:
    """Record a human decision on one record.

    Approving also approves the provenance row and mirrors the reviewed text into
    retrieval chunks, so the visibility gate and the assistant's grounding can
    never drift apart. Returns ``(found, chunks_written)``.
    """
    from ..repositories.farming_knowledge_repository import FarmingKnowledgeRepository

    record = _load(kind, slug)
    if record is None:
        return False, 0
    FarmingKnowledgeRepository.set_review_status(
        record, status=status, reviewer=reviewer, note=note,
    )
    chunks = 0
    if status == REVIEW_VERIFIED:
        source = db.session.get(KnowledgeSource, record.source_id)
        if source is not None:
            source.review_status = KnowledgeSource.STATUS_APPROVED
            source.reviewed_at = record.reviewed_at
            source.last_verified_at = source.accessed_at
            source.review_due_at = record.review_due_at
            db.session.commit()
        chunks = mirror_record_to_retrieval(kind, record)
    return True, chunks


def _list_records() -> int:
    for label, model in (("technique", FarmingTechnique), ("pesticide", PesticideInformation)):
        rows = list(db.session.execute(db.select(model).order_by(model.review_status, model.slug)).scalars())
        print(f"{label}s: {len(rows)}")
        for row in rows:
            title = getattr(row, "title", None) or getattr(row, "active_ingredient", "")
            print(f"  [{row.review_status:>13}] {row.slug} — {title}"
                  f" (category={getattr(row, 'category', getattr(row, 'pesticide_category', '?'))}"
                  f", due={row.review_due_at.date().isoformat() if row.review_due_at else 'n/a'})")
    sources = list(db.session.execute(db.select(KnowledgeSource).order_by(KnowledgeSource.source_key)).scalars())
    print(f"sources: {len(sources)}")
    for source in sources:
        print(f"  [{source.review_status:>13}] {source.source_key} — {source.organisation}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agriq.cli.review_knowledge",
        description="Approve, reject or expire Farming Techniques knowledge records.",
    )
    parser.add_argument("--list", action="store_true", help="Show every record with its review state")
    parser.add_argument("--approve", nargs=2, metavar=("KIND", "SLUG"))
    parser.add_argument("--reject", nargs=2, metavar=("KIND", "SLUG"))
    parser.add_argument("--expire", nargs=2, metavar=("KIND", "SLUG"))
    parser.add_argument("--translation", nargs=2, metavar=("KIND", "SLUG"))
    parser.add_argument("--language", choices=("hi", "or"))
    parser.add_argument("--field")
    parser.add_argument("--text")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--reviewed-by", dest="reviewed_by", default="")
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)

    from .. import create_app

    app = create_app()
    with app.app_context():
        if args.list or not any((args.approve, args.reject, args.expire, args.translation)):
            return _list_records()

        reviewer = (args.reviewer or args.reviewed_by).strip()

        if args.translation:
            kind, slug = args.translation
            record = _load(kind, slug)
            if record is None:
                print(f"No {kind} with slug {slug!r}.", file=sys.stderr)
                return 1
            if not reviewer:
                print("A reviewed translation needs --reviewed-by.", file=sys.stderr)
                return 2
            if not (args.language and args.field and args.text):
                print("--language, --field and --text are required for a translation.",
                      file=sys.stderr)
                return 2
            Repo.upsert_translation(
                kind, record.id, args.language, args.field, args.text,
                review_status=TRANSLATION_REVIEWED, translator=None,
                reviewer=reviewer, note=args.note or None,
            )
            print(f"Translation stored: {kind} {slug} {args.language}/{args.field} "
                  f"(REVIEWED by {reviewer})")
            return 0

        for action, status in (("approve", REVIEW_VERIFIED), ("reject", REVIEW_REJECTED),
                               ("expire", REVIEW_EXPIRED)):
            value = getattr(args, action)
            if not value:
                continue
            if not reviewer:
                print(f"--{action} requires --reviewer: an anonymous decision is not a decision.",
                      file=sys.stderr)
                return 2
            kind, slug = value
            if kind not in ("technique", "pesticide"):
                print("KIND must be 'technique' or 'pesticide'.", file=sys.stderr)
                return 2
            found, chunks = set_review_status(
                kind, slug, status=status, reviewer=reviewer, note=args.note or None,
            )
            if not found:
                print(f"No {kind} with slug {slug!r}.", file=sys.stderr)
                return 1
            print(f"{kind} {slug} → {status} by {reviewer}"
                  f"{f' (retrieval chunks: {chunks})' if chunks else ''}")
            return 0

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
