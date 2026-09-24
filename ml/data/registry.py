"""Dataset registry access (Phase 4).

Loads and validates ``ml/data/dataset_registry.yaml``. The registry is the
single source of truth for which datasets exist, their provenance and their
review status. Training may consume ONLY ``approved`` datasets.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

REGISTRY_PATH = Path(__file__).resolve().parent / "dataset_registry.yaml"

ALLOWED_STATUS = {
    "discovered",
    "licence_review_required",
    "quality_review_required",
    "approved",
    "rejected",
    "archived",
}

REQUIRED_FIELDS = (
    "dataset_id",
    "dataset_name",
    "original_source_url",
    "original_authors",
    "licence",
    "licence_verified",
    "crop",
    "status",
)


class RegistryError(Exception):
    """Raised when the registry file is missing or malformed."""


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load and structurally validate the dataset registry."""
    path = path or REGISTRY_PATH
    if not path.exists():
        raise RegistryError(f"Dataset registry not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    entries = data.get("datasets")
    if not isinstance(entries, list):
        raise RegistryError("Registry must contain a 'datasets' list")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise RegistryError("Each dataset entry must be a mapping")
        for field_name in REQUIRED_FIELDS:
            if field_name not in entry:
                raise RegistryError(f"Dataset '{entry.get('dataset_id', '?')}' missing field '{field_name}'")
        dsid = entry["dataset_id"]
        if dsid in seen:
            raise RegistryError(f"Duplicate dataset_id: {dsid}")
        seen.add(dsid)
        if entry["status"] not in ALLOWED_STATUS:
            raise RegistryError(f"Dataset '{dsid}' has invalid status '{entry['status']}'")
        if entry["status"] == "approved" and not entry.get("licence_verified"):
            raise RegistryError(f"Dataset '{dsid}' approved without licence verification")
        if entry["status"] == "approved" and not entry.get("checksum"):
            raise RegistryError(f"Dataset '{dsid}' approved without a recorded checksum")
        if entry["status"] == "approved" and not entry.get("reviewer"):
            raise RegistryError(f"Dataset '{dsid}' approved without a named reviewer")
    return data


def get_dataset(dataset_id: str, path: Path | None = None) -> Optional[dict[str, Any]]:
    """Return one dataset entry or None."""
    data = load_registry(path)
    for entry in data.get("datasets", []):
        if entry["dataset_id"] == dataset_id:
            return entry
    return None


def approved_dataset_ids(path: Path | None = None) -> list[str]:
    """IDs of datasets eligible for training."""
    data = load_registry(path)
    return [e["dataset_id"] for e in data.get("datasets", []) if e["status"] == "approved"]
