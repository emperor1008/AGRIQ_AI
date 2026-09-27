"""Reviewed import pipeline for the Farming Techniques dataset (Phase 7.2 §32/§33).

    file → schema validation → provenance validation → normalisation →
    deduplication (by slug) → review state → production availability

Rules this module enforces (in code, not in a prompt):

* Every record needs a complete provenance block: source name, organisation,
  URL, source type, publication title, publication/access dates and an evidence
  classification. A record without provenance is rejected outright.
* URLs must be ``https``, must not contain credentials, must not be IP literals
  or loopback/private names, and must be on the documented host allow-list.
  Nothing is fetched from the URL — this is a **validation allow-list, not a
  downloader**, so there is no SSRF surface here. (Raw documents are fetched
  only by the Phase 2 ingestion CLI, which has its own manifest allow-list.)
* Records are imported as ``PENDING_REVIEW`` unless an explicit, named reviewer
  approves them in the same run. Nothing becomes production knowledge by
  accident, and a ``DRAFT`` translation of a safety-critical field is refused
  (a draft must never be served as the safety text).
* Import is idempotent: re-running refreshes the same rows by slug, and the
  child rows (crops, regions, evidence, targets) are rebuilt from the file.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from ...models.farming_knowledge import (
    ALL_CATEGORIES,
    APPLICATION_DATA_UNVERIFIED,
    CATEGORY_MODERN_PESTICIDE,
    DATA_DOCUMENTED,
    EVIDENCE_LEVELS,
    KnowledgeTranslation,
    PREPARATION_DATA_UNAVAILABLE,
    REVIEW_PENDING,
    REVIEW_VERIFIED,
    TRANSLATION_DRAFT,
    TRANSLATION_REVIEWED,
    TRANSLATION_STATUSES,
)
from ...models.knowledge import KnowledgeSource
from ...repositories.copilot_repository import KnowledgeRepository
from ...repositories.farming_knowledge_repository import FarmingKnowledgeRepository as Repo
from .source_registry import ALLOWED_DOCUMENT_TYPES, ALLOWED_ORGANISATIONS

#: Where a record's information comes from (§20).
SOURCE_TYPES = (
    "GOVERNMENT",
    "RESEARCH_INSTITUTE",
    "AGRICULTURAL_UNIVERSITY",
    "EXTENSION_SERVICE",
    "INTERNATIONAL_ORGANIZATION",
    "PEER_REVIEWED_RESEARCH",
    "OFFICIAL_PRODUCT_LABEL",
    "HISTORICAL_REFERENCE",
)

#: Hosts a production knowledge record may cite. Suffix match, so
#: ``nrri.icar.gov.in`` is allowed by ``icar.gov.in``.
ALLOWED_SOURCE_HOSTS = (
    "icar.org.in",
    "icar.gov.in",
    "gov.in",
    "nic.in",
    "ouat.ac.in",
    "tnau.ac.in",
    "egranth.ac.in",
    "res.in",
    "fao.org",
    "cabi.org",
    "usda.gov",
    "cgiar.org",
    "irri.org",
    "doi.org",
    "ncbi.nlm.nih.gov",
    "nih.gov",
    "europa.eu",
)

#: Reserved documentation domains (RFC 2606). Only accepted when a caller
#: explicitly opts in — used by the test suite for fixtures, never in
#: production data.
TEST_SOURCE_HOSTS = ("example.org", "example.net", "example.com")

_PRIVATE_HOST_PATTERNS = (
    re.compile(r"^localhost$"),
    re.compile(r"\.local$"),
    re.compile(r"^127\."),
    re.compile(r"^10\."),
    re.compile(r"^192\.168\."),
    re.compile(r"^172\.(1[6-9]|2[0-9]|3[01])\."),
    re.compile(r"^169\.254\."),
    re.compile(r"^0\."),
    re.compile(r"^\[?::1\]?$"),
)

_IP_LITERAL = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

#: Text fields that must be present on a technique record.
_REQUIRED_TECHNIQUE_FIELDS = ("slug", "category", "title", "summary", "overview", "evidence_level")
_REQUIRED_PESTICIDE_FIELDS = ("slug", "pesticide_category", "evidence_level")

#: Pesticide record kinds: a product record names one active ingredient, while a
#: safety-guidance record carries official instructions that apply to any
#: registered product (and therefore has no single ingredient).
PESTICIDE_RECORD_TYPES = ("ACTIVE_INGREDIENT", "SAFETY_GUIDANCE")
#: ``publication_date`` is deliberately NOT in this list: an undated source is
#: allowed when the record carries ``date_note`` explaining why (see below).
_REQUIRED_SOURCE_FIELDS = (
    "source_key", "title", "organisation", "url", "source_type", "accessed_at",
)

_TEXT_FIELDS = (
    "summary", "overview", "principle", "traditional_purpose", "historical_context",
    "method_practice", "when_useful", "application_practice", "preparation_instructions",
    "materials", "crop_scope_note",
    "suitable_conditions", "benefits", "limitations", "what_to_avoid",
    "safety_precautions", "modern_relevance", "key_concepts", "study_summary",
)

_PESTICIDE_TEXT_FIELDS = (
    "mode_of_action", "approved_use", "registered_crops", "ppe", "pre_harvest_interval",
    "resistance_management", "environmental_precautions", "storage_handling",
    "regulatory_status", "first_aid_note", "label_directions_reference",
)

#: Section labels used when mirroring a record into retrieval chunks, so the
#: copilot cites the same fields a reader sees.
_CHUNK_FIELDS = (
    ("Overview", "overview"),
    ("Why it is used", "traditional_purpose"),
    ("Principle", "principle"),
    ("Method", "method_practice"),
    ("Application", "application_practice"),
    ("Benefits", "benefits"),
    ("Limitations", "limitations"),
    ("Precautions", "safety_precautions"),
    ("Modern relevance", "modern_relevance"),
)

_PESTICIDE_CHUNK_FIELDS = (
    ("Approved use", "approved_use"),
    ("Mode of action", "mode_of_action"),
    ("Registered crop use", "registered_crops"),
    ("Precautions", "ppe"),
    ("Environmental precautions", "environmental_precautions"),
    ("Storage and handling", "storage_handling"),
    ("Regulatory status", "regulatory_status"),
)


class DatasetError(ValueError):
    """Raised when the dataset file itself is unusable."""


@dataclass
class ImportReport:
    """One record's import outcome (no secrets, no payload dumps)."""

    slug: str
    status: str            # created | updated | skipped | failed
    detail: str
    chunks: int = 0
    review_status: str = REVIEW_PENDING
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _parse_date(value: Any, field_name: str, errors: list[str]) -> Optional[date]:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        errors.append(f"{field_name} must be an ISO date (YYYY-MM-DD), got {value!r}")
        return None


