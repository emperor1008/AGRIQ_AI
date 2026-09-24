"""Model registry access (Phase 4).

``ml/models/registry.yaml`` is the single source of truth for production
models. The web application may load ONLY entries with
``approved_for_production: true`` AND a passing checksum. If no approved
model exists the feature must report "Image analysis is not currently
available." — never a fabricated prediction.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "models" / "registry.yaml"


@dataclass
class ModelEntry:
    model_id: str
    model_name: str
    version: str
    supported_crop: str
    supported_classes: list[str]
    model_checksum: str
    framework: str
    input_size: list[int]
    preprocessing_version: str
    dataset_manifest_versions: list[str]
    split_manifest: str
    calibration_version: str
    abstention_thresholds: dict[str, Any]
    evaluation_report: str
    external_field_validation_status: str
    licence: str
    approved_for_production: bool
    approved_at: Optional[str]
    approver: Optional[str]
    weights_path: Optional[str] = None

    @classmethod
    def from_yaml(cls, d: dict[str, Any]) -> "ModelEntry":
        return cls(
            model_id=d["model_id"],
            model_name=d["model_name"],
            version=d["version"],
            supported_crop=d["supported_crop"],
            supported_classes=list(d["supported_classes"]),
            model_checksum=d["model_checksum"],
            framework=d["framework"],
            input_size=list(d["input_size"]),
            preprocessing_version=d["preprocessing_version"],
            dataset_manifest_versions=list(d.get("dataset_manifest_versions", [])),
            split_manifest=d["split_manifest"],
            calibration_version=d["calibration_version"],
            abstention_thresholds=dict(d.get("abstention_thresholds", {})),
            evaluation_report=d["evaluation_report"],
            external_field_validation_status=d["external_field_validation_status"],
            licence=d["licence"],
            approved_for_production=bool(d.get("approved_for_production", False)),
            approved_at=d.get("approved_at"),
            approver=d.get("approver"),
            weights_path=d.get("weights_path"),
        )

    def sha256_matches(self, weights_path: Path) -> bool:
        digest = hashlib.sha256()
        with open(weights_path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest() == self.model_checksum


class ModelRegistry:
    """Registry access with approval + checksum gating."""

    def __init__(self, registry_path: Path | None = None, models_dir: Path | None = None):
        self.registry_path = registry_path or REGISTRY_PATH
        self.models_dir = models_dir or self.registry_path.parent
        with open(self.registry_path, "r", encoding="utf-8") as fh:
            self._raw: dict[str, Any] = yaml.safe_load(fh) or {}

    @property
    def entries(self) -> list[ModelEntry]:
        return [ModelEntry.from_yaml(d) for d in (self._raw.get("models") or [])]

    def get(self, model_id: str) -> Optional[ModelEntry]:
        for e in self.entries:
            if e.model_id == model_id:
                return e
        return None

    def approved_for_crop(self, crop: str) -> Optional[ModelEntry]:
        """Return the approved model for a crop, or None (feature unavailable).

        An approved entry still fails closed if its weights are missing or the
        checksum does not match the recorded one.
        """
        crop = crop.lower().strip()
        for e in self.entries:
            if e.supported_crop.lower() != crop or not e.approved_for_production:
                continue
            if not e.weights_path:
                return None
            weights = self.models_dir / e.weights_path
            if not weights.is_file():
                return None
            try:
                if not e.sha256_matches(weights):
                    return None
            except OSError:
                return None
            return e
        return None
