"""Knowledge ingestion (Phase 2 §6).

Downloads allowlisted documents only, stores checksums, extracts text safely
and splits it into meaningful sections. Ingested sources always start as
``pending_review`` — a human reviewer must approve them before retrieval can
use them. Raw documents live outside the public static directory
(KNOWLEDGE_STORAGE_PATH), never reachable from the browser.

Failure behaviour is honest: a failed download records the error and moves
on; nothing partial is marked as ingested. No credentials are logged.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...core.time import utc_now
from ...repositories.copilot_repository import KnowledgeRepository
from ...models.knowledge import KnowledgeSource
from .source_registry import SourceEntry

# politeness + safety limits
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024          # 25 MB
MAX_RETRIES = 2
MIN_TEXT_LENGTH = 200                          # reject empty/corrupted extractions
_MIN_SECTION_LENGTH = 120                      # meaningful-section floor

_USER_AGENT = "AGRIQ-KnowledgeIngestion/1.0 (+agricultural extension use)"


@dataclass
class IngestionReport:
    """Per-source ingestion outcome (safe to print — no secrets)."""

    source_key: str
    status: str                    # ingested|updated|failed|skipped
    detail: str = ""
    chunks: int = 0
    checksum: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "status": self.status,
            "detail": self.detail,
            "chunks": self.chunks,
            "checksum": self.checksum,
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch(url: str) -> bytes:
    """Download with timeout + bounded retries. Raises on failure."""
    import time
    import requests

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            response = requests.get(
                url,
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
                headers={"User-Agent": _USER_AGENT},
                allow_redirects=True,
            )
            response.raise_for_status()
            content = response.content
            if len(content) > MAX_DOCUMENT_BYTES:
                raise ValueError(f"Document exceeds {MAX_DOCUMENT_BYTES} byte limit")
            return content
        except Exception as exc:  # noqa: BLE001 — network layer, report honestly
            last_error = exc
            if attempt <= MAX_RETRIES:
                time.sleep(2 * attempt)  # simple backoff
    raise RuntimeError(f"Download failed after {MAX_RETRIES + 1} attempts: {last_error}")


def _extract_text(content: bytes, url: str) -> str:
    """Extract readable text from HTML or PDF bytes; reject empties.

    PDFs are extracted only if a PDF library is installed; otherwise the
    document is reported as unsupported rather than silently skipped.
    """
    if content[:5] == b"%PDF-":
        try:
            from pypdf import PdfReader  # optional dependency
            import io
            reader = PdfReader(io.BytesIO(content))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except ImportError:
            raise RuntimeError("PDF source requires the optional 'pypdf' package to ingest.")
        if len(text.strip()) < MIN_TEXT_LENGTH:
            raise RuntimeError("PDF text extraction produced too little content (possibly scanned images).")
        return text

    # HTML: strip scripts/styles/tags conservatively
    try:
        html = content.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not decode document: {exc}") from exc
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<(br|/p|/div|/h[1-6]|/li)[^>]*>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < MIN_TEXT_LENGTH:
        raise RuntimeError("Extracted text is too short — document rejected as empty/corrupted.")
    return text


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split into meaningful sections by headings or blank-line paragraphs."""
    sections: list[tuple[str, str]] = []
    # Heading-style lines (short, no trailing period, often numbered/caps)
    lines = text.splitlines()
    current_title = "Introduction"
    buffer: list[str] = []
    for line in lines:
        stripped = line.strip()
        is_heading = (
            stripped
            and len(stripped) < 90
            and not stripped.endswith(".")
            and (bool(re.match(r"^\d+(\.\d+)*\s+\S", stripped))
                 or stripped.isupper()
                 or (stripped.istitle() and len(buffer) > 0))
        )
        if is_heading:
            if buffer:
                body = "\n".join(buffer).strip()
                if len(body) >= _MIN_SECTION_LENGTH:
                    sections.append((current_title[:200], body))
                buffer = []
            current_title = stripped
        else:
            buffer.append(line)
    if buffer:
        body = "\n".join(buffer).strip()
        if len(body) >= _MIN_SECTION_LENGTH:
            sections.append((current_title[:200], body))

    if not sections:
        # Fallback: paragraph chunking so content is still retrievable with
        # its position preserved as a section reference.
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) >= _MIN_SECTION_LENGTH]
        sections = [(f"Paragraph {i + 1}", p) for i, p in enumerate(paragraphs)]
    return sections