def validate_url(url: str, *, allow_test_hosts: bool = False) -> list[str]:
    """URL/SSRF validation for a provenance link (§36)."""
    errors: list[str] = []
    if not url or not isinstance(url, str):
        return ["source.url is required"]
    parsed = urlparse(url)
    if parsed.scheme != "https":
        errors.append("source.url must use https")
    if parsed.username or parsed.password:
        errors.append("source.url must not contain credentials")
    host = (parsed.hostname or "").lower()
    if not host:
        errors.append("source.url must include a host")
        return errors
    if _IP_LITERAL.match(host):
        errors.append("source.url must not be a bare IP address")
    for pattern in _PRIVATE_HOST_PATTERNS:
        if pattern.search(host):
            errors.append("source.url must not point at a private or loopback host")
            break
    hosts = ALLOWED_SOURCE_HOSTS + (TEST_SOURCE_HOSTS if allow_test_hosts else ())
    if not any(host == allowed or host.endswith("." + allowed) for allowed in hosts):
        errors.append(f"source.url host {host!r} is not on the approved source list")
    return errors


def validate_source(source: dict[str, Any], *, allow_test_hosts: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(source, dict):
        return ["source must be an object"]
    for key in _REQUIRED_SOURCE_FIELDS:
        if not source.get(key):
            errors.append(f"source.{key} is required")
    if source.get("source_type") and source["source_type"] not in SOURCE_TYPES:
        errors.append(f"source.source_type {source['source_type']!r} is not a supported type")
    if source.get("organisation") and source["organisation"] not in ALLOWED_ORGANISATIONS:
        errors.append(
            f"source.organisation {source['organisation']!r} is not on the approved organisation list"
        )
    if source.get("document_type") and source["document_type"] not in ALLOWED_DOCUMENT_TYPES:
        errors.append(f"source.document_type {source['document_type']!r} is not permitted")
    if source.get("region") and not isinstance(source["region"], str):
        errors.append("source.region must be a string")
    errors.extend(validate_url(source.get("url"), allow_test_hosts=allow_test_hosts))
    if source.get("publication_date"):
        _parse_date(source["publication_date"], "source.publication_date", errors)
    elif not source.get("date_note"):
        # An undated document is allowed, an *invented* date is not: the record
        # must say why the date is absent instead of guessing one.
        errors.append(
            "source.publication_date is missing, so source.date_note is required "
            "(e.g. 'the page does not state a publication date')"
        )
    if not source.get("accessed_at"):
        errors.append("source.accessed_at is required (the date the source was retrieved)")
    else:
        _parse_date(source["accessed_at"], "source.accessed_at", errors)
    if source.get("licence_note") is None:
        errors.append(
            "source.licence_note is required: state the reuse basis (or "
            "\"metadata/excerpts only\" when the full text is not reproduced)"
        )
    return errors


def _validate_common_statuses(entry: dict[str, Any], errors: list[str],
                              *, require_category: bool = True) -> None:
    if require_category and entry.get("category") not in ALL_CATEGORIES:
        errors.append(f"category {entry.get('category')!r} is not a supported category")
    if entry.get("evidence_level") not in EVIDENCE_LEVELS:
        errors.append(f"evidence_level {entry.get('evidence_level')!r} is not a supported level")
    if not entry.get("region_scope"):
        errors.append("region_scope is required: a practice is not universally applicable")
    if entry.get("source_language") not in (None, "en", "hi", "or"):
        errors.append("source_language must be one of en, hi, or")


def validate_technique(entry: dict[str, Any], *, category: Optional[str] = None,
                       allow_test_hosts: bool = False) -> list[str]:  # noqa: D401 - see module docstring
    errors: list[str] = []
    for key in _REQUIRED_TECHNIQUE_FIELDS:
        if not entry.get(key):
            errors.append(f"{key} is required")
    if entry.get("category") == CATEGORY_MODERN_PESTICIDE:
        errors.append(
            "modern pesticide information must be imported as a pesticide record, "
            "not a technique"
        )
    if category and entry.get("category") != category:
        errors.append(f"category {entry.get('category')!r} does not match the file section")
    _validate_common_statuses(entry, errors)

    preparation_status = entry.get("preparation_status", PREPARATION_DATA_UNAVAILABLE)
    if preparation_status not in (DATA_DOCUMENTED, PREPARATION_DATA_UNAVAILABLE):
        errors.append("preparation_status must be DOCUMENTED or PREPARATION_DATA_UNAVAILABLE")
    application_status = entry.get("application_status", APPLICATION_DATA_UNVERIFIED)
    if application_status not in (DATA_DOCUMENTED, APPLICATION_DATA_UNVERIFIED):
        errors.append("application_status must be DOCUMENTED or APPLICATION_DATA_UNVERIFIED")
    if preparation_status == DATA_DOCUMENTED and not (
        entry.get("preparation_instructions") or entry.get("application_practice")
    ):
        errors.append(
            "preparation_status DOCUMENTED requires preparation_instructions "
            "(a documented preparation, never an invented one)"
        )
    if application_status == DATA_DOCUMENTED and not entry.get("application_practice"):
        errors.append("application_status DOCUMENTED requires application_practice")
    crops = entry.get("crops")
    if not isinstance(crops, list):
        errors.append("crops must be a list (use [] plus crop_scope_note when the source is not crop-specific)")
    elif not crops and not entry.get("crop_scope_note"):
        errors.append(
            "either list the documented crops or add crop_scope_note explaining that "
            "the source documents the practice without naming a specific crop"
        )
    if not entry.get("regions") or not isinstance(entry.get("regions"), list):
        errors.append("regions must list at least one documented region")
    errors.extend(validate_source(entry.get("source", {}), allow_test_hosts=allow_test_hosts))
    errors.extend(_validate_translations(entry.get("translations") or []))
    return errors


def validate_pesticide(entry: dict[str, Any], *, allow_test_hosts: bool = False) -> list[str]:
    errors: list[str] = []
    for key in _REQUIRED_PESTICIDE_FIELDS:
        if not entry.get(key):
            errors.append(f"{key} is required")
    record_type = entry.get("record_type", "ACTIVE_INGREDIENT")
    if record_type not in PESTICIDE_RECORD_TYPES:
        errors.append(f"record_type {record_type!r} is not supported")
    if record_type == "ACTIVE_INGREDIENT":
        if not entry.get("active_ingredient"):
            errors.append("active_ingredient is required for an ACTIVE_INGREDIENT record")
    else:
        if entry.get("active_ingredient"):
            errors.append(
                "a SAFETY_GUIDANCE record must not name an active ingredient: it "
                "describes instructions that apply to any registered product"
            )
        if not entry.get("title"):
            errors.append("a SAFETY_GUIDANCE record requires a title")
    # Pesticides live in their own table and their own section, so they carry
    # ``pesticide_category`` instead of the technique ``category`` field.
    _validate_common_statuses(entry, errors, require_category=False)
    if entry.get("category") not in (None, CATEGORY_MODERN_PESTICIDE):
        errors.append("pesticide records must use category modern_pesticide")
    if entry.get("application_status", APPLICATION_DATA_UNVERIFIED) not in (
        DATA_DOCUMENTED, APPLICATION_DATA_UNVERIFIED,
    ):
        errors.append("application_status must be DOCUMENTED or APPLICATION_DATA_UNVERIFIED")
    # A documented dose must name the authoritative document it came from.
    if entry.get("application_status") == DATA_DOCUMENTED and not (
        entry.get("label_directions_reference")
    ):
        errors.append(
            "application_status DOCUMENTED requires label_directions_reference "
            "(the official document the application data came from)"
        )
    for key in ("manufacturing_instructions", "synthesis_route", "formulation_recipe"):
        if entry.get(key):
            errors.append(
                f"{key} must never be imported: AGRIQ does not store manufacturing instructions"
            )
    targets = entry.get("targets")
    if not isinstance(targets, list):
        errors.append("targets must be a list")
    elif not targets and record_type == "ACTIVE_INGREDIENT":
        errors.append("targets must list at least one source-documented crop/target pair")
    errors.extend(validate_source(entry.get("source", {}), allow_test_hosts=allow_test_hosts))
    errors.extend(_validate_translations(entry.get("translations") or []))
    return errors


def _validate_translations(translations: list[Any]) -> list[str]:
    errors: list[str] = []
    for index, item in enumerate(translations):
        if not isinstance(item, dict):
            errors.append(f"translations[{index}] must be an object")
            continue
        if item.get("language") not in ("hi", "or"):
            errors.append(f"translations[{index}].language must be hi or or")
        if not item.get("field"):
            errors.append(f"translations[{index}].field is required")
        if not item.get("text"):
            errors.append(f"translations[{index}].text is required")
        status = item.get("review_status", TRANSLATION_DRAFT)
        if status not in TRANSLATION_STATUSES:
            errors.append(f"translations[{index}].review_status {status!r} is not supported")
        if status == TRANSLATION_REVIEWED and not item.get("reviewed_by"):
            errors.append(f"translations[{index}] marked REVIEWED must name reviewed_by")
        if status == TRANSLATION_DRAFT and item.get("field") in KnowledgeTranslation.HIGH_RISK_FIELDS:
            errors.append(
                f"translations[{index}] targets safety-critical field "
                f"{item['field']!r}: a DRAFT translation of safety text is never imported "
                "(§18) — review it or leave the field untranslated"
            )
    return errors


def load_dataset(path: str | Path) -> dict[str, Any]:
    """Read and shape-check the dataset file."""
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise DatasetError(f"Dataset not found: {dataset_path}")
    try:
        data = json.loads(dataset_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetError(f"Dataset is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DatasetError("Dataset must be a JSON object")
    if data.get("dataset_version") is None or data.get("review_policy") is None:
        raise DatasetError(
            "Dataset must declare 'dataset_version' and 'review_policy' so a "
            "reviewer knows what they are approving"
        )
    for section in ("techniques", "pesticides"):
        value = data.get(section, [])
        if not isinstance(value, list):
            raise DatasetError(f"'{section}' must be a list")
    return data


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _source_row_key(entry: dict[str, Any]) -> str:
    return str(entry["source"]["source_key"])


def _ensure_source(entry: dict[str, Any], *, approved: bool, reviewer: Optional[str]) -> KnowledgeSource:
    """Create/refresh the provenance row (the single source table)."""
    source_data = entry["source"]
    # NOTE: ``reviewer`` is recorded on the record itself (set_review_status);
    # the source row only records that a human approved it.
    now = datetime.now(timezone.utc)
    accessed = _parse_date(source_data.get("accessed_at"), "source.accessed_at", [])
    published = _parse_date(source_data.get("publication_date"), "source.publication_date", [])
    payload = {
        "source_key": _source_row_key(entry),
        "title": source_data["title"],
        "organisation": source_data["organisation"],
        "source_url": source_data["url"],
        "document_type": source_data.get("document_type", "extension_material"),
        "crop": ", ".join(entry.get("crops", []))[:120] or None,
        "region": source_data.get("region") or entry.get("region_scope"),
        "language": entry.get("source_language", "en"),
        "publication_date": published,
        "licence_note": source_data.get("licence_note"),
        "version": str(source_data.get("version", "1")),
        "review_status": (KnowledgeSource.STATUS_APPROVED if approved
                          else KnowledgeSource.STATUS_PENDING),
        "retrieved_at": datetime.combine(accessed, datetime.min.time(), tzinfo=timezone.utc)
        if accessed else None,
        "reviewed_at": now if approved else None,
        "source_type": source_data["source_type"],
        "accessed_at": datetime.combine(accessed, datetime.min.time(), tzinfo=timezone.utc)
        if accessed else None,
        "last_verified_at": now if approved else None,
        "review_due_at": None,
    }
    return KnowledgeRepository.upsert_source(payload)


def _technique_payload(entry: dict[str, Any], source_id: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "slug": entry["slug"],
        "category": entry["category"],
        "title": entry["title"],
        "region_scope": entry.get("region_scope"),
        "evidence_level": entry["evidence_level"],
        "source_language": entry.get("source_language", "en"),
        "historical_period": entry.get("historical_period"),
        "crop_scope_note": entry.get("crop_scope_note"),
        "preparation_status": entry.get("preparation_status", PREPARATION_DATA_UNAVAILABLE),
        "application_status": entry.get("application_status", APPLICATION_DATA_UNVERIFIED),
        "source_id": source_id,
        "reference_note": entry.get("reference_note"),
        "review_status": REVIEW_PENDING,
    }
    for field_name in _TEXT_FIELDS:
        payload[field_name] = entry.get(field_name)
    return payload


def _pesticide_payload(entry: dict[str, Any], source_id: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "slug": entry["slug"],
        "record_type": entry.get("record_type", "ACTIVE_INGREDIENT"),
        "title": entry.get("title"),
        "active_ingredient": entry.get("active_ingredient"),
        "common_name": entry.get("common_name"),
        "pesticide_category": entry["pesticide_category"],
        "chemical_group": entry.get("chemical_group"),
        "evidence_level": entry["evidence_level"],
        "region_scope": entry.get("region_scope"),
        "source_language": entry.get("source_language", "en"),
        "application_status": entry.get("application_status", APPLICATION_DATA_UNVERIFIED),
        "source_id": source_id,
        "reference_note": entry.get("reference_note"),
        "review_status": REVIEW_PENDING,
    }
    for field_name in _PESTICIDE_TEXT_FIELDS:
        payload[field_name] = entry.get(field_name)
    return payload


def _region_rows(entry: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in entry.get("regions", []):
        if isinstance(item, dict):
            rows.append({"region": item["region"], "scope_note": item.get("scope_note")})
        else:
            rows.append({"region": str(item), "scope_note": None})
    return rows


def _evidence_rows(entry: dict[str, Any], source_id: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in entry.get("evidence", []):
        if not isinstance(item, dict) or not item.get("claim"):
            continue
        rows.append({
            "evidence_level": item.get("evidence_level", entry["evidence_level"]),
            "claim": item["claim"],
            "source_id": source_id,
            "source_section": item.get("source_section"),
            "note": item.get("note"),
        })
    return rows


def import_dataset(
    path: str | Path,
    *,
    approve: bool = False,
    reviewer: Optional[str] = None,
    allow_test_hosts: bool = False,
) -> tuple[dict[str, Any], list[ImportReport]]:
    """Validate and import the dataset. Returns ``(dataset, reports)``."""
    dataset = load_dataset(path)
    if approve and not (reviewer or "").strip():
        raise DatasetError(
            "Approving knowledge requires --reviewer: an anonymous approval is "
            "not an approval."
        )

    reports: list[ImportReport] = []
    for section, validator in (
        ("techniques", validate_technique),
        ("pesticides", validate_pesticide),
    ):
        for entry in dataset.get(section, []):
            slug = str(entry.get("slug") or f"<{section} entry without slug>")
            errors = validator(entry, allow_test_hosts=allow_test_hosts)
            if errors:
                reports.append(ImportReport(
                    slug=slug, status="failed",
                    detail="validation failed", errors=errors,
                ))
                continue

            source = _ensure_source(entry, approved=approve, reviewer=reviewer)
            if section == "pesticides":
                record, created = Repo.upsert_pesticide(
                    _pesticide_payload(entry, source.id),
                    targets=entry.get("targets", []),
                    evidence=_evidence_rows(entry, source.id),
                )
                kind = "pesticide"
            else:
                record, created = Repo.upsert_technique(
                    _technique_payload(entry, source.id),
                    crops=entry.get("crops", []),
                    regions=_region_rows(entry),
                    evidence=_evidence_rows(entry, source.id),
                )
                kind = "technique"

            chunks = 0
            status = REVIEW_PENDING
            if approve:
                Repo.set_review_status(
                    record, status=REVIEW_VERIFIED, reviewer=reviewer,  # type: ignore[arg-type]
                    note=entry.get("reviewer_note"),
                )
                source.review_status = KnowledgeSource.STATUS_APPROVED
                source.reviewed_at = datetime.now(timezone.utc)
                source.last_verified_at = source.accessed_at
                source.review_due_at = record.review_due_at
                from ...extensions import db

                db.session.commit()
                chunks = mirror_record_to_retrieval(kind, record)
                status = REVIEW_VERIFIED

            _import_translations(kind, record.id, entry.get("translations") or [], reviewer=reviewer)
            reports.append(ImportReport(
                slug=slug,
                status="created" if created else "updated",
                detail=f"{kind} imported from {source.source_key}",
                chunks=chunks,
                review_status=status,
            ))
    return dataset, reports


def _import_translations(kind: str, record_id: int, translations: list[dict[str, Any]],
                         *, reviewer: Optional[str]) -> None:
    for item in translations:
        Repo.upsert_translation(
            kind, record_id, item["language"], item["field"], item["text"],
            review_status=item.get("review_status", TRANSLATION_DRAFT),
            translator=item.get("translator"),
            reviewer=item.get("reviewed_by") or reviewer,
            note=item.get("review_note"),
        )


# ---------------------------------------------------------------------------
# Retrieval mirroring (so the copilot grounds on the same verified records)
# ---------------------------------------------------------------------------

def _chunk(text: str, section: str) -> dict[str, Any]:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"section_reference": section, "content": text, "content_hash": digest}


def mirror_record_to_retrieval(kind: str, record) -> int:
    """Mirror a verified record into retrieval chunks for the existing retriever.

    This is how the AI stays grounded without a second knowledge path: the
    Phase 2 retriever already reads ``knowledge_chunks`` of approved sources, so
    an approved technique appears there with its real provenance and the copilot
    can cite it. Only reviewed text is mirrored — nothing is summarised or
    generated here.
    """
    if kind == "pesticide":
        fields = _PESTICIDE_CHUNK_FIELDS
        header = f"{record.display_title} ({record.pesticide_category})"
    else:
        fields = _CHUNK_FIELDS
        header = record.title

    chunks: list[dict[str, Any]] = []
    for section, field_name in fields:
        value = getattr(record, field_name, None)
        if not value:
            continue
        chunks.append(_chunk(f"{header} — {section}: {value}", section))
    safety = getattr(record, "safety_precautions", None) or getattr(record, "ppe", None)
    if safety:
        chunks.append(_chunk(f"{header} — Safety: {safety}", "Safety"))
    if not chunks:
        return 0
    KnowledgeRepository.replace_chunks(record.source_id, chunks)
    source = KnowledgeRepository.get(record.source_id)
    if source is not None:
        source.checksum = hashlib.sha256("".join(c["content"] for c in chunks).encode("utf-8")).hexdigest()
        from ...extensions import db

        db.session.commit()
    return len(chunks)


def dataset_summary(dataset: dict[str, Any]) -> dict[str, Any]:
    """Honest count of what a dataset file actually contains."""
    return {
        "dataset_version": dataset.get("dataset_version"),
        "review_policy": dataset.get("review_policy"),
        "techniques": len(dataset.get("techniques", [])),
        "pesticides": len(dataset.get("pesticides", [])),
        "categories": sorted({
            entry.get("category") for entry in dataset.get("techniques", []) if entry.get("category")
        }),
    }


__all__ = [
    "ALLOWED_SOURCE_HOSTS",
    "DatasetError",
    "ImportReport",
    "SOURCE_TYPES",
    "TEST_SOURCE_HOSTS",
    "dataset_summary",
    "import_dataset",
    "load_dataset",
    "mirror_record_to_retrieval",
    "validate_pesticide",
    "validate_source",
    "validate_technique",
    "validate_url",
]
