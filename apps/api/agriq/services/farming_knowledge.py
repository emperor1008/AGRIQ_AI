"""Farming Techniques service (Phase 7.2).

One canonical knowledge base, two presentations:

    Canonical verified record ──┬──▶ Farmer Mode projection (practical order)
                                └──▶ Student Mode projection (study order)

Nothing is duplicated per mode and no text is generated here. This module
decides *what can be shown*, in which order, and which honest state applies:

* ``DATA_UNAVAILABLE``                — nothing verified exists for this request
* ``INSUFFICIENT_REAL_DATA``          — a search matched no verified record
* ``PREPARATION_DATA_UNAVAILABLE``    — no source documents a preparation
* ``APPLICATION_DATA_UNVERIFIED``     — application details not verified
* ``TRANSLATION_PENDING_REVIEW``      — interface language is an unreviewed draft
* ``SOURCE_LANGUAGE_SHOWN``           — content served in its source language
* ``STALE_SOURCE``                    — record past its review date

The service never fills a gap with plausible text: an empty field stays empty
and the matching state token is returned instead.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from ..core.constants import (
    TOKEN_DATA_UNAVAILABLE,
    TOKEN_INSUFFICIENT_REAL_DATA,
)
from ..i18n import (
    DEFAULT_LANGUAGE,
    TRANSLATION_PENDING_REVIEW,
    is_translation_pending,
    normalise_language,
    translate,
    translation_status,
)
from ..models.farming_knowledge import (
    ALL_CATEGORIES,
    APPLICATION_DATA_UNVERIFIED,
    CATEGORY_LABEL_KEYS,
    CATEGORY_MODERN_PESTICIDE,
    EVIDENCE_LEVELS,
    PREPARATION_DATA_UNAVAILABLE,
)
from ..repositories.farming_knowledge_repository import (
    DEFAULT_PAGE_SIZE,
    FarmingKnowledgeRepository as Repo,
    MAX_PAGE_SIZE,
)

__all__ = [
    "categories_overview",
    "entry_detail",
    "facets",
    "knowledge_status",
    "list_entries",
    "source_index",
    "retrieve_verified_knowledge",
    "review_due_state",
    "MODE_FARMER_VIEW",
    "MODE_STUDENT_VIEW",
]

MODE_FARMER_VIEW = "farmer"
MODE_STUDENT_VIEW = "student"

#: Display order of the five categories inside Farming Techniques.
CATEGORY_ORDER = ALL_CATEGORIES

#: Farmer projection (§12): practical decision support first.
FARMER_SECTIONS = (
    ("what_is_it", ("overview", "summary")),
    ("why_useful", ("benefits",)),
    ("how_applied", ("application_practice", "method_practice")),
    ("what_to_avoid", ("what_to_avoid",)),
    ("safety_precautions", ("safety_precautions",)),
)

#: Student projection (§13): teaching order, with the historical/traditional
#: framing preserved so documented practice is never read as a validation.
STUDENT_SECTIONS = (
    ("definition", ("overview", "summary")),
    ("historical_context", ("historical_context", "historical_period")),
    ("principle", ("principle", "traditional_purpose")),
    ("method", ("method_practice", "application_practice")),
    ("advantages", ("benefits",)),
    ("limitations", ("limitations",)),
    ("applications", ("when_useful", "modern_relevance")),
)

#: Pesticide fields that are never invented and never silently translated.
PESTICIDE_DISPLAY_FIELDS = (
    ("active_ingredient", "active_ingredient"),
    ("pesticide_category", "pesticide_category"),
    ("mode_of_action", "mode_of_action"),
    ("approved_use", "approved_use"),
    ("registered_crops", "registered_crops"),
    ("ppe", "ppe"),
    ("pre_harvest_interval", "pre_harvest_interval"),
    ("resistance_management", "resistance_management"),
    ("environmental_precautions", "environmental_precautions"),
    ("storage_handling", "storage_handling"),
    ("regulatory_status", "regulatory_status"),
    ("first_aid_note", "first_aid_note"),
)

#: Fields whose translated form must always be shown next to the source text.
HIGH_RISK_FIELD_NAMES = (
    "safety_precautions", "what_to_avoid", "application_practice",
    "pre_harvest_interval", "ppe", "label_directions_reference",
    "regulatory_status", "environmental_precautions", "storage_handling",
    "first_aid_note",
)


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

def review_due_state(review_due_at: Optional[datetime], now: Optional[datetime] = None) -> dict[str, Any]:
    """Honest freshness state of one record."""
    moment = now or datetime.utcnow()
    if review_due_at is None:
        return {"status": "UNKNOWN", "label_key": "knowledge.freshness_due", "review_due_at": None}
    if review_due_at >= moment:
        return {
            "status": "CURRENT",
            "label_key": "knowledge.freshness_current",
            "review_due_at": review_due_at.isoformat(),
        }
    due_soon = (moment - review_due_at).days <= 30
    return {
        "status": "DUE" if due_soon else "EXPIRED",
        "label_key": "knowledge.freshness_due" if due_soon else "knowledge.freshness_expired",
        "review_due_at": review_due_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

def _category_label_key(category: str) -> str:
    return CATEGORY_LABEL_KEYS.get(category, "knowledge.category_label_modern")


def categories_overview(now: Optional[datetime] = None) -> dict[str, Any]:
    """The five categories with verified counts, or an honest unavailable state."""
    counts = Repo.category_counts(now=now)
    categories: list[dict[str, Any]] = []
    for code in CATEGORY_ORDER:
        bucket = counts.get(code, {"verified": 0, "expired": 0, "pending": 0})
        verified = bucket["verified"]
        categories.append({
            "code": code,
            "label_key": _category_label_key(code),
            "verified": verified,
            "expired": bucket["expired"],
            "pending": bucket["pending"],
            "status": "OK" if verified else TOKEN_DATA_UNAVAILABLE,
            "state_key": "knowledge.empty_category" if not verified else None,
        })
    total = sum(item["verified"] for item in categories)
    return {
        "ok": True,
        "categories": categories,
        "state": "OK" if total else TOKEN_DATA_UNAVAILABLE,
        "verified_total": total,
        "pending_total": sum(item["pending"] for item in categories),
        "expired_total": sum(item["expired"] for item in categories),
    }


def knowledge_status() -> dict[str, Any]:
    """How much verified knowledge this deployment actually holds."""
    counts = Repo.counts_by_status()
    verified = sum(value for key, value in counts.items() if key.endswith(".VERIFIED"))
    pending = sum(value for key, value in counts.items() if key.endswith(".PENDING_REVIEW"))
    expired = sum(value for key, value in counts.items() if key.endswith(".EXPIRED"))
    sources = len(Repo.verified_sources())
    return {
        "ok": True,
        "verified_records": verified,
        "pending_records": pending,
        "expired_records": expired,
        "approved_sources": sources,
        "state": "OK" if verified else TOKEN_DATA_UNAVAILABLE,
        "reviews_available": False if not verified else True,
    }


def facets() -> dict[str, Any]:
    """Filter values that actually exist in verified records (never invented)."""
    crops = Repo.verified_crops()
    regions = Repo.verified_regions()
    return {
        "ok": True,
        "crops": crops,
        "regions": regions,
        "categories": [
            {"code": code, "label_key": _category_label_key(code)} for code in CATEGORY_ORDER
        ],
        "evidence_levels": list(EVIDENCE_LEVELS),
        "max_page_size": MAX_PAGE_SIZE,
    }


def source_index(language: Any = DEFAULT_LANGUAGE) -> dict[str, Any]:
    """The reviewed sources behind the knowledge base, with their real URLs."""
    sources = Repo.verified_sources()
    language_code = normalise_language(language)
    if not sources:
        return {
            "ok": True,
            "status": TOKEN_DATA_UNAVAILABLE,
            "reason": translate("knowledge.empty_category_hint", language_code),
            "sources": [],
        }
    return {
        "ok": True,
        "status": "OK",
        "sources": [
            {
                "key": source.source_key,
                "title": source.title,
                "organisation": source.organisation,
                "source_type": source.source_type,
                "url": source.source_url,
                "region": source.region,
                "language": source.language,
                "publication_date": source.publication_date.isoformat() if source.publication_date else None,
                "accessed_at": source.accessed_at.isoformat() if source.accessed_at else None,
                "last_verified_at": source.last_verified_at.isoformat() if source.last_verified_at else None,
                "review_due_at": source.review_due_at.isoformat() if source.review_due_at else None,
                "licence_note": source.licence_note,
            }
            for source in sources
        ],
    }


# ---------------------------------------------------------------------------
# List / search
# ---------------------------------------------------------------------------

def _source_card(source) -> dict[str, Any]:
    if source is None:
        return {}
    return {
        "title": source.title,
        "organisation": source.organisation,
        "source_type": source.source_type,
        "url": source.source_url,
        "publication_date": source.publication_date.isoformat() if source.publication_date else None,
        "accessed_at": source.accessed_at.isoformat() if source.accessed_at else None,
        "last_verified_at": source.last_verified_at.isoformat() if source.last_verified_at else None,
        "licence_note": source.licence_note,
    }


def _technique_card(technique, language: str) -> dict[str, Any]:
    return {
        "kind": "technique",
        "slug": technique.slug,
        "title": technique.title,
        "category": technique.category,
        "category_label_key": _category_label_key(technique.category),
        "summary": (technique.summary or technique.overview or "")[:280] or None,
        "crops": [crop.crop for crop in technique.crops],
        "crop_scope_note": technique.crop_scope_note,
        "regions": [region.region for region in technique.regions],
        "region_scope": technique.region_scope,
        "evidence_level": technique.evidence_level,
        "source_language": technique.source_language,
        "preparation_status": technique.preparation_status,
        "application_status": technique.application_status,
        "freshness": review_due_state(technique.review_due_at),
        "source": _source_card(technique.source),
        "last_verified_at": technique.last_verified_at.isoformat() if technique.last_verified_at else None,
        "review_status": technique.review_status,
        "detail_url": f"/farming-techniques/technique/{technique.slug}",
    }


def _pesticide_card(pesticide, language: str) -> dict[str, Any]:
    return {
        "kind": "pesticide",
        "slug": pesticide.slug,
        "title": pesticide.display_title,
        "record_type": pesticide.record_type,
        "common_name": pesticide.common_name,
        "category": CATEGORY_MODERN_PESTICIDE,
        "category_label_key": _category_label_key(CATEGORY_MODERN_PESTICIDE),
        "summary": (pesticide.approved_use or "")[:280] or None,
        "crops": sorted({target.crop for target in pesticide.targets}),
        "regions": [pesticide.region_scope] if pesticide.region_scope else [],
        "region_scope": pesticide.region_scope,
        "evidence_level": pesticide.evidence_level,
        "source_language": pesticide.source_language,
        "application_status": pesticide.application_status,
        "freshness": review_due_state(pesticide.review_due_at),
        "source": _source_card(pesticide.source),
        "last_verified_at": pesticide.last_verified_at.isoformat() if pesticide.last_verified_at else None,
        "review_status": pesticide.review_status,
        "detail_url": f"/farming-techniques/pesticide/{pesticide.slug}",
    }


def list_entries(
    *,
    language: Any = DEFAULT_LANGUAGE,
    category: Optional[str] = None,
    crop: Optional[str] = None,
    region: Optional[str] = None,
    evidence: Optional[str] = None,
    query: Optional[str] = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    mode: str = MODE_FARMER_VIEW,
) -> dict[str, Any]:
    """One page of verified entries, or a canonical unavailable state.

    ``DATA_UNAVAILABLE`` is returned when nothing verified exists at all;
    ``INSUFFICIENT_REAL_DATA`` when filters matched no record. Both are honest
    states — the caller must render them instead of asking for a substitute.
    """
    language_code = normalise_language(language)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    term = (query or "").strip() or None
    category = (category or "").strip().lower() or None
    if category and category not in CATEGORY_ORDER:
        category = None

    entries: list[dict[str, Any]] = []
    total = 0

    counts = Repo.counts_by_status()
    any_verified = any(key.endswith(".VERIFIED") for key, value in counts.items() if value)

    if category == CATEGORY_MODERN_PESTICIDE:
        rows, total = Repo.list_pesticides(
            crop=crop, region=region, evidence=evidence, search=term,
            limit=page_size, offset=(page - 1) * page_size,
        )
        entries = [_pesticide_card(row, language_code) for row in rows]
    else:
        # "All" lists documented practices; modern pesticide information keeps
        # its own section and its own safety framing (it is never mixed into a
        # general practice list where a reader could mistake it for advice).
        rows, total = Repo.list_techniques(
            category=category, crop=crop, region=region, evidence=evidence, search=term,
            limit=page_size, offset=(page - 1) * page_size,
        )
        entries = [_technique_card(row, language_code) for row in rows]

    awaiting = knowledge_status()["pending_records"]
    if not entries:
        reason_key = ("common.data_unavailable" if not any_verified
                      else "knowledge.no_results")
        return {
            "ok": True,
            "status": TOKEN_DATA_UNAVAILABLE if not any_verified else TOKEN_INSUFFICIENT_REAL_DATA,
            "reason_key": reason_key,
            "reason": translate(reason_key, language_code),
            "hint_key": "knowledge.empty_category_hint" if not any_verified else "knowledge.no_results_hint",
            "hint": translate(
                "knowledge.empty_category_hint" if not any_verified else "knowledge.no_results_hint",
                language_code,
            ),
            "page": page,
            "page_size": page_size,
            "count": 0,
            "pages": 0,
            "entries": [],
            "awaiting_review": awaiting,
            "filters": {
                "category": category, "crop": crop, "region": region,
                "evidence": evidence, "q": term,
            },
        }

    pages = max(1, (total + page_size - 1) // page_size)
    return {
        "ok": True,
        "status": "OK",
        "mode": MODE_STUDENT_VIEW if mode == MODE_STUDENT_VIEW else MODE_FARMER_VIEW,
        "page": page,
        "page_size": page_size,
        "count": total,
        "pages": pages,
        "has_next": page < pages,
        "has_previous": page > 1,
        "entries": entries,
        "awaiting_review": awaiting,
        "context_note_key": (
            "farmer.not_a_recommendation" if mode != MODE_STUDENT_VIEW else "student.not_a_recommendation"
        ),
        "filters": {
            "category": category, "crop": crop, "region": region,
            "evidence": evidence, "q": term,
        },
    }


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

def _apply_translations(entry, entity_type: str, language: str,
                        source_language: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Resolve reviewed translations; report drafts instead of serving them.

    Returns ``(overrides, translation_state)``. ``overrides[field]`` carries
    ``text`` (reviewed translation) and, for high-risk fields, the source
    language original as ``source_text`` so the two are always shown together.
    """
    state: dict[str, Any] = {
        "requested_language": language,
        "source_language": source_language,
        "status": "SOURCE_LANGUAGE",
        "served_reviewed_fields": [],
        "draft_fields": [],
        # Two independent notices: one about the *content* available for this
        # record, one about the interface catalog being an unreviewed draft.
        "notice_key": None,
        "ui_notice_key": None,
    }
    if language == source_language:
        return {}, state

    rows = Repo.translations_for(entity_type, entry.id, language)
    overrides: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.review_status == "REVIEWED":
            state["served_reviewed_fields"].append(row.field)
            overrides[row.field] = {"text": row.text, "reviewed_by": row.reviewed_by}
        else:
            state["draft_fields"].append(row.field)

    if is_translation_pending(language):
        state["ui_notice_key"] = f"knowledge_states.{TRANSLATION_PENDING_REVIEW}"
    if not state["served_reviewed_fields"]:
        state["status"] = "SOURCE_LANGUAGE_SHOWN"
        state["notice_key"] = "knowledge_states.SOURCE_LANGUAGE_SHOWN"
    elif state["draft_fields"]:
        state["status"] = "PARTIAL"
        state["notice_key"] = f"knowledge_states.{TRANSLATION_PENDING_REVIEW}"
    else:
        state["status"] = "TRANSLATED"
    return overrides, state


