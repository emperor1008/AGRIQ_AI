"""Source registry (Phase 2 §5).

The registry is a versioned JSON manifest of *approved-candidate* sources.
Nothing enters the recommendation path until a human reviewer sets
``review_status = approved`` in the database. The manifest only defines what
ingestion may download — it is an allowlist, not an approval.

Allowed organisations (Phase 2 policy):
- ICAR and ICAR-CIARI publications
- Odisha Department of Agriculture and Farmers' Empowerment
- OUAT material where reuse is allowed
- KVK / ICAR extension material
- Government package-of-practices documents
- Official pesticide labels where legally reusable
- Peer-reviewed open-access research

Manifest entries carry every provenance field the knowledge_sources table
stores; the ingestion CLI never invents metadata.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Organisations permitted in the manifest. Ingestion rejects anything else.
ALLOWED_ORGANISATIONS = {
    "ICAR",
    "ICAR-CIARI",
    "ICAR-IIRI",
    "ICAR-NRRI",
    "ICAR-CRRI",
    "Department of Agriculture and Farmers' Empowerment, Government of Odisha",
    "Odisha University of Agriculture and Technology",
    "KVK Odisha",
    "Government of Odisha",
    "Government of India",
    "Ministry of Agriculture and Farmers Welfare",
}

ALLOWED_DOCUMENT_TYPES = {
    "advisory", "package_of_practices", "pesticide_label", "research_paper",
    "extension_material", "government_circular", "newsletter",
}

ALLOWED_LANGUAGES = {"en", "hi", "or"}


@dataclass
class SourceEntry:
    """One manifest entry — full provenance metadata, no generated values."""

    source_key: str
    title: str
    organisation: str
    source_url: str
    document_type: str
    crop: Optional[str] = None
    region: Optional[str] = None
    language: str = "en"
    publication_date: Optional[str] = None
    licence_note: Optional[str] = None
    document_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "title": self.title,
            "organisation": self.organisation,
            "source_url": self.source_url,
            "document_type": self.document_type,
            "crop": self.crop,
            "region": self.region,
            "language": self.language,
            "publication_date": self.publication_date,
            "licence_note": self.licence_note,
            "document_version": self.document_version,
        }


class ManifestError(ValueError):
    """Raised for invalid manifests (bad organisation, missing fields...)."""


def load_manifest(path: str | Path) -> list[SourceEntry]:
    """Load and validate a source manifest (allowlist-enforced)."""
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise ManifestError(f"Manifest not found: {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Manifest is not valid JSON: {exc}") from exc

    entries_raw = data.get("sources")
    if not isinstance(entries_raw, list) or not entries_raw:
        raise ManifestError("Manifest must contain a non-empty 'sources' list.")

    entries: list[SourceEntry] = []
    seen_keys: set[str] = set()
    for i, raw in enumerate(entries_raw):
        required = ("source_key", "title", "organisation", "source_url", "document_type")
        missing = [k for k in required if not raw.get(k)]
        if missing:
            raise ManifestError(f"Source #{i}: missing required fields {missing}")
        if raw["organisation"] not in ALLOWED_ORGANISATIONS:
            raise ManifestError(
                f"Source #{i} ('{raw['source_key']}'): organisation "
                f"'{raw['organisation']}' is not in the approved allowlist."
            )
        if raw["document_type"] not in ALLOWED_DOCUMENT_TYPES:
            raise ManifestError(
                f"Source #{i}: document_type '{raw['document_type']}' is not permitted."
            )
        if raw.get("language", "en") not in ALLOWED_LANGUAGES:
            raise ManifestError(f"Source #{i}: language '{raw.get('language')}' is not supported.")
        key = raw["source_key"]
        if key in seen_keys:
            raise ManifestError(f"Duplicate source_key '{key}' in manifest.")
        seen_keys.add(key)
        entries.append(SourceEntry(
            source_key=key,
            title=raw["title"],
            organisation=raw["organisation"],
            source_url=raw["source_url"],
            document_type=raw["document_type"],
            crop=raw.get("crop"),
            region=raw.get("region"),
            language=raw.get("language", "en"),
            publication_date=raw.get("publication_date"),
            licence_note=raw.get("licence_note"),
            document_version=str(raw.get("document_version", "1")),
        ))
    return entries


__all__ = ["SourceEntry", "load_manifest", "ManifestError",
           "ALLOWED_ORGANISATIONS", "ALLOWED_DOCUMENT_TYPES", "ALLOWED_LANGUAGES"]
