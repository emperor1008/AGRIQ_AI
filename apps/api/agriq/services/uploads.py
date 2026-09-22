"""Safe file upload service (Phase 1).

Stores farmer-uploaded soil-test reports and observation images under
``AGRIQ_UPLOAD_FOLDER`` with hardening:

- Extension AND magic-byte content validation.
- Hard size ceiling per file type.
- Randomised server-side filenames (never the client-supplied name).
- Private storage layout: ``uploads/<kind>/<user_id>/<uuid>.<ext>`` —
  never inside the static folder, never web-servable directly.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from ..core.constants import (
    ALLOWED_SOIL_REPORT_EXTENSIONS,
    MAX_SOIL_REPORT_BYTES,
    MAX_UPLOAD_BYTES,
)
from ..core.exceptions import InvalidImageError, ValidationError
from ..core.logging import get_logger

logger = get_logger("services.uploads")

_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"RIFF", "webp"),
)
_PDF_MAGIC = b"%PDF"


def _upload_root() -> Path:
    from flask import current_app

    root = Path(current_app.config.get("AGRIQ_UPLOAD_FOLDER") or "uploads")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _validate_size(storage: Any, max_bytes: int) -> None:
    storage.seek(0, 2)
    size = storage.tell()
    storage.seek(0)
    if size == 0:
        raise ValidationError("The uploaded file is empty.")
    if size > max_bytes:
        raise InvalidImageError() if max_bytes == MAX_UPLOAD_BYTES else ValidationError(
            f"Soil report must be under {max_bytes // (1024 * 1024)} MiB."
        )


def _detect_extension(storage: Any, allowed: set[str]) -> str:
    """Return the extension only when magic bytes match an allowed type."""
    head = storage.read(16)
    storage.seek(0)
    for magic, ext in _IMAGE_MAGIC:
        if head.startswith(magic) and ext in allowed:
            return "jpg" if ext == "jpg" else ext
    if head.startswith(_PDF_MAGIC) and "pdf" in allowed:
        return "pdf"
    raise InvalidImageError() if "pdf" not in allowed else ValidationError(
        "Soil report must be a PDF, JPG or PNG file."
    )


def save_observation_image(user_id: int, storage: Any) -> str:
    """Validate and store an observation image; returns the relative path."""
    _validate_size(storage, MAX_UPLOAD_BYTES)
    ext = _detect_extension(storage, {"jpg", "png", "webp"})
    return _store(user_id, "observations", storage, ext)


def save_soil_report(user_id: int, storage: Any) -> str:
    """Validate and store a soil-test report; returns the relative path."""
    _validate_size(storage, MAX_SOIL_REPORT_BYTES)
    ext = _detect_extension(storage, set(ALLOWED_SOIL_REPORT_EXTENSIONS))
    return _store(user_id, "soil_reports", storage, ext)


def _store(user_id: int, kind: str, storage: Any, ext: str) -> str:
    target_dir = _upload_root() / kind / str(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    target = target_dir / filename
    storage.seek(0)
    target.write_bytes(storage.read())
    relative = f"{kind}/{user_id}/{filename}"
    logger.info("upload_stored kind=%s user_id=%s path=%s", kind, user_id, relative)
    return relative


__all__ = ["save_observation_image", "save_soil_report"]
