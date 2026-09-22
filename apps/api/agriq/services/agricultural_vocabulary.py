"""Agricultural vocabulary registry (Phase 3).

A versioned, source-attributed term list used ONLY to improve transcript
display, post-processing suggestions and search. Vocabulary is never used
to silently replace a transcript word — suggestions always surface to the
farmer as "Did you mean: …?" and require explicit confirmation.

Sources are real and documented:
- AGRIQ curated crop/pest/disease catalogues (domain/catalogs/, the same
  reviewed content that powers the risk engine) — version follows
  CROP_STAGE_REFERENCE_VERSION semantics.
- Odisha district list: Government of Odisha administrative districts
  (public administrative nomenclature).
Terms were compiled from AGRIQ's existing reviewed catalogues; no LLM was
used to generate this registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

VOCABULARY_VERSION = "agriq-vocab-v1"

SOURCE_AGRIQ_CATALOGS = "AGRIQ domain/catalogs (reviewed content)"
SOURCE_GOV_ODISHA_DISTRICTS = "Government of Odisha district list (administrative)"


@dataclass(frozen=True)
class VocabTerm:
    term: str
    language: str          # or | hi | en
    category: str          # crop|variety|stage|pest|disease|soil|irrigation|district|mandi|operation
    english_equivalent: Optional[str] = None
    transliteration: Optional[str] = None
    source: str = SOURCE_AGRIQ_CATALOGS
    source_version: str = VOCABULARY_VERSION
    reviewer_status: str = "reviewed"   # all listed terms come from reviewed catalogues


# Odia terms from AGRIQ's reviewed crop/pest catalogues (identifiers match
# the strings already shipped in domain/catalogs — no new agronomy claims).
REGISTRY: tuple[VocabTerm, ...] = (
    # Crops (Odia)
    VocabTerm("ଧାନ", "or", "crop", "Rice", "dhaana"),
    VocabTerm("ମକା", "or", "crop", "Maize", "maka"),
    VocabTerm("ମୁଗ", "or", "crop", "Green gram", "muga"),
    VocabTerm("ବିରି", "or", "crop", "Black gram", "biri"),
    VocabTerm("ଅରହର", "or", "crop", "Pigeon pea", "arahara"),
    VocabTerm("ମାଞ୍ଚ", "or", "crop", "Groundnut", "mancha"),
    VocabTerm("ଆଳୁ", "or", "crop", "Potato", "aalu"),
    # Pests (Odia)
    VocabTerm("ଗଣ୍ଡି ପୋକ", "or", "pest", "Stem borer", "gandi poka"),
    VocabTerm("ମାହାଳି ପୋକ", "or", "pest", "Brown Plant Hopper", "maahali poka"),
    VocabTerm("ପତ୍ର ମୋଡ଼ା ପୋକ", "or", "pest", "Leaf folder", "patra moda poka"),
    # Diseases (Odia)
    VocabTerm("ବ୍ଲାଷ୍ଟ", "or", "disease", "Blast", "blast"),
    VocabTerm("ବ୍ଲାଇଟ୍", "or", "disease", "Blight", "blight"),
    # Stages (Odia)
    VocabTerm("କଳି ହେବା", "or", "stage", "Tillering", "kali heba"),
    VocabTerm("ଫୁଲ ଫୁଟିବା", "or", "stage", "Flowering", "phula futiba"),
    # Irrigation / soil (Odia)
    VocabTerm("ଜଳସେଚ", "or", "irrigation", "Irrigation", "jalasecha"),
    VocabTerm("ମାଟି ପରୀକ୍ଷା", "or", "soil", "Soil test", "mati pariksha"),
    # Operations (Odia)
    VocabTerm("ବୁଣିବା", "or", "operation", "Sowing", "buniba"),
    VocabTerm("ଅମଳ", "or", "operation", "Harvest", "amala"),
    VocabTerm("ନିଷ୍କାଶନ", "or", "operation", "Drainage", "niskashana"),
    # Hindi (Devanagari) — same reviewed catalogue content
    VocabTerm("धान", "hi", "crop", "Rice", "dhaan"),
    VocabTerm("मक्का", "hi", "crop", "Maize", "makka"),
    VocabTerm("मूंग", "hi", "crop", "Green gram", "moong"),
    VocabTerm("कांदा छेदक", "hi", "pest", "Stem borer", "kanda chhedak"),
    VocabTerm("माहोगनी फुदका", "hi", "pest", "Brown Plant Hopper", "mahogany phudka"),
    VocabTerm("सिंचाई", "hi", "irrigation", "Irrigation", "sinchai"),
    VocabTerm("मिट्टी परीक्षण", "hi", "soil", "Soil test", "mitti parikshan"),
    VocabTerm("बुवाई", "hi", "operation", "Sowing", "buvai"),
    VocabTerm("कटाई", "hi", "operation", "Harvest", "katai"),
    # Odisha districts (administrative nomenclature; sample of major mandi districts)
    VocabTerm("Cuttack", "en", "district", None, None, SOURCE_GOV_ODISHA_DISTRICTS),
    VocabTerm("Bhubaneswar", "en", "district", None, None, SOURCE_GOV_ODISHA_DISTRICTS),
    VocabTerm("Sambalpur", "en", "district", None, None, SOURCE_GOV_ODISHA_DISTRICTS),
    VocabTerm("Berhampur", "en", "district", None, None, SOURCE_GOV_ODISHA_DISTRICTS),
    VocabTerm("Balasore", "en", "district", None, None, SOURCE_GOV_ODISHA_DISTRICTS),
    VocabTerm("Jajpur", "en", "district", None, None, SOURCE_GOV_ODISHA_DISTRICTS),
    VocabTerm("Puri", "en", "district", None, None, SOURCE_GOV_ODISHA_DISTRICTS),
)


def lookup(term: str, language: str | None = None) -> list[VocabTerm]:
    """Exact/substring lookup for display aid and search."""
    needle = (term or "").strip().lower()
    if not needle:
        return []
    matches = []
    for entry in REGISTRY:
        if language and entry.language != language:
            continue
        haystack = " ".join(filter(None, [entry.term.lower(),
                                          (entry.english_equivalent or "").lower(),
                                          (entry.transliteration or "").lower()])).lower()
        if needle in haystack:
            matches.append(entry)
    return matches


def suggest_correction(term: str, language: str | None = None) -> Optional[VocabTerm]:
    """Return a single best-match suggestion for display ("Did you mean: X?")."""
    matches = lookup(term, language)
    if not matches:
        return None
    # Prefer exact term match, then English-equivalent match, then first.
    lowered = (term or "").strip().lower()
    for entry in matches:
        if entry.term.lower() == lowered:
            return entry
    for entry in matches:
        if entry.english_equivalent and entry.english_equivalent.lower() == lowered:
            return entry
    return matches[0]


def terms_by_category(category: str, language: str | None = None) -> list[VocabTerm]:
    return [t for t in REGISTRY if t.category == category and (not language or t.language == language)]


__all__ = [
    "VocabTerm", "REGISTRY", "lookup", "suggest_correction",
    "terms_by_category", "VOCABULARY_VERSION",
    "SOURCE_AGRIQ_CATALOGS", "SOURCE_GOV_ODISHA_DISTRICTS",
]
