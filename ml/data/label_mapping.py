"""Label mapping between dataset labels and AGRIQ labels (Phase 4).

Mappings are versioned, reviewed artefacts stored under
``ml/data/label_mappings/<dataset_id>.json``. An ambiguous dataset label must
be rejected or mapped to the AGRIQ ``unsupported`` label — never silently
relabelled, and healthy labels are never inferred from missing disease labels.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

MAPPINGS_DIR = Path(__file__).resolve().parent / "label_mappings"

# AGRIQ Phase 4 supported scope (from the product specification).
AGRIQ_RICE_LABELS = {
    "rice_healthy",
    "rice_blast",
    "rice_bacterial_leaf_blight",
    "rice_brown_spot",
    "unsupported",
}
AGRIQ_TOMATO_LABELS = {
    "tomato_healthy",
    "tomato_early_blight",
    "tomato_late_blight",
    "unsupported",
}

_LABEL_RE = re.compile(r"^[a-z]+(_[a-z0-9]+)*$")


class LabelMappingError(Exception):
    """Raised when a mapping file is invalid or used without approval."""


def agriq_labels(crop: str) -> set[str]:
    return AGRIQ_RICE_LABELS if crop == "rice" else AGRIQ_TOMATO_LABELS


def validate_mapping_document(doc: dict[str, Any]) -> None:
    """Structural validation of one mapping document."""
    for key in ("dataset_id", "agriq_crop", "version", "mappings"):
        if key not in doc:
            raise LabelMappingError(f"Mapping document missing '{key}'")
    crop = doc["agriq_crop"]
    if crop not in ("rice", "tomato"):
        raise LabelMappingError(f"Unsupported crop '{crop}'")
    allowed = agriq_labels(crop)
    for item in doc["mappings"]:
        for key in ("dataset_label", "agriq_label", "mapping_status"):
            if key not in item:
                raise LabelMappingError(f"Mapping entry missing '{key}'")
        if not _LABEL_RE.match(item["dataset_label"]):
            raise LabelMappingError(f"Malformed dataset_label '{item['dataset_label']}'")
        if item["agriq_label"] not in allowed:
            raise LabelMappingError(
                f"'{item['agriq_label']}' is not an AGRIQ {crop} label (unsupported classes stay unsupported)"
            )
        if item["mapping_status"] not in ("approved", "rejected", "pending"):
            raise LabelMappingError(f"Invalid mapping_status '{item['mapping_status']}'")
        if item["mapping_status"] == "approved" and not item.get("reviewer"):
            raise LabelMappingError("Approved mapping requires a named reviewer")


def load_mapping(dataset_id: str, mappings_dir: Path | None = None) -> Optional[dict[str, Any]]:
    """Load the mapping document for a dataset, if present."""
    path = (mappings_dir or MAPPINGS_DIR) / f"{dataset_id}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        doc = json.load(fh)
    validate_mapping_document(doc)
    return doc


def map_label(dataset_id: str, dataset_label: str, mappings_dir: Path | None = None) -> str:
    """Translate a dataset label into the AGRIQ label.

    Raises LabelMappingError for unmapped/ambiguous labels — callers must
    never guess. Rejected mappings always resolve to ``unsupported``.
    """
    doc = load_mapping(dataset_id, mappings_dir)
    if doc is None:
        raise LabelMappingError(f"No label mapping document for dataset '{dataset_id}'")
    normalised = dataset_label.strip().lower().replace(" ", "_").replace("-", "_")
    for item in doc["mappings"]:
        if item["dataset_label"] == normalised:
            if item["mapping_status"] == "rejected":
                return "unsupported"
            if item["mapping_status"] == "approved":
                return item["agriq_label"]
            raise LabelMappingError(f"Mapping for '{dataset_label}' is pending review")
    raise LabelMappingError(f"Dataset label '{dataset_label}' has no mapping entry")
