"""Farming-knowledge models (Phase 7.2).

Canonical, source-backed agricultural knowledge shared by Farmer Mode and
Student Mode. There is exactly one copy of every fact: the two modes differ
only in how the record is *presented* (see ``services.farming_knowledge``).

Rules encoded in the schema (not in the UI):

* **Provenance is mandatory.** Every technique and every pesticide record points
  at a row in ``knowledge_sources`` (the Phase 2 provenance table, extended
  with ``source_type``/``accessed_at``/``last_verified_at``/``review_due_at``).
  A record without a source cannot exist.
* **Review state is explicit.** Rows start ``PENDING_REVIEW``; only
  ``VERIFIED`` rows are ever served as production knowledge, and only when their
  source row is ``approved`` (the same gate the copilot retriever uses).
* **Freshness is per category.** Modern pesticide information expires quickly,
  historical practices do not. ``review_due_at`` is stored per row so an
  expired record is reported as expired instead of silently looking current.
* **Missing preparation/application data is a state, not a blank.** Each record
  carries ``preparation_status``/``application_status`` so the API can say
  ``PREPARATION_DATA_UNAVAILABLE`` / ``APPLICATION_DATA_UNVERIFIED`` instead of
  letting a model or the UI fill the gap.

No seed rows are created here and no agricultural text is generated at import
time: content arrives only from the reviewed source dataset (``data/``) through
``cli/import_farming_knowledge.py``.
"""
from __future__ import annotations

from datetime import datetime

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Vocabularies (mirrored in core.constants for the API layer)
# ---------------------------------------------------------------------------

CATEGORY_ANCIENT = "ancient"
CATEGORY_TRADITIONAL = "traditional"
CATEGORY_MODERN = "modern"
CATEGORY_ORGANIC_BIOLOGICAL = "organic_biological"
CATEGORY_MODERN_PESTICIDE = "modern_pesticide"

#: Categories stored in ``farming_techniques`` (pesticides have their own table
#: because their safety-critical fields are genuinely different).
TECHNIQUE_CATEGORIES = (
    CATEGORY_ANCIENT,
    CATEGORY_TRADITIONAL,
    CATEGORY_MODERN,
    CATEGORY_ORGANIC_BIOLOGICAL,
)
ALL_CATEGORIES = TECHNIQUE_CATEGORIES + (CATEGORY_MODERN_PESTICIDE,)

#: ``knowledge.*`` catalog keys for each category label (other -> translated on
#: the interface; the category code itself is never shown to a user).
CATEGORY_LABEL_KEYS = {
    CATEGORY_ANCIENT: "knowledge.category_label_ancient",
    CATEGORY_TRADITIONAL: "knowledge.category_label_traditional",
    CATEGORY_MODERN: "knowledge.category_label_modern",
    CATEGORY_ORGANIC_BIOLOGICAL: "knowledge.category_label_organic_biological",
    CATEGORY_MODERN_PESTICIDE: "knowledge.category_label_modern_pesticide",
}

# Evidence classification (§21).
EVIDENCE_HISTORICAL = "HISTORICAL"
EVIDENCE_TRADITIONAL = "TRADITIONAL"
EVIDENCE_EXTENSION = "EXTENSION_RECOMMENDATION"
EVIDENCE_RESEARCH = "RESEARCH_SUPPORTED"
EVIDENCE_REGULATORY = "REGULATORY"
EVIDENCE_PRODUCT_INFORMATION = "OFFICIAL_PRODUCT_INFORMATION"
EVIDENCE_LIMITED = "EVIDENCE_LIMITED"
EVIDENCE_LEVELS = (
    EVIDENCE_HISTORICAL,
    EVIDENCE_TRADITIONAL,
    EVIDENCE_EXTENSION,
    EVIDENCE_RESEARCH,
    EVIDENCE_REGULATORY,
    EVIDENCE_PRODUCT_INFORMATION,
    EVIDENCE_LIMITED,
)

#: Evidence levels that describe documented practice rather than a validated
#: modern recommendation (§6/§21) — the UI must label these differently.
HISTORICAL_EVIDENCE_LEVELS = (EVIDENCE_HISTORICAL, EVIDENCE_TRADITIONAL, EVIDENCE_LIMITED)