def _section_payload(fields: Iterable[str], record,
                     overrides: dict[str, dict[str, Any]]) -> Optional[dict[str, Any]]:
    """First non-empty documented field, with translation handling applied."""
    for field in fields:
        value = getattr(record, field, None)
        if not value:
            continue
        override = overrides.get(field)
        # ``text`` is ALWAYS the source-language original (provenance is never
        # rewritten). A reviewed translation is surfaced in ``translation`` and
        # the UI prefers it for ordinary fields; for safety-critical fields it
        # is shown *next to* the original instead of replacing it. A draft is
        # never surfaced at all.
        payload: dict[str, Any] = {
            "field": field,
            "text": value,
            "source_language": record.source_language,
            "high_risk": field in HIGH_RISK_FIELD_NAMES,
            "translation": override["text"] if override else None,
            "translation_status": "REVIEWED" if override else "NOT_SHOWN",
        }
        return payload
    return None


def _evidence_payload(records) -> list[dict[str, Any]]:
    return [
        {
            "evidence_level": record.evidence_level,
            "claim": record.claim,
            "source_section": record.source_section,
            "note": record.note,
            "source": _source_card(record.source) if record.source else {},
        }
        for record in records
    ]


def entry_detail(
    kind: str,
    slug: str,
    *,
    language: Any = DEFAULT_LANGUAGE,
    mode: str = MODE_FARMER_VIEW,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Full detail payload for one verified record, presented per mode.

    Returns ``None`` when no verified record exists for ``slug`` (the route
    turns that into 404 without revealing whether a pending row exists).
    """
    language_code = normalise_language(language)
    view_mode = MODE_STUDENT_VIEW if mode == MODE_STUDENT_VIEW else MODE_FARMER_VIEW

    if kind == "pesticide":
        pesticide = Repo.get_pesticide(slug)
        if pesticide is None:
            return None
        freshness = review_due_state(pesticide.review_due_at, now)
        if freshness["status"] != "CURRENT":
            # Regulatory/product information is only served while it is inside a
            # current verification window (§27). Overdue is not "current": a
            # stale approved-use claim is exactly the kind of thing that must
            # disappear rather than look authoritative.
            return {
                "ok": True,
                "status": TOKEN_DATA_UNAVAILABLE,
                "kind": "pesticide",
                "slug": slug,
                "reason_key": "knowledge_states.STALE_SOURCE",
                "reason": translate("knowledge_states.STALE_SOURCE", language_code),
                "freshness": freshness,
                "entry": None,
            }
        overrides, translation_state = _apply_translations(
            pesticide, "pesticide", language_code, pesticide.source_language
        )
        fields: list[dict[str, Any]] = []
        for label_key, field in PESTICIDE_DISPLAY_FIELDS:
            value = getattr(pesticide, field, None)
            if not value:
                continue
            override = overrides.get(field)
            fields.append({
                "label_key": f"pesticide.{label_key}",
                "field": field,
                "text": value,
                "translation": override["text"] if override else None,
                "high_risk": field in HIGH_RISK_FIELD_NAMES,
            })
        application_verified = pesticide.application_status != APPLICATION_DATA_UNVERIFIED
        return {
            "ok": True,
            "status": "OK",
            "kind": "pesticide",
            "mode": view_mode,
            "freshness": freshness,
            "translation": translation_state,
            "entry": {
                "slug": pesticide.slug,
                "title": pesticide.display_title,
                "record_type": pesticide.record_type,
                "active_ingredient": pesticide.active_ingredient,
                "common_name": pesticide.common_name,
                "category": CATEGORY_MODERN_PESTICIDE,
                "category_label_key": _category_label_key(CATEGORY_MODERN_PESTICIDE),
                "region_scope": pesticide.region_scope,
                "evidence_level": pesticide.evidence_level,
                "source_language": pesticide.source_language,
                "review_status": pesticide.review_status,
                "reviewed_by": pesticide.reviewed_by,
                "reviewed_at": pesticide.reviewed_at.isoformat() if pesticide.reviewed_at else None,
                "last_verified_at": pesticide.last_verified_at.isoformat() if pesticide.last_verified_at else None,
                "published_at": pesticide.published_at.isoformat() if pesticide.published_at else None,
                "label_directions_reference": pesticide.label_directions_reference,
            },
            "fields": fields,
            "targets": [
                {"crop": target.crop, "target": target.target,
                 "target_kind": target.target_kind, "notes": target.notes}
                for target in pesticide.targets
            ],
        "evidence": _evidence_payload(pesticide.evidence_records),
        "sources": [_source_card(pesticide.source)],
            "application": {
                "status": pesticide.application_status,
                "verified": application_verified,
                "state_key": "pesticide.application_unverified" if not application_verified else None,
                "note_key": "pesticide.application_unverified_note" if not application_verified else None,
                "label_directions_reference": pesticide.label_directions_reference,
            },
            "notices": ["pesticide.label_notice"],
            "safety": {
                "manufacturing_policy_key": "pesticide.manufacturing_refusal",
                "no_manufacturing_key": "pesticide.no_manufacturing",
            },
        }

    technique = Repo.get_technique(slug)
    if technique is None:
        return None
    freshness = review_due_state(technique.review_due_at, now)
    overrides, translation_state = _apply_translations(
        technique, "technique", language_code, technique.source_language
    )

    section_spec = STUDENT_SECTIONS if view_mode == MODE_STUDENT_VIEW else FARMER_SECTIONS
    sections: list[dict[str, Any]] = []
    for label_key, fields in section_spec:
        payload = _section_payload(fields, technique, overrides)
        if payload is None:
            continue
        sections.append({"label_key": f"{'student' if view_mode == MODE_STUDENT_VIEW else 'farmer'}.{label_key}", **payload})

    # Fields shown in both modes but framed separately.
    shared: list[dict[str, Any]] = []
    for label_key, field in (
        ("knowledge.filter_crop", "suitable_conditions"),
        ("farmer.materials", "materials"),
        ("common.limitations", "limitations"),
        ("common.region", "region_scope"),
        ("knowledge.crop_scope_heading", "crop_scope_note"),
    ):
        value = getattr(technique, field, None)
        if value and not any(section["field"] == field for section in sections):
            shared.append({"label_key": label_key, "field": field, "text": value})

    study: list[dict[str, Any]] = []
    if view_mode == MODE_STUDENT_VIEW:
        for label_key, field in (
            ("student.key_concepts", "key_concepts"),
            ("knowledge.results_heading", "study_summary"),
            ("student.examples", "materials"),
        ):
            value = getattr(technique, field, None)
            if value and not any(section["field"] == field for section in sections):
                study.append({"label_key": label_key, "field": field, "text": value})

    preparation_documented = technique.preparation_status != PREPARATION_DATA_UNAVAILABLE
    return {
        "ok": True,
        "status": "OK",
        "kind": "technique",
        "mode": view_mode,
        "freshness": freshness,
        "translation": translation_state,
        "entry": {
            "slug": technique.slug,
            "title": technique.title,
            "category": technique.category,
            "category_label_key": _category_label_key(technique.category),
            "summary": technique.summary,
            "historical_period": technique.historical_period,
            "region_scope": technique.region_scope,
            "regions": [region.region for region in technique.regions],
            "region_notes": [region.scope_note for region in technique.regions if region.scope_note],
            "crops": [crop.crop for crop in technique.crops],
            "crop_scope_note": technique.crop_scope_note,
            "evidence_level": technique.evidence_level,
            "source_language": technique.source_language,
            "review_status": technique.review_status,
            "reviewed_by": technique.reviewed_by,
            "reviewed_at": technique.reviewed_at.isoformat() if technique.reviewed_at else None,
            "reviewer_note": technique.reviewer_note,
            "last_verified_at": technique.last_verified_at.isoformat() if technique.last_verified_at else None,
            "published_at": technique.published_at.isoformat() if technique.published_at else None,
        },
        "sections": sections,
        "shared": shared,
        "study": study,
        "evidence": _evidence_payload(technique.evidence_records),
        "sources": [_source_card(technique.source)],
        "preparation": {
            "status": technique.preparation_status,
            "documented": preparation_documented,
            # Present only when a credible source documents it — the column is
            # never populated with an inferred recipe.
            "instructions": technique.preparation_instructions if preparation_documented else None,
            "state_key": None if preparation_documented else "knowledge_states.PREPARATION_DATA_UNAVAILABLE",
            "state_message": None if preparation_documented
            else translate("knowledge_states.PREPARATION_DATA_UNAVAILABLE", language_code),
        },
        "application": {
            "status": technique.application_status,
            "verified": technique.application_status != APPLICATION_DATA_UNVERIFIED,
            "state_key": None if technique.application_status != APPLICATION_DATA_UNVERIFIED
            else "knowledge_states.APPLICATION_DATA_UNVERIFIED",
            "state_message": None if technique.application_status != APPLICATION_DATA_UNVERIFIED
            else translate("knowledge_states.APPLICATION_DATA_UNVERIFIED", language_code),
        },
        "notices": (
            (["farmer.not_a_recommendation"] if view_mode != MODE_STUDENT_VIEW
             else ["student.not_a_recommendation", "student.evidence_note"])
        ),
        "historical": technique.evidence_level in ("HISTORICAL", "TRADITIONAL", "EVIDENCE_LIMITED"),
        "ui_translation_status": translation_status(language_code),
    }


# ---------------------------------------------------------------------------
# AI grounding surface (§25)
# ---------------------------------------------------------------------------

def retrieve_verified_knowledge(question: str, *, crop: Optional[str] = None,
                                region: Optional[str] = None,
                                language: Any = DEFAULT_LANGUAGE,
                                limit: int = 3) -> dict[str, Any]:
    """Retrieve only review-verified records for an AI answer.

    An AI consumer may use *only* what this returns; when it returns
    ``available: false`` the caller must state that verified guidance is
    unavailable rather than composing an answer. Every passage carries the
    source title, organisation, URL and the record identity.
    """
    language_code = normalise_language(language)
    rows, total = Repo.list_techniques(search=question, crop=crop, limit=limit, offset=0)
    pesticide_rows, pesticide_total = Repo.list_pesticides(search=question, crop=crop, limit=limit, offset=0)

    passages: list[dict[str, Any]] = []
    for row in rows:
        passages.append({
            "kind": "technique",
            "slug": row.slug,
            "title": row.title,
            "category": row.category,
            "text": " ".join(filter(None, [row.summary, row.overview, row.principle, row.method_practice]))[:1200],
            "evidence_level": row.evidence_level,
            "region_scope": row.region_scope,
            "source_title": row.source.title if row.source else None,
            "source_organisation": row.source.organisation if row.source else None,
            "source_url": row.source.source_url if row.source else None,
            "last_verified_at": row.last_verified_at.isoformat() if row.last_verified_at else None,
            "preparation_status": row.preparation_status,
            "application_status": row.application_status,
        })
    for row in pesticide_rows:
        passages.append({
            "kind": "pesticide",
            "slug": row.slug,
            "title": row.display_title,
            "category": CATEGORY_MODERN_PESTICIDE,
            "text": " ".join(filter(None, [row.approved_use, row.mode_of_action]))[:1200],
            "evidence_level": row.evidence_level,
            "region_scope": row.region_scope,
            "source_title": row.source.title if row.source else None,
            "source_organisation": row.source.organisation if row.source else None,
            "source_url": row.source.source_url if row.source else None,
            "last_verified_at": row.last_verified_at.isoformat() if row.last_verified_at else None,
            "application_status": row.application_status,
            "application_data_verified": row.application_status != APPLICATION_DATA_UNVERIFIED,
        })
    passages = passages[:max(1, limit)]
    if not passages:
        return {
            "available": False,
            "method": "reviewed_lexical",
            "passages": [],
            "reason_key": "knowledge.no_results",
            "reason": translate("knowledge.no_results", language_code),
            "matched_records": 0,
        }
    return {
        "available": True,
        "method": "reviewed_lexical",
        "passages": passages,
        "matched_records": total + pesticide_total,
    }
