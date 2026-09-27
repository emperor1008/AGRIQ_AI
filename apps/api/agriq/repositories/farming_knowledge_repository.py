"""Data access for the Farming Techniques knowledge base (Phase 7.2).

Read methods are **review-gated twice**: a record is returned only when its own
``review_status`` is ``VERIFIED`` *and* its provenance row in
``knowledge_sources`` is ``approved``. That is the same gate the Phase 2
retriever applies, so the AI can never ground on a record a reviewer has not
approved.

Write methods exist for the review/import CLI only — no HTTP route may call
them (see ``docs/SECURITY_AND_ACCESS.md``).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional, Sequence

from ..extensions import db
from ..models.farming_knowledge import (
    ALL_CATEGORIES,
    REVIEW_VERIFIED,
    FarmingTechnique,
    KnowledgeEvidence,
    KnowledgeTranslation,
    PesticideInformation,
    PesticideTarget,
    TechniqueCrop,
    TechniqueRegion,
    review_due_for,
)
from ..models.knowledge import KnowledgeSource

#: Hard bounds so one request can never ask for the whole database (§37).
DEFAULT_PAGE_SIZE = 12
MAX_PAGE_SIZE = 48
#: Search needs a bounded scan even before pagination is applied.
MAX_LIST_ROWS = 300


def _approved_source_ids() -> list[int]:
    return list(db.session.execute(
        db.select(KnowledgeSource.id).where(KnowledgeSource.review_status == KnowledgeSource.STATUS_APPROVED)
    ).scalars())


#: Words that carry no agricultural meaning. Dropped before matching so that a
#: question ("what is mulch?") matches the knowledge text ("biomass mulching").
SEARCH_STOPWORDS = frozenset({
    "a", "about", "an", "and", "any", "are", "as", "at", "be", "been", "by",
    "can", "could", "describe", "did", "do", "does", "explain", "for", "from",
    "get", "give", "has", "have", "help", "how", "i", "if", "in", "is", "it",
    "its", "know", "learn", "list", "look", "looking", "me", "method", "my",
    "need", "of", "on", "or", "our", "please", "show", "teach", "tell", "the",
    "their", "them", "there", "these", "this", "to", "us", "want", "was", "we",
    "were", "what", "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your",
})


def _word_variants(token: str) -> tuple[str, ...]:
    """Conservative English word-form variants for one token.

    Deliberately small and predictable: a plural, gerund or derived form of the
    *same* word, never a different word. Nothing here invents vocabulary — it
    only stops "mulch" from failing to find "mulching".
    """
    forms = {token}
    if token.endswith("ies") and len(token) > 4:
        forms.add(token[:-3] + "y")
    if token.endswith("ing") and len(token) > 5:
        base = token[:-3]
        forms.add(base)
        forms.add(base + "e")
    if token.endswith("es") and len(token) > 4:
        forms.add(token[:-2])
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        forms.add(token[:-1])
    forms.add(token + "s")
    forms.add(token + "ing")
    return tuple(sorted(form for form in forms if len(form) >= 3))


def _pesticide_search_clause(term: str):
    """Tokenised search for regulatory pesticide records (same rule as above)."""
    terms = search_terms(term)
    if not terms:
        return None
    text_fields = (
        PesticideInformation.active_ingredient,
        PesticideInformation.title,
        PesticideInformation.common_name,
        PesticideInformation.pesticide_category,
        PesticideInformation.approved_use,
        PesticideInformation.registered_crops,
        PesticideInformation.mode_of_action,
        PesticideInformation.label_directions_reference,
        PesticideInformation.ppe,
        PesticideInformation.pre_harvest_interval,
        PesticideInformation.resistance_management,
        PesticideInformation.environmental_precautions,
        PesticideInformation.storage_handling,
        PesticideInformation.regulatory_status,
    )
    groups = []
    for term_token in terms:
        groups.append(db.or_(
            _term_clause(term_token, text_fields),
            PesticideInformation.id.in_(
                db.select(PesticideTarget.pesticide_id).where(db.or_(
                    PesticideTarget.crop.ilike(f"%{term_token}%"),
                    PesticideTarget.target.ilike(f"%{term_token}%"),
                ))
            ),
            PesticideInformation.slug.ilike(f"%{term_token}%"),
        ))
    return db.and_(*groups)


def search_terms(term: str) -> tuple[str, ...]:
    """Significant tokens of a search box entry or a natural-language question."""
    words = re.findall(r"[0-9A-Za-z\u0900-\u097f\u0b00-\u0b7f]+", (term or "").lower())
    terms = [word for word in words if word not in SEARCH_STOPWORDS and len(word) >= 2]
    if not terms:
        terms = [word for word in words if len(word) >= 2]
    seen: list[str] = []
    for word in terms:
        if word not in seen:
            seen.append(word)
    return tuple(seen[:8])


def _term_clause(term: str, fields: tuple[Any, ...]):
    """One significant term matched against the documented text fields."""
    return db.or_(*[field.ilike(f"%{variant}%")
                    for variant in _word_variants(term)
                    for field in fields])


def _search_clause(term: str):
    """Lexical search over the documented text fields plus crop/region joins.

    Tokenised rather than phrase-matched: every significant word of the input
    must appear somewhere in the record (in any of its normal word forms). One
    phrase LIKE over the whole question never matched anything, which silently
    turned real, reviewed knowledge into a false ``DATA_UNAVAILABLE``.
    """
    terms = search_terms(term)
    if not terms:
        return None
    text_fields = (
        FarmingTechnique.title,
        FarmingTechnique.summary,
        FarmingTechnique.overview,
        FarmingTechnique.principle,
        FarmingTechnique.traditional_purpose,
        FarmingTechnique.method_practice,
        FarmingTechnique.benefits,
        FarmingTechnique.limitations,
        FarmingTechnique.safety_precautions,
        FarmingTechnique.modern_relevance,
        FarmingTechnique.preparation_instructions,
        FarmingTechnique.application_practice,
    )
    groups = []
    for term_token in terms:
        crop_match = db.select(TechniqueCrop.technique_id).where(
            TechniqueCrop.crop.ilike(f"%{term_token}%")
        )
        region_match = db.select(TechniqueRegion.technique_id).where(
            TechniqueRegion.region.ilike(f"%{term_token}%")
        )
        groups.append(db.or_(
            _term_clause(term_token, text_fields),
            FarmingTechnique.id.in_(crop_match),
            FarmingTechnique.id.in_(region_match),
            FarmingTechnique.slug.ilike(f"%{term_token}%"),
        ))
    return db.and_(*groups)


class FarmingKnowledgeRepository:
    """Reads and (CLI-only) writes for farming techniques and pesticides."""

    # ------------------------------------------------------------------ reads
    @staticmethod
    def _verified_technique_filters(
        *,
        category: Optional[str] = None,
        crop: Optional[str] = None,
        region: Optional[str] = None,
        evidence: Optional[str] = None,
        search: Optional[str] = None,
        include_expired: bool = False,
        now: Optional[datetime] = None,
    ) -> list[Any]:
        moment = now or datetime.utcnow()
        approved = _approved_source_ids()
        if not approved:
            return []
        clauses: list[Any] = [
            FarmingTechnique.review_status == REVIEW_VERIFIED,
            FarmingTechnique.source_id.in_(approved),
        ]
        if not include_expired:
            clauses.append(db.or_(
                FarmingTechnique.review_due_at.is_(None),
                FarmingTechnique.review_due_at >= moment,
            ))
        if category:
            clauses.append(FarmingTechnique.category == category)
        if evidence:
            clauses.append(FarmingTechnique.evidence_level == evidence)
        if crop:
            crop_match = db.select(TechniqueCrop.technique_id).where(
                TechniqueCrop.crop.ilike(f"%{crop}%")
            )
            clauses.append(FarmingTechnique.id.in_(crop_match))
        if region:
            region_match = db.select(TechniqueRegion.technique_id).where(
                TechniqueRegion.region.ilike(f"%{region}%")
            )
            clauses.append(FarmingTechnique.id.in_(region_match))
        if search:
            clause = _search_clause(search)
            if clause is not None:
                clauses.append(clause)
        return clauses

    @staticmethod
    def list_techniques(
        *,
        category: Optional[str] = None,
        crop: Optional[str] = None,
        region: Optional[str] = None,
        evidence: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        include_expired: bool = False,
        now: Optional[datetime] = None,
    ) -> tuple[list[FarmingTechnique], int]:
        """Return ``(rows, total)`` for the current page (bounded)."""
        clauses = FarmingKnowledgeRepository._verified_technique_filters(
            category=category, crop=crop, region=region, evidence=evidence,
            search=search, include_expired=include_expired, now=now,
        )
        if not clauses:
            return [], 0
        limit = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
        offset = max(0, int(offset or 0))
        total = int(db.session.execute(
            db.select(db.func.count(FarmingTechnique.id)).where(*clauses)
        ).scalar() or 0)
        rows = list(db.session.execute(
            db.select(FarmingTechnique)
            .where(*clauses)
            .order_by(FarmingTechnique.category, FarmingTechnique.title)
            .offset(offset)
            .limit(limit)
        ).scalars())
        return rows, total

    @staticmethod
    def get_technique(slug: str, *, include_unverified: bool = False,
                      now: Optional[datetime] = None) -> Optional[FarmingTechnique]:
        """One technique by slug. Verified + approved-source gated by default.

        The record is returned even when it is past its review date so the
        caller can report ``EXPIRED`` honestly; it is never returned when it
        fails the review gate.
        """
        technique = db.session.execute(
            db.select(FarmingTechnique).where(FarmingTechnique.slug == slug)
        ).scalar_one_or_none()
        if technique is None:
            return None
        if include_unverified:
            return technique
        if technique.review_status != REVIEW_VERIFIED:
            return None
        source = db.session.get(KnowledgeSource, technique.source_id)
        if source is None or source.review_status != KnowledgeSource.STATUS_APPROVED:
            return None
        return technique

    @staticmethod
    def list_pesticides(
        *,
        crop: Optional[str] = None,
        region: Optional[str] = None,
        evidence: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        include_expired: bool = False,
        now: Optional[datetime] = None,
    ) -> tuple[list[PesticideInformation], int]:
        moment = now or datetime.utcnow()
        approved = _approved_source_ids()
        if not approved:
            return [], 0
        clauses: list[Any] = [
            PesticideInformation.review_status == REVIEW_VERIFIED,
            PesticideInformation.source_id.in_(approved),
        ]
        if not include_expired:
            clauses.append(db.or_(
                PesticideInformation.review_due_at.is_(None),
                PesticideInformation.review_due_at >= moment,
            ))
        if evidence:
            clauses.append(PesticideInformation.evidence_level == evidence)
        if region:
            clauses.append(PesticideInformation.region_scope.ilike(f"%{region}%"))
        if crop:
            crop_match = db.select(PesticideTarget.pesticide_id).where(
                PesticideTarget.crop.ilike(f"%{crop}%")
            )
            clauses.append(PesticideInformation.id.in_(crop_match))
        if search:
            clause = _pesticide_search_clause(search)
            if clause is not None:
                clauses.append(clause)
        limit = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
        offset = max(0, int(offset or 0))
        total = int(db.session.execute(
            db.select(db.func.count(PesticideInformation.id)).where(*clauses)
        ).scalar() or 0)
        rows = list(db.session.execute(
            db.select(PesticideInformation)
            .where(*clauses)
            .order_by(db.func.coalesce(
                PesticideInformation.active_ingredient, PesticideInformation.title
            ))
            .offset(offset)
            .limit(limit)
        ).scalars())
        return rows, total

    @staticmethod
    def get_pesticide(slug: str, *, include_unverified: bool = False) -> Optional[PesticideInformation]:
        pesticide = db.session.execute(
            db.select(PesticideInformation).where(PesticideInformation.slug == slug)
        ).scalar_one_or_none()
        if pesticide is None:
            return None
        if include_unverified:
            return pesticide
        if pesticide.review_status != REVIEW_VERIFIED:
            return None
        source = db.session.get(KnowledgeSource, pesticide.source_id)
        if source is None or source.review_status != KnowledgeSource.STATUS_APPROVED:
            return None
        return pesticide

    @staticmethod
    def verified_crops() -> list[str]:
        """Crops with at least one review-verified record (facets only)."""
        approved = _approved_source_ids()
        if not approved:
            return []
        crops = set(db.session.execute(
            db.select(TechniqueCrop.crop)
            .join(FarmingTechnique, TechniqueCrop.technique_id == FarmingTechnique.id)
            .where(
                FarmingTechnique.review_status == REVIEW_VERIFIED,
                FarmingTechnique.source_id.in_(approved),
            )
        ).scalars())
        crops.update(db.session.execute(
            db.select(PesticideTarget.crop)
            .join(PesticideInformation, PesticideTarget.pesticide_id == PesticideInformation.id)
            .where(
                PesticideInformation.review_status == REVIEW_VERIFIED,
                PesticideInformation.source_id.in_(approved),
            )
        ).scalars())
        return sorted({crop for crop in crops if crop})

    @staticmethod
    def verified_regions() -> list[str]:
        approved = _approved_source_ids()
        if not approved:
            return []
        regions = set(db.session.execute(
            db.select(TechniqueRegion.region)
            .join(FarmingTechnique, TechniqueRegion.technique_id == FarmingTechnique.id)
            .where(
                FarmingTechnique.review_status == REVIEW_VERIFIED,
                FarmingTechnique.source_id.in_(approved),
            )
        ).scalars())
        regions.update(db.session.execute(
            db.select(PesticideInformation.region_scope).where(
                PesticideInformation.review_status == REVIEW_VERIFIED,
                PesticideInformation.source_id.in_(approved),
                PesticideInformation.region_scope.isnot(None),
            )
        ).scalars())
        return sorted({region for region in regions if region})

    @staticmethod
    def category_counts(now: Optional[datetime] = None) -> dict[str, dict[str, int]]:
        """Per-category ``{verified, expired, pending}`` counts for the overview."""
        moment = now or datetime.utcnow()
        counts: dict[str, dict[str, int]] = {
            category: {"verified": 0, "expired": 0, "pending": 0} for category in ALL_CATEGORIES
        }
        approved = set(_approved_source_ids())
        rows = db.session.execute(
            db.select(
                FarmingTechnique.category,
                FarmingTechnique.review_status,
                FarmingTechnique.source_id,
                FarmingTechnique.review_due_at,
            )
        ).all()
        for category, status, source_id, due in rows:
            bucket = counts.setdefault(category, {"verified": 0, "expired": 0, "pending": 0})
            genuine = status == REVIEW_VERIFIED and source_id in approved
            if genuine and (due is None or due >= moment):
                bucket["verified"] += 1
            elif genuine:
                bucket["expired"] += 1
            else:
                bucket["pending"] += 1
        pesticide_rows = db.session.execute(
            db.select(
                PesticideInformation.review_status,
                PesticideInformation.source_id,
                PesticideInformation.review_due_at,
            )
        ).all()
        bucket = counts.setdefault(
            "modern_pesticide", {"verified": 0, "expired": 0, "pending": 0}
        )
        for status, source_id, due in pesticide_rows:
            genuine = status == REVIEW_VERIFIED and source_id in approved
            if genuine and (due is None or due >= moment):
                bucket["verified"] += 1
            elif genuine:
                bucket["expired"] += 1
            else:
                bucket["pending"] += 1
        return counts

    @staticmethod
    def translations_for(entity_type: str, entity_id: int,
                         language: Optional[str] = None) -> list[KnowledgeTranslation]:
        stmt = db.select(KnowledgeTranslation).where(
            KnowledgeTranslation.entity_type == entity_type,
            KnowledgeTranslation.entity_id == entity_id,
        )
        if language:
            stmt = stmt.where(KnowledgeTranslation.language == language)
        return list(db.session.execute(stmt).scalars())

    @staticmethod
    def verified_sources() -> list[KnowledgeSource]:
        """Sources actually backing at least one verified record."""
        stmt = (
            db.select(KnowledgeSource)
            .where(KnowledgeSource.review_status == KnowledgeSource.STATUS_APPROVED)
            .order_by(KnowledgeSource.organisation, KnowledgeSource.title)
        )
        return list(db.session.execute(stmt).scalars())

    # ----------------------------------------------------------------- writes
    # CLI-only (``cli/import_farming_knowledge.py``, ``cli/review_knowledge.py``).

    @staticmethod
    def upsert_technique(data: dict[str, Any], *, crops: Sequence[str] = (),
                         regions: Sequence[dict[str, Any]] = (),
                         evidence: Sequence[dict[str, Any]] = ()) -> tuple[FarmingTechnique, bool]:
        """Insert or refresh a technique by slug (idempotent re-import)."""
        technique = db.session.execute(
            db.select(FarmingTechnique).where(FarmingTechnique.slug == data["slug"])
        ).scalar_one_or_none()
        created = technique is None
        if technique is None:
            technique = FarmingTechnique(**data)
            db.session.add(technique)
            db.session.flush()
        else:
            for key, value in data.items():
                setattr(technique, key, value)
            db.session.flush()
            db.session.execute(
                db.delete(TechniqueCrop).where(TechniqueCrop.technique_id == technique.id)
            )
            db.session.execute(
                db.delete(TechniqueRegion).where(TechniqueRegion.technique_id == technique.id)
            )
            db.session.execute(
                db.delete(KnowledgeEvidence).where(KnowledgeEvidence.technique_id == technique.id)
            )
        for crop in crops:
            db.session.add(TechniqueCrop(technique_id=technique.id, crop=crop))
        for region in regions:
            db.session.add(TechniqueRegion(
                technique_id=technique.id,
                region=region["region"],
                scope_note=region.get("scope_note"),
            ))
        for item in evidence:
            db.session.add(KnowledgeEvidence(
                technique_id=technique.id,
                evidence_level=item["evidence_level"],
                claim=item["claim"],
                source_id=item.get("source_id"),
                source_section=item.get("source_section"),
                note=item.get("note"),
            ))
        db.session.commit()
        return technique, created

    @staticmethod
    def upsert_pesticide(data: dict[str, Any],
                         targets: Sequence[dict[str, Any]] = (),
                         evidence: Sequence[dict[str, Any]] = ()) -> tuple[PesticideInformation, bool]:
        pesticide = db.session.execute(
            db.select(PesticideInformation).where(PesticideInformation.slug == data["slug"])
        ).scalar_one_or_none()
        created = pesticide is None
        if pesticide is None:
            pesticide = PesticideInformation(**data)
            db.session.add(pesticide)
            db.session.flush()
        else:
            for key, value in data.items():
                setattr(pesticide, key, value)
            db.session.flush()
            db.session.execute(
                db.delete(PesticideTarget).where(PesticideTarget.pesticide_id == pesticide.id)
            )
            db.session.execute(
                db.delete(KnowledgeEvidence).where(KnowledgeEvidence.pesticide_id == pesticide.id)
            )
        for target in targets:
            db.session.add(PesticideTarget(
                pesticide_id=pesticide.id,
                crop=target["crop"],
                target=target["target"],
                target_kind=target.get("target_kind"),
                notes=target.get("notes"),
            ))
        for item in evidence:
            db.session.add(KnowledgeEvidence(
                pesticide_id=pesticide.id,
                evidence_level=item["evidence_level"],
                claim=item["claim"],
                source_id=item.get("source_id"),
                source_section=item.get("source_section"),
                note=item.get("note"),
            ))
        db.session.commit()
        return pesticide, created

    @staticmethod
    def set_review_status(record, *, status: str, reviewer: str, note: Optional[str],
                          verified_at: Optional[datetime] = None) -> None:
        """Approve/reject a record and stamp its freshness windows."""
        moment = verified_at or datetime.utcnow()
        record.review_status = status
        record.reviewed_by = reviewer
        record.reviewed_at = moment
        record.reviewer_note = note
        if status == REVIEW_VERIFIED:
            record.last_verified_at = moment
            record.review_due_at = review_due_for(record.category, moment) if hasattr(record, "category") \
                else review_due_for(record.pesticide_category or "modern", moment)
            if getattr(record, "published_at", None) is None:
                record.published_at = moment
        db.session.commit()

    @staticmethod
    def upsert_translation(entity_type: str, entity_id: int, language: str, field: str,
                           text: str, *, review_status: str, translator: Optional[str] = None,
                           reviewer: Optional[str] = None, note: Optional[str] = None) -> KnowledgeTranslation:
        translation = db.session.execute(
            db.select(KnowledgeTranslation).where(
                KnowledgeTranslation.entity_type == entity_type,
                KnowledgeTranslation.entity_id == entity_id,
                KnowledgeTranslation.language == language,
                KnowledgeTranslation.field == field,
            )
        ).scalar_one_or_none()
        if translation is None:
            translation = KnowledgeTranslation(
                entity_type=entity_type, entity_id=entity_id, language=language, field=field,
            )
            db.session.add(translation)
        translation.text = text
        translation.review_status = review_status
        translation.translator = translator
        if review_status == "REVIEWED":
            translation.reviewed_by = reviewer
            translation.reviewed_at = datetime.utcnow()
            translation.review_note = note
        db.session.commit()
        return translation

    @staticmethod
    def all_verified_techniques(limit: int = MAX_LIST_ROWS) -> list[FarmingTechnique]:
        clauses = FarmingKnowledgeRepository._verified_technique_filters()
        if not clauses:
            return []
        return list(db.session.execute(
            db.select(FarmingTechnique).where(*clauses).limit(limit)
        ).scalars())

    @staticmethod
    def all_verified_pesticides(limit: int = MAX_LIST_ROWS) -> list[PesticideInformation]:
        rows, _total = FarmingKnowledgeRepository.list_pesticides(limit=min(limit, MAX_PAGE_SIZE))
        return rows

    @staticmethod
    def counts_by_status() -> dict[str, int]:
        """Honest statement of how much knowledge exists and how much is reviewed."""
        result: dict[str, int] = {}
        for label, model in (("techniques", FarmingTechnique), ("pesticides", PesticideInformation)):
            rows = db.session.execute(
                db.select(model.review_status, db.func.count(model.id)).group_by(model.review_status)
            ).all()
            for status, count in rows:
                result[f"{label}.{status}"] = int(count)
        return result


__all__ = [
    "FarmingKnowledgeRepository",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "MAX_LIST_ROWS",
]