# Review workflow (§32).
REVIEW_PENDING = "PENDING_REVIEW"
REVIEW_VERIFIED = "VERIFIED"
REVIEW_REJECTED = "REJECTED"
REVIEW_EXPIRED = "EXPIRED"
REVIEW_STATUSES = (REVIEW_PENDING, REVIEW_VERIFIED, REVIEW_REJECTED, REVIEW_EXPIRED)

#: Pesticide record kinds (mirrored from the model for convenience).
PESTICIDE_RECORD_TYPES = ("ACTIVE_INGREDIENT", "SAFETY_GUIDANCE")

# Missing-information states (§9/§11).
DATA_DOCUMENTED = "DOCUMENTED"
PREPARATION_DATA_UNAVAILABLE = "PREPARATION_DATA_UNAVAILABLE"
APPLICATION_DATA_UNVERIFIED = "APPLICATION_DATA_UNVERIFIED"

#: Days a record of each category stays current before it must be re-verified.
#: Pesticide/regulatory information is the most perishable; historical practice
#: documentation is the least.
REVIEW_WINDOW_DAYS = {
    CATEGORY_MODERN_PESTICIDE: 180,
    CATEGORY_ORGANIC_BIOLOGICAL: 730,
    CATEGORY_MODERN: 730,
    CATEGORY_TRADITIONAL: 1825,
    CATEGORY_ANCIENT: 3650,
}

#: Field name used by the dataset/importer for ``crop_scope_note``.
CROP_SCOPE_NOTE_FIELD = "crop_scope_note"
#: Field carrying documented preparation steps (never an inferred recipe).
PREPARATION_INSTRUCTIONS_FIELD = "preparation_instructions"

#: Default source languages allowed for a knowledge record.
SOURCE_LANGUAGES = ("en", "hi", "or")

TRANSLATION_DRAFT = "DRAFT"
TRANSLATION_REVIEWED = "REVIEWED"
TRANSLATION_REJECTED = "REJECTED"
TRANSLATION_STATUSES = (TRANSLATION_DRAFT, TRANSLATION_REVIEWED, TRANSLATION_REJECTED)


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------


