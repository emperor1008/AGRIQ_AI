"""Knowledge retrieval (Phase 2 §7).

Phase 2 ships approved **lexical retrieval**: a scored keyword/phrase match
over approved knowledge chunks. No fake embeddings are stored — if an
embedding provider is added later, ``embedding_reference`` on chunks is the
hook and this module is the integration point. Until then the API reports
that semantic retrieval is unavailable; lexical is the approved method.

Rules enforced here (not in routes, not in the LLM):
- Only ``approved`` sources can ever be retrieved.
- Every retrieved passage retains source id, title, organisation, section,
  publication date, relevance score and retrieval timestamp.
- Below the relevance threshold the retriever returns an explicit
  ``unavailable`` result — the copilot then says verified guidance is
  unavailable instead of letting the LLM improvise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ...core.time import utc_now
from ...repositories.copilot_repository import KnowledgeRepository
from ...models.knowledge import KnowledgeSource

# Environment-configurable minimum relevance (0-1). Below this, "no approved
# evidence" is returned rather than weak matches.
DEFAULT_MIN_RELEVANCE = 0.18


@dataclass
class RetrievedPassage:
    """One retrieved knowledge passage with full provenance."""

    source_id: int
    source_key: str
    title: str
    organisation: str
    section_reference: Optional[str]
    content: str
    publication_date: Optional[str]
    relevance: float
    retrieved_at: str
    language: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_key": self.source_key,
            "title": self.title,
            "organisation": self.organisation,
            "section_reference": self.section_reference,
            "content": self.content,
            "publication_date": self.publication_date,
            "relevance": round(self.relevance, 3),
            "retrieved_at": self.retrieved_at,
            "language": self.language,
        }


@dataclass
class RetrievalResult:
    """Outcome of one retrieval call."""

    available: bool
    passages: list[RetrievedPassage] = field(default_factory=list)
    top_score: float = 0.0
    method: str = "lexical"
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "passages": [p.to_dict() for p in self.passages],
            "top_score": round(self.top_score, 3),
            "method": self.method,
            "reason": self.reason,
        }


# Simple generic stopwords (kept minimal: agronomy vocabulary is meaningful)
_STOP = {
    "the", "a", "an", "is", "are", "my", "i", "should", "can", "do", "does",
    "what", "when", "how", "why", "of", "in", "on", "for", "to", "and", "with",
    "me", "you", "it", "this", "that", "at", "be", "will", "if",
}


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^\w]+", (text or "").lower()) if len(t) > 1 and t not in _STOP]


def _score_chunk(query_terms: list[str], chunk_text: str) -> float:
    """Lexical relevance: coverage of query terms weighted by rarity in chunk."""
    if not query_terms:
        return 0.0
    lowered = chunk_text.lower()
    hits = 0
    for term in query_terms:
        if term in lowered:
            hits += 1
    coverage = hits / len(query_terms)
    # Small bonus when a rare multi-token phrase appears verbatim.
    phrase_bonus = 0.1 if " ".join(query_terms[:2]) in lowered and len(query_terms) > 1 else 0.0
    return min(1.0, coverage * 0.9 + phrase_bonus)


class KnowledgeRetriever:
    """Retrieves from approved sources only (review-status enforced)."""

    def __init__(self, min_relevance: Optional[float] = None) -> None:
        import os
        try:
            configured = float(os.environ.get("KNOWLEDGE_MIN_RELEVANCE_SCORE", ""))
        except ValueError:
            configured = None
        self.min_relevance = (
            min_relevance if min_relevance is not None
            else (configured if configured is not None else DEFAULT_MIN_RELEVANCE)
        )

    def retrieve(
        self,
        question: str,
        *,
        crop: Optional[str] = None,
        stage: Optional[str] = None,
        district: Optional[str] = None,
        state: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 3,
    ) -> RetrievalResult:
        """Retrieve up to ``limit`` approved passages meeting the threshold."""
        sources = KnowledgeRepository.approved_sources(crop=crop)
        if not sources:
            return RetrievalResult(
                available=False, method="lexical",
                reason="No approved knowledge sources are available for verification.",
            )
        source_ids = [s.id for s in sources]
        chunks = KnowledgeRepository.approved_chunks_for_sources(source_ids)
        if not chunks:
            return RetrievalResult(
                available=False, method="lexical",
                reason="Approved sources have no ingested sections yet.",
            )

        query_terms = _tokenize(question)
        if stage:
            query_terms.extend(_tokenize(stage))
        if crop:
            query_terms.append(crop.lower())

        source_by_id = {s.id: s for s in sources}
        scored: list[tuple[float, Any, Any]] = []
        for chunk in chunks:
            source = source_by_id.get(chunk.source_id)
            if source is None:
                continue
            base = _score_chunk(query_terms, chunk.content)
            # Region relevance: district/state mention in content or region field.
            region_bonus = 0.0
            if district and district.lower() in (chunk.content or "").lower():
                region_bonus = 0.08
            elif state and state.lower() in (source.region or "").lower():
                region_bonus = 0.05
            # Recency: newer publications score slightly higher.
            recency_bonus = 0.0
            if source.publication_date:
                try:
                    from datetime import date
                    pub = source.publication_date if isinstance(source.publication_date, date) else None
                    if pub:
                        age_days = (utc_now().date() - pub).days
                        recency_bonus = 0.05 if age_days < 1825 else (0.02 if age_days < 3650 else 0.0)
                except (TypeError, ValueError):
                    recency_bonus = 0.0
            # Language preference: exact language match gets a small boost, but
            # English sources remain retrievable for translation-safe summaries.
            lang_bonus = 0.03 if language and source.language == language else 0.0
            score = min(1.0, base + region_bonus + recency_bonus + lang_bonus)
            if score > 0:
                scored.append((score, chunk, source))

        scored.sort(key=lambda t: t[0], reverse=True)
        retrieved_at = utc_now().isoformat()

        passages: list[RetrievedPassage] = []
        for score, chunk, source in scored[:limit]:
            if score < self.min_relevance:
                break
            passages.append(RetrievedPassage(
                source_id=source.id,
                source_key=source.source_key,
                title=source.title,
                organisation=source.organisation,
                section_reference=chunk.section_reference,
                content=chunk.content,
                publication_date=source.publication_date.isoformat() if source.publication_date else None,
                relevance=score,
                retrieved_at=retrieved_at,
                language=source.language,
            ))

        if not passages:
            return RetrievalResult(
                available=False, method="lexical", top_score=scored[0][0] if scored else 0.0,
                reason="No approved passage met the relevance threshold for this question.",
            )
        return RetrievalResult(
            available=True,
            passages=passages,
            top_score=passages[0].relevance,
            method="lexical",
        )


__all__ = ["KnowledgeRetriever", "RetrievalResult", "RetrievedPassage", "DEFAULT_MIN_RELEVANCE"]