def ingest_source(entry: SourceEntry, storage_path: str | Path) -> IngestionReport:
    """Download, extract, checksum, section and persist one source.

    The resulting knowledge_source row is always ``pending_review`` on first
    ingest; re-ingestion keeps the existing review status but refreshes the
    checksum, so an approved source must be re-approved-by-review only if its
    content changes (checksum mismatch marks it ``pending_review`` again).
    """
    existing = KnowledgeRepository.get_by_key(entry.source_key)
    if existing is not None and existing.review_status == KnowledgeSource.STATUS_APPROVED \
            and existing.version == entry.document_version:
        return IngestionReport(source_key=entry.source_key, status="skipped",
                               detail="Approved source already ingested at this version.")

    try:
        content = _fetch(entry.source_url)
    except Exception as exc:  # noqa: BLE001 — reported honestly per source
        return IngestionReport(source_key=entry.source_key, status="failed",
                               detail=str(exc)[:300])

    checksum = _sha256(content)

    # Duplicate prevention: identical checksum + version → skip.
    if existing is not None and existing.checksum == checksum \
            and existing.version == entry.document_version:
        return IngestionReport(source_key=entry.source_key, status="skipped",
                               detail="Unchanged document already ingested.")

    try:
        text = _extract_text(content, entry.source_url)
    except Exception as exc:  # noqa: BLE001
        return IngestionReport(source_key=entry.source_key, status="failed",
                               detail=f"Extraction failed: {exc}"[:300])

    # Raw document archived outside the public static tree.
    storage = Path(storage_path)
    raw_dir = storage / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.-]+", "_", entry.source_key)[:80]
    raw_path = raw_dir / f"{safe_name}.bin"
    raw_path.write_bytes(content)

    # Review status: checksum change on a previously approved source demotes it.
    review_status = KnowledgeSource.STATUS_PENDING
    if existing is not None and existing.review_status == KnowledgeSource.STATUS_APPROVED \
            and existing.checksum == checksum:
        review_status = KnowledgeSource.STATUS_APPROVED
    publication_date = None
    if entry.publication_date:
        from datetime import date
        try:
            publication_date = date.fromisoformat(entry.publication_date)
        except ValueError:
            publication_date = None

    source_row = KnowledgeRepository.upsert_source({
        "source_key": entry.source_key,
        "title": entry.title,
        "organisation": entry.organisation,
        "source_url": entry.source_url,
        "document_type": entry.document_type,
        "crop": entry.crop,
        "region": entry.region,
        "language": entry.language,
        "publication_date": publication_date,
        "licence_note": entry.licence_note,
        "checksum": checksum,
        "version": entry.document_version,
        "review_status": review_status,
        "retrieved_at": utc_now(),
    })

    sections = _split_sections(text)
    chunks_payload = []
    for section_title, body in sections:
        chunks_payload.append({
            "section_reference": f"{section_title}",
            "content": body,
            "content_hash": _sha256(body.encode("utf-8")),
            "embedding_reference": None,   # no embedding provider in Phase 2
        })
    KnowledgeRepository.replace_chunks(source_row.id, chunks_payload)

    status = "updated" if existing is not None else "ingested"
    return IngestionReport(
        source_key=entry.source_key,
        status=status,
        detail=f"review_status={review_status}",
        chunks=len(chunks_payload),
        checksum=checksum,
    )


def ingest_manifest(manifest_path: str | Path, storage_path: str | Path) -> list[IngestionReport]:
    """Ingest every source in a validated manifest; per-source failure isolation."""
    from .source_registry import load_manifest
    entries = load_manifest(manifest_path)
    return [ingest_source(entry, storage_path) for entry in entries]


__all__ = ["IngestionReport", "ingest_source", "ingest_manifest",
           "DOWNLOAD_TIMEOUT_SECONDS", "MAX_DOCUMENT_BYTES"]