class FarmingTechnique(db.Model):
    """One documented agricultural practice (ancient/traditional/modern/organic)."""

    __tablename__ = "farming_techniques"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), nullable=False, unique=True, index=True)
    category = db.Column(db.String(40), nullable=False, index=True)

    # Content is stored in the source language exactly as the source documents
    # it (see ``source_language``). Nothing is machine-generated into these
    # columns; reviewed translations live in ``knowledge_translations``.
    title = db.Column(db.String(300), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    overview = db.Column(db.Text, nullable=True)             # what it is / definition
    principle = db.Column(db.Text, nullable=True)            # how it works
    traditional_purpose = db.Column(db.Text, nullable=True)  # why it was used
    historical_context = db.Column(db.Text, nullable=True)   # period / setting
    historical_period = db.Column(db.String(120), nullable=True)
    method_practice = db.Column(db.Text, nullable=True)      # the documented method
    #:Documented preparation/formulation steps (§9). Populated ONLY from a
    #: credible source; a record without one carries
    #: ``PREPARATION_DATA_UNAVAILABLE`` instead of a plausible recipe.
    preparation_instructions = db.Column(db.Text, nullable=True)
    when_useful = db.Column(db.Text, nullable=True)
    application_practice = db.Column(db.Text, nullable=True)
    materials = db.Column(db.Text, nullable=True)
    suitable_conditions = db.Column(db.Text, nullable=True)
    benefits = db.Column(db.Text, nullable=True)
    limitations = db.Column(db.Text, nullable=True)
    what_to_avoid = db.Column(db.Text, nullable=True)
    safety_precautions = db.Column(db.Text, nullable=True)
    modern_relevance = db.Column(db.Text, nullable=True)
    key_concepts = db.Column(db.Text, nullable=True)         # student-mode study aid
    study_summary = db.Column(db.Text, nullable=True)

    region_scope = db.Column(db.String(160), nullable=True, index=True)
    #: Why no crop list is given (e.g. the source documents the practice for
    #: agriculture generally). Prevents an empty crop list from looking like an
    #: oversight or, worse, an implicit "applies to your crop".
    crop_scope_note = db.Column(db.Text, nullable=True)
    evidence_level = db.Column(db.String(40), nullable=False, index=True)
    source_language = db.Column(db.String(10), nullable=False, default="en")

    preparation_status = db.Column(db.String(40), nullable=False, default=PREPARATION_DATA_UNAVAILABLE)
    application_status = db.Column(db.String(40), nullable=False, default=APPLICATION_DATA_UNVERIFIED)

    source_id = db.Column(db.Integer, db.ForeignKey("knowledge_sources.id"), nullable=False, index=True)
    reference_note = db.Column(db.String(300), nullable=True)

    review_status = db.Column(db.String(20), nullable=False, default=REVIEW_PENDING, index=True)
    reviewed_by = db.Column(db.String(160), nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reviewer_note = db.Column(db.String(500), nullable=True)

    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    review_due_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    source = db.relationship("KnowledgeSource")
    crops = db.relationship(
        "TechniqueCrop", back_populates="technique", cascade="all, delete-orphan",
        lazy="selectin", order_by="TechniqueCrop.crop",
    )
    regions = db.relationship(
        "TechniqueRegion", back_populates="technique", cascade="all, delete-orphan",
        lazy="selectin", order_by="TechniqueRegion.region",
    )
    evidence_records = db.relationship(
        "KnowledgeEvidence", back_populates="technique", cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FarmingTechnique {self.slug} ({self.category}/{self.review_status})>"


class TechniqueCrop(db.Model):
    """Crop applicability of one technique (documented, never assumed)."""

    __tablename__ = "farming_technique_crops"
    __table_args__ = (
        db.UniqueConstraint("technique_id", "crop", name="uq_technique_crop"),
    )

    id = db.Column(db.Integer, primary_key=True)
    technique_id = db.Column(
        db.Integer, db.ForeignKey("farming_techniques.id"), nullable=False, index=True
    )
    crop = db.Column(db.String(120), nullable=False, index=True)
    notes = db.Column(db.String(300), nullable=True)

    technique = db.relationship("FarmingTechnique", back_populates="crops")


class TechniqueRegion(db.Model):
    """Geographic applicability of one technique (a practice is not universal)."""

    __tablename__ = "farming_technique_regions"
    __table_args__ = (
        db.UniqueConstraint("technique_id", "region", name="uq_technique_region"),
    )

    id = db.Column(db.Integer, primary_key=True)
    technique_id = db.Column(
        db.Integer, db.ForeignKey("farming_techniques.id"), nullable=False, index=True
    )
    region = db.Column(db.String(160), nullable=False, index=True)
    scope_note = db.Column(db.String(300), nullable=True)

    technique = db.relationship("FarmingTechnique", back_populates="regions")


class KnowledgeEvidence(db.Model):
    """Evidence classification for one claim inside a technique record.

    A record's overall ``evidence_level`` is the *strongest* level its sources
    support; each individual claim states what the source actually supports, so
    a historical practice can never inherit the appearance of a research-backed
    recommendation.
    """

    __tablename__ = "farming_knowledge_evidence"

    id = db.Column(db.Integer, primary_key=True)
    technique_id = db.Column(
        db.Integer, db.ForeignKey("farming_techniques.id"), nullable=True, index=True
    )
    pesticide_id = db.Column(
        db.Integer, db.ForeignKey("pesticide_information.id"), nullable=True, index=True
    )
    evidence_level = db.Column(db.String(40), nullable=False, index=True)
    claim = db.Column(db.Text, nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey("knowledge_sources.id"), nullable=True, index=True)
    source_section = db.Column(db.String(200), nullable=True)
    note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    technique = db.relationship("FarmingTechnique", back_populates="evidence_records")
    pesticide = db.relationship("PesticideInformation", back_populates="evidence_records")
    source = db.relationship("KnowledgeSource")


class PesticideInformation(db.Model):
    """Approved-product information for one pesticide active ingredient.

    This table is informational and safety-focused. It stores what an official
    source says about an *approved product* — never a recipe, a synthesis route
    or a dose that AGRIQ derived itself. ``application_status`` records whether
    application details could be verified from a current authoritative source;
    when they could not, the API returns ``APPLICATION_DATA_UNVERIFIED`` and the
    UI points at the official label instead of showing a number.
    """

    __tablename__ = "pesticide_information"

    RECORD_ACTIVE_INGREDIENT = "ACTIVE_INGREDIENT"
    RECORD_SAFETY_GUIDANCE = "SAFETY_GUIDANCE"
    RECORD_TYPES = (RECORD_ACTIVE_INGREDIENT, RECORD_SAFETY_GUIDANCE)

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), nullable=False, unique=True, index=True)
    #: Active-ingredient records describe one approved product; SAFETY_GUIDANCE
    #: records carry official safe-use/storage/handling instructions that apply
    #: to any registered pesticide and therefore have no single ingredient.
    record_type = db.Column(db.String(30), nullable=False,
                            default=RECORD_ACTIVE_INGREDIENT, index=True)
    title = db.Column(db.String(300), nullable=True)          # display title
    active_ingredient = db.Column(db.String(200), nullable=True, index=True)
    common_name = db.Column(db.String(200), nullable=True)
    pesticide_category = db.Column(db.String(60), nullable=False)   # insecticide/fungicide/…
    chemical_group = db.Column(db.String(160), nullable=True)       # e.g. an IRAC/HRAC group

    mode_of_action = db.Column(db.Text, nullable=True)
    approved_use = db.Column(db.Text, nullable=True)
    registered_crops = db.Column(db.Text, nullable=True)            # summary text from the source
    label_directions_reference = db.Column(db.String(500), nullable=True)
    ppe = db.Column(db.Text, nullable=True)
    pre_harvest_interval = db.Column(db.String(200), nullable=True)  # only when the source states it
    resistance_management = db.Column(db.Text, nullable=True)
    environmental_precautions = db.Column(db.Text, nullable=True)
    storage_handling = db.Column(db.Text, nullable=True)
    regulatory_status = db.Column(db.Text, nullable=True)
    first_aid_note = db.Column(db.Text, nullable=True)

    evidence_level = db.Column(db.String(40), nullable=False, index=True)
    region_scope = db.Column(db.String(160), nullable=True, index=True)
    source_language = db.Column(db.String(10), nullable=False, default="en")
    application_status = db.Column(db.String(40), nullable=False, default=APPLICATION_DATA_UNVERIFIED)

    source_id = db.Column(db.Integer, db.ForeignKey("knowledge_sources.id"), nullable=False, index=True)
    reference_note = db.Column(db.String(300), nullable=True)

    review_status = db.Column(db.String(20), nullable=False, default=REVIEW_PENDING, index=True)
    reviewed_by = db.Column(db.String(160), nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reviewer_note = db.Column(db.String(500), nullable=True)

    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    review_due_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    source = db.relationship("KnowledgeSource")
    targets = db.relationship(
        "PesticideTarget", back_populates="pesticide", cascade="all, delete-orphan",
        lazy="selectin", order_by="PesticideTarget.crop",
    )
    # NOTE: ``evidence_records`` is declared above; keep both relationships on
    # their own nullable FK so one evidence row can never belong to both a
    # technique and a pesticide.
    evidence_records = db.relationship(
        "KnowledgeEvidence", back_populates="pesticide", cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def display_title(self) -> str:
        """Title shown to a user (never generated: falls back to the ingredient)."""
        return self.title or self.active_ingredient or self.slug

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PesticideInformation {self.slug} ({self.review_status})>"


class PesticideTarget(db.Model):
    """A registered crop/pest combination stated by the official source."""

    __tablename__ = "farming_pesticide_targets"
    __table_args__ = (
        db.UniqueConstraint("pesticide_id", "crop", "target", name="uq_pesticide_target"),
    )

    id = db.Column(db.Integer, primary_key=True)
    pesticide_id = db.Column(
        db.Integer, db.ForeignKey("pesticide_information.id"), nullable=False, index=True
    )
    crop = db.Column(db.String(120), nullable=False, index=True)
    target = db.Column(db.String(200), nullable=False)
    target_kind = db.Column(db.String(40), nullable=True)   # pest | disease | weed
    notes = db.Column(db.String(300), nullable=True)

    pesticide = db.relationship("PesticideInformation", back_populates="targets")


class KnowledgeTranslation(db.Model):
    """A reviewed translation of one field of one knowledge record (§16-§18).

    Deliberately a single polymorphic table (``entity_type`` + ``entity_id``)
    so technique, pesticide and evidence text share one review workflow instead
    of duplicating translation columns per table.

    ``review_status`` gates serving: only ``REVIEWED`` rows are returned to a
    user. ``DRAFT`` rows exist for a reviewer to finish and are never presented
    as verified content — the UI shows the source-language text plus the
    ``SOURCE_LANGUAGE_SHOWN`` notice instead.
    """

    __tablename__ = "knowledge_translations"
    __table_args__ = (
        db.UniqueConstraint(
            "entity_type", "entity_id", "language", "field", name="uq_knowledge_translation"
        ),
    )

    ENTITY_TECHNIQUE = "technique"
    ENTITY_PESTICIDE = "pesticide"
    ENTITY_TYPES = (ENTITY_TECHNIQUE, ENTITY_PESTICIDE)

    #: Fields that must never be served as a translation without human review
    #: (safety-critical or legally meaningful text, §18).
    HIGH_RISK_FIELDS = (
        "safety_precautions", "what_to_avoid", "application_practice",
        "preparation_instructions", "pre_harvest_interval", "ppe",
        "label_directions_reference", "regulatory_status", "first_aid_note",
        "environmental_precautions", "storage_handling", "application_status_note",
    )

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(20), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    language = db.Column(db.String(10), nullable=False, index=True)
    field = db.Column(db.String(80), nullable=False)
    text = db.Column(db.Text, nullable=False)
    review_status = db.Column(db.String(20), nullable=False, default=TRANSLATION_DRAFT, index=True)
    translator = db.Column(db.String(160), nullable=True)
    reviewed_by = db.Column(db.String(160), nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    review_note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "field": self.field,
            "text": self.text,
            "review_status": self.review_status,
            "translator": self.translator,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


def review_due_for(category: str, verified_at: datetime) -> datetime:
    """Review deadline for a record of ``category`` verified at ``verified_at``."""
    from datetime import timedelta

    days = REVIEW_WINDOW_DAYS.get(category, REVIEW_WINDOW_DAYS[CATEGORY_MODERN])
    return verified_at + timedelta(days=days)


__all__ = [
    "ALL_CATEGORIES",
    "APPLICATION_DATA_UNVERIFIED",
    "CATEGORY_ANCIENT",
    "CATEGORY_LABEL_KEYS",
    "CATEGORY_MODERN",
    "CATEGORY_MODERN_PESTICIDE",
    "CATEGORY_ORGANIC_BIOLOGICAL",
    "CATEGORY_TRADITIONAL",
    "CROP_SCOPE_NOTE_FIELD",
    "DATA_DOCUMENTED",
    "EVIDENCE_EXTENSION",
    "EVIDENCE_HISTORICAL",
    "EVIDENCE_LEVELS",
    "EVIDENCE_LIMITED",
    "EVIDENCE_PRODUCT_INFORMATION",
    "EVIDENCE_REGULATORY",
    "EVIDENCE_RESEARCH",
    "EVIDENCE_TRADITIONAL",
    "FarmingTechnique",
    "HISTORICAL_EVIDENCE_LEVELS",
    "KnowledgeEvidence",
    "KnowledgeTranslation",
    "PREPARATION_DATA_UNAVAILABLE",
    "PREPARATION_INSTRUCTIONS_FIELD",
    "PesticideInformation",
    "PesticideTarget",
    "REVIEW_EXPIRED",
    "REVIEW_PENDING",
    "REVIEW_REJECTED",
    "REVIEW_STATUSES",
    "REVIEW_VERIFIED",
    "REVIEW_WINDOW_DAYS",
    "SOURCE_LANGUAGES",
    "TECHNIQUE_CATEGORIES",
    "PESTICIDE_RECORD_TYPES",
    "TRANSLATION_DRAFT",
    "TRANSLATION_REJECTED",
    "TRANSLATION_REVIEWED",
    "TRANSLATION_STATUSES",
    "TechniqueCrop",
    "TechniqueRegion",
    "review_due_for",
]
