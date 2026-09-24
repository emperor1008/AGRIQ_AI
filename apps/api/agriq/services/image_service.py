"""Crop-image analysis service (Phase 4) — web-app side.

Bridges the lightweight ``ml.inference`` package and the Flask app. Owns:
- validated image upload handling (allowlist, decoded-format verification,
  decompression-bomb protection, EXIF-stripped processed copy, random
  storage keys, private storage)
- persistence via the image repository
- honest unavailable/rejected/abstained states (never fabricated output)

The service NEVER prescribes treatment — recommendations flow only through
the Phase 2 copilot + safety guardrails.
"""
from __future__ import annotations

import hashlib
import io
import secrets
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from ..core.config import get_config
from ..core.exceptions import InvalidImageError, ValidationError
from ..core.logging import get_logger
from ..repositories.image_repository import ImageAnalysisRepository
from ..schemas.image_analysis import validate_analyse_request

logger = get_logger("services.image_service")

ALLOWED_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
#: Declared-pixel ceiling (decompression-bomb guard) before decode.
MAX_DECLARED_PIXELS = 50_000_000


def _storage_root() -> Path:
    root = Path(get_config().get("IMAGE_STORAGE_PATH") or "image_store")
    (root / "originals").mkdir(parents=True, exist_ok=True)
    (root / "processed").mkdir(parents=True, exist_ok=True)
    return root


def _read_upload(storage: Any) -> bytes:
    """Read an upload with the configured size ceiling enforced on bytes."""
    limit_mb = int(get_config().get("IMAGE_MAX_FILE_SIZE_MB") or 5)
    data = storage.read(limit_mb * 1024 * 1024 + 1)
    if len(data) > limit_mb * 1024 * 1024:
        raise ValidationError(f"Image must be under {limit_mb} MiB.")
    if not data:
        raise ValidationError("The uploaded file is empty.")
    return data


def _decode_strict(data: bytes) -> Image.Image:
    """Decode and verify the *actual* format — never trust MIME or extension.

    Raises InvalidImageError for anything but an allowed raster format,
    oversized declared dimensions, or an unfinishing decode.
    """
    try:
        img = Image.open(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        logger.info("image_decode_failed reason=not_an_image")
        raise InvalidImageError() from exc

    if img.format not in ALLOWED_FORMATS:
        logger.info("image_decode_failed reason=disallowed_format format=%s", img.format)
        raise InvalidImageError()
    width, height = img.size
    if width * height > MAX_DECLARED_PIXELS:
        raise ValidationError("Image dimensions are too large.")
    try:
        img.load()
    except Exception as exc:  # noqa: BLE001 — truncated/corrupted payloads
        raise InvalidImageError() from exc
    if getattr(img, "n_frames", 1) > 1:
        raise InvalidImageError()  # animated images are not farm photos
    return img


def _processed_copy(img: Image.Image) -> tuple[bytes, str]:
    """EXIF-stripped, orientation-normalised PNG copy for analysis.

    The ORIGINAL upload is preserved untouched on disk; only this derived
    copy (which carries no location/device metadata) is analysed.
    """
    max_dim = int(get_config().get("IMAGE_MAX_DIMENSION") or 6000)
    normalised = ImageOps.exif_transpose(img)
    if max(normalised.size) > max_dim:
        normalised.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    normalised.convert("RGB").save(buf, format="PNG")
    return buf.getvalue(), "png"


def _store_private(user_id: int, data: bytes, ext: str, kind: str) -> str:
    key = f"{kind}/{user_id}/{secrets.token_hex(16)}.{ext}"
    target = _storage_root() / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return key


class CropImageService:
    """Analyse one uploaded crop image (fail-closed everywhere)."""

    def available(self) -> bool:
        """True only when an approved model with a passing checksum exists
        for at least one supported crop. Drives the UI's honest state."""
        from ml.inference.registry import ModelRegistry

        try:
            registry = ModelRegistry()
        except Exception:  # noqa: BLE001 — unreadable registry = unavailable
            return False
        return any(
            registry.approved_for_crop(crop) is not None for crop in ("rice", "tomato")
        )

    def analyse_upload(self, user_id: int, *, storage: Any, expected_crop: str) -> dict[str, Any]:
        validate_analyse_request(expected_crop=expected_crop)

        data = _read_upload(storage)
        img = _decode_strict(data)
        checksum = hashlib.sha256(data).hexdigest()

        processed_bytes, processed_ext = _processed_copy(img)

        from ml.inference.predictor import CropImagePredictor

        predictor = CropImagePredictor()
        result = predictor.analyse(file_bytes=processed_bytes, expected_crop=expected_crop)

        record: dict[str, Any] = {
            "expected_crop": expected_crop,
            "original_checksum": checksum,
            "original_storage_key": _store_private(user_id, data, ALLOWED_FORMATS[img.format], "originals"),
            "processed_storage_key": _store_private(user_id, processed_bytes, processed_ext, "processed"),
            "abstained": False,
            "requires_expert_confirmation": True,
        }

        analysis_payload: dict[str, Any]
        if result.status == "unavailable":
            record.update(
                status="unavailable",
                model_name=None,
                model_version=None,
            )
            analysis_payload = {
                "status": "unavailable",
                "message": result.message,
                "crop": {"expected": expected_crop, "supported": False},
            }
        elif result.status == "rejected":
            quality = result.analysis.get("image_quality", {})
            record.update(
                status="rejected",
                abstained=True,
                abstention_reason=result.analysis.get("abstention", {}).get("reason", "image_quality_insufficient"),
                image_quality_json=_dumps(quality),
            )
            analysis_payload = {
                "status": "rejected",
                "message": result.message,
                "crop": {"expected": expected_crop, "supported": True},
                "image_quality": quality,
                "guidance": quality.get("guidance", []),
            }
        else:  # completed — real model output (only reachable with trained weights)
            analysis_payload = result.analysis
            record.update(
                status="completed",
                model_name=analysis_payload.get("model", {}).get("name"),
                model_version=analysis_payload.get("model", {}).get("version"),
                predicted_class=(analysis_payload.get("predictions") or [{}])[0].get("condition"),
                calibrated_confidence=(analysis_payload.get("predictions") or [{}])[0].get("probability"),
                confidence_category=analysis_payload.get("confidence_category"),
                predictions_json=_dumps(analysis_payload.get("predictions", [])),
                explanation_json=_dumps(analysis_payload.get("explanation", [])),
                image_quality_json=_dumps(analysis_payload.get("image_quality", {})),
                abstained=bool(analysis_payload.get("abstained")),
                abstention_reason=analysis_payload.get("abstention_reason"),
            )

        row = ImageAnalysisRepository.create(user_id, record)
        payload = row.to_json()
        # Merge the transient unavailable/rejected messaging into the row JSON.
        for key in ("message", "guidance"):
            if key in analysis_payload and key not in payload:
                payload[key] = analysis_payload[key]
        payload["crop"]["supported"] = row.status == "completed"
        return payload

    def get_owned(self, analysis_id: int, user_id: int) -> dict[str, Any] | None:
        row = ImageAnalysisRepository.get_owned(analysis_id, user_id)
        return row.to_json() if row else None

    def delete_owned(self, analysis_id: int, user_id: int) -> bool:
        row = ImageAnalysisRepository.get_owned(analysis_id, user_id)
        if row is None:
            return False
        ImageAnalysisRepository.soft_delete(row)
        return True


def _dumps(value: Any) -> str | None:
    import json

    return json.dumps(value, ensure_ascii=False) if value else None


__all__ = ["CropImageService"]
